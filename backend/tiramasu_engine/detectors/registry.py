from __future__ import annotations
from dataclasses import dataclass
from tiramasu_engine.detectors.base import BaseDetector


@dataclass(frozen=True)
class EngineSpec:
    name: str            # canonical name used in CLI, API, config
    label: str           # human-readable label for reports
    phase: int           # 1 = shipped, 2 = coming soon
    speed: str           # fast | medium | slow  (matters for pre-commit vs full scan)
    description: str
    cls: type[BaseDetector]


def _load() -> dict[str, EngineSpec]:
    # Imported lazily inside function to keep module load fast and avoid
    # circular imports. Each import only pays cost when registry is first built.
    from tiramasu_engine.detectors.dead_code import DeadCodeDetector
    from tiramasu_engine.detectors.duplicate_logic.detector import DuplicateLogicDetector
    from tiramasu_engine.detectors.refactor.detector import RefactorDetector
    from tiramasu_engine.detectors.arch_drift.detector import ArchDriftDetector
    from tiramasu_engine.detectors.config_health.detector import ConfigHealthDetector
    from tiramasu_engine.detectors.doc_health.detector import DocHealthDetector
    from tiramasu_engine.detectors.dependency_health.detector import DependencyHealthDetector
    from tiramasu_engine.detectors.test_health.detector import TestHealthDetector
    from tiramasu_engine.detectors.naming.detector import NamingConsistencyDetector

    specs = [
        EngineSpec(
            name="dead_code",
            label="Dead Code",
            phase=1,
            speed="fast",
            description="Detects unused functions, methods, and classes with zero callers.",
            cls=DeadCodeDetector,
        ),
        EngineSpec(
            name="duplicate_logic",
            label="Duplicate Logic",
            phase=1,
            speed="slow",
            description="Detects structurally identical functions via AST fingerprinting.",
            cls=DuplicateLogicDetector,
        ),
        EngineSpec(
            name="refactor",
            label="Incomplete Refactors",
            phase=1,
            speed="medium",
            description="Detects coexisting old/new APIs and abandoned migration leftovers.",
            cls=RefactorDetector,
        ),
        EngineSpec(
            name="arch_drift",
            label="Architectural Drift",
            phase=1,
            speed="medium",
            description="Detects boundary violations, cyclic dependencies, and layer leakage.",
            cls=ArchDriftDetector,
        ),
        EngineSpec(
            name="config_health",
            label="Configuration Health",
            phase=1,
            speed="fast",
            description="Detects conflicts and drift across .env config files.",
            cls=ConfigHealthDetector,
        ),
        EngineSpec(
            name="doc_health",
            label="Documentation Health",
            phase=1,
            speed="medium",
            description="Detects stale TODO/FIXME comments and misleading docstrings.",
            cls=DocHealthDetector,
        ),
        EngineSpec(
            name="dependency_health",
            label="Dependency Health",
            phase=1,
            speed="fast",
            description="Detects unused, duplicate, and undeclared packages.",
            cls=DependencyHealthDetector,
        ),
        EngineSpec(
            name="test_health",
            label="Test Health",
            phase=1,
            speed="medium",
            description="Detects orphan tests calling functions that no longer exist.",
            cls=TestHealthDetector,
        ),
        EngineSpec(
            name="naming",
            label="Naming Consistency",
            phase=1,
            speed="slow",
            description="Detects duplicate DTOs, near-identical models, and inconsistent conventions.",
            cls=NamingConsistencyDetector,
        ),
    ]
    return {s.name: s for s in specs}


_registry: dict[str, EngineSpec] | None = None


def get_registry() -> dict[str, EngineSpec]:
    global _registry
    if _registry is None:
        _registry = _load()
    return _registry


def get_engine(name: str) -> EngineSpec:
    reg = get_registry()
    if name not in reg:
        raise KeyError(f"Unknown engine '{name}'. Available: {list(reg)}")
    return reg[name]


def available_engines() -> list[str]:
    return list(get_registry().keys())


def phase1_engines() -> list[str]:
    return [name for name, spec in get_registry().items() if spec.phase == 1]


def fast_engines() -> list[str]:
    """Engines suitable for pre-commit hooks (<10s target)."""
    return [name for name, spec in get_registry().items() if spec.speed == "fast" and spec.phase == 1]
