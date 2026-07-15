from __future__ import annotations
from dataclasses import dataclass, field
from ghostlint_engine.indexer import FileInfo


@dataclass
class SymbolDef:
    name: str
    kind: str           # function | class | method | arrow_function
    file_path: str
    line_start: int
    line_end: int
    is_private: bool    # name starts with _ in Python, or not exported in JS
    is_exported: bool   # part of module's public API
    decorators: list[str] = field(default_factory=list)
    parent_class: str | None = None
    base_classes: list[str] = field(default_factory=list)


@dataclass
class SymbolRef:
    name: str
    file_path: str
    line: int
    kind: str = "call"  # call | import | attribute


class BaseParser:
    language: str = ""

    def parse_file(self, file_info: FileInfo) -> tuple[list[SymbolDef], list[SymbolRef]]:
        raise NotImplementedError
