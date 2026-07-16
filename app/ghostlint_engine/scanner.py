from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ghostlint_engine.indexer import FileIndexer
from ghostlint_engine.ast_engine import PARSERS
from ghostlint_engine.graph.symbol_graph import SymbolGraph
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.detectors.registry import get_registry, phase1_engines, fast_engines
from ghostlint_engine.health_score import compute_health_score
from ghostlint_engine.recommendations import generate_recommendations
from ghostlint_engine.models.findings import ScanResult, HealthScore
from ghostlint_engine.db.session import get_session
from ghostlint_engine.db.models import ScanRecord, FindingRecord

#: Sentinel passed to engines= to mean "run all phase-1 engines"
ALL_ENGINES = "__all__"
#: Sentinel to run only fast engines (pre-commit mode)
FAST_ENGINES = "__fast__"


@dataclass
class ScanConfig:
    repo_path: Path
    scan_mode: str = "full"
    exclude_dirs: set[str] = field(default_factory=set)
    exclude_paths: list[str] = field(default_factory=list)
    confidence_threshold: float = 0.6
    engines: list[str] = field(default_factory=lambda: [ALL_ENGINES])
    changed_files: list[str] | None = None  # if set, filter findings to these files only
    skip_persist: bool = False              # if True, don't write to SQLite history
    trust_repo_config: bool = True          # if False, skip ghostlint.toml in repo root
    on_progress: Callable[[str, int, int], None] | None = None  # (stage, current, total)


