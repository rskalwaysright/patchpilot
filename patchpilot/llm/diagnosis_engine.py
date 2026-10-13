import os
import re
from typing import Optional, Tuple
from patchpilot.config import DEFAULT_PRICING, settings
from patchpilot.models import CostAccounting, DiagnosisOutput, EvidenceBundle, RepoIndex
from patchpilot.llm.provider import DIAGNOSIS_PROMPT_TEMPLATE, BaseLLMProvider, get_llm_provider


class DiagnosisEngine:
    def __init__(self, repo_index: RepoIndex, provider: Optional[BaseLLMProvider] = None):
        self.repo_index = repo_index
        self.provider = provider or get_llm_provider()

    def run_diagnosis(
        self,
        bug_description: str,
        evidence_bundle: EvidenceBundle,
        raw_traceback: Optional[str] = None,
        cost_accounting: Optional[CostAccounting] = None,
    ) -> Tuple[DiagnosisOutput, CostAccounting]:
        accounting = cost_accounting or CostAccounting(budget_limit_tokens=evidence_bundle.target_budget_tokens)

        # Check if already over budget
        if accounting.total_tokens >= accounting.budget_limit_tokens:
            accounting.is_budget_exceeded = True
            diag = DiagnosisOutput(
                root_cause_hypothesis="Task budget exhausted prior to diagnosis generation.",
                supporting_evidence_references=[],
                confidence_score=0.0,
                confidence_explanation="Execution stopped because the token budget limit was reached.",
                is_inconclusive=True,
                is_patch_justified=False,
                validation_status="BUDGET_EXCEEDED",
            )
            return diag, accounting

        # Format evidence bundle into prompt text
        evidence_lines = []
        for it in evidence_bundle.items:
            evidence_lines.append(
                f"--- EVIDENCE ITEM [{it.item_id}] ---\n"
                f"file_path: {it.file_path}\n"
                f"lines: {it.start_line}-{it.end_line}\n"
                f"type: {it.evidence_type.value}\n"
                f"relation: {it.relation_to_fault}\n"
                f"```python\n{it.code_content}\n```\n"
            )

        evidence_text = "\n".join(evidence_lines) if evidence_lines else "None provided."
        traceback_context = raw_traceback.strip() if raw_traceback else "None provided."

        prompt = DIAGNOSIS_PROMPT_TEMPLATE.format(
            bug_description=bug_description,
            traceback_context=traceback_context,
            evidence_text=evidence_text,
        )

        # Execute single LLM call
        try:
            remaining_budget = max(200, accounting.budget_limit_tokens - accounting.total_tokens)
            raw_output, prompt_toks, comp_toks = self.provider.generate_diagnosis(
                prompt=prompt,
                budget_tokens=remaining_budget,
            )
            accounting.prompt_tokens += prompt_toks
            accounting.completion_tokens += comp_toks
            accounting.total_tokens += prompt_toks + comp_toks
            accounting.llm_call_count += 1

            # Update cost
            pricing = DEFAULT_PRICING.get(settings.openai_model, DEFAULT_PRICING["mock"])
            accounting.estimated_cost_usd += (
                (prompt_toks / 1000.0) * pricing.prompt_per_1k
                + (comp_toks / 1000.0) * pricing.completion_per_1k
            )

            if accounting.total_tokens > accounting.budget_limit_tokens:
                accounting.is_budget_exceeded = True

            # Parse and validate response
            diagnosis = DiagnosisOutput(
                root_cause_hypothesis=raw_output.get("root_cause_hypothesis", "Unknown"),
                supporting_evidence_references=raw_output.get("supporting_evidence_references", []),
                contradictory_evidence=raw_output.get("contradictory_evidence"),
                missing_evidence=raw_output.get("missing_evidence"),
                recommended_tests=raw_output.get("recommended_tests", []),
                confidence_score=float(raw_output.get("confidence_score", 0.5)),
                confidence_explanation=raw_output.get("confidence_explanation", ""),
                is_inconclusive=bool(raw_output.get("is_inconclusive", False)),
                is_patch_justified=bool(raw_output.get("is_patch_justified", False)),
                suggested_patch_diff=raw_output.get("suggested_patch_diff"),
            )

            # Validate cited file paths against repository index
            validation_status = self._validate_citations(diagnosis, evidence_bundle)
            diagnosis.validation_status = validation_status

            return diagnosis, accounting

        except Exception as e:
            err_diag = DiagnosisOutput(
                root_cause_hypothesis=f"Diagnosis generation failed due to error: {str(e)}",
                supporting_evidence_references=[],
                confidence_score=0.0,
                confidence_explanation=f"Provider exception: {e}",
                is_inconclusive=True,
                is_patch_justified=False,
                validation_status="ERROR",
            )
            return err_diag, accounting

    def _validate_citations(self, diagnosis: DiagnosisOutput, evidence_bundle: EvidenceBundle) -> str:
        """Verifies that every cited file path exists in the repository index or evidence bundle."""
        if not diagnosis.supporting_evidence_references:
            return "VALIDATED" if not diagnosis.is_patch_justified else "NO_CITATIONS"

        all_evidence_files = {it.file_path for it in evidence_bundle.items}

        for ref in diagnosis.supporting_evidence_references:
            # Check if reference is an item ID
            if any(it.item_id == ref for it in evidence_bundle.items):
                continue

            # Handle Windows drive letters like C:\path\file.py:L10-L20
            # Strip trailing line range like :L10-L20 or :10-20 or :L10
            file_part = re.sub(r":(?:L?\d+(?:-L?\d+)?)$", "", ref).strip()

            # Check if cited file exists in indexed repo or evidence
            is_valid_file = False
            for indexed_p in self.repo_index.indexed_files.keys():
                if (
                    indexed_p.endswith(file_part)
                    or os.path.basename(indexed_p) == os.path.basename(file_part)
                    or file_part in all_evidence_files
                ):
                    is_valid_file = True
                    break

            if not is_valid_file and file_part not in {"<test_execution_stdout>", "<unknown>"}:
                # Hallucinated or non-existent file path cited
                return "INVALID_CITATION"

        return "VALIDATED"
