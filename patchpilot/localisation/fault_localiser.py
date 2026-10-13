import os
import re
from typing import Dict, List, Optional, Set, Tuple
from patchpilot.models import (
    FeatureBreakdown,
    ParsedTraceback,
    RankedCandidate,
    RepoIndex,
    SymbolInfo,
)


class FaultLocaliser:
    WEIGHT_TRACEBACK = 0.40
    WEIGHT_SYMBOL_OVERLAP = 0.25
    WEIGHT_FAILING_TEST = 0.15
    WEIGHT_CALL_GRAPH = 0.15
    WEIGHT_STATIC = 0.05

    def __init__(self, index: RepoIndex):
        self.index = index

    def rank_candidates(
        self,
        bug_description: str,
        parsed_traceback: Optional[ParsedTraceback] = None,
        top_k: int = 5,
    ) -> List[RankedCandidate]:
        words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", bug_description.lower()))
        
        # Collect traceback lines and files
        tb_frames_by_file: Dict[str, List[int]] = {}
        tb_functions: Set[str] = set()

        if parsed_traceback and parsed_traceback.frames:
            for frame in parsed_traceback.frames:
                norm_frame_path = os.path.normpath(frame.file_path).lower()
                tb_frames_by_file.setdefault(norm_frame_path, []).append(frame.line_number)
                if frame.function_name and frame.function_name != "<unknown>":
                    tb_functions.add(frame.function_name.lower())

        candidates: List[Tuple[SymbolInfo, FeatureBreakdown, str]] = []

        # Iterate over all indexed symbols
        for symbol_list in self.index.symbol_table.values():
            for sym in symbol_list:
                # Do not duplicate if registered under multiple keys
                if any(c[0] is sym for c in candidates):
                    continue

                norm_sym_path = os.path.normpath(sym.file_path).lower()
                rel_sym_path = os.path.relpath(sym.file_path, self.index.repo_path).replace("\\", "/")

                # Feature 1: Traceback & Line Number relevance
                tb_score = 0.0
                tb_reason = []
                for tb_file, lines in tb_frames_by_file.items():
                    # Check if file matches (by full path or basename/relative match)
                    if tb_file == norm_sym_path or norm_sym_path.endswith(tb_file) or tb_file.endswith(norm_sym_path) or os.path.basename(tb_file) == os.path.basename(norm_sym_path):
                        for line in lines:
                            if sym.start_line <= line <= sym.end_line:
                                tb_score = max(tb_score, 1.0)
                                tb_reason.append(f"Direct traceback hit at line {line}")
                            elif abs(sym.start_line - line) <= 15 or abs(sym.end_line - line) <= 15:
                                tb_score = max(tb_score, 0.6)
                                tb_reason.append(f"Traceback frame near candidate ({line})")

                if sym.name.lower() in tb_functions or (sym.name.split(".")[-1].lower() in tb_functions):
                    tb_score = max(tb_score, 0.8)
                    tb_reason.append(f"Function name '{sym.name}' named in traceback")

                # Feature 2: Symbol and identifier overlap
                sym_tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", sym.name.lower()))
                for p in sym.parameters:
                    sym_tokens.update(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", p.lower()))
                
                overlap = sym_tokens.intersection(words)
                overlap_score = min(1.0, len(overlap) / max(1, len(sym_tokens))) if overlap else 0.0
                overlap_reason = f"Matches query terms: {', '.join(sorted(list(overlap)))}" if overlap else ""

                # Feature 3: Failing-test relevance & test function handling
                failing_test_score = 0.0
                is_in_test = "test" in os.path.basename(sym.file_path).lower()
                test_penalty = 1.0
                if is_in_test:
                    # Test functions should be deprioritized as fault locations compared to production code
                    test_penalty = 0.35
                    if tb_score > 0.5:
                        failing_test_score = 0.4
                else:
                    # Check if any test file imports or calls this candidate
                    for test_path in self.index.test_files:
                        test_idx = self.index.indexed_files.get(test_path)
                        if test_idx and any(sym.name.split(".")[-1] in s.name for s in test_idx.symbols):
                            failing_test_score = 0.5

                # Feature 4: Call graph proximity to traceback functions
                call_graph_score = 0.0
                if tb_functions:
                    # Candidate calls traceback function
                    for callee in sym.callees:
                        if callee.lower() in tb_functions:
                            call_graph_score = 0.7
                            break
                    # Candidate is called by traceback function
                    if sym.name in self.index.reverse_call_graph:
                        for caller in self.index.reverse_call_graph[sym.name]:
                            if caller.lower() in tb_functions:
                                call_graph_score = max(call_graph_score, 0.9)
                                break

                # Feature 5: Static findings / pattern clues
                static_score = 0.0
                if parsed_traceback and parsed_traceback.error_type:
                    err = parsed_traceback.error_type.lower()
                    if "zerodivision" in err and "/" in sym.callees:
                        static_score = 0.5
                    elif "indexerror" in err or "keyerror" in err:
                        static_score = 0.3
                    elif "attributeerror" in err or "typeerror" in err:
                        static_score = 0.3

                raw_total = (
                    self.WEIGHT_TRACEBACK * tb_score
                    + self.WEIGHT_SYMBOL_OVERLAP * overlap_score
                    + self.WEIGHT_FAILING_TEST * failing_test_score
                    + self.WEIGHT_CALL_GRAPH * call_graph_score
                    + self.WEIGHT_STATIC * static_score
                )
                total_score = raw_total * test_penalty

                if total_score > 0.02:
                    breakdown = FeatureBreakdown(
                        traceback_score=round(tb_score, 3),
                        symbol_overlap_score=round(overlap_score, 3),
                        failing_test_proximity_score=round(failing_test_score, 3),
                        call_graph_proximity_score=round(call_graph_score, 3),
                        static_finding_score=round(static_score, 3),
                        total_score=round(total_score, 4),
                    )

                    reasons = []
                    if tb_reason:
                        reasons.extend(tb_reason)
                    if overlap_reason:
                        reasons.append(overlap_reason)
                    if call_graph_score > 0:
                        reasons.append("Connected to traceback in call graph")
                    if failing_test_score > 0:
                        reasons.append("Referenced by repository tests")
                    
                    rationale = "; ".join(reasons) if reasons else "Keyword / structural alignment"
                    candidates.append((sym, breakdown, rationale))

        # Sort descending by total score, then by start line
        candidates.sort(key=lambda c: (c[1].total_score, -c[0].start_line), reverse=True)

        results: List[RankedCandidate] = []
        for sym, breakdown, rationale in candidates[:top_k]:
            results.append(
                RankedCandidate(
                    symbol_name=sym.name,
                    file_path=sym.file_path,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    symbol_type=sym.symbol_type,
                    features=breakdown,
                    rationale=rationale,
                )
            )

        return results
