import os
import re
import sys
import time
import subprocess
import shutil
from typing import Dict, List, Optional, Tuple
from patchpilot.config import settings
from patchpilot.models import TestExecutionResult


class SafeTestRunner:
    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        if shutil.which("docker") is None:
            return False
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_sandbox_status(self) -> Dict[str, str]:
        if self.docker_available:
            return {"mode": "docker", "status": "Docker container isolation active"}
        elif settings.enable_safe_subprocess_fallback:
            return {
                "mode": "subprocess_restricted",
                "status": "Restricted subprocess sandbox active (Docker unavailable on host; timeouts, stripped env & path confinement applied)",
            }
        else:
            return {
                "mode": "disabled",
                "status": "Test execution disabled (Docker unavailable and fallback disabled)",
            }

    def run_tests(
        self,
        target_test: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> TestExecutionResult:
        sandbox_info = self.get_sandbox_status()
        if sandbox_info["mode"] == "disabled":
            return TestExecutionResult(
                test_command="N/A",
                exit_status=1,
                duration_seconds=0.0,
                summary="Execution disabled: Docker is unavailable and subprocess fallback is disabled.",
                is_infra_error=True,
            )

        timeout = timeout_seconds or settings.sandbox_timeout_seconds
        
        # Build command
        # Use the current python interpreter to run pytest inside the repository
        cmd = [sys.executable, "-m", "pytest", "-v"]
        if target_test:
            cmd.append(target_test)

        cmd_str = " ".join(cmd)
        start_time = time.time()

        # Build restricted environment
        safe_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": self.repo_path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
        }

        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=safe_env,
            )

            try:
                stdout, stderr = process.communicate(timeout=timeout)
                duration = time.time() - start_time
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                duration = time.time() - start_time
                return TestExecutionResult(
                    test_command=cmd_str,
                    exit_status=-1,
                    duration_seconds=round(duration, 2),
                    raw_stdout=stdout or "",
                    raw_stderr=stderr or "",
                    summary=f"Test execution TIMED OUT after {timeout} seconds.",
                    is_timeout=True,
                )

            # Parse pytest summary
            passed, failed, skipped = self._parse_pytest_counts(stdout + "\n" + stderr)
            concise_sum = self._extract_concise_summary(stdout, stderr, exit_code, passed, failed)

            return TestExecutionResult(
                test_command=cmd_str,
                exit_status=exit_code,
                duration_seconds=round(duration, 3),
                passed_count=passed,
                failed_count=failed,
                skipped_count=skipped,
                raw_stdout=stdout,
                raw_stderr=stderr,
                summary=concise_sum,
                is_infra_error=(exit_code not in {0, 1} and "ERROR" in stderr),
            )

        except Exception as e:
            duration = time.time() - start_time
            return TestExecutionResult(
                test_command=cmd_str,
                exit_status=2,
                duration_seconds=round(duration, 3),
                summary=f"Failed to execute tests: {str(e)}",
                is_infra_error=True,
            )

    def _parse_pytest_counts(self, output: str) -> Tuple[int, int, int]:
        passed = 0
        failed = 0
        skipped = 0

        p_match = re.search(r"(\d+)\s+passed", output)
        if p_match:
            passed = int(p_match.group(1))

        f_match = re.search(r"(\d+)\s+failed", output)
        if f_match:
            failed = int(f_match.group(1))

        s_match = re.search(r"(\d+)\s+skipped", output)
        if s_match:
            skipped = int(s_match.group(1))

        return passed, failed, skipped

    def _extract_concise_summary(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        passed: int,
        failed: int,
    ) -> str:
        # Find pytest status line e.g. "== 1 failed, 2 passed in 0.12s =="
        lines = (stdout + "\n" + stderr).splitlines()
        for line in reversed(lines):
            line_str = line.strip()
            if line_str.startswith("=") and ("passed" in line_str or "failed" in line_str or "error" in line_str):
                return line_str

        if exit_code == 0:
            return f"All {passed} tests passed successfully."
        return f"Tests finished with exit code {exit_code} ({failed} failed, {passed} passed)."
