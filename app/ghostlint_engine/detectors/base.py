from __future__ import annotations
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import Finding


class BaseDetector:
    category: str = ""

    def detect(self, context: AnalysisContext) -> list[Finding]:
        raise NotImplementedError
