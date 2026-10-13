from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    CANDIDATE_FUNCTION = "candidate_function"
    TRACEBACK_FRAME = "traceback_frame"
    CALLER_CONTEXT = "caller_context"
    RELATED_TEST = "related_test"
    TEST_FAILURE_SUMMARY = "test_failure_summary"
    STATIC_ANALYSIS = "static_analysis"


class EvidenceStrategyType(str, Enum):
    DIRECT_PROMPT = "direct_prompt"
    TRACEBACK_TEXT_SEARCH = "traceback_text_search"
    FIXED_CONTEXT = "fixed_context"
    HEURISTIC_RETRIEVAL = "heuristic_retrieval"
    ADAPTIVE_EVIDENCE = "adaptive_evidence"


class SymbolType(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    MODULE = "module"


class SymbolInfo(BaseModel):
    name: str
    symbol_type: SymbolType
    file_path: str
    start_line: int
    end_line: int
    parent_class: Optional[str] = None
    parameters: List[str] = Field(default_factory=list)
    docstring: Optional[str] = None
    callees: List[str] = Field(default_factory=list)
    content_hash: str


class FileIndex(BaseModel):
    file_path: str
    relative_path: str
    content_hash: str
    line_count: int
    symbols: List[SymbolInfo] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    is_test_file: bool = False


class RepoIndex(BaseModel):
    repo_path: str
    indexed_files: Dict[str, FileIndex] = Field(default_factory=dict)
    symbol_table: Dict[str, List[SymbolInfo]] = Field(default_factory=dict)
    call_graph: Dict[str, List[str]] = Field(default_factory=dict)
    reverse_call_graph: Dict[str, List[str]] = Field(default_factory=dict)
    test_files: List[str] = Field(default_factory=list)
    commit_or_head_hash: Optional[str] = None


class TracebackFrame(BaseModel):
    file_path: str
    relative_path: Optional[str] = None
    line_number: int
    function_name: str
    code_snippet: Optional[str] = None


class ParsedTraceback(BaseModel):
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    frames: List[TracebackFrame] = Field(default_factory=list)
    raw_traceback: str


class FeatureBreakdown(BaseModel):
    traceback_score: float = 0.0
    symbol_overlap_score: float = 0.0
    failing_test_proximity_score: float = 0.0
    call_graph_proximity_score: float = 0.0
    static_finding_score: float = 0.0
    total_score: float = 0.0


class RankedCandidate(BaseModel):
    symbol_name: str
    file_path: str
    start_line: int
    end_line: int
    symbol_type: SymbolType
    features: FeatureBreakdown
    rationale: str


class EvidenceItem(BaseModel):
    item_id: str
    file_path: str
    start_line: int
    end_line: int
    code_content: str
    evidence_type: EvidenceType
    relevance_score: float
    estimated_token_count: int
    relation_to_fault: str
    provenance: str
    is_included: bool = True
    exclusion_reason: Optional[str] = None


class EvidenceBundle(BaseModel):
    strategy: EvidenceStrategyType
    target_budget_tokens: int
    total_estimated_tokens: int
    items: List[EvidenceItem] = Field(default_factory=list)
    excluded_items: List[EvidenceItem] = Field(default_factory=list)
    selection_log: List[str] = Field(default_factory=list)


class DiagnosisOutput(BaseModel):
    root_cause_hypothesis: str
    supporting_evidence_references: List[str] = Field(default_factory=list)
    contradictory_evidence: Optional[str] = None
    missing_evidence: Optional[str] = None
    recommended_tests: List[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_explanation: str
    is_inconclusive: bool = False
    is_patch_justified: bool = False
    suggested_patch_diff: Optional[str] = None
    validation_status: str = "VALIDATED"  # VALIDATED | INVALID_CITATION | UNVERIFIED


class TestExecutionResult(BaseModel):
    test_command: str
    exit_status: int
    duration_seconds: float
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""
    summary: str = ""
    is_timeout: bool = False
    is_infra_error: bool = False


class VerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    REGRESSION_FAILED = "REGRESSION_FAILED"
    REPRODUCTION_FAILED = "REPRODUCTION_FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    TIMEOUT = "TIMEOUT"
    REVERTED = "REVERTED"


class PatchVerificationResult(BaseModel):
    applied: bool
    diff: str
    outcome: VerificationOutcome
    reproduction_test_result: Optional[TestExecutionResult] = None
    regression_test_result: Optional[TestExecutionResult] = None
    message: str


class CostAccounting(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    llm_call_count: int = 0
    budget_limit_tokens: int = 4000
    is_budget_exceeded: bool = False


class ExecutionTrace(BaseModel):
    task_id: str
    repo_path: str
    bug_description: str
    strategy_used: EvidenceStrategyType
    latency_seconds: float = 0.0
    top_candidates: List[RankedCandidate] = Field(default_factory=list)
    evidence_bundle: Optional[EvidenceBundle] = None
    diagnosis: Optional[DiagnosisOutput] = None
    patch_result: Optional[PatchVerificationResult] = None
    accounting: CostAccounting = Field(default_factory=CostAccounting)
    sandbox_mode: str = "subprocess_restricted"  # docker | subprocess_restricted | disabled
