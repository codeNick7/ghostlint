from __future__ import annotations
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node
from ghostlint_engine.indexer import FileInfo
from ghostlint_engine.ast_engine.base import BaseParser, SymbolDef, SymbolRef

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)

# Symbols that are never dead by convention
ENTRY_POINT_NAMES = {"main", "__init__", "__new__", "__call__", "__str__", "__repr__",
                     "__enter__", "__exit__", "__iter__", "__next__", "__len__",
                     "__getitem__", "__setitem__", "__delitem__", "__contains__",
                     "__eq__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__",
                     "__add__", "__sub__", "__mul__", "__truediv__", "__mod__",
                     "__bool__", "__int__", "__float__", "__bytes__", "__format__",
                     "setUp", "tearDown", "setUpClass", "tearDownClass"}


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_decorators(func_node: Node, source: bytes) -> list[str]:
    decorators = []
    for child in func_node.children:
        if child.type == "decorator":
            decorators.append(_node_text(child, source).strip())
    return decorators


def _get_base_classes(class_node: Node, source: bytes) -> list[str]:
    """Extract base class names from a class_definition node's argument_list."""
    bases: list[str] = []
    arg_list = class_node.child_by_field_name("superclasses")
    if arg_list is None:
        return bases
    for child in arg_list.children:
        if child.type == "identifier":
            bases.append(_node_text(child, source))
        elif child.type == "attribute":
            # e.g. models.Model → take just the attribute name "Model"
            attr = child.child_by_field_name("attribute")
            if attr:
                bases.append(_node_text(attr, source))
    return bases


def _walk_definitions(
    node: Node,
    source: bytes,
    file_path: str,
    defs: list[SymbolDef],
    parent_class: str | None = None,
    exported_names: set[str] | None = None,
    inherited_decorators: list[str] | None = None,
) -> None:
    for child in node.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                # Decorators are on the function_definition node itself (for class methods)
                # OR passed in from a parent decorated_definition node
                decorators = inherited_decorators or _get_decorators(child, source)
                is_private = name.startswith("_") and not name.startswith("__")
                is_entry = name in ENTRY_POINT_NAMES or name.startswith("test_")
                is_exported = (exported_names is None or name in (exported_names or set())) and not is_private
                kind = "method" if parent_class else "function"
                defs.append(SymbolDef(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    is_private=is_private,
                    is_exported=is_exported and not is_entry,
                    decorators=decorators,
                    parent_class=parent_class,
                ))
            # Recurse into function body for nested functions
            body = child.child_by_field_name("body")
            if body:
                _walk_definitions(body, source, file_path, defs, parent_class)

        elif child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            if name_node:
                class_name = _node_text(name_node, source)
                is_private = class_name.startswith("_")
                class_decorators = inherited_decorators or []
                base_classes = _get_base_classes(child, source)
                defs.append(SymbolDef(
                    name=class_name,
                    kind="class",
                    file_path=file_path,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    is_private=is_private,
                    is_exported=not is_private,
                    decorators=class_decorators,
                    base_classes=base_classes,
                ))
                body = child.child_by_field_name("body")
                if body:
                    _walk_definitions(body, source, file_path, defs, parent_class=class_name)

        elif child.type == "decorated_definition":
            # Collect decorators from this node, then recurse into the inner definition
            child_decorators = _get_decorators(child, source)
            _walk_definitions(child, source, file_path, defs, parent_class, exported_names,
                              inherited_decorators=child_decorators)

        elif child.type in ("block", "module"):
            _walk_definitions(child, source, file_path, defs, parent_class)


