"""Shared fixtures for unit tests."""
from __future__ import annotations
import tempfile
from pathlib import Path
import pytest

from ghostlint_engine.indexer import FileInfo, FileIndexer
from ghostlint_engine.ast_engine.base import SymbolDef, SymbolRef
from ghostlint_engine.graph.symbol_graph import SymbolGraph
from ghostlint_engine.graph.context import AnalysisContext


def make_file_info(relative_path: str, content: str, language: str = "python") -> FileInfo:
    """Create a FileInfo object from inline content (no disk I/O needed)."""
    import hashlib
    return FileInfo(
        path=Path(relative_path),
        relative_path=relative_path,
        language=language,
        size=len(content),
        content_hash=hashlib.md5(content.encode()).hexdigest(),
        content=content,
    )


def make_symbol_def(
    name: str,
    kind: str = "function",
    file_path: str = "test.py",
    line_start: int = 1,
    line_end: int = 5,
    is_private: bool = False,
    is_exported: bool = True,
    decorators: list[str] | None = None,
    parent_class: str | None = None,
) -> SymbolDef:
    return SymbolDef(
        name=name,
        kind=kind,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        is_private=is_private,
        is_exported=is_exported,
        decorators=decorators or [],
        parent_class=parent_class,
    )


def make_symbol_ref(
    name: str,
    file_path: str = "caller.py",
    line: int = 10,
    kind: str = "call",
) -> SymbolRef:
    return SymbolRef(name=name, file_path=file_path, line=line, kind=kind)


@pytest.fixture
def simple_graph() -> SymbolGraph:
    """A graph with two definitions and one reference to the first."""
    g = SymbolGraph()
    d1 = make_symbol_def("my_func", file_path="a.py", line_start=1)
    d2 = make_symbol_def("orphan_func", file_path="a.py", line_start=10)
    r1 = make_symbol_ref("my_func", file_path="b.py")
    g.add_definition(d1)
    g.add_definition(d2)
    g.add_reference(r1)
    return g


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Return a temp directory with a few Python files."""
    (tmp_path / "main.py").write_text("def run():\n    helper()\n\ndef helper():\n    pass\n")
    (tmp_path / "utils.py").write_text("def _private_util():\n    pass\n\ndef public_util():\n    pass\n")
    return tmp_path
