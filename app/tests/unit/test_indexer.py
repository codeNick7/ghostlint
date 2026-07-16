"""Tests for the FileIndexer."""
from __future__ import annotations
from pathlib import Path
import pytest
from ghostlint_engine.indexer import FileIndexer, LANGUAGE_MAP


def test_indexer_finds_python_files(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("x = 1")
    (tmp_path / "helper.py").write_text("y = 2")
    indexer = FileIndexer()
    files = indexer.index(tmp_path)
    paths = [f.relative_path for f in files]
    assert "main.py" in paths
    assert "helper.py" in paths


def test_indexer_excludes_venv(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("# venv file")
    (tmp_path / "app.py").write_text("pass")
    indexer = FileIndexer()
    files = indexer.index(tmp_path)
    paths = [f.relative_path for f in files]
    assert "app.py" in paths
    assert not any(".venv" in p for p in paths)


def test_indexer_detects_languages(tmp_path: Path) -> None:
    (tmp_path / "comp.jsx").write_text("export default function Comp() {}")
    (tmp_path / "script.js").write_text("const x = 1;")
    (tmp_path / "types.ts").write_text("type Foo = string;")
    indexer = FileIndexer()
    files = indexer.index(tmp_path)
    by_path = {f.relative_path: f for f in files}
    assert by_path["comp.jsx"].language == "javascript"
    assert by_path["script.js"].language == "javascript"
    assert by_path["types.ts"].language == "typescript"


def test_indexer_skips_large_files(tmp_path: Path) -> None:
    large = tmp_path / "big.py"
    large.write_bytes(b"x = 1\n" * 100_000)  # ~600KB
    small = tmp_path / "small.py"
    small.write_text("x = 1")
    indexer = FileIndexer()
    files = indexer.index(tmp_path)
    paths = [f.relative_path for f in files]
    assert "small.py" in paths
    assert "big.py" not in paths


def test_indexer_content_hash_is_stable(tmp_path: Path) -> None:
    (tmp_path / "file.py").write_text("hello")
    indexer = FileIndexer()
    files1 = indexer.index(tmp_path)
    files2 = indexer.index(tmp_path)
    assert files1[0].content_hash == files2[0].content_hash


def test_indexer_excludes_node_modules(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("module.exports = {}")
    (tmp_path / "index.js").write_text("const x = require('lib');")
    indexer = FileIndexer()
    files = indexer.index(tmp_path)
    paths = [f.relative_path for f in files]
    assert "index.js" in paths
    assert not any("node_modules" in p for p in paths)