def _detect_head_sha(repo_path: Path) -> str | None:
    """Return the short HEAD commit SHA for repo_path, or None if not a git repo."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--short=8", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = result.stdout.strip()
        return sha if sha else None
    except Exception:
        return None


def _load_repo_config(repo_path: Path) -> dict:
    """Load ghostlint.toml from the repository root, if present.

    Returns a dict with zero or more of these keys:
      ``exclude`` — list of validated path patterns to exclude from scanning

    Only the ``[scan]`` table is honoured — flat top-level keys are ignored so
    a malicious config cannot silently override settings by omitting the table.
    Silent on any parse error so a broken config file never prevents a scan.
    Only call this for repos the user owns/trusts; skip for cloned/foreign repos.
    """
    cfg_path = repo_path / "ghostlint.toml"
    if not cfg_path.exists():
        return {}
    try:
        import tomllib
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
        scan_section = data.get("scan")
        if not isinstance(scan_section, dict):
            return {}
        raw_excludes = scan_section.get("exclude", [])
        if not isinstance(raw_excludes, list):
            raw_excludes = []
        return {"exclude": _validate_exclude_patterns(raw_excludes)}
    except Exception:
        return {}


# Trivially-broad patterns that would exclude most or all source files.
# A repo-shipped config that contains any of these is treated as malicious or
# misconfigured and the pattern is silently dropped.
_OVERBROAD_PATTERNS: frozenset[str] = frozenset({
    "*", "**", "**/*", "/", ".", "./", "./*",
})
_MAX_REPO_CONFIG_PATTERNS = 50


def _validate_exclude_patterns(patterns: list[str]) -> list[str]:
    """Return a cleaned, safe subset of user-supplied exclude patterns.

    Drops:
      - trivially broad globs (``*``, ``**``, ``**/*``, ``/``, ``./``)
      - patterns whose non-wildcard, non-separator content is empty
      - entries beyond the first 50 (cap against unbounded lists)
    Strips surrounding whitespace and trailing slashes.
    """
    safe: list[str] = []
    for raw in patterns[:_MAX_REPO_CONFIG_PATTERNS]:
        p = str(raw).strip().rstrip("/")
        if not p:
            continue
        if p in _OVERBROAD_PATTERNS:
            continue
        # Pattern with nothing but wildcards/separators after stripping
        if not p.replace("*", "").replace("?", "").replace("/", "").replace(".", ""):
            continue
        safe.append(p)
    return safe


class Scanner:
    def __init__(self, config: ScanConfig) -> None:
        self.config = config
        self.indexer = FileIndexer()

    def _resolve_engines(self) -> list[tuple]:
        """Return list of (detector_instance, display_label) pairs for enabled engines."""
        registry = get_registry()
        requested = self.config.engines

        if requested == [ALL_ENGINES]:
            names = phase1_engines()
        elif requested == [FAST_ENGINES]:
            names = fast_engines()
        else:
            names = requested

        detectors = []
        for name in names:
            if name not in registry:
                continue
            spec = registry[name]
            if spec.phase == 1:  # only run implemented engines
                detectors.append((spec.cls(), spec.label))
        return detectors

    def _emit(self, stage: str, step: int, total: int) -> None:
        if self.config.on_progress is not None:
            self.config.on_progress(stage, step, total)

    def scan(self) -> ScanResult:
        started_at = datetime.now(timezone.utc)
        detector_pairs = self._resolve_engines()
        total_steps = 4 + len(detector_pairs)  # index + parse + build-refs + N engines + git metrics
        step = 0

        # 1. Merge CLI/API excludes with ghostlint.toml (only for trusted/local repos)
        cfg_excludes: list[str] = []
        if self.config.trust_repo_config:
            repo_cfg = _load_repo_config(self.config.repo_path)
            cfg_excludes = repo_cfg.get("exclude", [])
        merged_exclude_paths = list(self.config.exclude_paths) + cfg_excludes

        # 2. Index all relevant files
        step += 1
        self._emit("Indexing files", step, total_steps)
        files = self.indexer.index(
            self.config.repo_path,
            self.config.exclude_dirs,
            exclude_paths=merged_exclude_paths,
        )

        # 3. Parse each file — two passes to ensure all definitions exist before
        #    references are resolved (avoids false dead-code when file A imports
        #    from file B that is parsed later alphabetically).
        step += 1
        self._emit("Parsing source files", step, total_steps)
        symbol_graph = SymbolGraph()
        parsed: list[tuple] = []
        for file_info in files:
            parser = PARSERS.get(file_info.language)
            if parser is None:
                continue
            try:
                defs, refs = parser.parse_file(file_info)
                parsed.append((defs, refs))
            except Exception:
                continue

        step += 1
        self._emit("Building symbol graph", step, total_steps)
        for defs, _ in parsed:
            for d in defs:
                symbol_graph.add_definition(d)

        for _, refs in parsed:
            for r in refs:
                symbol_graph.add_reference(r)

        context = AnalysisContext(
            files=files,
            symbol_graph=symbol_graph,
            repo_path=str(self.config.repo_path),
        )

        # 4. Run selected engines
        all_findings = []
        changed_set = set(self.config.changed_files) if self.config.changed_files else None
        for detector, label in detector_pairs:
            step += 1
            self._emit(f"Running: {label}", step, total_steps)
            try:
                findings = detector.detect(context)
                # Filter to changed files only (symbol graph still built from ALL files
                # for accurate cross-file reference resolution)
                if changed_set is not None:
                    findings = [f for f in findings if f.primary_file in changed_set]
                all_findings.extend(findings)
            except Exception:
                pass

        # 5. Score and recommend
        health_score = compute_health_score(
            all_findings,
            total_symbols=symbol_graph.total_definitions(),
            total_files=len(files),
        )
        recommendations = generate_recommendations(all_findings)

        # 6. Git metrics + HEAD SHA (best-effort — never fails the scan)
        step += 1
        self._emit("Analysing git history", step, total_steps)
        from ghostlint_engine.git_metrics import compute_git_metrics
        git_metrics = compute_git_metrics(self.config.repo_path)
        commit_sha = _detect_head_sha(self.config.repo_path)

        completed_at = datetime.now(timezone.utc)

        result = ScanResult(
            repo_path=str(self.config.repo_path),
            scan_mode=self.config.scan_mode,
            started_at=started_at,
            completed_at=completed_at,
            health_score=health_score,
            findings=all_findings,
            recommendations=recommendations,
            files_scanned=len(files),
            symbols_found=symbol_graph.total_definitions(),
            git_metrics=git_metrics,
            commit_sha=commit_sha,
        )

        # 7. Persist to SQLite (skipped for partial / ephemeral scans)
        if not self.config.skip_persist:
            self._save(result, health_score)
        return result

    def _save(self, result: ScanResult, health_score: HealthScore) -> None:
        try:
            session = get_session()
            scan_rec = ScanRecord(
                id=result.id,
                repo_path=result.repo_path,
                scan_mode=result.scan_mode,
                started_at=result.started_at,
                completed_at=result.completed_at,
                status="completed",
                health_score_overall=health_score.overall,
                health_score_json=json.dumps({
                    "overall": health_score.overall,
                    "dead_code": health_score.dead_code,
                    "duplicate_logic": health_score.duplicate_logic,
                    "refactor_completion": health_score.refactor_completion,
                    "architectural_drift": health_score.architectural_drift,
                    "dependency_health": health_score.dependency_health,
                    "documentation_freshness": health_score.documentation_freshness,
                    "test_health": health_score.test_health,
                    "config_consistency": health_score.config_consistency,
                }),
                files_scanned=result.files_scanned,
                symbols_found=result.symbols_found,
                commit_sha=result.commit_sha,
            )
            for f in result.findings:
                scan_rec.findings.append(FindingRecord(
                    id=f.id,
                    scan_id=result.id,
                    category=f.category.value,
                    title=f.title,
                    description=f.description,
                    file_path=f.primary_file,
                    line_start=f.primary_line,
                    line_end=f.evidence[0].line_end if f.evidence else 0,
                    confidence=f.confidence,
                    risk=f.risk.value,
                    effort=f.effort.value,
                    benefit=f.benefit,
                    autofix_available=f.autofix_available,
                    evidence_json=json.dumps([
                        {"file": e.file_path, "line_start": e.line_start,
                         "line_end": e.line_end, "snippet": e.snippet}
                        for e in f.evidence
                    ]),
                ))
            session.add(scan_rec)
            session.commit()
            session.close()
        except Exception:
            pass  # storage failure should never crash a scan
