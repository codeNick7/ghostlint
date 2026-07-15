"""Tests for git_metrics module."""
from __future__ import annotations
import subprocess
from pathlib import Path
import pytest

from tiramisu_engine.git_metrics import (
    compute_git_metrics,
    _large_file_ratio,
    _count_debt_markers_in_tree,
)
from tiramisu_engine.models.findings import GitMetrics


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with a few commits."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)

    # Commit 1 — adds a model and a helper
    (tmp_path / "model.py").write_text("class User:\n    pass\n")
    (tmp_path / "helper.py").write_text("def util():\n    pass\n# TODO: wire this\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "feat: add user model"], capture_output=True)

    # Commit 2 — fix commit touching model (core file churn)
    (tmp_path / "model.py").write_text("class User:\n    id: int\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "fix: add id field to User"], capture_output=True)

    # Commit 3 — removes TODO (improves refactor completion)
    (tmp_path / "helper.py").write_text("def util():\n    pass\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "refactor: clean up helper"], capture_output=True)

    return tmp_path


def test_returns_unavailable_for_non_git_dir(tmp_path: Path) -> None:
    result = compute_git_metrics(tmp_path)
    assert result.available is False


def test_returns_available_for_git_repo(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert result.available is True


def test_total_commits_analyzed(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert result.total_commits_analyzed == 3


def test_stability_index_is_float_in_range(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert 0.0 <= result.stability_index <= 100.0


def test_maintenance_velocity_is_float_in_range(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    # fix commit exists → velocity should be > 0
    assert 0.0 <= result.maintenance_velocity <= 1.0
    assert result.maintenance_velocity > 0.0


def test_friction_index_is_float_in_range(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert 0.0 <= result.friction_index <= 100.0


def test_refactor_completion_rate_is_float_in_range(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert 0.0 <= result.refactor_completion_rate <= 100.0


def test_repo_age_days_positive(git_repo: Path) -> None:
    result = compute_git_metrics(git_repo)
    assert result.repo_age_days >= 0


def test_large_file_ratio_empty_dir(tmp_path: Path) -> None:
    assert _large_file_ratio(tmp_path) == 0.0


def test_large_file_ratio_all_small(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text("x = 1\n" * 10)
    assert _large_file_ratio(tmp_path) == 0.0


def test_large_file_ratio_one_large(tmp_path: Path) -> None:
    (tmp_path / "big.py").write_text("x = 1\n" * 501)
    (tmp_path / "small.py").write_text("y = 2\n")
    ratio = _large_file_ratio(tmp_path)
    assert ratio == pytest.approx(0.5)


def test_git_metrics_dataclass_defaults() -> None:
    gm = GitMetrics()
    assert gm.available is False
    assert gm.stability_index == 0.0
    assert gm.friction_index == 0.0
