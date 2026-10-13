import os
import shutil
import tempfile
import pytest
from patchpilot.core import PatchPilotEngine
from patchpilot.indexer.repo_indexer import SafeRepoIndexer
from patchpilot.localisation.traceback_parser import TracebackParser
from patchpilot.models import EvidenceStrategyType, EvidenceType, SymbolType
from patchpilot.evidence.token_counter import count_tokens
from patchpilot.patching.patch_applier import PatchManager


@pytest.fixture
def sample_repo():
    tmp_dir = tempfile.mkdtemp(prefix="test_patchpilot_repo_")
    
    # Create simple module structure
    # main.py
    main_code = """
def calculate_average(numbers):
    if not numbers:
        return 0
    total = sum(numbers)
    return total / len(numbers)

def process_data(payload):
    data = payload.get("values", [])
    avg = calculate_average(data)
    return {"average": avg}
"""
    with open(os.path.join(tmp_dir, "main.py"), "w", encoding="utf-8") as f:
        f.write(main_code)

    # tests/test_main.py
    os.makedirs(os.path.join(tmp_dir, "tests"), exist_ok=True)
    test_code = """
import pytest
from main import calculate_average, process_data

def test_calculate_average():
    assert calculate_average([10, 20]) == 15
    assert calculate_average([]) == 0

def test_process_data():
    res = process_data({"values": [1, 2, 3]})
    assert res["average"] == 2
"""
    with open(os.path.join(tmp_dir, "tests", "test_main.py"), "w", encoding="utf-8") as f:
        f.write(test_code)

    yield tmp_dir

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_safe_repo_indexer(sample_repo):
    indexer = SafeRepoIndexer(sample_repo)
    index = indexer.index_repository()

    assert len(index.indexed_files) >= 2
    assert "calculate_average" in index.symbol_table
    assert "process_data" in index.symbol_table
    assert len(index.test_files) >= 1

    # Check invalid repo path
    with pytest.raises(FileNotFoundError):
        SafeRepoIndexer(os.path.join(sample_repo, "non_existent_dir_12345"))


def test_traceback_parser():
    tb_text = """
Traceback (most recent call last):
  File "main.py", line 6, in calculate_average
    return total / len(numbers)
ZeroDivisionError: division by zero
"""
    parsed = TracebackParser.parse(tb_text)
    assert parsed.error_type == "ZeroDivisionError"
    assert len(parsed.frames) == 1
    assert parsed.frames[0].line_number == 6
    assert parsed.frames[0].function_name == "calculate_average"


def test_fault_localisation(sample_repo):
    engine = PatchPilotEngine(sample_repo)
    traceback_sample = """
Traceback (most recent call last):
  File "main.py", line 6, in calculate_average
    return total / len(numbers)
ZeroDivisionError: division by zero
"""
    candidates = engine.localiser.rank_candidates(
        bug_description="calculate_average crashes with ZeroDivisionError when empty",
        parsed_traceback=TracebackParser.parse(traceback_sample),
        top_k=5,
    )

    assert len(candidates) > 0
    top = candidates[0]
    assert top.symbol_name == "calculate_average"
    assert top.features.traceback_score > 0.5
    assert top.features.total_score > 0.5


def test_evidence_selection_budget(sample_repo):
    engine = PatchPilotEngine(sample_repo)
    candidates = engine.localiser.rank_candidates(
        bug_description="Bug in calculate_average function",
        top_k=5,
    )
    pool = engine.evidence_selector.build_candidate_pool(candidates)
    
    # Test budget limit
    small_budget = 50
    bundle_adaptive = engine.evidence_selector.select(
        strategy=EvidenceStrategyType.ADAPTIVE_EVIDENCE,
        token_budget=small_budget,
        pool=pool,
    )
    assert bundle_adaptive.total_estimated_tokens <= small_budget or len(bundle_adaptive.items) <= 1
    assert bundle_adaptive.strategy == EvidenceStrategyType.ADAPTIVE_EVIDENCE


def test_token_counter():
    count, method = count_tokens("def foo():\n    return 42\n")
    assert count > 0
    assert "tiktoken" in method or "heuristic" in method


def test_patch_manager_revert(sample_repo):
    patcher = PatchManager(sample_repo)
    target = os.path.join(sample_repo, "main.py")
    with open(target, "r", encoding="utf-8") as f:
        original = f.read()

    new_content = original + "\n# Modified line\n"
    applied = patcher.apply_patch_safely(target, new_content)
    assert applied is True

    # Revert
    patcher.revert_all()
    with open(target, "r", encoding="utf-8") as f:
        reverted = f.read()
    assert reverted == original


def test_end_to_end_mock_diagnosis(sample_repo):
    engine = PatchPilotEngine(sample_repo)
    trace = engine.diagnose_bug(
        bug_description="ZeroDivisionError when numbers list is empty in calculate_average",
        raw_traceback="""File "main.py", line 6, in calculate_average\nZeroDivisionError: division by zero""",
        strategy=EvidenceStrategyType.ADAPTIVE_EVIDENCE,
        token_budget=2000,
    )

    assert trace.task_id is not None
    assert len(trace.top_candidates) > 0
    assert trace.diagnosis is not None
    assert trace.diagnosis.validation_status == "VALIDATED"
    assert trace.accounting.llm_call_count == 1
    assert trace.accounting.total_tokens > 0
