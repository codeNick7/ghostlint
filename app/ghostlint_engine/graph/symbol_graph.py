from __future__ import annotations
import networkx as nx
from ghostlint_engine.ast_engine.base import SymbolDef, SymbolRef


class SymbolGraph:
    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        # All definitions keyed by symbol name; one name can have multiple defs (overloads, same name diff file)
        self.definitions: dict[str, list[SymbolDef]] = {}
        self.references: dict[str, list[SymbolRef]] = {}

    def add_definition(self, symbol: SymbolDef) -> None:
        node_id = self._def_id(symbol)
        self.graph.add_node(node_id, symbol=symbol)
        self.definitions.setdefault(symbol.name, []).append(symbol)

    def add_reference(self, ref: SymbolRef) -> None:
        self.references.setdefault(ref.name, []).append(ref)
        # Add edges: if we can resolve the reference to a definition, link them
        if ref.name in self.definitions:
            for sym in self.definitions[ref.name]:
                src_id = f"ref:{ref.file_path}:{ref.line}:{ref.name}"
                dst_id = self._def_id(sym)
                self.graph.add_node(src_id, ref=ref)
                self.graph.add_edge(src_id, dst_id)

    def get_unreferenced(self) -> list[SymbolDef]:
        """Return definitions that have zero incoming edges (no call/import references)."""
        unreferenced = []
        for node_id, data in self.graph.nodes(data=True):
            if "symbol" not in data:
                continue
            sym: SymbolDef = data["symbol"]
            if self.graph.in_degree(node_id) == 0:
                unreferenced.append(sym)
        return unreferenced

    def total_definitions(self) -> int:
        return sum(1 for _, d in self.graph.nodes(data=True) if "symbol" in d)

    @staticmethod
    def _def_id(symbol: SymbolDef) -> str:
        return f"def:{symbol.file_path}:{symbol.line_start}:{symbol.name}"
