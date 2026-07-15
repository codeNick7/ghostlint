from __future__ import annotations
from dataclasses import dataclass
from ghostlint_engine.indexer import FileInfo
from ghostlint_engine.graph.symbol_graph import SymbolGraph


@dataclass
class AnalysisContext:
    files: list[FileInfo]
    symbol_graph: SymbolGraph
    repo_path: str
