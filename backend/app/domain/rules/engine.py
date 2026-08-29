from typing import Any
from app.domain.rules.models import Rule, Ruleset, RuleReason, ScoreResult
from app.domain.rules.operators import OPERATORS

_MISSING = object()


def _signals_used(when: dict[str, Any]) -> list[str]:
    if "all" in when or "any" in when:
        out: list[str] = []
        for cond in when.get("all") or when.get("any") or []:
            out.extend(_signals_used(cond))
        return out
    return [when["signal"]]


def _applicable(rule: Rule, signals: dict[str, Any]) -> bool:
    """A skip-rule is applicable only when every signal it reads is present."""
    if rule.on_missing == "zero":
        return True
    return all(signals.get(name, _MISSING) is not _MISSING
               for name in _signals_used(rule.when))


def _matches(when: dict[str, Any], signals: dict[str, Any]) -> bool:
    if "all" in when:
        return all(_matches(c, signals) for c in when["all"])
    if "any" in when:
        return any(_matches(c, signals) for c in when["any"])
    value = signals.get(when["signal"])
    return OPERATORS[when["op"]](value, when.get("value"))


def _score_track(rules: list[Rule], signals: dict[str, Any]
                 ) -> tuple[int, list[RuleReason], int, int]:
    earned = possible = 0
    reasons: list[RuleReason] = []
    applicable_count = 0
    for rule in rules:
        if not _applicable(rule, signals):
            continue
        applicable_count += 1
        possible += rule.points
        matched = _matches(rule.when, signals)
        if matched:
            earned += rule.points
        reasons.append(RuleReason(
            rule=rule.id, track=rule.track, matched=matched,
            points=rule.points if matched else 0,
            label=rule.label.format(**signals) if matched else rule.label,
            evidence=signals.get(rule.evidence) if (matched and rule.evidence) else None,
        ))
    score = round(earned / possible * 100) if possible else 0
    return score, reasons, applicable_count, len(rules)


def evaluate(signals: dict[str, Any], ruleset: Ruleset) -> ScoreResult:
    fit, fit_reasons, fit_app, fit_total = _score_track(ruleset.fit_rules, signals)
    pain, pain_reasons, pain_app, pain_total = _score_track(ruleset.pain_rules, signals)

    total = fit_total + pain_total
    coverage = (fit_app + pain_app) / total if total else 0.0

    t = ruleset.threshold
    if fit >= t and pain >= t:
        quadrant = "go_now"
    elif fit >= t:
        quadrant = "nurture"
    elif pain >= t:
        quadrant = "low_fit"
    else:
        quadrant = "cold"

    return ScoreResult(fit, pain, quadrant, round(coverage, 3),
                       fit_reasons + pain_reasons)
