"""A deterministic dataset for end-to-end tests and local demos.

Writes fixed rows so Playwright can assert on known values. Idempotent: a
second call is a no-op, so `docker compose up` can run it unconditionally.
Never call this against a database holding real run data.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.segments import segment_for
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, Review, Score, Signals
from app.models.manual import Contact
from app.models.run import Run

RULESET = "hvac_v1"
_SEED_PREFIX = "seed-"
_EXTRACTOR_VERSION = "seed"

# Fixed instant everything else in the seed is offset from. Pinned as a
# module constant (rather than computed inside `_insert`) because
# `_seed_counts` also needs it, to identify the two seed `Run` rows by their
# exact `(status, created_at)` -- `Run` carries no "seed-" marker the way
# `Business.cid` does.
_BASE = datetime(2026, 9, 1, 9, 0, 0)

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

# `(status, created_at)` for the two `Run` rows `_insert` writes. `Run` has
# no "seed-" prefix to filter on the way `Business.cid` does, so identity is
# this exact pair instead -- `created_at` is a fixed value nothing but this
# module ever writes, so a collision with a real run is not a practical
# concern.
_RUN_MARKERS = [
    ("complete", _BASE),
    ("failed", _BASE + timedelta(hours=1)),
]


def _already_seeded(session: Session) -> bool:
    return session.query(Business).filter(
        Business.cid.like(f"{_SEED_PREFIX}%")).count() > 0


def _seed_counts(session: Session) -> dict[str, int]:
    """Live counts of the seed's rows, queried fresh every call.

    Never assumed: `seed_demo` used to return a hardcoded constant on the
    idempotent path, which kept reporting the full dataset even after a
    caller deleted one seeded row out from under it. These queries reflect
    whatever is actually in the database right now.
    """
    businesses = session.query(Business).filter(
        Business.cid.like(f"{_SEED_PREFIX}%")).count()
    scores = (session.query(Score)
              .join(Business, Score.business_id == Business.id)
              .filter(Business.cid.like(f"{_SEED_PREFIX}%"))
              .count())
    runs = sum(
        session.query(Run).filter_by(status=status, created_at=created_at).count()
        for status, created_at in _RUN_MARKERS)
    contacts = (session.query(Contact)
                .join(Business, Contact.business_id == Business.id)
                .filter(Business.cid.like(f"{_SEED_PREFIX}%"))
                .count())
    return {"businesses": businesses, "scores": scores, "runs": runs,
            "contacts": contacts}


def _insert(session: Session) -> None:
    complete = Run(status="complete", source="ui",
                   search_plan={"vertical": "hvac", "state": "tx",
                                "location": None, "pages": 2},
                   stats={"discover": 10, "scrape": 10},
                   max_cost_usd=5.0, estimated_cost=0.012, actual_cost=0.05,
                   created_at=_BASE, started_at=_BASE + timedelta(seconds=5),
                   finished_at=_BASE + timedelta(minutes=4))
    failed = Run(status="failed", source="ui",
                 search_plan={"vertical": "hvac", "location": "Dallas, TX",
                              "state": None, "pages": 5},
                 max_cost_usd=0.01, estimated_cost=0.03, actual_cost=0.012,
                 created_at=_BASE + timedelta(hours=1),
                 started_at=_BASE + timedelta(hours=1, seconds=5),
                 finished_at=_BASE + timedelta(hours=1, minutes=1),
                 error="budget: spent $0.01 of $0.01 ceiling")
    session.add_all([complete, failed])
    session.flush()

    for i, (cid, name, city, state, fit, pain, quad, cov, valid, reviews) in enumerate(_LEADS):
        business = Business(
            cid=cid, name=name, city=city, state=state,
            address=f"{100 + i} Main St, {city}, {state}",
            phone="+17135550100", phone_is_valid=valid,
            # `.test` (RFC 6761), not `.example.com`: `example.com` is on the
            # harvester's vendor-domain denylist, so seeded addresses would be
            # rejected and the harvest end-to-end test would pass against a
            # broken harvester.
            website=f"https://{cid}.test",
            rating=4.7, review_count=reviews, vertical="hvac",
            # Derived by the real classifier -- verified signature:
            #   segment_for(rating_count: int | None) -> Segment | None
            # Returns None below SEGMENT_FLOOR (50 reviews), so seed-08 (40)
            # and seed-09 (12) land as None on purpose: the leads table has to
            # render a missing segment without breaking.
            segment=segment_for(reviews),
            status=BusinessStatus.SCORED,
            first_seen_run_id=complete.id,
            created_at=_BASE, updated_at=_BASE)
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
            review_velocity_90d=5,
            # Both carry ORM-side defaults (`datetime.utcnow` /
            # "unknown") that vary between runs if left unset -- pinned
            # explicitly so a wipe-and-reseed reproduces identical rows,
            # not just identical row *counts*.
            extracted_at=_BASE, extractor_version=_EXTRACTOR_VERSION))

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
            scored_at=_BASE + timedelta(minutes=3)))

        if cid == "seed-01":
            # A RawPayload the harvester can actually find addresses in, so
            # the end-to-end harvest test exercises the real extractor rather
            # than a mock.
            session.add(RawPayload(
                business_id=business.id, source="firecrawl",
                url=f"https://{cid}.test/contact", fetched_at=_BASE,
                payload={},
                raw_text=('<html><body>'
                          f'<a href="mailto:owner@{cid}.test">Email the owner</a>'
                          '<p>noreply@' + cid + '.test</p>'
                          '</body></html>')))

        if cid == "seed-02":
            session.add(Contact(
                business_id=business.id, name="Dana Reyes", role="Owner",
                email="dana@seed-02.test", source="manual", confidence=None,
                is_primary=True, confirmed_at=_BASE, created_at=_BASE))

        if pain > 60:
            session.add(Review(
                business_id=business.id, author="A. Customer", rating=1,
                text=_COMPLAINT, published_at=_BASE - timedelta(days=10),
                source="serpapi"))

    session.commit()


def seed_demo(session: Session) -> dict[str, int]:
    """Insert the fixed dataset once; always return what is actually there.

    Idempotence here is a coarse existence check -- `_already_seeded` asks
    only whether any `seed-`-prefixed `Business` is present, then skips
    the insert entirely. It does NOT verify the seed is intact: if a
    caller (a test, typically) deletes a single seeded row -- one
    business's `Score`, say -- a later call sees the surviving `seed-`
    businesses, skips re-inserting anything, and that gap is not repaired.
    What this function does not do is misreport it: the returned counts
    are a live query of the seed's rows in the database, so a partial
    seed shows up in the return value even though nothing here fixes it.
    The remedy for a partial seed is to delete every `seed-`-prefixed row
    (and the two seed `Run` rows) and call this again.
    """
    if not _already_seeded(session):
        _insert(session)
    return _seed_counts(session)
