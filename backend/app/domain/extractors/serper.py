from typing import Any
from app.domain.hours import parse_opening_hours
from app.domain.booking import classify_booking_links


def extract_serper_signals(opening_hours: dict[str, str] | None,
                           booking_links: list[str] | None,
                           segment: str | None) -> dict[str, Any]:
    """Everything obtainable at discovery — ~65 of 200 points, free (ADR-021)."""
    hours = parse_opening_hours(opening_hours)
    booking = classify_booking_links(booking_links)
    return {
        "is_24_7": hours.is_24_7,
        "closes_before_6pm": hours.closes_before_6pm,
        "closed_weekends": hours.closed_weekends,
        "hours_parse_failed": hours.parse_failed,
        "booking_vendor": str(booking.vendor),
        "has_booking_link": booking.has_booking,
        "is_phone_only": booking.is_phone_only,
        "segment": segment,
    }
