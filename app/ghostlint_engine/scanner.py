from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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


def _load_repo_config(repo_path: Path) -> dict:
    """Load ghostlint.toml from the repository root, if present.

    Returns a dict with zero or more of these keys:
      ``exclude`` — list of path patterns to exclude from scanning

    Silent on any parse error so a broken config file never prevents a scan.
    """
    for name in ("ghostlint.toml",):
        cfg_path = repo_path / name
        if not cfg_path.exists():
            continue
        try:
            import tomllib
            with cfg_path.open("rb") as fh:
                data = tomllib.load(fh)
            return data.get("scan", data)  # support [scan] table or flat top-level
        except Exception:
            pass
    return {}


class Scanner:
    def __init__(self, config: ScanConfig) -> None:
        self.config = config
        self.indexer = FileIndexer()

    def _resolve_engines(self) -> list:
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
                detectors.append(spec.cls())
        return detectors

    def scan(self) -> ScanResult:
        started_at = datetime.now(timezone.utc)
        detectors = self._resolve_engines()

        # 1. Merge CLI/API excludes with any ghostlint.toml config from the repo root
        repo_cfg = _load_repo_config(self.config.repo_path)
        cfg_excludes: list[str] = repo_cfg.get("exclude", [])
        if not isinstance(cfg_excludes, list):
            cfg_excludes = []
        merged_exclude_paths = list(self.config.exclude_paths) + cfg_excludes

        # 2. Index all relevant files
        files = self.indexer.index(
            self.config.repo_path,
            self.config.exclude_dirs,
            exclude_paths=merged_exclude_paths,
        )

        # 3. Parse each file — two passes to ensure all definitions exist before
        #    references are resolved (avoids false dead-code when file A imports
        #    from file B that is parsed later alphabetically).
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
        for detector in detectors:
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
        health_score = compute_health_score(all_findings, symbol_graph.total_definitions())
        recommendations = generate_recommendations(all_findings)

        # 6. Git metrics (best-effort — never fails the scan)
        from ghostlint_engine.git_metrics import compute_git_metrics
        git_metrics = compute_git_metrics(self.config.repo_path)

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
