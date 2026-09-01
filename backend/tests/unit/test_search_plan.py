"""`build_search_plan` is the single place the CLI, the API router, and the
scheduler (via `execute_run`) turn a vertical/state/location into queries.
Normalisation and validation belong here, once, rather than duplicated (or
worse, missing) in each caller.
"""
import pytest

from app.services.search_plan import build_search_plan

VERTICALS = {"hvac": {"search_terms": ["hvac contractor", "ac repair"],
                      "ruleset": "hvac_v1"}}
LOCATIONS = {"tx": {"metros": ["Houston, TX", "Dallas, TX", "Austin, TX"]}}


@pytest.mark.parametrize("state", ["TX", "tx", "Tx"])
def test_build_search_plan_is_case_insensitive_on_state(state):
    plan = build_search_plan("hvac", state, None, VERTICALS, LOCATIONS)

    assert plan.locations == ["Houston, TX", "Dallas, TX", "Austin, TX"]


def test_build_search_plan_returns_identical_plans_across_state_casing():
    plans = [build_search_plan("hvac", s, None, VERTICALS, LOCATIONS)
             for s in ("TX", "tx", "Tx")]

    assert plans[0] == plans[1] == plans[2]


def test_build_search_plan_rejects_an_unknown_state_with_a_value_error():
    with pytest.raises(ValueError):
        build_search_plan("hvac", "ZZ", None, VERTICALS, LOCATIONS)


def test_build_search_plan_rejects_an_unknown_vertical_with_a_value_error():
    with pytest.raises(ValueError):
        build_search_plan("not_a_vertical", None, "Houston, TX",
                          VERTICALS, LOCATIONS)
