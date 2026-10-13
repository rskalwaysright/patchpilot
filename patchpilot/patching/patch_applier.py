import os
import re
import difflib
from typing import Dict, List, Optional, Tuple
from patchpilot.models import PatchVerificationResult, VerificationOutcome
from patchpilot.sandbox.test_runner import SafeTestRunner


class PatchManager:
    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.runner = SafeTestRunner(self.repo_path)
        self._backups: Dict[str, str] = {}

    def parse_unified_diff(self, diff_text: str) -> List[Tuple[str, str, str]]:
        """
        Parses a unified diff into a list of tuples: (file_path, old_content, new_content).
        Supports standard diff / git diff formatting.
        """
        # Simple robust multi-file patch parser
        changes = []
        file_diffs = re.split(r"(?:^|\n)--- (?:a/)?", diff_text)
        
        for chunk in file_diffs:
            if not chunk.strip():
                continue
            lines = chunk.splitlines()
            header_match = re.match(r"^([^\s\t\n]+)", lines[0])
            if not header_match:
                continue
            rel_file = header_match.group(1).lstrip("b/").strip()
            
            # Find the target file
            target_path = os.path.join(self.repo_path, rel_file)
            if not os.path.exists(target_path):
                # Search by basename
                found = False
                for root, _, files in os.walk(self.repo_path):
                    if os.path.basename(rel_file) in files:
                        target_path = os.path.join(root, os.path.basename(rel_file))
                        found = True
                        break
                if not found:
                    continue

            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                original_text = f.read()

            applied_text = self._apply_hunks(original_text, chunk)
            if applied_text is not None:
                changes.append((target_path, original_text, applied_text))

        return changes

    def _apply_hunks(self, original_text: str, diff_chunk: str) -> Optional[str]:
        orig_lines = original_text.splitlines(keepends=True)
        hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        
        lines = diff_chunk.splitlines(keepends=True)
        curr_orig_idx = 0
        result_lines = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            m = hunk_header.match(line)
            if m:
                old_start = int(m.group(1)) - 1
                # Copy unmodified lines up to old_start
                while curr_orig_idx < old_start and curr_orig_idx < len(orig_lines):
                    result_lines.append(orig_lines[curr_orig_idx])
                    curr_orig_idx += 1

                i += 1
                while i < len(lines) and not hunk_header.match(lines[i]):
                    hline = lines[i]
                    if hline.startswith("+"):
                        result_lines.append(hline[1:])
                    elif hline.startswith("-"):
                        curr_orig_idx += 1
                    elif hline.startswith(" "):
                        result_lines.append(orig_lines[curr_orig_idx] if curr_orig_idx < len(orig_lines) else hline[1:])
                        curr_orig_idx += 1
                    i += 1
                continue
            i += 1

        while curr_orig_idx < len(orig_lines):
            result_lines.append(orig_lines[curr_orig_idx])
            curr_orig_idx += 1

        return "".join(result_lines) if result_lines else None

    def apply_patch_safely(self, target_file: str, new_content: str) -> bool:
        if not os.path.exists(target_file):
            return False
            
        # Store backup
        if target_file not in self._backups:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                self._backups[target_file] = f.read()

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    def revert_all(self):
        for path, original in self._backups.items():
            if os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(original)
        self._backups.clear()

    def verify_patch(
        self,
        diff_text: str,
        reproduction_test: Optional[str] = None,
        regression_test: Optional[str] = None,
    ) -> PatchVerificationResult:
        changes = self.parse_unified_diff(diff_text)
        if not changes:
            return PatchVerificationResult(
                applied=False,
                diff=diff_text,
                outcome=VerificationOutcome.INCONCLUSIVE,
                message="Could not parse valid diff hunks matching repository files.",
            )

        # Apply changes
        for target_file, orig, new_c in changes:
            self.apply_patch_safely(target_file, new_c)

        # Run reproduction test
        repro_res = None
        if reproduction_test:
            repro_res = self.runner.run_tests(target_test=reproduction_test)
            if repro_res.is_timeout:
                self.revert_all()
                return PatchVerificationResult(
                    applied=True,
                    diff=diff_text,
                    outcome=VerificationOutcome.TIMEOUT,
                    reproduction_test_result=repro_res,
                    message="Reproduction test timed out after applying patch. Reverted modifications.",
                )
            if repro_res.failed_count > 0 or repro_res.exit_status != 0:
                self.revert_all()
                return PatchVerificationResult(
                    applied=True,
                    diff=diff_text,
                    outcome=VerificationOutcome.REPRODUCTION_FAILED,
                    reproduction_test_result=repro_res,
                    message="Reproduction test still failed after patch application. Reverted modifications.",
                )

        # Run regression tests
        reg_res = self.runner.run_tests(target_test=regression_test)
        if reg_res.is_timeout:
            self.revert_all()
            return PatchVerificationResult(
                applied=True,
                diff=diff_text,
                outcome=VerificationOutcome.TIMEOUT,
                reproduction_test_result=repro_res,
                regression_test_result=reg_res,
                message="Regression tests timed out. Reverted modifications.",
            )

        if reg_res.failed_count > 0 or reg_res.exit_status != 0:
            self.revert_all()
            return PatchVerificationResult(
                applied=True,
                diff=diff_text,
                outcome=VerificationOutcome.REGRESSION_FAILED,
                reproduction_test_result=repro_res,
                regression_test_result=reg_res,
                message=f"Regression tests failed ({reg_res.failed_count} failures). Reverted modifications.",
            )

        return PatchVerificationResult(
            applied=True,
            diff=diff_text,
            outcome=VerificationOutcome.VERIFIED,
            reproduction_test_result=repro_res,
            regression_test_result=reg_res,
            message="VERIFIED: All reproduction and regression tests passed without errors.",
        )
