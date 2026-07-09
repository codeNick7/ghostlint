from __future__ import annotations
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import Finding


class BaseDetector:
    category: str = ""

    def detect(self, context: AnalysisContext) -> list[Finding]:
        raise NotImplementedError
