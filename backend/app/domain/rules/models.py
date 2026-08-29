from dataclasses import dataclass, field
from typing import Any, Literal

Track = Literal["fit", "pain"]
OnMissing = Literal["skip", "zero"]


@dataclass(frozen=True)
class Rule:
    id: str
    track: Track
    when: dict[str, Any]
    points: int
    label: str
    on_missing: OnMissing = "skip"
    evidence: str | None = None


@dataclass(frozen=True)
class Ruleset:
    version: str
    vertical: str
    threshold: int
    fit_rules: list[Rule] = field(default_factory=list)
    pain_rules: list[Rule] = field(default_factory=list)


@dataclass(frozen=True)
class RuleReason:
    rule: str
    track: str
    matched: bool
    points: int
    label: str
    evidence: list[str] | None = None


@dataclass(frozen=True)
class ScoreResult:
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    reasons: list[RuleReason]
