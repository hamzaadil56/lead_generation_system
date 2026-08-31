import enum


class Segment(enum.StrEnum):
    EMERGING = "emerging"
    GROWTH = "growth"
    ESTABLISHED = "established"
    ENTERPRISE = "enterprise"


SEGMENT_FLOOR = 50


def segment_for(rating_count: int | None) -> Segment | None:
    """Label only — never a filter, never scored (ADR-022)."""
    if rating_count is None or rating_count < SEGMENT_FLOOR:
        return None
    if rating_count < 200:
        return Segment.EMERGING
    if rating_count < 2000:
        return Segment.GROWTH
    if rating_count < 5000:
        return Segment.ESTABLISHED
    return Segment.ENTERPRISE
