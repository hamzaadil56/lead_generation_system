import re

_DIGITS = re.compile(r"\D")


def validate_phone(raw: str | None) -> str | None:
    """Return E.164 for a valid US number, else None.

    Serper sometimes returns the street address in `phoneNumber` (ADR-013),
    so this is a gate, not a formatter.
    """
    if not raw:
        return None
    digits = _DIGITS.sub("", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[0] in "01" or digits[3] in "01":   # invalid NANP area/exchange
        return None
    return f"+1{digits}"
