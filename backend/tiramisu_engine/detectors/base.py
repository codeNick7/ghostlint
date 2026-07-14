from __future__ import annotations
from tiramisu_engine.graph.context import AnalysisContext
from tiramisu_engine.models.findings import Finding


class BaseDetector:
    category: str = ""

    def detect(self, context: AnalysisContext) -> list[Finding]:
        raise NotImplementedError
