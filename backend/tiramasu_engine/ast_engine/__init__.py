from tiramasu_engine.ast_engine.base import BaseParser, SymbolDef, SymbolRef
from tiramasu_engine.ast_engine.python_parser import PythonParser
from tiramasu_engine.ast_engine.js_parser import JSParser

PARSERS: dict[str, BaseParser] = {
    "python": PythonParser(),
    "javascript": JSParser(),
}

__all__ = ["BaseParser", "SymbolDef", "SymbolRef", "PythonParser", "JSParser", "PARSERS"]
