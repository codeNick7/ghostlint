"""Tests for the JSParser."""
from __future__ import annotations
import pytest
from ghostlint_engine.ast_engine.js_parser import JSParser
from tests.unit.conftest import make_file_info

parser = JSParser()


def test_parse_function_declaration() -> None:
    fi = make_file_info("app.js", "function greet(name) { return 'hello ' + name; }\n", language="javascript")
    defs, _ = parser.parse_file(fi)
    assert any(d.name == "greet" for d in defs)


def test_parse_arrow_function() -> None:
    fi = make_file_info("utils.js", "const add = (a, b) => a + b;\n", language="javascript")
    defs, _ = parser.parse_file(fi)
    assert any(d.name == "add" and d.kind == "arrow_function" for d in defs)


def test_parse_class_declaration() -> None:
    code = "class UserService {\n  constructor() {}\n  getUser(id) { return id; }\n}\n"
    fi = make_file_info("service.js", code, language="javascript")
    defs, _ = parser.parse_file(fi)
    names = {d.name: d.kind for d in defs}
    assert "UserService" in names
    assert names["UserService"] == "class"


def test_parse_exported_function() -> None:
    fi = make_file_info("lib.js", "export function compute() { return 42; }\n", language="javascript")
    defs, _ = parser.parse_file(fi)
    assert any(d.name == "compute" and d.is_exported for d in defs)


def test_parse_import_reference() -> None:
    fi = make_file_info("main.js", "import { useState, useEffect } from 'react';\n", language="javascript")
    _, refs = parser.parse_file(fi)
    ref_names = [r.name for r in refs if r.kind == "import"]
    assert "useState" in ref_names
    assert "useEffect" in ref_names


def test_parse_jsx_component_reference() -> None:
    code = "function App() { return <MyButton onClick={handleClick} />; }\n"
    fi = make_file_info("App.jsx", code, language="javascript")
    _, refs = parser.parse_file(fi)
    ref_names = [r.name for r in refs]
    assert "MyButton" in ref_names


def test_parse_call_expression() -> None:
    fi = make_file_info("script.js", "function main() { console.log('hello'); doWork(); }\n", language="javascript")
    _, refs = parser.parse_file(fi)
    ref_names = [r.name for r in refs if r.kind == "call"]
    assert "doWork" in ref_names
