"""Unit tests for the check_diff path-traversal validator."""
from __future__ import annotations
import pytest

from ghostlint_mcp.server import _validate_diff_paths


class TestValidateDiffPaths:
    def test_clean_diff_passes(self) -> None:
        diff = (
            "--- a/src/utils.py\n"
            "+++ b/src/utils.py\n"
            "@@ -1,3 +1,4 @@\n"
            " def foo():\n"
            "+    pass\n"
        )
        assert _validate_diff_paths(diff) is None

    def test_dotdot_traversal_rejected(self) -> None:
        diff = (
            "--- a/../../etc/passwd\n"
            "+++ b/../../etc/passwd\n"
            "@@ -1 +1 @@\n"
            "-root\n+pwned\n"
        )
        result = _validate_diff_paths(diff)
        assert result is not None
        assert "traversal" in result.lower() or "rejected" in result.lower()

    def test_absolute_path_rejected(self) -> None:
        diff = (
            "--- /etc/hosts\n"
            "+++ /etc/hosts\n"
            "@@ -1 +1 @@\n"
            "-127.0.0.1\n+0.0.0.0\n"
        )
        result = _validate_diff_paths(diff)
        assert result is not None
        assert "rejected" in result.lower()

    def test_devnull_allowed(self) -> None:
        # New files in a diff use /dev/null as the before-path
        diff = (
            "--- /dev/null\n"
            "+++ b/new_file.py\n"
            "@@ -0,0 +1 @@\n"
            "+x = 1\n"
        )
        assert _validate_diff_paths(diff) is None

    def test_nested_path_without_dotdot_passes(self) -> None:
        diff = (
            "--- a/src/deep/nested/module.py\n"
            "+++ b/src/deep/nested/module.py\n"
            "@@ -1 +1 @@\n"
            "-old\n+new\n"
        )
        assert _validate_diff_paths(diff) is None

    def test_dotdot_in_git_b_prefix_rejected(self) -> None:
        # Traversal hidden after b/ git prefix
        diff = (
            "--- a/safe.py\n"
            "+++ b/../../../tmp/evil.py\n"
            "@@ -1 +1 @@\n"
            "-x\n+y\n"
        )
        result = _validate_diff_paths(diff)
        assert result is not None

    def test_empty_diff_passes(self) -> None:
        assert _validate_diff_paths("") is None

    def test_multiple_files_all_clean_passes(self) -> None:
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-a\n+b\n"
            "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1 @@\n-c\n+d\n"
        )
        assert _validate_diff_paths(diff) is None

    def test_one_malicious_file_among_clean_rejected(self) -> None:
        diff = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-a\n+b\n"
            "--- a/../../evil\n+++ b/../../evil\n@@ -1 +1 @@\n-x\n+y\n"
        )
        result = _validate_diff_paths(diff)
        assert result is not None