def _walk_references(node: Node, source: bytes, file_path: str, refs: list[SymbolRef]) -> None:
    if node.type == "call":
        func_node = node.child_by_field_name("function")
        if func_node:
            if func_node.type == "identifier":
                refs.append(SymbolRef(
                    name=_node_text(func_node, source),
                    file_path=file_path,
                    line=func_node.start_point[0] + 1,
                    kind="call",
                ))
            elif func_node.type == "attribute":
                # Method call: obj.method() — record the attribute name with
                # kind="attribute" so detectors can distinguish library method
                # calls (e.g. datetime.utcnow(), session.commit()) from bare
                # project function calls (foo()). The symbol graph still builds
                # edges from refs of any kind, so dead-code detection is unaffected.
                attr_node = func_node.child_by_field_name("attribute")
                if attr_node:
                    refs.append(SymbolRef(
                        name=_node_text(attr_node, source),
                        file_path=file_path,
                        line=func_node.start_point[0] + 1,
                        kind="attribute",
                    ))

        # Also track identifiers passed as arguments — e.g. add_task(run_precompute)
        # or thread = Thread(target=worker). These are valid references even though the
        # symbol is not being called at this point in the source.
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
                elif arg.type == "attribute":
                    # Only track self.X / cls.X passed as positional callback arguments —
                    # e.g. mpl_connect('button_press_event', self._on_click) or
                    # scheduler.add_job(self._run_task). Tracking ANY obj.attr would
                    # create false-positive orphan-call refs for attribute names like
                    # `response.content`, `path.parent`, `np.float32`, `logging.INFO`, etc.
                    obj_node = arg.child_by_field_name("object")
                    attr_node = arg.child_by_field_name("attribute")
                    if obj_node and attr_node:
                        obj_text = _node_text(obj_node, source)
                        if obj_text in ("self", "cls"):
                            refs.append(SymbolRef(
                                name=_node_text(attr_node, source),
                                file_path=file_path,
                                line=arg.start_point[0] + 1,
                                kind="call",
                            ))
                elif arg.type == "keyword_argument":
                    # keyword_argument: name=value — capture the value if it's an identifier
                    # or a self.X / cls.X attribute (e.g. target=self._worker).
                    val = arg.child_by_field_name("value")
                    if val and val.type == "identifier":
                        refs.append(SymbolRef(
                            name=_node_text(val, source),
                            file_path=file_path,
                            line=val.start_point[0] + 1,
                            kind="call",
                        ))
                    elif val and val.type == "attribute":
                        obj_node = val.child_by_field_name("object")
                        attr_node = val.child_by_field_name("attribute")
                        if obj_node and attr_node:
                            obj_text = _node_text(obj_node, source)
                            if obj_text in ("self", "cls"):
                                refs.append(SymbolRef(
                                    name=_node_text(attr_node, source),
                                    file_path=file_path,
                                    line=val.start_point[0] + 1,
                                    kind="call",
                                ))

    elif node.type == "import_from_statement":
        for child in node.children:
            if child.type == "dotted_name" and child != node.child_by_field_name("module_name"):
                refs.append(SymbolRef(
                    name=_node_text(child, source),
                    file_path=file_path,
                    line=child.start_point[0] + 1,
                    kind="import",
                ))
            elif child.type == "aliased_import":
                name_node = child.children[0] if child.children else None
                if name_node:
                    refs.append(SymbolRef(
                        name=_node_text(name_node, source),
                        file_path=file_path,
                        line=child.start_point[0] + 1,
                        kind="import",
                    ))

    elif node.type == "import_statement":
        for child in node.children:
            if child.type == "dotted_name":
                parts = _node_text(child, source).split(".")
                refs.append(SymbolRef(
                    name=parts[-1],
                    file_path=file_path,
                    line=child.start_point[0] + 1,
                    kind="import",
                ))

    for child in node.children:
        _walk_references(child, source, file_path, refs)


def _extract_all(node: Node, source: bytes) -> set[str] | None:
    """Return names in __all__ if defined, else None (meaning all public names exported)."""
    for child in node.children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "assignment":
                left = expr.child_by_field_name("left")
                right = expr.child_by_field_name("right")
                if left and _node_text(left, source) == "__all__" and right:
                    names = set()
                    for item in right.children:
                        if item.type == "string":
                            raw = _node_text(item, source).strip("'\"")
                            names.add(raw)
                    return names
    return None


class PythonParser(BaseParser):
    language = "python"

    def parse_file(self, file_info: FileInfo) -> tuple[list[SymbolDef], list[SymbolRef]]:
        source = file_info.content.encode("utf-8")
        tree = _parser.parse(source)
        root = tree.root_node

        exported_names = _extract_all(root, source)
        defs: list[SymbolDef] = []
        refs: list[SymbolRef] = []

        _walk_definitions(root, source, file_info.relative_path, defs, exported_names=exported_names)
        _walk_references(root, source, file_info.relative_path, refs)

        return defs, refs
