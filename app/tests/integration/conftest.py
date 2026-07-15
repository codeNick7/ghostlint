"""Shared fixtures for integration tests."""
from __future__ import annotations
import subprocess
from pathlib import Path
import pytest


@pytest.fixture(scope="module")
def committed_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A temp git repo with Python and JS files committed."""
    repo = tmp_path_factory.mktemp("repo")

    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@ghostlint.dev"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Ghostlint CI"],
        capture_output=True, check=True,
    )

    # Python module
    (repo / "auth.py").write_text(
        "def login(user, password):\n    return True\n\n"
        "def _unused_helper():\n    pass\n"
    )
    (repo / "utils.py").write_text(
        "def format_date(dt):\n    return str(dt)\n\n"
        "def _dead_func():\n    pass\n"
    )
    # JS module
    (repo / "app.js").write_text(
        "function greet(name) { return `Hello, ${name}`; }\n"
        "function unusedFn() { return 42; }\n"
    )
    # Test file
    (repo / "test_auth.py").write_text(
        "from auth import login\n\ndef test_login():\n    assert login('u', 'p')\n"
    )

    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "feat: initial commit"],
        capture_output=True, check=True,
    )

    # Second commit — a fix
    (repo / "auth.py").write_text(
        "def login(user, password):\n    if not user:\n        return False\n    return True\n\n"
        "def _unused_helper():\n    pass\n"
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "fix: guard empty user in login"],
        capture_output=True, check=True,
    )

    return repo
