"""AST-only source inspection for the small C1 input scope."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
from typing import NoReturn

from testgen_agent.models import FunctionInfo, ImportInfo, SourceBranch, SourceInfo

from .source_reader import LoadedSource, MAX_SOURCE_BYTES, read_source


class SourceAnalysisError(ValueError):
    """A safe, classified analysis failure that callers can show directly."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path,
        line: int | None = None,
        offset: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.line = line
        self.offset = offset


class UnsupportedSourceError(SourceAnalysisError):
    """The file is valid Python but outside this project's stated scope."""


def analyze_source(
    source_path: str | Path,
    *,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> SourceInfo:
    """Read, validate and summarize a source file without importing it."""

    return analyze_loaded_source(read_source(source_path, max_bytes=max_bytes))


def analyze_loaded_source(source: LoadedSource) -> SourceInfo:
    """Parse an already bounded and decoded source file into ``SourceInfo``."""

    try:
        tree = ast.parse(source.code, filename=str(source.path), type_comments=True)
    except SyntaxError as error:
        reason = error.msg or "无效语法"
        line = error.lineno
        location = f"第 {line} 行" if line is not None else "未知行"
        raise SourceAnalysisError(
            "syntax_error",
            f"Python 语法错误（{location}）：{reason}",
            path=source.path,
            line=line,
            offset=error.offset,
        ) from None

    _reject_unsupported(tree, source)
    function_nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if not function_nodes:
        raise SourceAnalysisError(
            "no_target_functions",
            "源码中没有可测试的顶层同步函数；不会进入测试生成循环。",
            path=source.path,
        )
    if len(function_nodes) > 5:
        raise UnsupportedSourceError(
            "too_many_functions",
            f"当前不支持超过 5 个顶层函数（检测到 {len(function_nodes)} 个）。",
            path=source.path,
            line=function_nodes[5].lineno,
        )

    functions = tuple(_function_info(node) for node in function_nodes)
    imports = tuple(_import_info(node, source.code) for node in _import_nodes(tree))
    branches = tuple(
        branch
        for function in function_nodes
        for branch in _branches(function, source.code)
    )
    return SourceInfo(
        source_path=source.path,
        source_code=source.code,
        encoding=source.encoding,
        functions=functions,
        imports=imports,
        branches=branches,
    )


def _function_info(node: ast.FunctionDef) -> FunctionInfo:
    return FunctionInfo(
        name=node.name,
        signature=f"({ast.unparse(node.args)})",
        start_line=node.lineno,
        end_line=node.end_lineno or node.lineno,
        docstring=ast.get_docstring(node, clean=True),
    )


def _import_nodes(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    return sorted(
        (node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))),
        key=lambda item: (item.lineno, item.col_offset),
    )


def _import_info(node: ast.Import | ast.ImportFrom, source_code: str) -> ImportInfo:
    segment = ast.get_source_segment(source_code, node) or ast.unparse(node)
    module = node.module if isinstance(node, ast.ImportFrom) else None
    return ImportInfo(
        statement=segment,
        line=node.lineno,
        module=module,
        names=tuple(alias.name for alias in node.names),
    )


class _BranchVisitor(ast.NodeVisitor):
    """Visit one function body while excluding definitions executed only later."""

    def __init__(self, source_code: str) -> None:
        self.source_code = source_code
        self.items: list[SourceBranch] = []

    def inspect(self, function: ast.FunctionDef) -> tuple[SourceBranch, ...]:
        for statement in function.body:
            self.visit(statement)
        return tuple(self.items)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return None

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self._add("if", node, f"if {_segment(self.source_code, node.test)}")
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        self._add("match", node, f"match {_segment(self.source_code, node.subject)}")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._add(
            "loop", node,
            f"for {_segment(self.source_code, node.target)} in {_segment(self.source_code, node.iter)}",
        )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self._add("loop", node, f"while {_segment(self.source_code, node.test)}")
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self._add("try", node, "try")
        self.generic_visit(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:  # noqa: N802
        self._add("try", node, "try")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        self._add("raise", node, _segment(self.source_code, node))
        self.generic_visit(node)

    def _add(self, kind: str, node: ast.AST, source: str) -> None:
        self.items.append(SourceBranch(kind=kind, line=node.lineno, source=source))


def _branches(function: ast.FunctionDef, source_code: str) -> tuple[SourceBranch, ...]:
    return _BranchVisitor(source_code).inspect(function)


def _segment(source_code: str, node: ast.AST) -> str:
    return ast.get_source_segment(source_code, node) or ast.unparse(node)


def _reject_unsupported(tree: ast.Module, source: LoadedSource) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            _unsupported(source, "async_function", node.lineno, "异步函数")
        if isinstance(node, (ast.AsyncFor, ast.AsyncWith, ast.Await)):
            _unsupported(source, "async_syntax", node.lineno, "异步语法")
        if isinstance(node, ast.ImportFrom) and node.level:
            _unsupported(source, "relative_import", node.lineno, "相对导入")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any(alias.name == "*" for alias in node.names):
                _unsupported(source, "wildcard_import", node.lineno, "通配符导入")
            external = _external_modules(node)
            if external:
                joined = "、".join(external)
                _unsupported(source, "external_dependency", node.lineno, f"外部依赖 {joined}")

    top_level_classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if top_level_classes:
        _unsupported(source, "top_level_class", top_level_classes[0].lineno, "顶层类")


def _external_modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.ImportFrom):
        modules = () if node.module is None else (node.module.split(".", 1)[0],)
    else:
        modules = tuple(alias.name.split(".", 1)[0] for alias in node.names)
    return tuple(dict.fromkeys(module for module in modules if module not in sys.stdlib_module_names))


def _unsupported(source: LoadedSource, code: str, line: int, structure: str) -> NoReturn:
    raise UnsupportedSourceError(
        code,
        f"第 {line} 行包含当前不支持的结构：{structure}。",
        path=source.path,
        line=line,
    )
