import re
from dataclasses import dataclass

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
WEEKEND = ["Saturday", "Sunday"]
_RANGE = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*[–\-—]\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OpeningHours:
    is_24_7: bool
    closes_before_6pm: bool
    closed_weekends: bool
    parse_failed: bool


def _close_hour_24(text: str) -> int | None:
    """Return the closing hour on a 24h clock, or None if unparseable."""
    m = _RANGE.match(text)
    if not m:
        return None
    open_h, _, open_ap, close_h, _, close_ap = m.groups()
    open_24 = int(open_h) % 12 + (12 if open_ap.upper() == "PM" else 0)
    close_24 = int(close_h) % 12 + (12 if close_ap.upper() == "PM" else 0)
    if close_24 <= open_24:
        return None      # "8 AM–5 AM" — closing before opening is a mis-parse
    return close_24


def parse_opening_hours(raw: dict[str, str] | None) -> OpeningHours:
    if not raw:
        return OpeningHours(False, False, False, parse_failed=True)

    parse_failed = False
    closes_early: list[bool] = []

    for day in WEEKDAYS:
        text = (raw.get(day) or "").strip()
        if text.lower() == "open 24 hours":
            closes_early.append(False)
        elif text.lower() == "closed":
            closes_early.append(True)
        else:
            hour = _close_hour_24(text)
            if hour is None:
                parse_failed = True
            else:
                closes_early.append(hour < 18)

    weekend_states = [(raw.get(d) or "").strip().lower() for d in WEEKEND]
    closed_weekends = all(s == "closed" for s in weekend_states)
    is_24_7 = all(
        (raw.get(d) or "").strip().lower() == "open 24 hours"
        for d in WEEKDAYS + WEEKEND
    )

    return OpeningHours(
        is_24_7=is_24_7,
        closes_before_6pm=bool(closes_early) and all(closes_early),
        closed_weekends=closed_weekends,
        parse_failed=parse_failed,
    )
