import pytest
from pydantic import ValidationError

from app.schemas.contacts import ContactIn, ContactUpdate


def test_an_address_is_normalised_on_the_way_in():
    assert ContactIn(email="  Owner@ACME.test ").email == "owner@acme.test"


def test_a_malformed_address_is_rejected():
    with pytest.raises(ValidationError):
        ContactIn(email="not-an-email")


def test_a_contact_needs_at_least_a_name_or_an_address():
    """A row with neither is not a contact."""
    with pytest.raises(ValidationError):
        ContactIn(phone="+17135550100")


def test_a_name_with_no_address_is_allowed():
    """Recording 'the owner is John Smith, address unknown' is legitimate
    contact discovery."""
    assert ContactIn(name="John Smith").name == "John Smith"


def test_a_linkedin_url_must_be_http():
    with pytest.raises(ValidationError):
        ContactIn(name="John", linkedin_url="linkedin.com/in/john")


@pytest.mark.parametrize("field,value", [
    ("name", "x" * 201), ("role", "x" * 101), ("linkedin_url", "x" * 501),
])
def test_over_long_fields_are_rejected(field, value):
    # NOTE: the brief's literal `ContactIn(name="John", **{field: value})`
    # raises TypeError (duplicate keyword) rather than ValidationError when
    # field == "name" -- a test-authoring bug, not a schema behaviour
    # question. Building kwargs this way preserves the intent (a
    # valid base plus one overlong field) for every parametrize case.
    kwargs = {"name": "John"}
    kwargs[field] = value
    with pytest.raises(ValidationError):
        ContactIn(**kwargs)


def test_contact_update_with_only_a_role_constructs_cleanly():
    """The name-or-email rule belongs to creation, not to a partial edit.
    `{"role": "GM"}` is a legitimate partial update of a contact that
    already has a name -- if ContactUpdate inherited ContactIn's
    model_validator, this would raise a ValidationError and make every
    partial edit a 422."""
    update = ContactUpdate(role="GM")
    assert update.role == "GM"
