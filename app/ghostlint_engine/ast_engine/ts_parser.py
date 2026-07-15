"""TypeScript / TSX parser.

TypeScript is a syntactic superset of JavaScript: the node types for
function/class definitions, call/import references, and JSX elements are
identical to JavaScript's grammar. We therefore reuse the JS parser's
``_walk_definitions`` / ``_walk_references`` tree-walkers and only swap the
underlying tree-sitter language (so type annotations, interfaces, enums, and
TSX-specific syntax parse correctly).

Two language objects are required because TypeScript and TSX differ in how
``<Foo>`` is disambiguated (type assertion vs JSX element):
  - ``.ts``  → ``language_typescript()``
  - ``.tsx`` → ``language_tsx()``
"""
from __future__ import annotations
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser
from ghostlint_engine.indexer import FileInfo
from ghostlint_engine.ast_engine.base import BaseParser, SymbolDef, SymbolRef
# Reuse the JS tree-walkers — the AST node types are the same.
from ghostlint_engine.ast_engine.js_parser import _walk_definitions, _walk_references

_TS_LANGUAGE = Language(tsts.language_typescript())
_TSX_LANGUAGE = Language(tsts.language_tsx())

# One parser per language variant. tree-sitter parsers are bound to a single
# language at construction, so we need two.
_ts_parser = Parser(_TS_LANGUAGE)
_tsx_parser = Parser(_TSX_LANGUAGE)


class TSParser(BaseParser):
    """Parses both ``.ts`` and ``.tsx`` files.

    The indexer assigns ``language == "typescript"`` to both extensions, so this
    parser selects the concrete grammar from the file extension at parse time.
    """

    language = "typescript"

    def parse_file(self, file_info: FileInfo) -> tuple[list[SymbolDef], list[SymbolRef]]:
        source = file_info.content.encode("utf-8")
        # TSX uses the jsx-capable grammar so <Component /> parses as JSX.
        parser = _tsx_parser if file_info.path.suffix.lower() == ".tsx" else _ts_parser
        tree = parser.parse(source)
        root = tree.root_node

        defs: list[SymbolDef] = []
        refs: list[SymbolRef] = []
        _walk_definitions(root, source, file_info.relative_path, defs)
        _walk_references(root, source, file_info.relative_path, refs)

        return defs, refs
