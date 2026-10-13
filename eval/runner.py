import os
import sys
import json
import time
import statistics

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
from eval.benchmark.cases import BENCHMARK_CASES, BenchmarkCase
from eval.benchmark.generator import BenchmarkRepoGenerator
from patchpilot.core import PatchPilotEngine
from patchpilot.models import EvidenceStrategyType, VerificationOutcome


@dataclass
class BaselineMetrics:
    strategy: str
    total_tasks: int
    top_1_fl_accuracy: float
    top_5_fl_accuracy: float
    diagnosis_correctness: float
    inconclusive_rate: float
    verified_fix_rate: float
    regression_rate: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    avg_total_tokens: float
    avg_cost_usd: float
    cost_per_verified_fix: float
    median_latency_seconds: float
    p95_latency_seconds: float


class ExperimentRunner:
    def __init__(self, cases: Optional[List[BenchmarkCase]] = None):
        self.cases = cases or BENCHMARK_CASES

    def run_all_baselines(
        self,
        token_budget: int = 2000,
        output_json_path: Optional[str] = None,
    ) -> Dict[str, BaselineMetrics]:
        strategies = [
            EvidenceStrategyType.DIRECT_PROMPT,
            EvidenceStrategyType.TRACEBACK_TEXT_SEARCH,
            EvidenceStrategyType.FIXED_CONTEXT,
            EvidenceStrategyType.HEURISTIC_RETRIEVAL,
            EvidenceStrategyType.ADAPTIVE_EVIDENCE,
        ]

        results_by_strategy: Dict[str, BaselineMetrics] = {}
        raw_traces: List[Dict[str, Any]] = []

        for strat in strategies:
            strat_name = strat.value
            top1_hits = 0
            top5_hits = 0
            diag_correct = 0
            inconclusives = 0
            verified_fixes = 0
            regressions = 0
            prompt_toks: List[int] = []
            comp_toks: List[int] = []
            total_toks: List[int] = []
            costs: List[float] = []
            latencies: List[float] = []

            for case in self.cases:
                repo_dir = BenchmarkRepoGenerator.materialize_case(case)
                try:
                    engine = PatchPilotEngine(repo_dir)
                    trace = engine.diagnose_bug(
                        bug_description=case.bug_description,
                        raw_traceback=case.raw_traceback,
                        strategy=strat,
                        token_budget=token_budget,
                    )

                    latencies.append(trace.latency_seconds)
                    prompt_toks.append(trace.accounting.prompt_tokens)
                    comp_toks.append(trace.accounting.completion_tokens)
                    total_toks.append(trace.accounting.total_tokens)
                    costs.append(trace.accounting.estimated_cost_usd)

                    if trace.diagnosis and trace.diagnosis.is_inconclusive:
                        inconclusives += 1

                    # Localisation accuracy
                    cands = [c.symbol_name.split(".")[-1] for c in trace.top_candidates]
                    if cands:
                        if case.target_faulty_symbol in cands[0]:
                            top1_hits += 1
                        if any(case.target_faulty_symbol in c for c in cands[:5]):
                            top5_hits += 1

                    # Diagnosis evaluation
                    is_diag_ok = False
                    if case.is_ambiguous:
                        if trace.diagnosis and trace.diagnosis.is_inconclusive:
                            is_diag_ok = True
                    else:
                        if trace.diagnosis and not trace.diagnosis.is_inconclusive and trace.diagnosis.validation_status == "VALIDATED":
                            is_diag_ok = True
                    if is_diag_ok:
                        diag_correct += 1

                    # Verified patch simulation using ground truth patch if justified
                    if case.ground_truth_patch and trace.diagnosis and trace.diagnosis.is_patch_justified:
                        patch_res = engine.verify_patch_opt_in(
                            diff_text=case.ground_truth_patch,
                            reproduction_test=case.reproduction_test,
                            regression_test=case.regression_test,
                        )
                        if patch_res.outcome == VerificationOutcome.VERIFIED:
                            verified_fixes += 1
                        elif patch_res.outcome == VerificationOutcome.REGRESSION_FAILED:
                            regressions += 1

                    raw_traces.append({
                        "case_id": case.case_id,
                        "strategy": strat_name,
                        "latency": trace.latency_seconds,
                        "tokens": trace.accounting.total_tokens,
                        "top_cands": [c.symbol_name for c in trace.top_candidates],
                        "inconclusive": trace.diagnosis.is_inconclusive if trace.diagnosis else True,
                    })

                finally:
                    BenchmarkRepoGenerator.cleanup_case(repo_dir)

            n = len(self.cases)
            p95_lat = sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0.0
            avg_cost = sum(costs) / n if n else 0.0
            cost_per_fix = (sum(costs) / verified_fixes) if verified_fixes > 0 else 0.0

            metric = BaselineMetrics(
                strategy=strat_name,
                total_tasks=n,
                top_1_fl_accuracy=round(top1_hits / n, 3),
                top_5_fl_accuracy=round(top5_hits / n, 3),
                diagnosis_correctness=round(diag_correct / n, 3),
                inconclusive_rate=round(inconclusives / n, 3),
                verified_fix_rate=round(verified_fixes / n, 3),
                regression_rate=round(regressions / n, 3),
                avg_prompt_tokens=round(statistics.mean(prompt_toks), 1) if prompt_toks else 0.0,
                avg_completion_tokens=round(statistics.mean(comp_toks), 1) if comp_toks else 0.0,
                avg_total_tokens=round(statistics.mean(total_toks), 1) if total_toks else 0.0,
                avg_cost_usd=round(avg_cost, 5),
                cost_per_verified_fix=round(cost_per_fix, 5),
                median_latency_seconds=round(statistics.median(latencies), 3) if latencies else 0.0,
                p95_latency_seconds=round(p95_lat, 3),
            )
            results_by_strategy[strat_name] = metric

        if output_json_path:
            payload = {
                "metrics": {k: asdict(v) for k, v in results_by_strategy.items()},
                "raw_traces": raw_traces,
            }
            os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

        return results_by_strategy

    def generate_markdown_report(self, metrics: Dict[str, BaselineMetrics]) -> str:
        lines = [
            "# PatchPilot Experimental Baseline Comparison Report\n",
            "| Strategy | Top-1 FL | Top-5 FL | Diag Correct | Inconclusive | Verified Fix | Avg Tokens | Median Lat (s) |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
        for name, m in metrics.items():
            lines.append(
                f"| `{name}` | {m.top_1_fl_accuracy*100:.1f}% | {m.top_5_fl_accuracy*100:.1f}% | "
                f"{m.diagnosis_correctness*100:.1f}% | {m.inconclusive_rate*100:.1f}% | "
                f"{m.verified_fix_rate*100:.1f}% | {m.avg_total_tokens:.0f} | {m.median_latency_seconds:.3f}s |"
            )
        return "\n".join(lines)


if __name__ == "__main__":
    runner = ExperimentRunner()
    results = runner.run_all_baselines(token_budget=2000, output_json_path="eval/results.json")
    print(runner.generate_markdown_report(results))
