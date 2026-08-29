import pytest
from app.domain.rules.models import Rule, Ruleset
from app.domain.rules.engine import evaluate

RS = Ruleset(
    version="test_v1", vertical="hvac", threshold=60,
    fit_rules=[
        Rule(id="software", track="fit",
             when={"signal": "booking_vendor", "op": "in",
                   "value": ["servicetitan", "housecallpro"]},
             points=60, label="Uses {booking_vendor}"),
        Rule(id="employees", track="fit",
             when={"signal": "estimated_employees", "op": "gte", "value": 10},
             points=40, label="10+ employees", on_missing="skip"),
    ],
    pain_rules=[
        Rule(id="closed_weekends", track="pain",
             when={"signal": "closed_weekends", "op": "is_true"},
             points=70, label="Closed weekends"),
        Rule(id="complaints", track="pain",
             when={"signal": "missed_call_complaints_90d", "op": "gte", "value": 3},
             points=30, label="{missed_call_complaints_90d} complaints",
             on_missing="skip", evidence="complaint_quotes"),
    ],
)


def test_all_rules_present_and_matching():
    r = evaluate({"booking_vendor": "servicetitan", "estimated_employees": 20,
                  "closed_weekends": True, "missed_call_complaints_90d": 4,
                  "complaint_quotes": ["nobody answered"]}, RS)
    assert r.fit_score == 100 and r.pain_score == 100
    assert r.coverage == 1.0
    assert r.quadrant == "go_now"


def test_missing_signal_is_skipped_not_zeroed():
    """The core of ADR-005. A basic-tier lead has no review data; skipping
    keeps its pain score comparable instead of unfairly crushing it."""
    r = evaluate({"booking_vendor": "servicetitan", "closed_weekends": True}, RS)
    assert r.fit_score == 100        # 60 of 60 applicable — employees skipped
    assert r.pain_score == 100       # 70 of 70 applicable — complaints skipped
    assert r.coverage == 0.5         # 2 of 4 rules applicable


def test_on_missing_zero_counts_against_the_denominator():
    rs = Ruleset(version="z", vertical="hvac", threshold=60, fit_rules=[
        Rule(id="a", track="fit", when={"signal": "x", "op": "is_true"},
             points=50, label="a"),
        Rule(id="b", track="fit", when={"signal": "y", "op": "is_true"},
             points=50, label="b", on_missing="zero"),
    ], pain_rules=[])
    r = evaluate({"x": True}, rs)
    assert r.fit_score == 50         # y is absent but still in the denominator


def test_quadrants():
    assert evaluate({"booking_vendor": "servicetitan",
                     "closed_weekends": False}, RS).quadrant == "nurture"
    assert evaluate({"booking_vendor": "own",
                     "closed_weekends": True}, RS).quadrant == "low_fit"
    assert evaluate({"booking_vendor": "own",
                     "closed_weekends": False}, RS).quadrant == "cold"


def test_all_rules_skipped_yields_zero_coverage_not_a_crash():
    r = evaluate({}, RS)
    assert r.coverage == 0.0
    assert r.fit_score == 0 and r.pain_score == 0


def test_label_is_interpolated_and_evidence_attached():
    r = evaluate({"booking_vendor": "servicetitan", "closed_weekends": True,
                  "missed_call_complaints_90d": 4,
                  "complaint_quotes": ["called 3 times, no answer"]}, RS)
    by_id = {x.rule: x for x in r.reasons}
    assert by_id["software"].label == "Uses servicetitan"
    assert by_id["complaints"].evidence == ["called 3 times, no answer"]


def test_all_group_requires_every_condition():
    rs = Ruleset(version="g", vertical="hvac", threshold=60, fit_rules=[
        Rule(id="combo", track="fit",
             when={"all": [{"signal": "a", "op": "is_true"},
                           {"signal": "b", "op": "is_true"}]},
             points=100, label="both"),
    ], pain_rules=[])
    assert evaluate({"a": True, "b": True}, rs).fit_score == 100
    assert evaluate({"a": True, "b": False}, rs).fit_score == 0
