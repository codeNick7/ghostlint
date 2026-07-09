from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tiramasu_engine.indexer import FileIndexer
from tiramasu_engine.ast_engine import PARSERS
from tiramasu_engine.graph.symbol_graph import SymbolGraph
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.detectors.registry import get_registry, phase1_engines, fast_engines
from tiramasu_engine.health_score import compute_health_score
from tiramasu_engine.recommendations import generate_recommendations
from tiramasu_engine.models.findings import ScanResult, HealthScore
from tiramasu_engine.db.session import get_session
from tiramasu_engine.db.models import ScanRecord, FindingRecord

#: Sentinel passed to engines= to mean "run all phase-1 engines"
ALL_ENGINES = "__all__"
#: Sentinel to run only fast engines (pre-commit mode)
FAST_ENGINES = "__fast__"


@dataclass
class ScanConfig:
    repo_path: Path
    scan_mode: str = "full"
    exclude_dirs: set[str] = field(default_factory=set)
    confidence_threshold: float = 0.6
    engines: list[str] = field(default_factory=lambda: [ALL_ENGINES])


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

        # 1. Index all relevant files
        files = self.indexer.index(self.config.repo_path, self.config.exclude_dirs)

        # 2. Parse each file — two passes to ensure all definitions exist before
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

        # 3. Run selected engines
        all_findings = []
        for detector in detectors:
            try:
                findings = detector.detect(context)
                all_findings.extend(findings)
            except Exception:
                pass

        # 4. Score and recommend
        health_score = compute_health_score(all_findings, symbol_graph.total_definitions())
        recommendations = generate_recommendations(all_findings)
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
        )

        # 5. Persist to SQLite
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
