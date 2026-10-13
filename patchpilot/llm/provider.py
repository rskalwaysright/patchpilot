import abc
import json
import os
import re
from typing import Any, Dict, Optional, Tuple
from patchpilot.config import DEFAULT_PRICING, settings
from patchpilot.models import CostAccounting, DiagnosisOutput, EvidenceBundle, RepoIndex


DIAGNOSIS_PROMPT_TEMPLATE = """You are PatchPilot, an evidence-first, budget-aware automated debugging system.
Analyze the following bug report, traceback, and curated evidence snippets from the repository.

# BUG REPORT:
{bug_description}

# TRACEBACK / FAILURE CONTEXT:
{traceback_context}

# CODE EVIDENCE:
{evidence_text}

# INSTRUCTIONS:
1. Provide a rigorous, evidence-grounded diagnosis.
2. Every file path and line number you cite MUST exist in the provided evidence. DO NOT hallucinate files or lines.
3. If the evidence is insufficient to identify the root cause with confidence, set "is_inconclusive": true and "is_patch_justified": false.
4. Output strictly valid JSON matching this schema:
{{
  "root_cause_hypothesis": "A concise explanation of why the bug occurs",
  "supporting_evidence_references": ["file.py:L10-L15", "item_id"],
  "contradictory_evidence": "Any evidence that does not fit the hypothesis, or null",
  "missing_evidence": "Information needed to confirm the hypothesis, or null",
  "recommended_tests": ["test_name_or_file"],
  "confidence_score": 0.85,
  "confidence_explanation": "Justification for confidence level",
  "is_inconclusive": false,
  "is_patch_justified": true,
  "suggested_patch_diff": "Unified diff or null"
}}
"""


class BaseLLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate_diagnosis(
        self,
        prompt: str,
        budget_tokens: int,
    ) -> Tuple[Dict[str, Any], int, int]:
        """
        Returns (parsed_json_dict, prompt_tokens, completion_tokens).
        """
        pass


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic offline mock provider.
    Inspects the prompt and produces an evidence-grounded diagnosis without external API calls.
    Supports deterministic tests and offline experiments.
    """
    def generate_diagnosis(
        self,
        prompt: str,
        budget_tokens: int,
    ) -> Tuple[Dict[str, Any], int, int]:
        # Count approximate tokens in prompt
        prompt_tokens = max(10, len(prompt.split()) * 4 // 3)
        
        # Determine if evidence exists
        has_evidence = "# CODE EVIDENCE:" in prompt and len(prompt.split("# CODE EVIDENCE:")[1].strip()) > 20
        has_tb = "Traceback" in prompt or "Error" in prompt

        if not has_evidence and not has_tb:
            # Inconclusive case
            result = {
                "root_cause_hypothesis": "Insufficient evidence provided to determine the root cause of the reported issue.",
                "supporting_evidence_references": [],
                "contradictory_evidence": "No traceback or repository code snippets available in the current context bundle.",
                "missing_evidence": "Failing test output, traceback frame, or candidate function source code.",
                "recommended_tests": ["tests/"],
                "confidence_score": 0.1,
                "confidence_explanation": "Context contains only raw bug description without code grounding.",
                "is_inconclusive": True,
                "is_patch_justified": False,
                "suggested_patch_diff": None,
            }
        else:
            # Extract cited file paths from prompt if present
            found_paths = re.findall(r"file_path:\s*([^\s\n]+)", prompt)
            first_path = found_paths[0] if found_paths else "main.py"
            
            # Formulate grounded mock response
            result = {
                "root_cause_hypothesis": "A boundary condition or unhandled exception occurs in the primary candidate function.",
                "supporting_evidence_references": [f"{first_path}:L1-L20"],
                "contradictory_evidence": None,
                "missing_evidence": None,
                "recommended_tests": ["test_boundary_conditions"],
                "confidence_score": 0.88,
                "confidence_explanation": f"Grounded in verified evidence snippet from {first_path}.",
                "is_inconclusive": False,
                "is_patch_justified": True,
                "suggested_patch_diff": None,
            }

        completion_tokens = max(10, len(json.dumps(result).split()) * 4 // 3)
        return result, prompt_tokens, completion_tokens


class OpenAILLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def generate_diagnosis(
        self,
        prompt: str,
        budget_tokens: int,
    ) -> Tuple[Dict[str, Any], int, int]:
        import httpx
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise, evidence-grounded software debugging engine. You output valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": min(1500, budget_tokens),
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{self.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
            choice = data["choices"][0]["message"]["content"]
            parsed = json.loads(choice)
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", len(prompt.split()))
            completion_tokens = usage.get("completion_tokens", len(choice.split()))
            return parsed, prompt_tokens, completion_tokens


def get_llm_provider() -> BaseLLMProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai" and settings.openai_api_key:
        return OpenAILLMProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
    return MockLLMProvider()
