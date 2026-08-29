import yaml
from pathlib import Path
import pytest
from app.domain.rules.loader import load_ruleset
from app.domain.rules.engine import evaluate

RULESET = load_ruleset(
    yaml.safe_load(Path("config/rulesets/hvac_v1.yaml").read_text())
)

# Real Houston businesses. Golden expectations — when a weight changes,
# this diff shows exactly which leads moved.
ROYAL_AIR = {            # 8,758 reviews, 8-5 M-F, closed weekends, own booking
    "booking_vendor": "own", "has_booking_link": True, "is_phone_only": False,
    "closed_weekends": True, "closes_before_6pm": True,
    "has_chat_widget": False, "runs_google_ads": True,
}
AIR_TECH = {             # 6,445 reviews, 24/7 every day, ServiceTitan
    "booking_vendor": "servicetitan", "has_booking_link": True,
    "is_phone_only": False, "closed_weekends": False, "closes_before_6pm": False,
    "has_chat_widget": True, "runs_google_ads": True,
}
HEIGHTS_AC = {           # 72 reviews, 8-5 M-F, closed weekends, NO booking link
    "booking_vendor": "none", "has_booking_link": False, "is_phone_only": True,
    "closed_weekends": True, "closes_before_6pm": True,
    "has_chat_widget": False, "runs_google_ads": False,
}


def test_royal_air_is_high_pain_despite_being_enterprise_sized():
    """ADR-022's motivating case: big AND provably uncovered."""
    r = evaluate(ROYAL_AIR, RULESET)
    # fit:  ads 25 + booking 20 = 45 earned of 75 applicable
    #       (software rule applicable but unmatched; employees skipped) -> 60
    assert r.fit_score == 60
    # pain: weekends 30 + closes_early 25 + no_chat 20 = 75 of 100 applicable
    #       (phone_only unmatched; both review rules skipped) -> 75
    assert r.pain_score == 75
    assert r.coverage == 0.7          # 7 of 10 rules applicable
    assert r.quadrant == "go_now"


def test_air_tech_is_good_fit_but_low_pain():
    r = evaluate(AIR_TECH, RULESET)
    assert r.fit_score == 100         # software 30 + ads 25 + booking 20 of 75
    assert r.pain_score == 0          # 24/7, has booking, has chat
    assert r.quadrant == "nurture"


def test_heights_ac_is_all_pain_and_little_fit():
    r = evaluate(HEIGHTS_AC, RULESET)
    assert r.pain_score == 100        # all four always-on pain rules matched
    assert r.fit_score == 0           # no software, no ads, no booking
    assert r.quadrant == "low_fit"


def test_dormant_review_rules_are_skipped_at_basic_tier():
    r = evaluate(ROYAL_AIR, RULESET)
    ids = {x.rule for x in r.reasons}
    assert "missed_call_complaints" not in ids
    assert "review_velocity" not in ids
    assert r.coverage < 1.0


def test_enriched_tier_activates_the_review_rules():
    enriched = {**ROYAL_AIR, "missed_call_complaints_90d": 4,
                "review_velocity_90d": 9,
                "complaint_quotes": ["Called 3 times, nobody answered"]}
    r = evaluate(enriched, RULESET)
    ids = {x.rule for x in r.reasons}
    assert "missed_call_complaints" in ids
    assert r.coverage > evaluate(ROYAL_AIR, RULESET).coverage
