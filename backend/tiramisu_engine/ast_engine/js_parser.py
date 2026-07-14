from __future__ import annotations
import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, Node
from tiramisu_engine.indexer import FileInfo
from tiramisu_engine.ast_engine.base import BaseParser, SymbolDef, SymbolRef

JS_LANGUAGE = Language(tsjs.language())
_parser = Parser(JS_LANGUAGE)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _walk_definitions(
    node: Node,
    source: bytes,
    file_path: str,
    defs: list[SymbolDef],
    parent_class: str | None = None,
    is_module_exported: bool = False,
) -> None:
    for child in node.children:
        exported = is_module_exported or child.type == "export_statement"

        if child.type == "function_declaration":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                defs.append(SymbolDef(
                    name=name,
                    kind="function",
                    file_path=file_path,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    is_private=name.startswith("_"),
                    is_exported=exported,
                ))

        elif child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            if name_node:
                class_name = _node_text(name_node, source)
                defs.append(SymbolDef(
                    name=class_name,
                    kind="class",
                    file_path=file_path,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    is_private=class_name.startswith("_"),
                    is_exported=exported,
                ))
                body = child.child_by_field_name("body")
                if body:
                    _walk_class_body(body, source, file_path, defs, class_name)

        elif child.type == "lexical_declaration":
            # const foo = () => {} or const foo = function() {}
            for declarator in child.children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    value_node = declarator.child_by_field_name("value")
                    if name_node and value_node and value_node.type in ("arrow_function", "function"):
                        name = _node_text(name_node, source)
                        defs.append(SymbolDef(
                            name=name,
                            kind="arrow_function",
                            file_path=file_path,
                            line_start=child.start_point[0] + 1,
                            line_end=child.end_point[0] + 1,
                            is_private=name.startswith("_"),
                            is_exported=exported,
                        ))

        elif child.type == "export_statement":
            _walk_definitions(child, source, file_path, defs, parent_class, is_module_exported=True)

        elif child.type in ("program", "statement_block"):
            _walk_definitions(child, source, file_path, defs, parent_class)


def _walk_class_body(node: Node, source: bytes, file_path: str, defs: list[SymbolDef], class_name: str) -> None:
    for child in node.children:
        if child.type == "method_definition":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                defs.append(SymbolDef(
                    name=name,
                    kind="method",
                    file_path=file_path,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    is_private=name.startswith("_") or name.startswith("#"),
                    is_exported=False,
                    parent_class=class_name,
                ))


def _walk_references(node: Node, source: bytes, file_path: str, refs: list[SymbolRef]) -> None:
    if node.type == "call_expression":
        func_node = node.child_by_field_name("function")
        if func_node:
            if func_node.type == "identifier":
                refs.append(SymbolRef(
                    name=_node_text(func_node, source),
                    file_path=file_path,
                    line=func_node.start_point[0] + 1,
                    kind="call",
                ))
            elif func_node.type == "member_expression":
                # Method call: obj.method() — record the property name with
                # kind="attribute" so detectors can distinguish library method
                # calls (e.g. JSON.parse(), response.json()) from bare project
                # function calls (foo()). The symbol graph still builds edges
                # from refs of any kind, so dead-code detection is unaffected.
                prop = func_node.child_by_field_name("property")
                if prop:
                    refs.append(SymbolRef(
                        name=_node_text(prop, source),
                        file_path=file_path,
                        line=func_node.start_point[0] + 1,
                        kind="attribute",
                    ))
        # Track identifier arguments: useStore(selector, shallow) → selector is referenced
        args_node = node.child_by_field_name("arguments")
        if args_node:
            for arg in args_node.children:
                if arg.type == "identifier":
                    refs.append(SymbolRef(
                        name=_node_text(arg, source),
                        file_path=file_path,
                        line=arg.start_point[0] + 1,
                        kind="call",
                    ))

    elif node.type == "import_statement":
        for child in node.children:
            if child.type == "import_clause":
                for item in child.children:
                    if item.type == "identifier":
                        refs.append(SymbolRef(
                            name=_node_text(item, source),
                            file_path=file_path,
                            line=child.start_point[0] + 1,
                            kind="import",
                        ))
                    elif item.type == "named_imports":
                        for spec in item.children:
                            if spec.type == "import_specifier":
                                name_node = spec.child_by_field_name("name")
                                if name_node:
                                    refs.append(SymbolRef(
                                        name=_node_text(name_node, source),
                                        file_path=file_path,
                                        line=spec.start_point[0] + 1,
                                        kind="import",
                                    ))

    # JSX elements: <StatRow /> or <PipelineUI> → StatRow and PipelineUI are references
    elif node.type in ("jsx_opening_element", "jsx_self_closing_element"):
        name_node = node.child_by_field_name("name")
        if name_node and name_node.type == "identifier":
            name = _node_text(name_node, source)
            # Only track capitalised names — those are components, not HTML tags
            if name and name[0].isupper():
                refs.append(SymbolRef(
                    name=name,
                    file_path=file_path,
                    line=name_node.start_point[0] + 1,
                    kind="call",
                ))

    for child in node.children:
        _walk_references(child, source, file_path, refs)


class JSParser(BaseParser):
    language = "javascript"

    def parse_file(self, file_info: FileInfo) -> tuple[list[SymbolDef], list[SymbolRef]]:
        source = file_info.content.encode("utf-8")
        tree = _parser.parse(source)
        root = tree.root_node

        defs: list[SymbolDef] = []
        refs: list[SymbolRef] = []
        _walk_definitions(root, source, file_info.relative_path, defs)
        _walk_references(root, source, file_info.relative_path, refs)

        return defs, refs
