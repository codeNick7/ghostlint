from __future__ import annotations
from tiramasu_engine.detectors.base import BaseDetector
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import Finding


class _StubDetector(BaseDetector):
    """Placeholder — implemented in Phase 2."""

    def detect(self, context: AnalysisContext) -> list[Finding]:
        return []
