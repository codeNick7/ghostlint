from ghostlint_engine.ast_engine.base import BaseParser, SymbolDef, SymbolRef
from ghostlint_engine.ast_engine.python_parser import PythonParser
from ghostlint_engine.ast_engine.js_parser import JSParser
from ghostlint_engine.ast_engine.ts_parser import TSParser

PARSERS: dict[str, BaseParser] = {
    "python": PythonParser(),
    "javascript": JSParser(),
    "typescript": TSParser(),
}

__all__ = [
    "BaseParser", "SymbolDef", "SymbolRef",
    "PythonParser", "JSParser", "TSParser", "PARSERS",
]
