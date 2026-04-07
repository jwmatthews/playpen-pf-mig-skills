"""
Pydantic v2 data models for the migration evaluation system.

Covers: evaluation configuration, scoring results, LLM assessment,
cross-attempt comparison, composite evaluation results, and problem areas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class PatternStatus(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    missing = "missing"
    file_missing = "file_missing"
    not_migrated = "not_migrated"
    not_applicable = "not_applicable"


class ProblemAreaType(str, Enum):
    pattern_cluster = "pattern_cluster"
    file_cluster = "file_cluster"
    complexity_tier = "complexity_tier"
    llm_finding = "llm_finding"


class ProblemAreaSource(str, Enum):
    deterministic = "deterministic"
    adversarial = "adversarial"


class RefereeVerdict(str, Enum):
    real = "real"
    not_real = "not_real"


# ---------------------------------------------------------------------------
# Evaluation config
# ---------------------------------------------------------------------------

class AttemptConfig(BaseModel):
    name: str
    path: str


class EvaluationConfig(BaseModel):
    golden_dir: str
    attempts: list[AttemptConfig]
    output_dir: str
    target: str | None = None


# ---------------------------------------------------------------------------
# Scoring results (mirrors scoring-results.json)
# ---------------------------------------------------------------------------

class ComponentScore(BaseModel):
    score: float
    weight: float
    weighted: float


class FileCoverageComponent(ComponentScore):
    matched: int = 0
    total: int = 0


class PatternScoreComponent(ComponentScore):
    by_complexity: dict[str, dict[str, int]] = Field(default_factory=dict)


class NoisePenaltyComponent(BaseModel):
    raw_penalty: float
    capped_penalty: float
    weight: float
    weighted: float
    instance_count: int = 0


class ScoreBreakdown(BaseModel):
    overall_score: float
    overall_percent: int
    grade: str
    points: float = 0.0
    positive_points: float = 0.0
    negative_points: float = 0.0
    components: dict[str, Any] = Field(default_factory=dict)


class PatternDetail(BaseModel):
    file: str
    abs_path: str = ""
    line: int | None = None
    status: str
    message: str = ""


class PatternResult(BaseModel):
    pattern_id: str
    name: str
    complexity: str = "moderate"
    weight: int = 2
    status: str
    message: str = ""
    files: list[str] = Field(default_factory=list)
    details: list[PatternDetail] = Field(default_factory=list)


class NoiseInstance(BaseModel):
    type: str
    file: str
    line: int | None = None
    detail: str = ""
    penalty: float = 0.0


class ScoringMetadata(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    target: str | None = None
    target_patterns_loaded: int = 0
    scoring_version: str = "1.0"
    dir_a: str = ""
    dir_b: str = ""
    label: str | None = None


class ScoringResults(BaseModel):
    metadata: ScoringMetadata
    score: ScoreBreakdown
    pattern_results: list[PatternResult] = Field(default_factory=list)
    noise_instances: list[NoiseInstance] = Field(default_factory=list)
    file_results: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM adversarial assessment
# ---------------------------------------------------------------------------

class AdversarialIssue(BaseModel):
    id: str
    description: str
    severity: Severity | None = Severity.medium
    impact_score: int = 5
    bug_finder_argument: str = ""
    adversary_argument: str = ""
    referee_verdict: RefereeVerdict = RefereeVerdict.real
    referee_confidence: float = 0.5


class FileAssessment(BaseModel):
    attempt: str
    file: str
    issues: list[AdversarialIssue] = Field(default_factory=list)
    summary_score: float = 1.0


class LLMAssessmentMetadata(BaseModel):
    files_assessed: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LLMAssessment(BaseModel):
    metadata: LLMAssessmentMetadata = Field(default_factory=LLMAssessmentMetadata)
    file_assessments: list[FileAssessment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cross-attempt comparison
# ---------------------------------------------------------------------------

class PatternAdvantage(BaseModel):
    pattern_id: str
    name: str = ""
    a_status: str = ""
    b_status: str = ""


class AttemptComparison(BaseModel):
    delta: float = 0.0
    a_advantages: list[PatternAdvantage] = Field(default_factory=list)
    b_advantages: list[PatternAdvantage] = Field(default_factory=list)
    ties: list[str] = Field(default_factory=list)
    neither: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Problem areas
# ---------------------------------------------------------------------------

class ProblemArea(BaseModel):
    type: ProblemAreaType
    source: ProblemAreaSource
    severity: Severity
    attempt: str
    pattern_ids: list[str] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)
    description: str
    recommendation: str = ""
    referee_confidence: float | None = None


# ---------------------------------------------------------------------------
# Composite evaluation results
# ---------------------------------------------------------------------------

class AttemptScore(BaseModel):
    overall_percent: int
    grade: str
    points: float = 0.0
    positive_points: float = 0.0
    negative_points: float = 0.0
    deterministic_percent: int = 0
    llm_score: float | None = None
    composite_percent: int | None = None
    composite_grade: str | None = None
    composite_points: float | None = None
    components: dict[str, Any] = Field(default_factory=dict)


class LLMSummary(BaseModel):
    files_assessed: int = 0
    issues_found: int = 0
    issues_confirmed: int = 0
    average_file_score: float = 0.0


class EvaluationMetadata(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    golden_dir: str = ""
    before_migration_dir: str | None = None
    attempts: dict[str, str] = Field(default_factory=dict)
    target: str | None = None


class EvaluationResults(BaseModel):
    metadata: EvaluationMetadata = Field(default_factory=EvaluationMetadata)
    attempt_scores: dict[str, AttemptScore] = Field(default_factory=dict)
    comparisons: dict[str, AttemptComparison] = Field(default_factory=dict)
    problem_areas: list[ProblemArea] = Field(default_factory=list)
    llm_summary: LLMSummary | None = None
    pairwise_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw pairwise scoring data keyed by attempt name",
    )
