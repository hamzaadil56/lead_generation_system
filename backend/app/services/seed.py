"""A deterministic dataset for end-to-end tests and local demos.

Writes fixed rows so Playwright can assert on known values. Idempotent: a
second call is a no-op, so `docker compose up` can run it unconditionally.
Never call this against a database holding real run data.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.segments import segment_for
from app.models.business import Business, BusinessStatus
from app.models.derived import Review, Score, Signals
from app.models.run import Run

RULESET = "hvac_v1"
_SEED_PREFIX = "seed-"

# Real cids are long numeric strings (e.g. "16433610908791049931"). These are
# deliberately not: the "seed-" prefix is what `_already_seeded` matches on,
# and it makes seeded rows obvious in a database you are inspecting by hand.
#
# (cid, name, city, state, fit, pain, quadrant, coverage, phone_valid, reviews)
_LEADS = [
    ("seed-01", "Uptown Air & Heat",      "Houston", "TX", 90, 85, "go_now",  0.90, True,  620),
    ("seed-02", "Mission Comfort Systems", "Houston", "TX", 78, 72, "go_now",  0.80, True,  310),
    ("seed-03", "Revolution Air",          "Dallas",  "TX", 66, 64, "go_now",  0.70, False, 145),
    ("seed-04", "Royal Air Conditioning",  "Houston", "TX", 88, 30, "nurture", 0.85, True,  8758),
    ("seed-05", "Bluebonnet Heating",      "Austin",  "TX", 72, 22, "nurture", 0.75, True,  240),
    ("seed-06", "Lone Star Cooling",       "Dallas",  "TX", 35, 80, "low_fit", 0.65, True,  90),
    ("seed-07", "Hill Country HVAC",       "Austin",  "TX", 28, 74, "low_fit", 0.40, True,  55),
    ("seed-08", "Gulf Coast Climate",      "Houston", "TX", 30, 25, "cold",    0.55, True,  40),
    ("seed-09", "Prairie Air Services",    "Dallas",  "TX", 20, 18, "cold",    0.50, True,  12),
    ("seed-10", "Alamo Air Repair",        "Houston", "TX", 61, 66, "go_now",  0.72, True,  180),
]

_COMPLAINT = "Called three times and nobody ever answered the phone."


def _already_seeded(session: Session) -> bool:
    return session.query(Business).filter(
        Business.cid.like(f"{_SEED_PREFIX}%")).count() > 0


def seed_demo(session: Session) -> dict[str, int]:
    """Insert the fixed dataset. Returns row counts. Safe to call repeatedly."""
    counts = {"businesses": len(_LEADS), "scores": len(_LEADS), "runs": 2}
    if _already_seeded(session):
        return counts

    base = datetime(2026, 9, 1, 9, 0, 0)

    complete = Run(status="complete", source="ui",
                   search_plan={"vertical": "hvac", "state": "tx",
                                "location": None, "pages": 2},
                   stats={"discover": 10, "scrape": 10},
                   max_cost_usd=5.0, estimated_cost=0.012, actual_cost=0.05,
                   created_at=base, started_at=base + timedelta(seconds=5),
                   finished_at=base + timedelta(minutes=4))
    failed = Run(status="failed", source="ui",
                 search_plan={"vertical": "hvac", "location": "Dallas, TX",
                              "state": None, "pages": 5},
                 max_cost_usd=0.01, estimated_cost=0.03, actual_cost=0.012,
                 created_at=base + timedelta(hours=1),
                 started_at=base + timedelta(hours=1, seconds=5),
                 finished_at=base + timedelta(hours=1, minutes=1),
                 error="budget: spent $0.01 of $0.01 ceiling")
    session.add_all([complete, failed])
    session.flush()

    for i, (cid, name, city, state, fit, pain, quad, cov, valid, reviews) in enumerate(_LEADS):
        business = Business(
            cid=cid, name=name, city=city, state=state,
            address=f"{100 + i} Main St, {city}, {state}",
            phone="+17135550100", phone_is_valid=valid,
            website=f"https://{cid}.example.com",
            rating=4.7, review_count=reviews, vertical="hvac",
            # Derived by the real classifier -- verified signature:
            #   segment_for(rating_count: int | None) -> Segment | None
            # Returns None below SEGMENT_FLOOR (50 reviews), so seed-08 (40)
            # and seed-09 (12) land as None on purpose: the leads table has to
            # render a missing segment without breaking.
            segment=segment_for(reviews),
            status=BusinessStatus.SCORED,
            first_seen_run_id=complete.id,
            created_at=base, updated_at=base)
        session.add(business)
        session.flush()

        session.add(Signals(
            business_id=business.id,
            has_booking_link=(i % 2 == 0), booking_vendor=(
                "servicetitan" if i % 3 == 0 else None),
            is_phone_only=(i % 4 == 0), is_24_7=False,
            closes_before_6pm=(pain > 50), closed_weekends=(pain > 60),
            hours_parse_failed=False, segment=None,
            # A None here means UNKNOWN. seed-07 leaves several unset on
            # purpose so the UI's "unknown" rendering has something to show.
            has_chat_widget=(None if cid == "seed-07" else (i % 3 == 0)),
            chat_vendor=None, has_contact_form=True,
            software_from_html=None,
            runs_google_ads=(None if cid == "seed-07" else (i % 2 == 0)),
            missed_call_complaints_90d=(3 if pain > 60 else 0),
            review_velocity_90d=5))

        session.add(Score(
            business_id=business.id, ruleset_version=RULESET,
            fit_score=fit, pain_score=pain, quadrant=quad, coverage=cov,
            reasons=[
                {"rule": "uses_fsm", "track": "fit", "matched": i % 3 == 0,
                 "points": 30, "label": "Uses field service software",
                 "evidence": None},
                {"rule": "closes_early", "track": "pain", "matched": pain > 50,
                 "points": 25, "label": "Closes before 6pm", "evidence": None},
                {"rule": "missed_calls", "track": "pain", "matched": pain > 60,
                 "points": 30, "label": "Reviews mention missed calls",
                 "evidence": [_COMPLAINT] if pain > 60 else None},
            ],
            scored_at=base + timedelta(minutes=3)))

        if pain > 60:
            session.add(Review(
                business_id=business.id, author="A. Customer", rating=1,
                text=_COMPLAINT, published_at=base - timedelta(days=10),
                source="serpapi"))

    session.commit()
    return counts
