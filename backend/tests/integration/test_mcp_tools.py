"""Integration tests for the tiramisu MCP server tools.

Each test calls the tool function directly (not via MCP transport) since
the functions are plain Python callables decorated with @mcp.tool().
"""
from __future__ import annotations
from pathlib import Path
import pytest

from tiramisu_mcp.server import (
    check_diff,
    estimate_cleanup_effort,
    explain_repository_history,
    find_architecture_violations,
    find_dead_code,
    find_duplicate_logic,
    find_incomplete_refactors,
    find_repository_patterns,
    generate_cleanup_plan,
    get_health_context,
    list_findings,
    recommend_cleanup,
    repository_health,
    repository_metrics,
    repository_overview,
    repository_timeline,
    scan_files,
    scan_repo,
    search_repository_knowledge,
)


class TestScanRepo:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        for key in ("health_score", "files_scanned", "git_metrics", "health_context"):
            assert key in result, f"Missing key: {key}"

    def test_health_score_in_range(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        score = result["health_score"]
        assert isinstance(score, (int, float))
        assert 0.0 <= score <= 100.0

    def test_git_metrics_available_for_git_repo(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        gm = result["git_metrics"]
        assert gm["available"] is True

    def test_git_metrics_have_expected_fields(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        gm = result["git_metrics"]
        for field in ("stability_index", "maintenance_velocity",
                      "refactor_completion_rate", "friction_index",
                      "total_commits_analyzed"):
            assert field in gm

    def test_health_context_is_nonempty_string(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        ctx = result["health_context"]
        assert isinstance(ctx, str)
        assert len(ctx) > 20

    def test_top_findings_is_list(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo))
        assert isinstance(result.get("top_findings", []), list)

    def test_engine_filter_limits_scope(self, committed_repo: Path) -> None:
        result = scan_repo(path=str(committed_repo), engines=["dead_code"])
        assert isinstance(result, dict)
        assert "health_score" in result

    def test_invalid_path_returns_error_dict(self) -> None:
        result = scan_repo(path="/no/such/repo")
        assert isinstance(result, dict)
        assert "error" in result


class TestScanFiles:
    def test_returns_dict(self, committed_repo: Path) -> None:
        files = [str(committed_repo / "auth.py")]
        result = scan_files(repo_path=str(committed_repo), files=files)
        assert isinstance(result, dict)

    def test_has_health_context(self, committed_repo: Path) -> None:
        files = [str(committed_repo / "auth.py")]
        result = scan_files(repo_path=str(committed_repo), files=files)
        assert "health_context" in result

    def test_has_findings_key(self, committed_repo: Path) -> None:
        files = [str(committed_repo / "auth.py")]
        result = scan_files(repo_path=str(committed_repo), files=files)
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_has_health_score(self, committed_repo: Path) -> None:
        files = [str(committed_repo / "auth.py")]
        result = scan_files(repo_path=str(committed_repo), files=files)
        assert "health_score" in result
        assert 0.0 <= result["health_score"] <= 100.0

    def test_invalid_repo_path_returns_error(self) -> None:
        result = scan_files(repo_path="/no/such/repo", files=["auth.py"])
        assert isinstance(result, dict)
        assert "error" in result

    def test_scan_files_does_not_corrupt_full_scan_cache(
        self, committed_repo: Path
    ) -> None:
        # Full scan first — caches result in SQLite
        full = scan_repo(path=str(committed_repo))
        initial_score = full["health_score"]

        # Partial scan — must NOT overwrite the full scan record
        scan_files(repo_path=str(committed_repo), files=[str(committed_repo / "auth.py")])

        # Read cache — must still reflect the full scan score
        cached = get_health_context(repo_path=str(committed_repo))
        if "error" not in cached and cached.get("cached"):
            cached_score = cached.get("health_score", initial_score)
            # Score should be recognisably from the full scan (not the 0-finding partial scan)
            assert abs(float(cached_score) - initial_score) < 15.0


class TestGetHealthContext:
    def test_returns_dict(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))  # ensure cache exists
        result = get_health_context(repo_path=str(committed_repo))
        assert isinstance(result, dict)

    def test_cached_true_after_scan(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = get_health_context(repo_path=str(committed_repo))
        if "error" not in result:
            assert result.get("cached") is True

    def test_has_health_score_when_cached(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = get_health_context(repo_path=str(committed_repo))
        if result.get("cached"):
            assert "health_score" in result
            assert 0.0 <= result["health_score"] <= 100.0

    def test_no_cache_returns_message(self, tmp_path: Path) -> None:
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        result = get_health_context(repo_path=str(tmp_path))
        assert isinstance(result, dict)
        # Either an error or a "no scan found" message
        has_guidance = "error" in result or "message" in result or not result.get("cached", True)
        assert has_guidance


class TestListFindings:
    def test_returns_dict_with_findings_list(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo))
        assert isinstance(result, dict)
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_has_total_matching_key(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo))
        assert "total_matching" in result

    def test_filter_by_category(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo), category="dead_code")
        for item in result["findings"]:
            assert item["category"] == "dead_code"

    def test_filter_by_risk(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo), risk="high")
        for item in result["findings"]:
            assert item["risk"] == "high"

    def test_limit_respected(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo), limit=2)
        assert len(result["findings"]) <= 2

    def test_filters_applied_key_present(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo), category="dead_code")
        assert "filters_applied" in result

    def test_filter_by_file_pattern(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = list_findings(repo_path=str(committed_repo), file_pattern="auth")
        assert isinstance(result["findings"], list)
        for item in result["findings"]:
            assert "auth" in (item.get("file") or "")

    def test_no_cache_returns_message(self, tmp_path: Path) -> None:
        result = list_findings(repo_path=str(tmp_path))
        assert isinstance(result, dict)
        assert "message" in result or "findings" in result


# ═══════════════════════════════════════════════════════════════════════════
# Higher-level repository-intelligence tools (14) + check_diff coverage
# ═══════════════════════════════════════════════════════════════════════════
#
# The committed_repo fixture yields mostly dead-code findings, so the category-
# specific tools for absent categories are asserted defensively (correct empty
# shape) rather than for non-empty results.


class TestRepositoryOverview:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = repository_overview(repo_path=str(committed_repo))
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = repository_overview(repo_path=str(committed_repo))
        for key in ("total_files", "total_lines", "files_by_language",
                    "entry_points", "detected_frameworks", "config_files"):
            assert key in result, f"Missing key: {key}"

    def test_counts_files(self, committed_repo: Path) -> None:
        result = repository_overview(repo_path=str(committed_repo))
        assert result["total_files"] >= 1
        assert isinstance(result["files_by_language"], dict)

    def test_invalid_path_returns_error(self) -> None:
        result = repository_overview(repo_path="/no/such/repo")
        assert isinstance(result, dict)
        assert "error" in result


class TestRepositoryHealth:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = repository_health(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = repository_health(repo_path=str(committed_repo), force_refresh=True)
        for key in ("health_score", "health_label", "findings_summary",
                    "git_metrics", "health_context"):
            assert key in result, f"Missing key: {key}"

    def test_score_in_range(self, committed_repo: Path) -> None:
        result = repository_health(repo_path=str(committed_repo), force_refresh=True)
        assert 0.0 <= result["health_score"] <= 100.0

    def test_git_metrics_available(self, committed_repo: Path) -> None:
        result = repository_health(repo_path=str(committed_repo), force_refresh=True)
        assert result["git_metrics"]["available"] is True

    def test_invalid_path_returns_error(self) -> None:
        result = repository_health(repo_path="/no/such/repo")
        assert "error" in result


class TestFindDeadCode:
    def test_returns_findings_list(self, committed_repo: Path) -> None:
        result = find_dead_code(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)
        assert result["category"] == "dead_code"
        assert isinstance(result["findings"], list)

    def test_findings_have_expected_shape(self, committed_repo: Path) -> None:
        result = find_dead_code(repo_path=str(committed_repo), force_refresh=True)
        for item in result["findings"]:
            assert item["category"] == "dead_code"
            assert "title" in item and "file" in item

    def test_dead_code_present_in_fixture(self, committed_repo: Path) -> None:
        # The fixture repo has unused helpers → dead-code findings expected.
        result = find_dead_code(repo_path=str(committed_repo), force_refresh=True)
        assert result["total"] >= 1

    def test_limit_respected(self, committed_repo: Path) -> None:
        result = find_dead_code(repo_path=str(committed_repo), limit=1, force_refresh=True)
        assert len(result["findings"]) <= 1


class TestFindDuplicateLogic:
    def test_returns_correct_category(self, committed_repo: Path) -> None:
        result = find_duplicate_logic(repo_path=str(committed_repo), force_refresh=True)
        assert result["category"] == "duplicate_logic"
        assert isinstance(result["findings"], list)

    def test_has_total_key(self, committed_repo: Path) -> None:
        result = find_duplicate_logic(repo_path=str(committed_repo), force_refresh=True)
        assert "total" in result

    def test_invalid_path_returns_error(self) -> None:
        result = find_duplicate_logic(repo_path="/no/such/repo")
        assert "error" in result

    def test_findings_have_expected_shape(self, committed_repo: Path) -> None:
        result = find_duplicate_logic(repo_path=str(committed_repo), force_refresh=True)
        for item in result["findings"]:
            assert item["category"] == "duplicate_logic"
            assert "title" in item and "file" in item


class TestFindIncompleteRefactors:
    def test_returns_correct_category(self, committed_repo: Path) -> None:
        result = find_incomplete_refactors(repo_path=str(committed_repo), force_refresh=True)
        assert result["category"] == "refactor_completion"
        assert isinstance(result["findings"], list)

    def test_has_total_key(self, committed_repo: Path) -> None:
        result = find_incomplete_refactors(repo_path=str(committed_repo), force_refresh=True)
        assert "total" in result

    def test_invalid_path_returns_error(self) -> None:
        result = find_incomplete_refactors(repo_path="/no/such/repo")
        assert "error" in result


class TestFindArchitectureViolations:
    def test_returns_correct_category(self, committed_repo: Path) -> None:
        result = find_architecture_violations(repo_path=str(committed_repo), force_refresh=True)
        assert result["category"] == "architectural_drift"
        assert isinstance(result["findings"], list)

    def test_has_total_key(self, committed_repo: Path) -> None:
        result = find_architecture_violations(repo_path=str(committed_repo), force_refresh=True)
        assert "total" in result

    def test_invalid_path_returns_error(self) -> None:
        result = find_architecture_violations(repo_path="/no/such/repo")
        assert "error" in result


class TestFindRepositoryPatterns:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = find_repository_patterns(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = find_repository_patterns(repo_path=str(committed_repo), force_refresh=True)
        for key in ("duplication_patterns", "naming_patterns",
                    "api_proliferation", "directory_structure", "summary"):
            assert key in result, f"Missing key: {key}"

    def test_directory_structure_present(self, committed_repo: Path) -> None:
        result = find_repository_patterns(repo_path=str(committed_repo), force_refresh=True)
        assert "top_source_directories" in result["directory_structure"]

    def test_invalid_path_returns_error(self) -> None:
        result = find_repository_patterns(repo_path="/no/such/repo")
        assert "error" in result


class TestExplainRepositoryHistory:
    def test_available_for_git_repo(self, committed_repo: Path) -> None:
        result = explain_repository_history(repo_path=str(committed_repo))
        assert result["available"] is True

    def test_has_recent_commits(self, committed_repo: Path) -> None:
        result = explain_repository_history(repo_path=str(committed_repo))
        assert isinstance(result["recent_commits"], list)
        assert len(result["recent_commits"]) >= 1

    def test_has_narrative(self, committed_repo: Path) -> None:
        result = explain_repository_history(repo_path=str(committed_repo))
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 20

    def test_not_git_returns_unavailable(self, tmp_path: Path) -> None:
        result = explain_repository_history(repo_path=str(tmp_path))
        assert result["available"] is False


class TestRecommendCleanup:
    def test_returns_recommendations_list(self, committed_repo: Path) -> None:
        result = recommend_cleanup(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)
        assert isinstance(result["recommendations"], list)

    def test_has_health_score(self, committed_repo: Path) -> None:
        result = recommend_cleanup(repo_path=str(committed_repo), force_refresh=True)
        assert 0.0 <= result["health_score"] <= 100.0

    def test_recommendations_have_est_hours(self, committed_repo: Path) -> None:
        result = recommend_cleanup(repo_path=str(committed_repo), force_refresh=True)
        for rec in result["recommendations"]:
            assert "est_hours" in rec

    def test_limit_respected(self, committed_repo: Path) -> None:
        result = recommend_cleanup(repo_path=str(committed_repo), force_refresh=True, limit=2)
        assert len(result["recommendations"]) <= 2

    def test_invalid_path_returns_error(self) -> None:
        result = recommend_cleanup(repo_path="/no/such/repo")
        assert "error" in result


class TestEstimateCleanupEffort:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = estimate_cleanup_effort(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = estimate_cleanup_effort(repo_path=str(committed_repo), force_refresh=True)
        for key in ("total_findings", "estimated_hours", "estimated_days",
                    "by_effort", "by_category", "quick_wins_count"):
            assert key in result, f"Missing key: {key}"

    def test_hours_non_negative(self, committed_repo: Path) -> None:
        result = estimate_cleanup_effort(repo_path=str(committed_repo), force_refresh=True)
        assert result["estimated_hours"] >= 0.0

    def test_invalid_path_returns_error(self) -> None:
        result = estimate_cleanup_effort(repo_path="/no/such/repo")
        assert "error" in result


class TestGenerateCleanupPlan:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = generate_cleanup_plan(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = generate_cleanup_plan(repo_path=str(committed_repo), force_refresh=True)
        for key in ("health_score", "phases", "total_estimated_hours",
                    "recommended_order", "summary"):
            assert key in result, f"Missing key: {key}"

    def test_phases_present(self, committed_repo: Path) -> None:
        result = generate_cleanup_plan(repo_path=str(committed_repo), force_refresh=True)
        for phase in ("1_quick_wins", "2_quick_fixes", "3_refactors", "4_strategic"):
            assert phase in result["phases"]
            assert "summary" in result["phases"][phase]
            assert "items" in result["phases"][phase]

    def test_invalid_path_returns_error(self) -> None:
        result = generate_cleanup_plan(repo_path="/no/such/repo")
        assert "error" in result


class TestSearchRepositoryKnowledge:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = search_repository_knowledge(
            repo_path=str(committed_repo), query="unused", force_refresh=True,
        )
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = search_repository_knowledge(
            repo_path=str(committed_repo), query="unused", force_refresh=True,
        )
        for key in ("query", "finding_matches", "file_matches", "total_matches"):
            assert key in result, f"Missing key: {key}"

    def test_query_echoed(self, committed_repo: Path) -> None:
        result = search_repository_knowledge(
            repo_path=str(committed_repo), query="login", force_refresh=True,
        )
        assert result["query"] == "login"

    def test_file_match_for_known_file(self, committed_repo: Path) -> None:
        result = search_repository_knowledge(
            repo_path=str(committed_repo), query="auth", force_refresh=True,
        )
        assert any("auth" in m["file"] for m in result["file_matches"])

    def test_empty_query_returns_message(self, committed_repo: Path) -> None:
        result = search_repository_knowledge(
            repo_path=str(committed_repo), query="   ", force_refresh=True,
        )
        assert isinstance(result, dict)
        assert "message" in result or "finding_matches" in result

    def test_invalid_path_returns_error(self) -> None:
        result = search_repository_knowledge(repo_path="/no/such/repo", query="auth")
        assert "error" in result


class TestRepositoryMetrics:
    def test_returns_dict(self, committed_repo: Path) -> None:
        result = repository_metrics(repo_path=str(committed_repo), force_refresh=True)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        result = repository_metrics(repo_path=str(committed_repo), force_refresh=True)
        for key in ("health_score", "health_label", "category_scores",
                    "weakest_categories", "findings_total", "git_metrics"):
            assert key in result, f"Missing key: {key}"

    def test_score_in_range(self, committed_repo: Path) -> None:
        result = repository_metrics(repo_path=str(committed_repo), force_refresh=True)
        assert 0.0 <= result["health_score"] <= 100.0

    def test_weakest_has_three(self, committed_repo: Path) -> None:
        result = repository_metrics(repo_path=str(committed_repo), force_refresh=True)
        assert len(result["weakest_categories"]) <= 3

    def test_has_hotspot_files_key(self, committed_repo: Path) -> None:
        result = repository_metrics(repo_path=str(committed_repo), force_refresh=True)
        assert "hotspot_files" in result
        assert isinstance(result["hotspot_files"], list)

    def test_invalid_path_returns_error(self) -> None:
        result = repository_metrics(repo_path="/no/such/repo")
        assert "error" in result


class TestRepositoryTimeline:
    def test_returns_dict(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))  # ensure at least one scan exists
        result = repository_timeline(repo_path=str(committed_repo))
        assert isinstance(result, dict)

    def test_available_after_scan(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = repository_timeline(repo_path=str(committed_repo))
        assert result["available"] is True
        assert result["scan_count"] >= 1

    def test_has_trend_key(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        result = repository_timeline(repo_path=str(committed_repo))
        assert result["trend"] in ("improving", "declining", "stable")

    def test_no_history_still_returns_shape(self, tmp_path: Path) -> None:
        result = repository_timeline(repo_path=str(tmp_path))
        assert isinstance(result, dict)
        assert result["available"] is False

    def test_limit_parameter(self, committed_repo: Path) -> None:
        scan_repo(path=str(committed_repo))
        scan_repo(path=str(committed_repo))  # ensure at least 2 records
        result = repository_timeline(repo_path=str(committed_repo), limit=1)
        assert result["scan_count"] <= 1


class TestCheckDiff:
    """check_diff was previously untested — this closes that gap."""

    def test_returns_dict(self, committed_repo: Path) -> None:
        diff = _make_diff_adding_unused_func(committed_repo)
        result = check_diff(repo_path=str(committed_repo), diff=diff)
        assert isinstance(result, dict)

    def test_has_required_keys(self, committed_repo: Path) -> None:
        diff = _make_diff_adding_unused_func(committed_repo)
        result = check_diff(repo_path=str(committed_repo), diff=diff)
        for key in ("score_before", "score_after", "delta",
                    "regression_risk", "summary"):
            assert key in result, f"Missing key: {key}"

    def test_scores_in_range(self, committed_repo: Path) -> None:
        diff = _make_diff_adding_unused_func(committed_repo)
        result = check_diff(repo_path=str(committed_repo), diff=diff)
        assert 0.0 <= result["score_before"] <= 100.0
        assert 0.0 <= result["score_after"] <= 100.0

    def test_regression_risk_is_known_value(self, committed_repo: Path) -> None:
        diff = _make_diff_adding_unused_func(committed_repo)
        result = check_diff(repo_path=str(committed_repo), diff=diff)
        assert result["regression_risk"] in ("LOW", "MEDIUM", "HIGH")

    def test_findings_lists_present(self, committed_repo: Path) -> None:
        diff = _make_diff_adding_unused_func(committed_repo)
        result = check_diff(repo_path=str(committed_repo), diff=diff)
        assert isinstance(result["new_findings"], list)
        assert isinstance(result["resolved_findings"], list)

    def test_invalid_path_returns_error(self) -> None:
        result = check_diff(repo_path="/no/such/repo", diff="")
        assert "error" in result

    def test_empty_diff_returns_no_change(self, committed_repo: Path) -> None:
        result = check_diff(repo_path=str(committed_repo), diff="")
        assert isinstance(result, dict)
        # Either succeeds with no net change or returns an error — both are acceptable
        if "error" not in result:
            assert isinstance(result.get("new_findings", []), list)
            assert isinstance(result.get("resolved_findings", []), list)


def _make_diff_adding_unused_func(committed_repo: Path) -> str:
    """Build a unified diff that adds a new unused function to utils.py.

    The diff is relative to the committed HEAD content of utils.py so it
    applies cleanly with `patch -p1`.
    """
    head_content = (committed_repo / "utils.py").read_text()
    added_line = "def _brand_new_dead():\n    pass\n"
    new_content = head_content.rstrip("\n") + "\n" + added_line
    head_lines = head_content.splitlines()
    new_lines = new_content.splitlines()
    return _unified_diff("utils.py", head_lines, new_lines)


def _unified_diff(path: str, before: list[str], after: list[str]) -> str:
    import difflib
    diff = difflib.unified_diff(
        before, after, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    )
    text = "\n".join(diff)
    return text + "\n" if text else ""
