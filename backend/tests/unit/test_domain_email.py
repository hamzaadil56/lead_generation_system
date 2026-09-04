import pytest

from app.domain.email import (domain_stem, email_domain, normalize_email,
                              registrable_domain)


@pytest.mark.parametrize("raw,expected", [
    ("  Owner@Acme.TEST ", "owner@acme.test"),
    ("<john@acme.test>", "john@acme.test"),
    ("john.smith+leads@acme.co.uk", "john.smith+leads@acme.co.uk"),
])
def test_valid_addresses_are_lowercased_and_stripped(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "   ", "no-at-sign.test", "two@at@signs.test",
    "@acme.test", "john@", "john@nodot", "john@acme..test",
    "john doe@acme.test", ".john@acme.test", "john.@acme.test",
    "a" * 250 + "@acme.test",
])
def test_unusable_addresses_return_none(raw):
    assert normalize_email(raw) is None


def test_email_domain_is_the_part_after_the_at():
    assert email_domain("john@mail.acme.test") == "mail.acme.test"


@pytest.mark.parametrize("host,expected", [
    ("acme.test", "acme.test"),
    ("www.acme.test", "acme.test"),
    ("mail.acme.test", "acme.test"),
    ("https://www.acme.test/about?x=1#y", "acme.test"),
    ("acme.test:8080", "acme.test"),
    ("ACME.TEST", "acme.test"),
    # Compound suffix: the registrable domain is three labels, not two.
    ("shop.acme.co.uk", "acme.co.uk"),
    ("localhost", None),
    (None, None),
    ("", None),
])
def test_registrable_domain(host, expected):
    assert registrable_domain(host) == expected


@pytest.mark.parametrize("host,expected", [
    ("www.tryleisuration.com", "tryleisuration"),
    ("acme.test", "acme"),
    ("shop.acme.co.uk", "acme"),
    ("localhost", None),
])
def test_domain_stem_drops_the_suffix(host, expected):
    assert domain_stem(host) == expected
