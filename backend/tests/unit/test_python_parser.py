"""Tests for the PythonParser."""
from __future__ import annotations
import pytest
from tiramasu_engine.ast_engine.python_parser import PythonParser
from tests.unit.conftest import make_file_info

parser = PythonParser()


def test_parse_function_definition() -> None:
    fi = make_file_info("test.py", "def greet(name):\n    return 'hello ' + name\n")
    defs, refs = parser.parse_file(fi)
    names = [d.name for d in defs]
    assert "greet" in names


def test_parse_class_definition() -> None:
    fi = make_file_info("test.py", "class MyService:\n    def run(self):\n        pass\n")
    defs, refs = parser.parse_file(fi)
    names = {d.name: d.kind for d in defs}
    assert "MyService" in names
    assert names["MyService"] == "class"
    assert "run" in names
    assert names["run"] == "method"


def test_parse_private_function() -> None:
    fi = make_file_info("test.py", "def _helper():\n    pass\n")
    defs, _ = parser.parse_file(fi)
    assert defs[0].is_private is True


def test_parse_function_call_ref() -> None:
    fi = make_file_info("caller.py", "def main():\n    greet('world')\n")
    _, refs = parser.parse_file(fi)
    ref_names = [r.name for r in refs]
    assert "greet" in ref_names


def test_parse_import_from_ref() -> None:
    fi = make_file_info("mod.py", "from os.path import join, exists\n")
    _, refs = parser.parse_file(fi)
    ref_names = [r.name for r in refs if r.kind == "import"]
    assert "join" in ref_names
    assert "exists" in ref_names


def test_parse_decorator() -> None:
    fi = make_file_info("routes.py", "@app.get('/health')\ndef health_check():\n    return {}\n")
    defs, _ = parser.parse_file(fi)
    assert any(d.name == "health_check" for d in defs)
    hc = next(d for d in defs if d.name == "health_check")
    assert any("app.get" in dec for dec in hc.decorators)


def test_parse_nested_function() -> None:
    code = "def outer():\n    def inner():\n        pass\n    inner()\n"
    fi = make_file_info("nested.py", code)
    defs, _ = parser.parse_file(fi)
    names = [d.name for d in defs]
    assert "outer" in names
    assert "inner" in names
