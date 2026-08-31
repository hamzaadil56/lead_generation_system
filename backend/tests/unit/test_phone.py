import pytest
from app.domain.phone import validate_phone


@pytest.mark.parametrize("raw,expected", [
    ("(832) 680-5546", "+18326805546"),
    ("(713) 428-2279", "+17134282279"),
    ("832-680-5546", "+18326805546"),
    ("+1 832 680 5546", "+18326805546"),
    # Real Serper defect: the address lands in the phone field (ADR-013).
    ("3950 24th St", None),
    ("3251 20th Ave Suite 340", None),
    ("", None),
    (None, None),
    ("555-1234", None),              # too few digits
])
def test_validate_phone(raw, expected):
    assert validate_phone(raw) == expected
