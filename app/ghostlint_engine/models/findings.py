from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import uuid


class DetectionCategory(str, Enum):
    DEAD_CODE = "dead_code"
    DUPLICATE_LOGIC = "duplicate_logic"
    REFACTOR_COMPLETION = "refactor_completion"
    ARCHITECTURAL_DRIFT = "architectural_drift"
    CONFIG_HEALTH = "config_health"
    DOC_HEALTH = "doc_health"
    DEPENDENCY_HEALTH = "dependency_health"
    TEST_HEALTH = "test_health"
    NAMING_CONSISTENCY = "naming_consistency"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EffortLevel(str, Enum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


@dataclass
class Evidence:
    file_path: str
    line_start: int
    line_end: int
    snippet: str = ""


@dataclass
class Finding:
    category: DetectionCategory
    title: str
    description: str
    evidence: list[Evidence]
    confidence: float           # 0.0–1.0
    risk: RiskLevel
    effort: EffortLevel
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    autofix_available: bool = False
    benefit: str = ""

    @property
    def primary_file(self) -> str:
        return self.evidence[0].file_path if self.evidence else ""

    @property
    def primary_line(self) -> int:
        return self.evidence[0].line_start if self.evidence else 0


@dataclass
class HealthScore:
    overall: float = 100.0
    dead_code: float = 100.0
    duplicate_logic: float = 100.0
    refactor_completion: float = 100.0
    architectural_drift: float = 100.0
    config_consistency: float = 100.0
    documentation_freshness: float = 100.0
    dependency_health: float = 100.0
    test_health: float = 100.0


@dataclass
class Recommendation:
    title: str
    description: str
    finding_id: str
    files: list[str]
    confidence: float
    risk: RiskLevel
    effort: EffortLevel
    benefit: str = ""


@dataclass
class GitMetrics:
    """Git-history-derived health metrics. All scores 0–100 unless noted."""
    available: bool = False                  # False when not a git repo
    stability_index: float = 0.0            # 100 = no core-file churn
    maintenance_velocity: float = 0.0       # 0–1 ratio of fix-commits / total
    refactor_completion_rate: float = 0.0   # % improvement in tech-debt markers
    friction_index: float = 0.0             # 0 = frictionless, 100 = high friction
    total_commits_analyzed: int = 0
    repo_age_days: int = 0
    top_contributors: int = 0


@dataclass
class ScanResult:
    repo_path: str
    scan_mode: str
    started_at: datetime
    completed_at: datetime
    health_score: HealthScore
    findings: list[Finding]
    recommendations: list[Recommendation]
    files_scanned: int
    symbols_found: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    git_metrics: GitMetrics = field(default_factory=GitMetrics)
    commit_sha: str | None = None
