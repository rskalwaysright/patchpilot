import os
import sys
import json
import statistics

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from eval.benchmark.cases import BENCHMARK_CASES
from eval.benchmark.generator import BenchmarkRepoGenerator
from patchpilot.core import PatchPilotEngine
from patchpilot.models import EvidenceStrategyType, VerificationOutcome


def run_budget_ablation_study():
    """Evaluates performance of Adaptive Evidence Selection across varying token budgets."""
    budgets = [500, 1000, 2000, 4000]
    cases = BENCHMARK_CASES
    results = {}

    print("Running Token Budget Sensitivity Study on Adaptive Evidence Selection...")
    for b in budgets:
        diag_correct = 0
        tokens = []
        verified_fixes = 0
        for case in cases:
            repo_dir = BenchmarkRepoGenerator.materialize_case(case)
            try:
                engine = PatchPilotEngine(repo_dir)
                trace = engine.diagnose_bug(
                    bug_description=case.bug_description,
                    raw_traceback=case.raw_traceback,
                    strategy=EvidenceStrategyType.ADAPTIVE_EVIDENCE,
                    token_budget=b,
                )
                tokens.append(trace.accounting.total_tokens)
                if case.is_ambiguous:
                    if trace.diagnosis and trace.diagnosis.is_inconclusive:
                        diag_correct += 1
                else:
                    if trace.diagnosis and not trace.diagnosis.is_inconclusive and trace.diagnosis.validation_status == "VALIDATED":
                        diag_correct += 1
                
                if case.ground_truth_patch and trace.diagnosis and trace.diagnosis.is_patch_justified:
                    patch_res = engine.verify_patch_opt_in(
                        diff_text=case.ground_truth_patch,
                        reproduction_test=case.reproduction_test,
                        regression_test=case.regression_test,
                    )
                    if patch_res.outcome == VerificationOutcome.VERIFIED:
                        verified_fixes += 1
            finally:
                BenchmarkRepoGenerator.cleanup_case(repo_dir)

        results[f"budget_{b}"] = {
            "budget_limit": b,
            "diagnosis_correctness": round(diag_correct / len(cases), 3),
            "verified_fix_rate": round(verified_fixes / len(cases), 3),
            "avg_tokens_used": round(statistics.mean(tokens), 1),
        }

    out_file = os.path.join(os.path.dirname(__file__), "ablation_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n--- Token Budget Sensitivity Results ---")
    print("| Token Budget | Avg Tokens Used | Diagnosis Correct | Verified Fix Rate |")
    print("| :---: | :---: | :---: | :---: |")
    for k, v in results.items():
        print(f"| {v['budget_limit']} | {v['avg_tokens_used']} | {v['diagnosis_correctness']*100:.1f}% | {v['verified_fix_rate']*100:.1f}% |")

    return results


if __name__ == "__main__":
    run_budget_ablation_study()
