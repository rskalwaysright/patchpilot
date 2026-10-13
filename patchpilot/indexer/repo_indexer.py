import os
import ast
import hashlib
import fnmatch
from typing import Dict, List, Optional
from patchpilot.models import FileIndex, RepoIndex, SymbolInfo
from patchpilot.indexer.ast_visitor import ASTSymbolExtractor


EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    ".env",
    "build",
    "dist",
    ".egg-info",
    "node_modules",
    ".idea",
    ".vscode",
    ".coverage",
    "htmlcov",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyd",
    ".pyo",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
    ".zip",
    ".tar",
    ".gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".env",
    ".key",
    ".pem",
}

MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB


class SafeRepoIndexer:
    def __init__(self, repo_path: str):
        self.repo_path = self._validate_and_canonicalize(repo_path)
        self._gitignore_patterns = self._load_gitignore()
        self._cache: Dict[str, FileIndex] = {}

    def _validate_and_canonicalize(self, path: str) -> str:
        if not path or not isinstance(path, str):
            raise ValueError("Repository path must be a non-empty string.")
        
        canonical = os.path.abspath(os.path.realpath(path))
        if not os.path.exists(canonical):
            raise FileNotFoundError(f"Repository directory does not exist: {canonical}")
        if not os.path.isdir(canonical):
            raise NotADirectoryError(f"Target path is not a directory: {canonical}")
            
        return canonical

    def _load_gitignore(self) -> List[str]:
        patterns = []
        gitignore_path = os.path.join(self.repo_path, ".gitignore")
        if os.path.exists(gitignore_path) and os.path.isfile(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass
        return patterns

    def is_ignored(self, rel_path: str) -> bool:
        norm_rel = rel_path.replace("\\", "/")
        parts = norm_rel.split("/")
        
        # Check against default excluded directories
        for part in parts:
            if part in EXCLUDE_DIRS:
                return True

        # Check gitignore patterns
        for pattern in self._gitignore_patterns:
            pat = pattern.rstrip("/")
            if fnmatch.fnmatch(norm_rel, pat) or fnmatch.fnmatch(parts[-1], pat):
                return True
            if norm_rel.startswith(pat + "/"):
                return True
        return False

    def compute_file_hash(self, file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def index_repository(self) -> RepoIndex:
        indexed_files: Dict[str, FileIndex] = {}
        symbol_table: Dict[str, List[SymbolInfo]] = {}
        call_graph: Dict[str, List[str]] = {}
        reverse_call_graph: Dict[str, List[str]] = {}
        test_files: List[str] = []

        for root, dirs, files in os.walk(self.repo_path):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not self.is_ignored(os.path.relpath(os.path.join(root, d), self.repo_path))]

            for file_name in files:
                abs_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(abs_path, self.repo_path)

                if self.is_ignored(rel_path):
                    continue

                _, ext = os.path.splitext(file_name)
                if ext.lower() in EXCLUDE_EXTENSIONS or ext.lower() != ".py":
                    continue

                try:
                    stat = os.stat(abs_path)
                    if stat.st_size > MAX_FILE_SIZE_BYTES:
                        continue
                except OSError:
                    continue

                # Compute content hash for incremental caching
                file_hash = self.compute_file_hash(abs_path)
                cached = self._cache.get(abs_path)

                if cached and cached.content_hash == file_hash:
                    file_idx = cached
                else:
                    file_idx = self._parse_file(abs_path, rel_path, file_hash)
                    self._cache[abs_path] = file_idx

                indexed_files[abs_path] = file_idx
                if file_idx.is_test_file:
                    test_files.append(abs_path)

                # Populate symbol table
                for sym in file_idx.symbols:
                    symbol_table.setdefault(sym.name, []).append(sym)
                    # Also register unqualified name if method
                    if "." in sym.name:
                        base_name = sym.name.split(".")[-1]
                        symbol_table.setdefault(base_name, []).append(sym)

                    # Build call graph
                    call_graph[sym.name] = sym.callees
                    for callee in sym.callees:
                        reverse_call_graph.setdefault(callee, []).append(sym.name)

        return RepoIndex(
            repo_path=self.repo_path,
            indexed_files=indexed_files,
            symbol_table=symbol_table,
            call_graph=call_graph,
            reverse_call_graph=reverse_call_graph,
            test_files=sorted(test_files),
        )

    def _parse_file(self, abs_path: str, rel_path: str, file_hash: str) -> FileIndex:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return FileIndex(
                file_path=abs_path,
                relative_path=rel_path,
                content_hash=file_hash,
                line_count=0,
                symbols=[],
                imports=[],
                is_test_file=False,
            )

        line_count = len(content.splitlines())
        is_test = (
            "test" in os.path.basename(abs_path).lower()
            or "tests" in rel_path.replace("\\", "/").split("/")
        )

        try:
            tree = ast.parse(content, filename=abs_path)
            extractor = ASTSymbolExtractor(abs_path, content)
            extractor.visit(tree)
            symbols = extractor.symbols
            imports = extractor.imports
        except SyntaxError:
            # Code might have syntax error currently being debugged
            symbols = []
            imports = []

        return FileIndex(
            file_path=abs_path,
            relative_path=rel_path,
            content_hash=file_hash,
            line_count=line_count,
            symbols=symbols,
            imports=imports,
            is_test_file=is_test,
        )
