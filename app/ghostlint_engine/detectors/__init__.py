from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.detectors.dead_code import DeadCodeDetector
from ghostlint_engine.detectors.registry import (
    get_registry,
    get_engine,
    available_engines,
    phase1_engines,
    fast_engines,
    EngineSpec,
)

__all__ = [
    "BaseDetector",
    "DeadCodeDetector",
    "get_registry",
    "get_engine",
    "available_engines",
    "phase1_engines",
    "fast_engines",
    "EngineSpec",
]
