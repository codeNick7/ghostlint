from __future__ import annotations
from dataclasses import dataclass
from tiramisu_engine.indexer import FileInfo
from tiramisu_engine.graph.symbol_graph import SymbolGraph


@dataclass
class AnalysisContext:
    files: list[FileInfo]
    symbol_graph: SymbolGraph
    repo_path: str
