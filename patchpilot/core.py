import time
import uuid
from typing import Optional
from patchpilot.config import settings
from patchpilot.models import (
    CostAccounting,
    EvidenceStrategyType,
    ExecutionTrace,
)
from patchpilot.indexer.repo_indexer import SafeRepoIndexer
from patchpilot.localisation.traceback_parser import TracebackParser
from patchpilot.localisation.fault_localiser import FaultLocaliser
from patchpilot.evidence.evidence_selector import EvidenceSelector
from patchpilot.llm.diagnosis_engine import DiagnosisEngine
from patchpilot.sandbox.test_runner import SafeTestRunner
from patchpilot.patching.patch_applier import PatchManager


class PatchPilotEngine:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.indexer = SafeRepoIndexer(repo_path)
        self.index = self.indexer.index_repository()
        self.localiser = FaultLocaliser(self.index)
        self.evidence_selector = EvidenceSelector(self.index)
        self.diagnosis_engine = DiagnosisEngine(self.index)
        self.test_runner = SafeTestRunner(repo_path)
        self.patch_manager = PatchManager(repo_path)

    def diagnose_bug(
        self,
        bug_description: str,
        raw_traceback: Optional[str] = None,
        strategy: EvidenceStrategyType = EvidenceStrategyType.ADAPTIVE_EVIDENCE,
        token_budget: Optional[int] = None,
        test_failure_summary: Optional[str] = None,
    ) -> ExecutionTrace:
        start_time = time.time()
        budget = token_budget or settings.default_token_budget
        task_id = str(uuid.uuid4())[:8]

        # 1. Parse Traceback if provided
        parsed_tb = TracebackParser.parse(raw_traceback) if raw_traceback else None

        # 2. Localise Faults
        candidates = self.localiser.rank_candidates(
            bug_description=bug_description,
            parsed_traceback=parsed_tb,
            top_k=5,
        )

        # 3. Select Evidence
        pool = self.evidence_selector.build_candidate_pool(
            ranked_candidates=candidates,
            parsed_traceback=parsed_tb,
            test_failure_summary=test_failure_summary,
        )
        evidence_bundle = self.evidence_selector.select(
            strategy=strategy,
            token_budget=budget,
            pool=pool,
        )

        # 4. Generate Diagnosis
        cost_acc = CostAccounting(budget_limit_tokens=budget)
        diagnosis, updated_acc = self.diagnosis_engine.run_diagnosis(
            bug_description=bug_description,
            evidence_bundle=evidence_bundle,
            raw_traceback=raw_traceback,
            cost_accounting=cost_acc,
        )

        sandbox_info = self.test_runner.get_sandbox_status()
        latency = round(time.time() - start_time, 3)

        return ExecutionTrace(
            task_id=task_id,
            repo_path=self.repo_path,
            bug_description=bug_description,
            strategy_used=strategy,
            latency_seconds=latency,
            top_candidates=candidates,
            evidence_bundle=evidence_bundle,
            diagnosis=diagnosis,
            patch_result=None,
            accounting=updated_acc,
            sandbox_mode=sandbox_info["mode"],
        )

    def verify_patch_opt_in(
        self,
        diff_text: str,
        reproduction_test: Optional[str] = None,
        regression_test: Optional[str] = None,
    ):
        return self.patch_manager.verify_patch(
            diff_text=diff_text,
            reproduction_test=reproduction_test,
            regression_test=regression_test,
        )
