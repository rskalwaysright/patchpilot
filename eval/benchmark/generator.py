import os
import shutil
import tempfile
from typing import Dict
from eval.benchmark.cases import BENCHMARK_CASES, BenchmarkCase


class BenchmarkRepoGenerator:
    @staticmethod
    def materialize_case(case: BenchmarkCase, target_dir: Optional[str] = None) -> str:
        dir_path = target_dir or tempfile.mkdtemp(prefix=f"patchpilot_bench_{case.case_id}_")
        
        for rel_path, content in case.files.items():
            full_path = os.path.join(dir_path, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

        # Create __init__.py in directories to make modules importable
        for root, dirs, _ in os.walk(dir_path):
            init_file = os.path.join(root, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w", encoding="utf-8") as f:
                    f.write("")

        return dir_path

    @staticmethod
    def cleanup_case(dir_path: str):
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
