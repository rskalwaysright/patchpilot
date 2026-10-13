import ast
import hashlib
from typing import List, Optional, Set
from patchpilot.models import SymbolInfo, SymbolType


class ASTSymbolExtractor(ast.NodeVisitor):
    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.symbols: List[SymbolInfo] = []
        self.imports: List[str] = []
        self.current_class: Optional[str] = None
        self.callees: Set[str] = set()

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            self.imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class = self.current_class
        self.current_class = node.name

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)
        snippet = "\n".join(self.lines[start_line - 1 : end_line])
        content_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()

        docstring = ast.get_docstring(node)

        self.symbols.append(
            SymbolInfo(
                name=node.name,
                symbol_type=SymbolType.CLASS,
                file_path=self.file_path,
                start_line=start_line,
                end_line=end_line,
                parent_class=prev_class,
                parameters=[],
                docstring=docstring,
                callees=[],
                content_hash=content_hash,
            )
        )

        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_func(node)

    def _process_func(self, node):
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)
        snippet = "\n".join(self.lines[start_line - 1 : end_line])
        content_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()

        params = [arg.arg for arg in node.args.args]
        docstring = ast.get_docstring(node)

        # Collect calls inside this function
        old_callees = self.callees
        self.callees = set()
        for stmt in node.body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        self.callees.add(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        self.callees.add(child.func.attr)

        func_callees = sorted(list(self.callees))
        self.callees = old_callees

        sym_type = SymbolType.METHOD if self.current_class else SymbolType.FUNCTION
        full_name = f"{self.current_class}.{node.name}" if self.current_class else node.name

        self.symbols.append(
            SymbolInfo(
                name=full_name,
                symbol_type=sym_type,
                file_path=self.file_path,
                start_line=start_line,
                end_line=end_line,
                parent_class=self.current_class,
                parameters=params,
                docstring=docstring,
                callees=func_callees,
                content_hash=content_hash,
            )
        )

        # Do not recursively visit function internal functions as members of the outer class
        prev_class = self.current_class
        self.generic_visit(node)
        self.current_class = prev_class
