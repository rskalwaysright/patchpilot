import os
from typing import Dict, List, Optional, Set, Tuple
from patchpilot.models import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceStrategyType,
    EvidenceType,
    ParsedTraceback,
    RankedCandidate,
    RepoIndex,
)
from patchpilot.evidence.token_counter import count_tokens


class EvidenceSelector:
    def __init__(self, index: RepoIndex):
        self.index = index

    def build_candidate_pool(
        self,
        ranked_candidates: List[RankedCandidate],
        parsed_traceback: Optional[ParsedTraceback] = None,
        test_failure_summary: Optional[str] = None,
    ) -> List[EvidenceItem]:
        pool: List[EvidenceItem] = []
        item_counter = 0

        # 1. Candidate functions
        for rank, cand in enumerate(ranked_candidates):
            content = self._read_lines(cand.file_path, cand.start_line, cand.end_line)
            tokens, method = count_tokens(content)
            item_counter += 1
            pool.append(
                EvidenceItem(
                    item_id=f"cand_{item_counter}",
                    file_path=cand.file_path,
                    start_line=cand.start_line,
                    end_line=cand.end_line,
                    code_content=content,
                    evidence_type=EvidenceType.CANDIDATE_FUNCTION,
                    relevance_score=cand.features.total_score,
                    estimated_token_count=tokens,
                    relation_to_fault=f"Rank #{rank+1} candidate function: {cand.symbol_name} ({cand.rationale})",
                    provenance=f"ast_index:{method}",
                )
            )

            # 2. Callers / Call graph context for top 2 candidates
            if rank < 2 and cand.symbol_name in self.index.reverse_call_graph:
                callers = self.index.reverse_call_graph[cand.symbol_name]
                for caller_name in callers[:2]:
                    caller_syms = self.index.symbol_table.get(caller_name, [])
                    if caller_syms:
                        csym = caller_syms[0]
                        c_content = self._read_lines(csym.file_path, csym.start_line, csym.end_line)
                        c_tokens, c_method = count_tokens(c_content)
                        item_counter += 1
                        pool.append(
                            EvidenceItem(
                                item_id=f"caller_{item_counter}",
                                file_path=csym.file_path,
                                start_line=csym.start_line,
                                end_line=csym.end_line,
                                code_content=c_content,
                                evidence_type=EvidenceType.CALLER_CONTEXT,
                                relevance_score=round(cand.features.total_score * 0.65, 3),
                                estimated_token_count=c_tokens,
                                relation_to_fault=f"Direct caller of {cand.symbol_name}",
                                provenance=f"call_graph:{c_method}",
                            )
                        )

        # 3. Traceback frames (actual lines cited in traceback if not already covered)
        if parsed_traceback:
            for f_idx, frame in enumerate(parsed_traceback.frames):
                full_path = self._resolve_frame_file(frame.file_path)
                if not full_path or not os.path.exists(full_path):
                    continue
                start_l = max(1, frame.line_number - 4)
                end_l = frame.line_number + 4
                f_content = self._read_lines(full_path, start_l, end_l)
                f_tokens, f_method = count_tokens(f_content)
                item_counter += 1
                pool.append(
                    EvidenceItem(
                        item_id=f"tb_{item_counter}",
                        file_path=full_path,
                        start_line=start_l,
                        end_line=end_l,
                        code_content=f_content,
                        evidence_type=EvidenceType.TRACEBACK_FRAME,
                        relevance_score=0.90 - (f_idx * 0.05),
                        estimated_token_count=f_tokens,
                        relation_to_fault=f"Traceback frame {f_idx+1} at line {frame.line_number}",
                        provenance=f"traceback_parser:{f_method}",
                    )
                )

        # 4. Related test cases
        for test_file in self.index.test_files[:3]:
            findex = self.index.indexed_files.get(test_file)
            if not findex:
                continue
            for tsym in findex.symbols:
                if any(c.symbol_name.split(".")[-1].lower() in tsym.name.lower() for c in ranked_candidates[:2]):
                    t_content = self._read_lines(tsym.file_path, tsym.start_line, tsym.end_line)
                    t_tokens, t_method = count_tokens(t_content)
                    item_counter += 1
                    pool.append(
                        EvidenceItem(
                            item_id=f"test_{item_counter}",
                            file_path=tsym.file_path,
                            start_line=tsym.start_line,
                            end_line=tsym.end_line,
                            code_content=t_content,
                            evidence_type=EvidenceType.RELATED_TEST,
                            relevance_score=0.75,
                            estimated_token_count=t_tokens,
                            relation_to_fault=f"Test case '{tsym.name}' referencing candidate",
                            provenance=f"test_index:{t_method}",
                        )
                    )

        # 5. Concise test failure summary if available
        if test_failure_summary and test_failure_summary.strip():
            sum_tokens, sum_method = count_tokens(test_failure_summary)
            item_counter += 1
            pool.append(
                EvidenceItem(
                    item_id=f"fail_{item_counter}",
                    file_path="<test_execution_stdout>",
                    start_line=1,
                    end_line=len(test_failure_summary.splitlines()),
                    code_content=test_failure_summary.strip(),
                    evidence_type=EvidenceType.TEST_FAILURE_SUMMARY,
                    relevance_score=0.95,
                    estimated_token_count=sum_tokens,
                    relation_to_fault="Concise test runner failure summary",
                    provenance=f"test_runner:{sum_method}",
                )
            )

        return pool

    def select(
        self,
        strategy: EvidenceStrategyType,
        token_budget: int,
        pool: List[EvidenceItem],
    ) -> EvidenceBundle:
        if strategy == EvidenceStrategyType.DIRECT_PROMPT:
            # Baseline 1: No repository evidence attached
            return EvidenceBundle(
                strategy=strategy,
                target_budget_tokens=token_budget,
                total_estimated_tokens=0,
                items=[],
                excluded_items=pool,
                selection_log=["Strategy: direct_prompt; excluded all repository evidence."],
            )

        if strategy == EvidenceStrategyType.TRACEBACK_TEXT_SEARCH:
            # Baseline 2: Only include raw traceback frames and immediate matches
            tb_items = [it for it in pool if it.evidence_type in {EvidenceType.TRACEBACK_FRAME, EvidenceType.TEST_FAILURE_SUMMARY}]
            return self._pack_greedy(tb_items, [it for it in pool if it not in tb_items], token_budget, strategy)

        if strategy == EvidenceStrategyType.FIXED_CONTEXT:
            # Baseline 3: Takes first N items in default candidate rank order until budget is reached
            return self._pack_greedy(pool, [], token_budget, strategy)

        if strategy == EvidenceStrategyType.HEURISTIC_RETRIEVAL:
            # Baseline 4: Sort purely by relevance score, greedily pack
            sorted_pool = sorted(pool, key=lambda x: x.relevance_score, reverse=True)
            return self._pack_greedy(sorted_pool, [], token_budget, strategy)

        # Strategy C: Adaptive Evidence Selection
        return self._adaptive_selection(pool, token_budget)

    def _pack_greedy(
        self,
        ordered_items: List[EvidenceItem],
        excluded_prior: List[EvidenceItem],
        budget: int,
        strategy: EvidenceStrategyType,
    ) -> EvidenceBundle:
        included: List[EvidenceItem] = []
        excluded: List[EvidenceItem] = list(excluded_prior)
        current_tokens = 0
        logs = [f"Applying greedy packing for strategy {strategy.value} under budget {budget} tokens."]

        for item in ordered_items:
            # Check overlap / redundancy
            if any(self._is_subsumed(item, inc) for inc in included):
                item_copy = item.model_copy()
                item_copy.is_included = False
                item_copy.exclusion_reason = "Subsumed by already included larger snippet"
                excluded.append(item_copy)
                logs.append(f"Excluded {item.item_id}: subsumed by existing snippet")
                continue

            if current_tokens + item.estimated_token_count <= budget:
                included.append(item)
                current_tokens += item.estimated_token_count
                logs.append(f"Included {item.item_id} ({item.estimated_token_count} tokens, cum: {current_tokens})")
            else:
                item_copy = item.model_copy()
                item_copy.is_included = False
                item_copy.exclusion_reason = f"Budget limit reached ({current_tokens} + {item.estimated_token_count} > {budget})"
                excluded.append(item_copy)
                logs.append(f"Excluded {item.item_id}: exceeds remaining budget")

        return EvidenceBundle(
            strategy=strategy,
            target_budget_tokens=budget,
            total_estimated_tokens=current_tokens,
            items=included,
            excluded_items=excluded,
            selection_log=logs,
        )

    def _adaptive_selection(
        self,
        pool: List[EvidenceItem],
        budget: int,
    ) -> EvidenceBundle:
        """
        Adaptive selection policy:
        Balances relevance and diversity under token constraint:
        - Prevents bloating prompt with multiple snippets from the same file/symbol.
        - Applies marginal utility penalty if a category (e.g. caller context) is already saturated.
        - Prefers concise test failures and primary fault functions.
        - Progressive expansion: if budget allows, includes caller / test context.
        """
        logs = [f"Running Adaptive Evidence Selection (budget={budget} tokens, candidate pool={len(pool)} items)."]
        
        # Deduplicate subsumed snippets first
        unique_pool: List[EvidenceItem] = []
        excluded: List[EvidenceItem] = []
        for it in pool:
            if any(self._is_subsumed(it, u) for u in unique_pool):
                it_copy = it.model_copy()
                it_copy.is_included = False
                it_copy.exclusion_reason = "Redundant snippet subsumed by another item"
                excluded.append(it_copy)
            else:
                unique_pool.append(it)

        # Iterative marginal benefit selection
        selected: List[EvidenceItem] = []
        current_tokens = 0
        remaining = list(unique_pool)

        # Track diversity dimensions
        included_files: Set[str] = set()
        type_counts: Dict[EvidenceType, int] = {}

        while remaining:
            best_item = None
            best_marginal_density = -1.0
            best_idx = -1

            for idx, candidate in enumerate(remaining):
                token_cost = max(1, candidate.estimated_token_count)
                if current_tokens + token_cost > budget:
                    continue

                # Compute diversity & complementarity discount
                diversity_penalty = 1.0

                # Same file penalty if > 2 snippets already in that file
                file_snippets = sum(1 for s in selected if s.file_path == candidate.file_path)
                if file_snippets >= 1:
                    diversity_penalty *= 0.75 ** file_snippets

                # Category saturation penalty
                curr_type_count = type_counts.get(candidate.evidence_type, 0)
                if curr_type_count >= 1:
                    diversity_penalty *= 0.70 ** curr_type_count

                # Boost primary candidate function and concise test failure
                priority_boost = 1.0
                if candidate.evidence_type == EvidenceType.CANDIDATE_FUNCTION and curr_type_count == 0:
                    priority_boost = 1.3
                elif candidate.evidence_type == EvidenceType.TEST_FAILURE_SUMMARY:
                    priority_boost = 1.4

                effective_value = candidate.relevance_score * diversity_penalty * priority_boost
                marginal_density = effective_value / (token_cost ** 0.5)  # sublinear token penalty for rich functions

                if marginal_density > best_marginal_density:
                    best_marginal_density = marginal_density
                    best_item = candidate
                    best_idx = idx

            if best_item is None:
                # No more candidates fit within the remaining budget
                break

            # Commit selection
            selected.append(best_item)
            current_tokens += best_item.estimated_token_count
            included_files.add(best_item.file_path)
            type_counts[best_item.evidence_type] = type_counts.get(best_item.evidence_type, 0) + 1
            remaining.pop(best_idx)
            logs.append(
                f"Selected {best_item.item_id} [{best_item.evidence_type.value}] "
                f"({best_item.estimated_token_count} toks, density={round(best_marginal_density, 4)}, total={current_tokens}/{budget})"
            )

        # Any unselected items are marked excluded
        for rem in remaining:
            rem_copy = rem.model_copy()
            rem_copy.is_included = False
            rem_copy.exclusion_reason = f"Lower marginal information density or exceeds budget ({current_tokens} toks used)"
            excluded.append(rem_copy)

        logs.append(f"Adaptive selection complete. Selected {len(selected)} items, {current_tokens} tokens total.")

        return EvidenceBundle(
            strategy=EvidenceStrategyType.ADAPTIVE_EVIDENCE,
            target_budget_tokens=budget,
            total_estimated_tokens=current_tokens,
            items=selected,
            excluded_items=excluded,
            selection_log=logs,
        )

    def _is_subsumed(self, item_a: EvidenceItem, item_b: EvidenceItem) -> bool:
        """Returns True if item_a is completely contained within item_b in the same file."""
        if item_a.file_path != item_b.file_path:
            return False
        if item_a.file_path == "<test_execution_stdout>":
            return False
        return item_b.start_line <= item_a.start_line and item_b.end_line >= item_a.end_line

    def _read_lines(self, file_path: str, start_line: int, end_line: int) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            sub = lines[max(0, start_line - 1) : end_line]
            return "".join(sub)
        except Exception as e:
            return f"# Could not read lines {start_line}-{end_line} of {file_path}: {e}\n"

    def _resolve_frame_file(self, raw_path: str) -> Optional[str]:
        if os.path.isabs(raw_path) and os.path.exists(raw_path):
            return raw_path
        # Try relative to repo
        joined = os.path.join(self.index.repo_path, raw_path)
        if os.path.exists(joined):
            return joined
        # Try matching by basename
        bname = os.path.basename(raw_path)
        for p in self.index.indexed_files.keys():
            if os.path.basename(p) == bname:
                return p
        return None
