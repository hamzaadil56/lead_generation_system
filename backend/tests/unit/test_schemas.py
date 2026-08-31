import pytest
from pydantic import ValidationError

from app.schemas.common import Page
from app.schemas.leads import LeadOut
from app.schemas.manual import OutcomeIn
from app.schemas.runs import RunCreate


def test_run_create_requires_one_of_state_or_location():
    with pytest.raises(ValidationError, match="state or location"):
        RunCreate(vertical="hvac")


def test_run_create_accepts_a_location_alone():
    r = RunCreate(vertical="hvac", location="Houston, TX")
    assert r.pages == 5 and r.max_cost_usd is None


def test_run_create_rejects_a_non_positive_page_count():
    with pytest.raises(ValidationError):
        RunCreate(vertical="hvac", location="Houston, TX", pages=0)


def test_outcome_in_rejects_an_unknown_status():
    with pytest.raises(ValidationError):
        OutcomeIn(status="definitely_not_a_status")


def test_outcome_in_accepts_every_valid_status():
    from app.services.outcomes import VALID
    for s in VALID:
        assert OutcomeIn(status=s).status == s


def test_page_reports_whether_more_rows_exist():
    p = Page[LeadOut](items=[], total=25, page=1, page_size=10)
    assert p.pages == 3 and p.has_next is True

    last = Page[LeadOut](items=[], total=25, page=3, page_size=10)
    assert last.has_next is False


def test_page_of_zero_rows_has_one_page_not_zero():
    """A UI that renders `page 1 of 0` looks broken."""
    p = Page[LeadOut](items=[], total=0, page=1, page_size=10)
    assert p.pages == 1 and p.has_next is False


def test_page_computed_fields_appear_in_model_dump():
    """`pages`/`has_next` must be @computed_field, not @property, so the
    frontend's pagination control actually receives them in the JSON body."""
    p = Page[LeadOut](items=[], total=25, page=1, page_size=10)
    dumped = p.model_dump()
    assert dumped["pages"] == 3
    assert dumped["has_next"] is True
