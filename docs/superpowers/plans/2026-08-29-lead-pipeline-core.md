# Lead Pipeline Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line pipeline that discovers HVAC businesses from Google Maps, scores them on independent fit and pain tracks, and exports a ranked CSV ready for email outreach.

**Architecture:** A staged pipeline over Postgres. Each business is a row with a `status`; each stage selects rows in one status, does one job, and advances the status. Stages 1–3 do all network I/O and archive raw payloads permanently; stages 4–5 are pure functions over that stored data, so re-scoring after a rule change costs nothing and touches no API. All external providers sit behind `Protocol` adapters so tests never hit the network.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (Data Mapper), Alembic, Pydantic v2, pydantic-settings, httpx, tenacity, structlog, Typer, pytest, Postgres 16, Docker Compose. `firecrawl-py` and `serpapi` for two of the three providers.

**Spec:** `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md`
**Decisions:** `docs/decisions/DECISIONS.md` (ADR-001 … ADR-022)

## Global Constraints

- **Python 3.12.** All code type-annotated; `mypy` clean.
- **`app/domain/` must import nothing framework-related.** No `fastapi`, no `sqlalchemy`, no `httpx`, no `firecrawl`, no `serpapi`. Enforced by `import-linter` in Task 1 and re-verified at every commit. This is ADR-002 and is not negotiable.
- **Alembic owns all DDL.** Never `create_all()` outside tests.
- **No `eval()`, no `exec()`, no expression language** in the rules engine. Fixed operator set only (ADR-005).
- **`on_missing` defaults to `skip`, never `0`.** A skipped rule leaves the denominator so scores stay comparable, and lowers `coverage` (ADR-005).
- **Raw payloads are append-only and never deleted.** `reviews`, `signals`, `scores` are derived and rebuildable (ADR-003).
- **Manual data never lives in a rebuildable table.** `manual_facts` is permanent (ADR-008).
- **`ratingCount` is a segment label only.** It is not a filter and not a scored signal (ADR-022).
- **Every API call logs actual cost** to `api_calls`, using the provider's self-reported `credits` where available (ADR-021).
- **Commit after every task.** Conventional commit messages (`feat:`, `test:`, `chore:`).

---

## File Structure

```
backend/
├── app/
│   ├── core/config.py            Settings; fails at startup on missing env
│   ├── core/db.py                engine, session factory
│   ├── core/errors.py            the four-way failure taxonomy
│   ├── models/                   SQLAlchemy ORM, one module per aggregate
│   ├── domain/                   PURE — no framework imports
│   │   ├── segments.py           ratingCount -> Segment
│   │   ├── phone.py              raw string -> E.164 | None
│   │   ├── hours.py              openingHours dict -> OpeningHours
│   │   ├── booking.py            bookingLinks -> BookingInfo
│   │   ├── rules/operators.py    fixed operator dispatch table
│   │   ├── rules/models.py       Rule, Ruleset, ScoreResult dataclasses
│   │   ├── rules/engine.py       evaluate(signals, ruleset)
│   │   └── extractors/serper.py  Serper record -> SignalSet
│   │   └── extractors/html.py    rawHtml -> SignalSet fragment
│   ├── clients/protocols.py      SearchProvider, WebScraper, ReviewProvider
│   ├── clients/{serper,firecrawl,serpapi_reviews,fakes}.py
│   ├── repositories/             one per aggregate
│   ├── pipeline/base.py          Stage template method + retry + error capture
│   ├── pipeline/{discover,scrape_site,extract_signals,score,fetch_reviews}.py
│   └── services/export.py        ranked CSV
├── config/verticals.yaml, locations.yaml, rulesets/hvac_v1.yaml
├── tests/{unit,integration,fixtures}/
├── alembic/
├── cli.py
└── pyproject.toml
```

---

### Task 1: Project scaffold, settings, and the domain import guard

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/core/config.py`, `backend/app/domain/__init__.py`, `backend/.importlinter`, `backend/tests/unit/test_config.py`, `docker-compose.yml`, `backend/.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: `Settings` with fields `database_url: str`, `serper_key: str`, `firecrawl_key: str`, `serpapi_key: str | None`, `sentry_dsn: str | None`, `enrichment_top_n: int = 25`, `stratified_per_segment: int = 15`. Instantiated as `get_settings() -> Settings`.

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "leadgen"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "sqlalchemy>=2.0", "alembic>=1.13", "psycopg[binary]>=3.1",
  "pydantic>=2.6", "pydantic-settings>=2.2", "httpx>=0.27",
  "tenacity>=8.2", "structlog>=24.1", "typer>=0.12", "pyyaml>=6.0",
  "firecrawl-py>=2.0", "serpapi>=0.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov", "mypy>=1.9", "import-linter>=2.0", "ruff>=0.4"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits real APIs; excluded from CI"]
addopts = "-m 'not live'"
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_config.py
import pytest
from pydantic import ValidationError
from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("SERPER_KEY", "sk-serper")
    monkeypatch.setenv("FIRECRAWL_KEY", "fc-key")
    s = Settings()
    assert s.serper_key == "sk-serper"
    assert s.enrichment_top_n == 25
    assert s.stratified_per_segment == 15
    assert s.serpapi_key is None


def test_settings_fails_fast_when_required_var_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SERPER_KEY", "sk-serper")
    monkeypatch.setenv("FIRECRAWL_KEY", "fc-key")
    with pytest.raises(ValidationError):
        Settings()
```

The second test is the point of this task: a missing variable must fail at
startup, not at 3am in the middle of a paid run.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 4: Write the implementation**

```python
# backend/app/core/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    serper_key: str
    firecrawl_key: str
    serpapi_key: str | None = None
    sentry_dsn: str | None = None

    enrichment_top_n: int = 25
    stratified_per_segment: int = 15
    serpapi_monthly_ceiling: int = 250


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Create the domain import guard**

```ini
# backend/.importlinter
[importlinter]
root_package = app

[importlinter:contract:domain-is-pure]
name = Domain layer imports no frameworks
type = forbidden
source_modules = app.domain
forbidden_modules =
    sqlalchemy
    httpx
    fastapi
    firecrawl
    serpapi
    app.models
    app.clients
    app.repositories
```

- [ ] **Step 7: Verify the guard passes on an empty domain**

Run: `cd backend && lint-imports`
Expected: `Contracts: 1 kept, 0 broken.`

- [ ] **Step 8: Write logging setup**

`structlog.get_logger()` is used from Task 11 onward and needs configuring once.

```python
# backend/app/core/logging.py
import logging
import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 9: Create `docker-compose.yml` and `.env.example`**

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: leadgen
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
volumes: { pgdata: }
```

```bash
# backend/.env.example
DATABASE_URL=postgresql+psycopg://postgres:dev@localhost:5432/leadgen
SERPER_KEY=
FIRECRAWL_KEY=
SERPAPI_KEY=
```

- [ ] **Step 10: Verify Postgres starts**

Run: `docker compose up -d db && docker compose exec db pg_isready -U postgres`
Expected: `accepting connections`

- [ ] **Step 11: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests backend/.importlinter backend/.env.example docker-compose.yml
git commit -m "chore: scaffold backend with fail-fast settings and domain import guard"
```

---

### Task 2: Database models and the first migration

**Files:**
- Create: `backend/app/models/base.py`, `backend/app/models/business.py`, `backend/app/models/run.py`, `backend/app/models/derived.py`, `backend/app/models/manual.py`, `backend/app/core/db.py`, `backend/alembic/`, `backend/tests/integration/test_models.py`

**Interfaces:**
- Consumes: `get_settings()` from Task 1
- Produces: ORM classes `Business`, `Run`, `RunBusiness`, `SearchQuery`, `RawPayload`, `ApiCall`, `Review`, `Signals`, `Score`, `ManualFacts`, `Contact`, `Outcome`, `Suppression`, `Ruleset`. Enum `BusinessStatus` with members `DISCOVERED`, `PLACE_FETCHED`, `SITE_SCRAPED`, `SIGNALS_EXTRACTED`, `SCORED`, `FILTERED_OUT`, `FAILED`. Session factory `get_session()`.
- **`Segment` is NOT defined here.** It lives in `app/domain/segments.py` (Task 3) and is imported. Task 3 must therefore be implemented before this task's migration runs, or `Segment` stubbed and replaced. Controller ruling, pre-flight scan.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_models.py
from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import Score


def test_business_cid_is_unique(session):
    session.add(Business(cid="123", name="A", status=BusinessStatus.DISCOVERED))
    session.commit()
    # ON CONFLICT DO NOTHING is the dedupe mechanism (ADR-013); a plain
    # second insert must raise so the mechanism is provably needed.
    import sqlalchemy.exc, pytest
    session.add(Business(cid="123", name="B", status=BusinessStatus.DISCOVERED))
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        session.commit()


def test_score_is_keyed_on_business_and_ruleset_version(session):
    b = Business(cid="c1", name="A", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=70, pain_score=60, quadrant="go_now", coverage=1.0,
                      reasons=[]))
    session.add(Score(business_id=b.id, ruleset_version="hvac_v2",
                      fit_score=80, pain_score=55, quadrant="nurture", coverage=1.0,
                      reasons=[]))
    session.commit()
    assert session.query(Score).count() == 2  # both versions coexist (ADR-005)
```

- [ ] **Step 2: Add the session fixture**

```python
# backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.base import Base

TEST_URL = "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    conn = engine.connect()
    txn = conn.begin()
    s = sessionmaker(bind=conn)()
    yield s
    s.close()
    txn.rollback()      # every test rolls back; no cross-test leakage
    conn.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.business'`

- [ ] **Step 4: Write the models**

```python
# backend/app/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
# backend/app/models/business.py
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Enum, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


# Segment is defined ONCE, in app/domain/segments.py (Task 3), and imported
# here. The domain may not import models, so the dependency runs this way
# only. Do not re-declare it in this module.
from app.domain.segments import Segment


class BusinessStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    PLACE_FETCHED = "place_fetched"
    SITE_SCRAPED = "site_scraped"
    SIGNALS_EXTRACTED = "signals_extracted"
    SCORED = "scored"
    FILTERED_OUT = "filtered_out"
    FAILED = "failed"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    cid: Mapped[str] = mapped_column(String, unique=True, index=True)
    place_id: Mapped[str | None] = mapped_column(String)
    fid: Mapped[str | None] = mapped_column(String)

    name: Mapped[str] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)   # absent for service-area businesses
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    phone: Mapped[str | None] = mapped_column(String)
    phone_is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    website: Mapped[str | None] = mapped_column(String)

    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    segment: Mapped[Segment | None] = mapped_column(Enum(Segment))

    primary_category: Mapped[str | None] = mapped_column(String)
    types: Mapped[list | None] = mapped_column(JSON)
    opening_hours: Mapped[dict | None] = mapped_column(JSON)
    booking_links: Mapped[list | None] = mapped_column(JSON)

    vertical: Mapped[str | None] = mapped_column(String)
    status: Mapped[BusinessStatus] = mapped_column(Enum(BusinessStatus), index=True)
    failed_stage: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(String)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    first_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)
```

Write the remaining three modules. Columns, in full:

```python
# backend/app/models/run.py
class Run(Base):
    __tablename__ = "runs"
    id: int PK
    status: str            # queued|running|complete|failed
    source: str            # ui|cli
    search_plan: JSON
    stats: JSON
    max_cost_usd: float | None
    estimated_cost: float | None
    actual_cost: float | None
    created_at, started_at, finished_at: datetime | None
    error: str | None


class RunBusiness(Base):
    __tablename__ = "run_businesses"
    run_id: int FK(runs.id)
    business_id: int FK(businesses.id)
    is_new: bool
    __table_args__ = (PrimaryKeyConstraint("run_id", "business_id"),)


class SearchQuery(Base):
    __tablename__ = "search_queries"
    id: int PK
    run_id: int | None FK(runs.id)
    term: str
    location: str | None
    executed_at: datetime
    result_count: int
```

```python
# backend/app/models/derived.py
class RawPayload(Base):            # PERMANENT, append-only (ADR-003)
    __tablename__ = "raw_payloads"
    id: int PK
    business_id: int FK
    source: str                     # serper_maps | firecrawl | serpapi_reviews
    url: str | None
    fetched_at: datetime
    payload: JSON
    raw_text: str | None


class ApiCall(Base):               # PERMANENT — cost accounting + budget guard
    __tablename__ = "api_calls"
    id: int PK
    run_id: int | None FK
    business_id: int | None FK
    provider: str                   # serper | firecrawl | serpapi
    endpoint: str
    credits: int
    cost_usd: float | None
    status_code: int | None
    duration_ms: int | None
    created_at: datetime            # indexed — the monthly ceiling queries it


class Review(Base):                # REBUILDABLE
    __tablename__ = "reviews"
    id: int PK
    business_id: int FK
    author: str | None
    rating: int | None
    text: str | None
    published_at: datetime | None
    published_at_is_approximate: bool = False
    source: str


class Signals(Base):               # REBUILDABLE — all columns nullable
    __tablename__ = "signals"
    business_id: int PK FK
    # from Serper /maps (free)
    has_booking_link: bool | None
    booking_vendor: str | None
    is_phone_only: bool | None
    is_24_7: bool | None
    closes_before_6pm: bool | None
    closed_weekends: bool | None
    hours_parse_failed: bool | None
    segment: str | None
    # from Firecrawl (scraped subset only)
    has_chat_widget: bool | None
    chat_vendor: str | None
    has_contact_form: bool | None
    software_from_html: str | None  # secondary vendor source, ADR-023
    runs_google_ads: bool | None
    has_meta_pixel: bool | None
    claims_24_7: bool | None
    website_status: str | None      # ok | none | dead | parked
    team_page_headcount: int | None
    # from SerpApi enrichment (top N only; absent = dormant rules skip)
    review_velocity_90d: float | None
    missed_call_complaints_90d: int | None
    complaint_quotes: JSON | None
    # from manual_facts overlay
    estimated_employees: int | None
    employee_est_source: str | None
    has_office_admin: bool | None
    owner_growth_focused: bool | None
    extracted_at: datetime
    extractor_version: str


class Score(Base):                 # REBUILDABLE
    __tablename__ = "scores"
    id: int PK
    business_id: int FK
    ruleset_version: str
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    reasons: JSON
    scored_at: datetime
    __table_args__ = (UniqueConstraint("business_id", "ruleset_version"),)
```

```python
# backend/app/models/manual.py
class ManualFacts(Base):           # PERMANENT — never wiped by a rebuild (ADR-008)
    __tablename__ = "manual_facts"
    business_id: int PK FK
    estimated_employees: int | None
    technician_count: int | None
    has_office_admin: bool | None
    owner_growth_focused: bool | None
    notes: str | None
    updated_at: datetime


class Contact(Base):               # PERMANENT — manual in v1, resolvers in v2
    __tablename__ = "contacts"
    id: int PK
    business_id: int FK
    name, role, email, phone, linkedin_url: str | None
    source: str                     # manual | license_registry | website | ...
    confidence: float | None
    verification_status: str | None  # unverified|valid|risky|invalid|catch_all
    is_primary: bool = False
    created_at, verified_at: datetime | None


class Outcome(Base):               # PERMANENT — the ground truth (ADR-006)
    __tablename__ = "outcomes"
    id: int PK
    business_id: int FK
    status: str                     # new|contacted|replied|booked|won|lost
    source: str = "manual"          # manual | email_event
    notes: str | None
    contacted_at, updated_at: datetime | None


class Suppression(Base):           # PERMANENT — required before the first email
    __tablename__ = "suppressions"
    email: str PK
    reason: str                     # unsubscribed|bounced|complained|manual
    source: str | None
    created_at: datetime


class Ruleset(Base):
    __tablename__ = "rulesets"
    version: str PK
    name, vertical: str
    definition: JSON
    is_active: bool
    created_at: datetime
```

Write these as real `mapped_column` declarations following the `Business`
pattern above. The two constraints shown (`UniqueConstraint` on `Score`,
composite PK on `RunBusiness`) carry design decisions and must not be
dropped.

- [ ] **Step 5: Write the session factory**

```python
# backend/app/core/db.py
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

_engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=_engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_models.py -v`
Expected: 2 passed

- [ ] **Step 7: Generate and apply the migration**

```bash
cd backend
alembic init alembic
# set sqlalchemy.url from settings in alembic/env.py, target_metadata = Base.metadata
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 8: Verify the migration round-trips**

Run: `cd backend && alembic downgrade base && alembic upgrade head`
Expected: both complete without error

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/app/core/db.py backend/alembic backend/tests
git commit -m "feat: add database models and initial migration"
```

---

### Task 3: Domain — segment classification and phone validation

**Files:**
- Create: `backend/app/domain/segments.py`, `backend/app/domain/phone.py`, `backend/tests/unit/test_segments.py`, `backend/tests/unit/test_phone.py`

**Interfaces:**
- Consumes: nothing. **`Segment` is DEFINED here**, in `app/domain/segments.py`,
  as a plain `StrEnum`. `app/models/business.py` (Task 2) imports it from here —
  never the reverse, because the domain may not import models.
- Produces: `segment_for(rating_count: int | None) -> Segment | None`,
  `validate_phone(raw: str | None) -> str | None` (E.164 or `None`)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_segments.py
import pytest
from app.domain.segments import Segment, segment_for


@pytest.mark.parametrize("count,expected", [
    (43, None),                      # below the floor — not a segment at all
    (72, Segment.EMERGING),
    (199, Segment.EMERGING),
    (200, Segment.GROWTH),
    (1999, Segment.GROWTH),
    (2000, Segment.ESTABLISHED),
    (4999, Segment.ESTABLISHED),
    (5000, Segment.ENTERPRISE),
    (10712, Segment.ENTERPRISE),     # real: One Hour Air Conditioning
    (None, None),
])
def test_segment_boundaries(count, expected):
    assert segment_for(count) == expected
```

```python
# backend/tests/unit/test_phone.py
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
```

The two address cases are the reason this function exists. An invalid phone
must never reach a dialler or a CSV column labelled "phone".

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_segments.py tests/unit/test_phone.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementations**

```python
# backend/app/domain/segments.py
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
```

```python
# backend/app/domain/phone.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_segments.py tests/unit/test_phone.py -v`
Expected: 19 passed

- [ ] **Step 5: Verify the domain is still pure**

Run: `cd backend && lint-imports`
Expected: `Contracts: 1 kept, 0 broken.`

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain backend/tests/unit
git commit -m "feat: add segment classification and phone validation"
```

---

### Task 4: Domain — opening hours parsing

**Files:**
- Create: `backend/app/domain/hours.py`, `backend/tests/unit/test_hours.py`

**Interfaces:**
- Consumes: nothing
- Produces: frozen dataclass `OpeningHours(is_24_7: bool, closes_before_6pm: bool, closed_weekends: bool, parse_failed: bool)` and `parse_opening_hours(raw: dict[str, str] | None) -> OpeningHours`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_hours.py
from app.domain.hours import parse_opening_hours

ALL_DAY = {d: "Open 24 hours" for d in
           ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]}


def test_open_24_hours_every_day():
    h = parse_opening_hours(ALL_DAY)            # real: Air Tech of Houston
    assert h.is_24_7 is True
    assert h.closes_before_6pm is False
    assert h.closed_weekends is False


def test_weekday_business_hours_closed_weekends():
    # real: Royal Air Houston, 8,758 reviews — the lead ADR-022 was written about
    h = parse_opening_hours({
        "Monday": "8 AM–5 PM", "Tuesday": "8 AM–5 PM", "Wednesday": "8 AM–5 PM",
        "Thursday": "8 AM–5 PM", "Friday": "8 AM–5 PM",
        "Saturday": "Closed", "Sunday": "Closed",
    })
    assert h.is_24_7 is False
    assert h.closes_before_6pm is True
    assert h.closed_weekends is True


def test_saturday_open_is_not_closed_weekends():
    # real: All American AC — Sat 8-12, Sun closed
    h = parse_opening_hours({
        **{d: "8 AM–6 PM" for d in ["Monday", "Tuesday", "Wednesday",
                                     "Thursday", "Friday"]},
        "Saturday": "8 AM–12 PM", "Sunday": "Closed",
    })
    assert h.closed_weekends is False
    assert h.closes_before_6pm is False          # 6 PM is not *before* 6 PM


def test_malformed_day_sets_parse_failed_and_is_not_guessed():
    # real defect: Ethan Clark returned "8 AM–5 AM" for Thursday (ADR-021)
    h = parse_opening_hours({
        "Monday": "8 AM–5 PM", "Tuesday": "8 AM–5 PM", "Wednesday": "8 AM–5 PM",
        "Thursday": "8 AM–5 AM", "Friday": "8 AM–5 PM",
        "Saturday": "8 AM–12 PM", "Sunday": "Closed",
    })
    assert h.parse_failed is True
    assert h.closes_before_6pm is True           # the four valid days still count


def test_missing_hours_returns_all_unknown():
    h = parse_opening_hours(None)
    assert h.parse_failed is True
    assert h.is_24_7 is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_hours.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.hours'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/domain/hours.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_hours.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/hours.py backend/tests/unit/test_hours.py
git commit -m "feat: parse Google opening hours with malformed-day guard"
```

---

### Task 5: Domain — booking link classification

**Files:**
- Create: `backend/app/domain/booking.py`, `backend/tests/unit/test_booking.py`

**Interfaces:**
- Consumes: nothing
- Produces: `BookingVendor` StrEnum (`SERVICETITAN`, `JOBBER`, `HOUSECALLPRO`, `OWN`, `NONE`), frozen dataclass `BookingInfo(vendor: BookingVendor, has_booking: bool, is_phone_only: bool)`, and `classify_booking_links(links: list[str] | None) -> BookingInfo`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_booking.py
from app.domain.booking import BookingVendor, classify_booking_links


def test_servicetitan_detected_from_real_url():
    info = classify_booking_links([
        "https://book.servicetitan.com/r403q9wgygvty8ghzvbhag5i?rwg_token=AE37R_ga"
    ])
    assert info.vendor is BookingVendor.SERVICETITAN
    assert info.has_booking is True
    assert info.is_phone_only is False


def test_housecallpro_detected_from_real_url():
    info = classify_booking_links([
        "https://allstarairtexas.com/contact/",
        "https://book.housecallpro.com/book/All-Star-AC/25086315e0864b46?v2=true",
    ])
    assert info.vendor is BookingVendor.HOUSECALLPRO   # vendor beats own-site


def test_own_site_booking_only():
    info = classify_booking_links(["https://www.houseproac.com/request-service/"])
    assert info.vendor is BookingVendor.OWN
    assert info.has_booking is True
    assert info.is_phone_only is False


def test_absent_key_means_phone_only():
    # 6 of 20 Houston records omitted bookingLinks entirely (ADR-021).
    # Absence IS the signal, worth 25 pain points.
    info = classify_booking_links(None)
    assert info.vendor is BookingVendor.NONE
    assert info.has_booking is False
    assert info.is_phone_only is True


def test_empty_list_is_treated_the_same_as_absent():
    assert classify_booking_links([]).is_phone_only is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_booking.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/domain/booking.py
import enum
from dataclasses import dataclass


class BookingVendor(enum.StrEnum):
    SERVICETITAN = "servicetitan"
    JOBBER = "jobber"
    HOUSECALLPRO = "housecallpro"
    OWN = "own"
    NONE = "none"


# Ordered: a recognised vendor always beats a generic own-site link.
_FINGERPRINTS: list[tuple[str, BookingVendor]] = [
    ("book.servicetitan.com", BookingVendor.SERVICETITAN),
    ("servicetitan.com", BookingVendor.SERVICETITAN),
    ("book.housecallpro.com", BookingVendor.HOUSECALLPRO),
    ("housecallpro.com", BookingVendor.HOUSECALLPRO),
    ("clienthub.getjobber.com", BookingVendor.JOBBER),
    ("getjobber.com", BookingVendor.JOBBER),
]


@dataclass(frozen=True)
class BookingInfo:
    vendor: BookingVendor
    has_booking: bool
    is_phone_only: bool


def classify_booking_links(links: list[str] | None) -> BookingInfo:
    if not links:
        return BookingInfo(BookingVendor.NONE, has_booking=False, is_phone_only=True)
    joined = " ".join(links).lower()
    for needle, vendor in _FINGERPRINTS:
        if needle in joined:
            return BookingInfo(vendor, has_booking=True, is_phone_only=False)
    return BookingInfo(BookingVendor.OWN, has_booking=True, is_phone_only=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_booking.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/booking.py backend/tests/unit/test_booking.py
git commit -m "feat: classify booking links into field-service vendors"
```

---

### Task 6: Domain — the rules engine

**Files:**
- Create: `backend/app/domain/rules/operators.py`, `backend/app/domain/rules/models.py`, `backend/app/domain/rules/engine.py`, `backend/tests/unit/test_rules_engine.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `OPERATORS: dict[str, Callable[[Any, Any], bool]]` with keys `gte, lte, gt, lt, eq, neq, in, not_in, is_true, is_false, is_null, not_null`
  - `Rule(id: str, track: Literal["fit","pain"], when: dict, points: int, label: str, on_missing: Literal["skip","zero"] = "skip", evidence: str | None = None)`
  - `Ruleset(version: str, vertical: str, threshold: int, fit_rules: list[Rule], pain_rules: list[Rule])`
  - `RuleReason(rule: str, track: str, matched: bool, points: int, label: str, evidence: list[str] | None)`
  - `ScoreResult(fit_score: int, pain_score: int, quadrant: str, coverage: float, reasons: list[RuleReason])`
  - `evaluate(signals: dict[str, Any], ruleset: Ruleset) -> ScoreResult`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_rules_engine.py
import pytest
from app.domain.rules.models import Rule, Ruleset
from app.domain.rules.engine import evaluate

RS = Ruleset(
    version="test_v1", vertical="hvac", threshold=60,
    fit_rules=[
        Rule(id="software", track="fit",
             when={"signal": "booking_vendor", "op": "in",
                   "value": ["servicetitan", "housecallpro"]},
             points=60, label="Uses {booking_vendor}"),
        Rule(id="employees", track="fit",
             when={"signal": "estimated_employees", "op": "gte", "value": 10},
             points=40, label="10+ employees", on_missing="skip"),
    ],
    pain_rules=[
        Rule(id="closed_weekends", track="pain",
             when={"signal": "closed_weekends", "op": "is_true"},
             points=70, label="Closed weekends"),
        Rule(id="complaints", track="pain",
             when={"signal": "missed_call_complaints_90d", "op": "gte", "value": 3},
             points=30, label="{missed_call_complaints_90d} complaints",
             on_missing="skip", evidence="complaint_quotes"),
    ],
)


def test_all_rules_present_and_matching():
    r = evaluate({"booking_vendor": "servicetitan", "estimated_employees": 20,
                  "closed_weekends": True, "missed_call_complaints_90d": 4,
                  "complaint_quotes": ["nobody answered"]}, RS)
    assert r.fit_score == 100 and r.pain_score == 100
    assert r.coverage == 1.0
    assert r.quadrant == "go_now"


def test_missing_signal_is_skipped_not_zeroed():
    """The core of ADR-005. A basic-tier lead has no review data; skipping
    keeps its pain score comparable instead of unfairly crushing it."""
    r = evaluate({"booking_vendor": "servicetitan", "closed_weekends": True}, RS)
    assert r.fit_score == 100        # 60 of 60 applicable — employees skipped
    assert r.pain_score == 100       # 70 of 70 applicable — complaints skipped
    assert r.coverage == 0.5         # 2 of 4 rules applicable


def test_on_missing_zero_counts_against_the_denominator():
    rs = Ruleset(version="z", vertical="hvac", threshold=60, fit_rules=[
        Rule(id="a", track="fit", when={"signal": "x", "op": "is_true"},
             points=50, label="a"),
        Rule(id="b", track="fit", when={"signal": "y", "op": "is_true"},
             points=50, label="b", on_missing="zero"),
    ], pain_rules=[])
    r = evaluate({"x": True}, rs)
    assert r.fit_score == 50         # y is absent but still in the denominator


def test_quadrants():
    assert evaluate({"booking_vendor": "servicetitan",
                     "closed_weekends": False}, RS).quadrant == "nurture"
    assert evaluate({"booking_vendor": "own",
                     "closed_weekends": True}, RS).quadrant == "low_fit"
    assert evaluate({"booking_vendor": "own",
                     "closed_weekends": False}, RS).quadrant == "cold"


def test_all_rules_skipped_yields_zero_coverage_not_a_crash():
    r = evaluate({}, RS)
    assert r.coverage == 0.0
    assert r.fit_score == 0 and r.pain_score == 0


def test_label_is_interpolated_and_evidence_attached():
    r = evaluate({"booking_vendor": "servicetitan", "closed_weekends": True,
                  "missed_call_complaints_90d": 4,
                  "complaint_quotes": ["called 3 times, no answer"]}, RS)
    by_id = {x.rule: x for x in r.reasons}
    assert by_id["software"].label == "Uses servicetitan"
    assert by_id["complaints"].evidence == ["called 3 times, no answer"]


def test_all_group_requires_every_condition():
    rs = Ruleset(version="g", vertical="hvac", threshold=60, fit_rules=[
        Rule(id="combo", track="fit",
             when={"all": [{"signal": "a", "op": "is_true"},
                           {"signal": "b", "op": "is_true"}]},
             points=100, label="both"),
    ], pain_rules=[])
    assert evaluate({"a": True, "b": True}, rs).fit_score == 100
    assert evaluate({"a": True, "b": False}, rs).fit_score == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_rules_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.rules'`

- [ ] **Step 3: Write the operators**

```python
# backend/app/domain/rules/operators.py
from typing import Any, Callable

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "gte":      lambda a, b: a >= b,
    "lte":      lambda a, b: a <= b,
    "gt":       lambda a, b: a > b,
    "lt":       lambda a, b: a < b,
    "eq":       lambda a, b: a == b,
    "neq":      lambda a, b: a != b,
    "in":       lambda a, b: a in b,
    "not_in":   lambda a, b: a not in b,
    "is_true":  lambda a, _: a is True,
    "is_false": lambda a, _: a is False,
    "is_null":  lambda a, _: a is None,
    "not_null": lambda a, _: a is not None,
}

# Deliberately a fixed table, not an expression language (ADR-005).
# If a rule cannot be expressed here, add a SIGNAL, not an operator.
```

- [ ] **Step 4: Write the models**

```python
# backend/app/domain/rules/models.py
from dataclasses import dataclass, field
from typing import Any, Literal

Track = Literal["fit", "pain"]
OnMissing = Literal["skip", "zero"]


@dataclass(frozen=True)
class Rule:
    id: str
    track: Track
    when: dict[str, Any]
    points: int
    label: str
    on_missing: OnMissing = "skip"
    evidence: str | None = None


@dataclass(frozen=True)
class Ruleset:
    version: str
    vertical: str
    threshold: int
    fit_rules: list[Rule] = field(default_factory=list)
    pain_rules: list[Rule] = field(default_factory=list)


@dataclass(frozen=True)
class RuleReason:
    rule: str
    track: str
    matched: bool
    points: int
    label: str
    evidence: list[str] | None = None


@dataclass(frozen=True)
class ScoreResult:
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    reasons: list[RuleReason]
```

- [ ] **Step 5: Write the engine**

```python
# backend/app/domain/rules/engine.py
from typing import Any
from app.domain.rules.models import Rule, Ruleset, RuleReason, ScoreResult
from app.domain.rules.operators import OPERATORS

_MISSING = object()


def _signals_used(when: dict[str, Any]) -> list[str]:
    if "all" in when or "any" in when:
        out: list[str] = []
        for cond in when.get("all") or when.get("any") or []:
            out.extend(_signals_used(cond))
        return out
    return [when["signal"]]


def _applicable(rule: Rule, signals: dict[str, Any]) -> bool:
    """A skip-rule is applicable only when every signal it reads is present."""
    if rule.on_missing == "zero":
        return True
    return all(signals.get(name, _MISSING) is not _MISSING
               for name in _signals_used(rule.when))


def _matches(when: dict[str, Any], signals: dict[str, Any]) -> bool:
    if "all" in when:
        return all(_matches(c, signals) for c in when["all"])
    if "any" in when:
        return any(_matches(c, signals) for c in when["any"])
    value = signals.get(when["signal"])
    return OPERATORS[when["op"]](value, when.get("value"))


def _score_track(rules: list[Rule], signals: dict[str, Any]
                 ) -> tuple[int, list[RuleReason], int, int]:
    earned = possible = 0
    reasons: list[RuleReason] = []
    applicable_count = 0
    for rule in rules:
        if not _applicable(rule, signals):
            continue
        applicable_count += 1
        possible += rule.points
        matched = _matches(rule.when, signals)
        if matched:
            earned += rule.points
        reasons.append(RuleReason(
            rule=rule.id, track=rule.track, matched=matched,
            points=rule.points if matched else 0,
            label=rule.label.format(**signals) if matched else rule.label,
            evidence=signals.get(rule.evidence) if (matched and rule.evidence) else None,
        ))
    score = round(earned / possible * 100) if possible else 0
    return score, reasons, applicable_count, len(rules)


def evaluate(signals: dict[str, Any], ruleset: Ruleset) -> ScoreResult:
    fit, fit_reasons, fit_app, fit_total = _score_track(ruleset.fit_rules, signals)
    pain, pain_reasons, pain_app, pain_total = _score_track(ruleset.pain_rules, signals)

    total = fit_total + pain_total
    coverage = (fit_app + pain_app) / total if total else 0.0

    t = ruleset.threshold
    if fit >= t and pain >= t:
        quadrant = "go_now"
    elif fit >= t:
        quadrant = "nurture"
    elif pain >= t:
        quadrant = "low_fit"
    else:
        quadrant = "cold"

    return ScoreResult(fit, pain, quadrant, round(coverage, 3),
                       fit_reasons + pain_reasons)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_rules_engine.py -v`
Expected: 7 passed

- [ ] **Step 7: Verify domain purity**

Run: `cd backend && lint-imports && mypy app/domain`
Expected: contracts kept, no type errors

- [ ] **Step 8: Commit**

```bash
git add backend/app/domain/rules backend/tests/unit/test_rules_engine.py
git commit -m "feat: add rules engine with skip-based coverage normalisation"
```

---

### Task 7: The `hvac_v1` ruleset, its loader, and golden tests

**Files:**
- Create: `backend/config/rulesets/hvac_v1.yaml`, `backend/config/verticals.yaml`, `backend/config/locations.yaml`, `backend/app/domain/rules/loader.py`, `backend/tests/unit/test_hvac_v1_golden.py`

**Interfaces:**
- Consumes: `Ruleset`, `Rule` (Task 6)
- Produces: `load_ruleset(raw: dict) -> Ruleset` (pure — takes parsed YAML, does no file I/O, keeping the domain clean). **`read_ruleset_file` is NOT produced here** — Task 14 creates it in `app/services/rulesets.py`, and Tasks 14 and 17 import it from there. Do not create it in this task.

- [ ] **Step 1: Write the ruleset**

```yaml
# backend/config/rulesets/hvac_v1.yaml
version: hvac_v1
vertical: hvac
threshold: 60

# NOTE: ratingCount and rating are deliberately absent from scoring.
# ratingCount is a segment label only (ADR-022); rating rated 4.6-5.0 across
# all 20 sampled Houston businesses and discriminated nothing (ADR-021).

fit_rules:
  - id: field_service_software
    track: fit
    when: {signal: booking_vendor, op: in, value: [servicetitan, jobber, housecallpro]}
    points: 30
    label: "Uses {booking_vendor}"

  - id: runs_google_ads
    track: fit
    when: {signal: runs_google_ads, op: is_true}
    points: 25
    label: "Running Google Ads"

  - id: employee_band
    track: fit
    when:
      all:
        - {signal: estimated_employees, op: gte, value: 10}
        - {signal: estimated_employees, op: lte, value: 40}
    points: 25
    label: "{estimated_employees} employees"
    on_missing: skip

  - id: has_online_booking
    track: fit
    when: {signal: has_booking_link, op: is_true}
    points: 20
    label: "Has online booking"

pain_rules:
  - id: closed_weekends
    track: pain
    when: {signal: closed_weekends, op: is_true}
    points: 30
    label: "Closed Saturday and Sunday in an emergency trade"

  - id: closes_before_6pm
    track: pain
    when: {signal: closes_before_6pm, op: is_true}
    points: 25
    label: "Closes before 6pm on weekdays"

  - id: phone_only_intake
    track: pain
    when: {signal: is_phone_only, op: is_true}
    points: 25
    label: "No online booking — every lead arrives as a phone call"

  - id: no_chat_widget
    track: pain
    when: {signal: has_chat_widget, op: is_false}
    points: 20
    label: "No chat widget"

  # Dormant until the SerpApi enrichment pass runs (ADR-020).
  - id: missed_call_complaints
    track: pain
    when: {signal: missed_call_complaints_90d, op: gte, value: 3}
    points: 30
    label: "{missed_call_complaints_90d} recent reviews mention unanswered calls"
    evidence: complaint_quotes
    on_missing: skip

  - id: review_velocity
    track: pain
    when: {signal: review_velocity_90d, op: gte, value: 5}
    points: 15
    label: "{review_velocity_90d} reviews/month — high call volume"
    on_missing: skip
```

```yaml
# backend/config/verticals.yaml
hvac:
  search_terms:
    - "hvac contractor"
    - "air conditioning repair"
    - "heating and cooling company"
    - "furnace repair"
  ruleset: hvac_v1
```

```yaml
# backend/config/locations.yaml
# Serper resolves natural-language locations and echoes back `ll`,
# so display names are sufficient — no centroids or zoom levels (ADR-021).
tx:
  metros: ["Houston, TX", "Dallas, TX", "San Antonio, TX",
           "Austin, TX", "Fort Worth, TX", "El Paso, TX"]
```

- [ ] **Step 2: Write the failing golden test**

```python
# backend/tests/unit/test_hvac_v1_golden.py
import yaml
from pathlib import Path
import pytest
from app.domain.rules.loader import load_ruleset
from app.domain.rules.engine import evaluate

RULESET = load_ruleset(
    yaml.safe_load(Path("config/rulesets/hvac_v1.yaml").read_text())
)

# Real Houston businesses. Golden expectations — when a weight changes,
# this diff shows exactly which leads moved.
ROYAL_AIR = {            # 8,758 reviews, 8-5 M-F, closed weekends, own booking
    "booking_vendor": "own", "has_booking_link": True, "is_phone_only": False,
    "closed_weekends": True, "closes_before_6pm": True,
    "has_chat_widget": False, "runs_google_ads": True,
}
AIR_TECH = {             # 6,445 reviews, 24/7 every day, ServiceTitan
    "booking_vendor": "servicetitan", "has_booking_link": True,
    "is_phone_only": False, "closed_weekends": False, "closes_before_6pm": False,
    "has_chat_widget": True, "runs_google_ads": True,
}
HEIGHTS_AC = {           # 72 reviews, 8-5 M-F, closed weekends, NO booking link
    "booking_vendor": "none", "has_booking_link": False, "is_phone_only": True,
    "closed_weekends": True, "closes_before_6pm": True,
    "has_chat_widget": False, "runs_google_ads": False,
}


def test_royal_air_is_high_pain_despite_being_enterprise_sized():
    """ADR-022's motivating case: big AND provably uncovered."""
    r = evaluate(ROYAL_AIR, RULESET)
    # fit:  ads 25 + booking 20 = 45 earned of 75 applicable
    #       (software rule applicable but unmatched; employees skipped) -> 60
    assert r.fit_score == 60
    # pain: weekends 30 + closes_early 25 + no_chat 20 = 75 of 100 applicable
    #       (phone_only unmatched; both review rules skipped) -> 75
    assert r.pain_score == 75
    assert r.coverage == 0.7          # 7 of 10 rules applicable
    assert r.quadrant == "go_now"


def test_air_tech_is_good_fit_but_low_pain():
    r = evaluate(AIR_TECH, RULESET)
    assert r.fit_score == 100         # software 30 + ads 25 + booking 20 of 75
    assert r.pain_score == 0          # 24/7, has booking, has chat
    assert r.quadrant == "nurture"


def test_heights_ac_is_all_pain_and_little_fit():
    r = evaluate(HEIGHTS_AC, RULESET)
    assert r.pain_score == 100        # all four always-on pain rules matched
    assert r.fit_score == 0           # no software, no ads, no booking
    assert r.quadrant == "low_fit"


def test_dormant_review_rules_are_skipped_at_basic_tier():
    r = evaluate(ROYAL_AIR, RULESET)
    ids = {x.rule for x in r.reasons}
    assert "missed_call_complaints" not in ids
    assert "review_velocity" not in ids
    assert r.coverage < 1.0


def test_enriched_tier_activates_the_review_rules():
    enriched = {**ROYAL_AIR, "missed_call_complaints_90d": 4,
                "review_velocity_90d": 9,
                "complaint_quotes": ["Called 3 times, nobody answered"]}
    r = evaluate(enriched, RULESET)
    ids = {x.rule for x in r.reasons}
    assert "missed_call_complaints" in ids
    assert r.coverage > evaluate(ROYAL_AIR, RULESET).coverage
```

The asserted numbers are computed from the ruleset by hand, not guessed. If
one fails, **the engine or the ruleset is wrong — do not edit the assertion
to make it pass.** These golden values are the regression net for every
future weight change.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_hvac_v1_golden.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.rules.loader'`

- [ ] **Step 4: Write the loader**

```python
# backend/app/domain/rules/loader.py
from typing import Any
from app.domain.rules.models import Rule, Ruleset


def load_ruleset(raw: dict[str, Any]) -> Ruleset:
    """Pure: takes already-parsed YAML. File I/O belongs in app/services."""
    def rules(key: str, track: str) -> list[Rule]:
        return [
            Rule(
                id=r["id"], track=track, when=r["when"], points=r["points"],
                label=r["label"], on_missing=r.get("on_missing", "skip"),
                evidence=r.get("evidence"),
            )
            for r in raw.get(key, [])
        ]

    return Ruleset(
        version=raw["version"], vertical=raw["vertical"],
        threshold=raw.get("threshold", 60),
        fit_rules=rules("fit_rules", "fit"),
        pain_rules=rules("pain_rules", "pain"),
    )
```

- [ ] **Step 5: Run, read the real numbers, correct the assertions, re-run**

Run: `cd backend && pytest tests/unit/test_hvac_v1_golden.py -v`
Expected: 5 passed once the golden numbers reflect actual output

- [ ] **Step 6: Commit**

```bash
git add backend/config backend/app/domain/rules/loader.py backend/tests/unit/test_hvac_v1_golden.py
git commit -m "feat: add hvac_v1 ruleset with golden tests from real Houston data"
```

---

### Task 8: Client protocols, fakes, and the Serper client

**Files:**
- Create: `backend/app/clients/protocols.py`, `backend/app/clients/serper.py`, `backend/app/clients/fakes.py`, `backend/tests/fixtures/serper_maps_houston_hvac.json`, `backend/tests/unit/test_serper_client.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 1)
- Produces:
  - `PlaceRecord` Pydantic model: `cid: str`, `place_id: str | None`, `fid: str | None`, `title: str`, `address: str | None`, `latitude: float | None`, `longitude: float | None`, `rating: float | None`, `rating_count: int | None`, `phone_number: str | None`, `website: str | None`, `type: str | None`, `types: list[str]`, `opening_hours: dict[str, str] | None`, `booking_links: list[str] | None`, `raw: dict`
  - `SearchResult` model: `records: list[PlaceRecord]`, `credits: int`, `raw: dict`
  - `SearchProvider` Protocol with `search(query: str, page: int = 1) -> SearchResult`
  - `SerperClient(SearchProvider)` and `FakeSearchProvider(SearchProvider)`

- [ ] **Step 1: Verify the fixture (already committed)**

`backend/tests/fixtures/serper_maps_houston_hvac.json` is committed — the real
20-record Serper `/maps` response for "hvac businesses in Houston", unmodified.
Confirm it before writing tests against it:

```bash
cd backend && python3 -c "
import json; d=json.load(open('tests/fixtures/serper_maps_houston_hvac.json'))
p=d['places']
assert len(p)==20 and d['credits']==3
assert len([x for x in p if 'address' not in x])==2      # service-area businesses
assert len([x for x in p if 'bookingLinks' not in x])==6  # phone-only signal
print('fixture ok')"
```
Expected: `fixture ok`

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_serper_client.py
import json
from pathlib import Path
from app.clients.serper import parse_search_response

RAW = json.loads(
    Path("tests/fixtures/serper_maps_houston_hvac.json").read_text()
)


def test_parses_all_records_and_reports_credits():
    result = parse_search_response(RAW)
    assert len(result.records) == 20
    assert result.credits == 3          # self-reported actual cost (ADR-021)


def test_maps_every_field_from_a_real_record():
    r = parse_search_response(RAW).records[0]
    assert r.title == "Air Tech of Houston AC & Plumbing"
    assert r.cid == "16433610908791049931"
    assert r.place_id == "ChIJnepQB1XGQIYRy455cw3qD-Q"
    assert r.rating_count == 6445
    assert r.opening_hours["Monday"] == "Open 24 hours"
    assert r.booking_links[0].startswith("https://book.servicetitan.com/")
    assert r.raw is not None             # full payload retained (ADR-003)


def test_missing_address_is_none_not_an_error():
    """Service-area businesses have no storefront (ADR-021)."""
    records = parse_search_response(RAW).records
    richmonds = next(r for r in records if r.title == "Richmonds Air")
    assert richmonds.address is None


def test_absent_booking_links_is_none_not_empty_list():
    """Absence IS the phone-only signal and must survive parsing."""
    records = parse_search_response(RAW).records
    htown = next(r for r in records
                 if r.title == "H-Town AC Repair HVAC services Houston")
    assert htown.booking_links is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_serper_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.clients.serper'`

- [ ] **Step 4: Write the protocols**

```python
# backend/app/clients/protocols.py
from typing import Protocol
from pydantic import BaseModel


class PlaceRecord(BaseModel):
    cid: str
    place_id: str | None = None
    fid: str | None = None
    title: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    rating_count: int | None = None
    phone_number: str | None = None
    website: str | None = None
    type: str | None = None
    types: list[str] = []
    opening_hours: dict[str, str] | None = None
    booking_links: list[str] | None = None
    raw: dict


class SearchResult(BaseModel):
    records: list[PlaceRecord]
    credits: int
    raw: dict


class ScrapeResult(BaseModel):
    url: str
    markdown: str | None = None
    raw_html: str | None = None
    links: list[str] = []
    status: str            # "ok" | "dead" | "parked"
    raw: dict


class ReviewRecord(BaseModel):
    rating: int | None = None
    iso_date: str | None = None
    snippet: str | None = None
    author: str | None = None


class ReviewResult(BaseModel):
    reviews: list[ReviewRecord]
    next_page_token: str | None = None
    raw: dict


class SearchProvider(Protocol):
    def search(self, query: str, page: int = 1) -> SearchResult: ...


class WebScraper(Protocol):
    def scrape(self, url: str) -> ScrapeResult: ...


class ReviewProvider(Protocol):
    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult: ...
```

- [ ] **Step 5: Write the Serper client**

```python
# backend/app/clients/serper.py
import httpx
from app.clients.protocols import PlaceRecord, SearchResult
from app.core.config import get_settings

ENDPOINT = "https://google.serper.dev/maps"


def parse_search_response(raw: dict) -> SearchResult:
    records = [
        PlaceRecord(
            cid=p["cid"], place_id=p.get("placeId"), fid=p.get("fid"),
            title=p["title"], address=p.get("address"),
            latitude=p.get("latitude"), longitude=p.get("longitude"),
            rating=p.get("rating"), rating_count=p.get("ratingCount"),
            phone_number=p.get("phoneNumber"), website=p.get("website"),
            type=p.get("type"), types=p.get("types", []),
            opening_hours=p.get("openingHours"),
            booking_links=p.get("bookingLinks"),   # absent stays None, not []
            raw=p,
        )
        for p in raw.get("places", [])
    ]
    return SearchResult(records=records, credits=raw.get("credits", 0), raw=raw)


class SerperClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._settings = get_settings()
        self._client = client or httpx.Client(timeout=30.0)

    def search(self, query: str, page: int = 1) -> SearchResult:
        resp = self._client.post(
            ENDPOINT,
            headers={"X-API-KEY": self._settings.serper_key,
                     "Content-Type": "application/json"},
            json={"q": query, "gl": "us", "hl": "en", "page": page},
        )
        resp.raise_for_status()
        return parse_search_response(resp.json())
```

- [ ] **Step 6: Write the fake**

```python
# backend/app/clients/fakes.py
import json
from pathlib import Path
from app.clients.protocols import (
    SearchResult, ScrapeResult, ReviewResult, ReviewRecord)
from app.clients.serper import parse_search_response

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures"


class FakeSearchProvider:
    """Replays the real Houston fixture. Zero API spend in tests."""

    def __init__(self, fixture: str = "serper_maps_houston_hvac.json") -> None:
        self._raw = json.loads((FIXTURES / fixture).read_text())
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, page: int = 1) -> SearchResult:
        self.calls.append((query, page))
        if page > 1:
            return SearchResult(records=[], credits=1, raw={"places": []})
        return parse_search_response(self._raw)


class FakeWebScraper:
    def __init__(self, html: str = "<html><body>hi</body></html>") -> None:
        self._html = html
        self.calls: list[str] = []

    def scrape(self, url: str) -> ScrapeResult:
        self.calls.append(url)
        return ScrapeResult(url=url, markdown="hi", raw_html=self._html,
                            links=[], status="ok", raw={})


class FakeReviewProvider:
    def __init__(self, reviews: list[ReviewRecord] | None = None) -> None:
        self._reviews = reviews or []
        self.calls: list[str] = []

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        self.calls.append(data_id)
        return ReviewResult(reviews=self._reviews, next_page_token=None, raw={})
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_serper_client.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/clients backend/tests
git commit -m "feat: add Serper client, provider protocols, and fakes"
```

---

### Task 9: Firecrawl client and HTML signal extraction

**Files:**
- Create: `backend/app/clients/firecrawl.py`, `backend/app/domain/extractors/html.py`, `backend/tests/fixtures/hvac_site_sample.html`, `backend/tests/unit/test_html_extractor.py`

**Interfaces:**
- Consumes: `ScrapeResult`, `WebScraper` (Task 8)
- Produces: `FirecrawlScraper(WebScraper)`, and pure
  `extract_html_signals(raw_html: str | None, markdown: str | None) -> dict[str, Any]`
  returning keys `has_chat_widget: bool`, `chat_vendor: str | None`,
  `has_contact_form: bool`, `runs_google_ads: bool`, `has_meta_pixel: bool`,
  `claims_24_7: bool`

- [ ] **Step 1: Fixtures are already captured — verify them**

**This step is done.** Four real Houston HVAC pages were fetched on
2026-08-29 and are committed at `backend/tests/fixtures/hvac_site_*.html`
(every `<script>` and `<link>` from the live document, plus real `<form>`
elements). What each one contains:

| Fixture | Contains |
|---|---|
| `hvac_site_uptown.html` | Housecall Pro chat, Google **Ads** (`AW-`), form |
| `hvac_site_mission.html` | ScheduleEngine chat, form |
| `hvac_site_revair.html` | PureChat, Meta Pixel, form |
| `hvac_site_royalair.html` | form only — the negative case |

Verify with:

```bash
cd backend && grep -c 'chat.housecallpro.com' tests/fixtures/hvac_site_uptown.html
```
Expected: `1` or more

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_html_extractor.py
from pathlib import Path
import pytest
from app.domain.extractors.html import extract_html_signals

FIX = Path("tests/fixtures")


def _load(name: str) -> str:
    return (FIX / f"hvac_site_{name}.html").read_text()


@pytest.mark.parametrize("site,vendor", [
    ("uptown", "housecallpro"),      # chat.housecallpro.com
    ("mission", "scheduleengine"),   # webchat.scheduleengine.net
    ("revair", "purechat"),          # app.purechat.com
])
def test_detects_real_chat_vendors(site, vendor):
    s = extract_html_signals(_load(site), None)
    assert s["has_chat_widget"] is True
    assert s["chat_vendor"] == vendor


def test_site_without_chat_reports_none():
    s = extract_html_signals(_load("royalair"), None)
    assert s["has_chat_widget"] is False
    assert s["chat_vendor"] is None


@pytest.mark.parametrize("junk", [
    "--wp--preset--shadow--crisp: 6px 6px 0px rgb(0,0,0)",   # WordPress CSS
    ".swiper-scrollbar-drag{height:100%}",                    # Swiper CSS
    'widgetUrl":"https:\\/\\/engage.wixapps.net\\/chat-widget-server\\/x"',
])
def test_known_false_positives_stay_excluded(junk):
    """Each of these matched a guessed fingerprint on real sites. If one ever
    trips has_chat_widget again, the pain track is silently corrupted."""
    assert extract_html_signals(junk, None)["has_chat_widget"] is False


def test_detects_google_ads_from_a_real_page():
    assert extract_html_signals(_load("uptown"), None)["runs_google_ads"] is True


def test_ga4_analytics_alone_is_not_google_ads():
    """G- is analytics; AW- is Ads. 5 of 20 real sites had G- and no ads."""
    html = '<script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123"></script>'
    assert extract_html_signals(html, None)["runs_google_ads"] is False


def test_detects_meta_pixel_from_a_real_page():
    assert extract_html_signals(_load("revair"), None)["has_meta_pixel"] is True


def test_detects_contact_form_on_real_pages():
    assert extract_html_signals(_load("royalair"), None)["has_contact_form"] is True


def test_html_catches_software_that_booking_links_missed():
    """House Pro's Serper bookingLinks pointed only at its own site, but the
    page embeds ServiceTitan. HTML adds ~10% coverage over bookingLinks."""
    html = '<script src="https://embed.scheduler.servicetitan.com/x.js"></script>'
    assert extract_html_signals(html, None)["software_from_html"] == "servicetitan"


def test_no_html_returns_all_false_not_a_crash():
    s = extract_html_signals(None, None)
    assert s["has_chat_widget"] is False
    assert s["runs_google_ads"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_html_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the extractor**

```python
# backend/app/domain/extractors/html.py
import re
from typing import Any

# CONFIRMED against 20 live Houston HVAC sites on 2026-08-29 (ADR-023).
# Every previously-guessed vendor (Podium, Intercom, Drift, Tawk, Tidio)
# scored ZERO hits and was removed. Do not re-add one without evidence.
CHAT_FINGERPRINTS: list[tuple[str, str]] = [
    ("webchat.scheduleengine.net", "scheduleengine"),   # 1/20 sites
    ("app.purechat.com", "purechat"),                   # 1/20
    ("chat.housecallpro.com", "housecallpro"),          # 1/20
]

# Substrings that LOOK like fingerprints and are not. Each was observed
# producing a false positive; the test suite asserts they stay excluded.
#   "crisp"        -> WordPress CSS var --wp--preset--shadow--crisp  (11/20 sites)
#   "rollbar"      -> the CSS class .swiper-scrollbar                 (7/20)
#   "chat-widget"  -> Wix boilerplate engage.wixapps.net/chat-widget-server,
#                     present whether or not chat is enabled          (2/20)

# Field-service software also appears as an embedded scheduler, catching
# businesses whose Serper bookingLinks pointed only at their own site.
SOFTWARE_FINGERPRINTS: list[tuple[str, str]] = [
    ("scheduler.servicetitan.com", "servicetitan"),     # 3/20
    ("housecallpro.com", "housecallpro"),               # 4/20
    ("getjobber.com", "jobber"),                        # 0/20 here, kept for other metros
]

# ONLY the AW- form indicates Google Ads. googleadservices.com and
# googleads.g.doubleclick both scored 0/20 and were removed.
# G- is GA4 analytics and must NEVER count (5/20 sites have it).
_ADS = re.compile(r"gtag/js\?id=AW-|[\"'&?]AW-\d{9,}", re.IGNORECASE)
_PIXEL = re.compile(r"connect\.facebook\.net|fbq\(", re.IGNORECASE)   # 4/20
_FORM = re.compile(r"<form[^>]*>.*?<input[^>]+type=[\"'](?:email|tel)[\"']",
                   re.IGNORECASE | re.DOTALL)
_24_7 = re.compile(r"24[\s/\-]?7|24 hours a day|around the clock", re.IGNORECASE)


def extract_html_signals(raw_html: str | None,
                         markdown: str | None) -> dict[str, Any]:
    html = (raw_html or "").lower()
    text = markdown or ""

    chat_vendor = next((v for needle, v in CHAT_FINGERPRINTS if needle in html), None)
    software = next((v for needle, v in SOFTWARE_FINGERPRINTS if needle in html), None)

    return {
        "has_chat_widget": chat_vendor is not None,
        "chat_vendor": chat_vendor,
        "software_from_html": software,
        "has_contact_form": bool(_FORM.search(raw_html or "")),
        "runs_google_ads": bool(_ADS.search(raw_html or "")),
        "has_meta_pixel": bool(_PIXEL.search(raw_html or "")),
        "claims_24_7": bool(_24_7.search(text)),
    }
```

- [ ] **Step 5: Write the Firecrawl client**

```python
# backend/app/clients/firecrawl.py
from firecrawl import Firecrawl
from app.clients.protocols import ScrapeResult
from app.core.config import get_settings

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")


class FirecrawlScraper:
    def __init__(self, client: Firecrawl | None = None) -> None:
        self._client = client or Firecrawl(api_key=get_settings().firecrawl_key)

    def scrape(self, url: str) -> ScrapeResult:
        try:
            doc = self._client.scrape(
                url,
                formats=["markdown", "rawHtml", "links"],
                only_main_content=False,   # MUST be False — footers hold contact
                                           # details and vendor badges (ADR-012)
                timeout=30000,
            )
        except Exception:
            return ScrapeResult(url=url, status="dead", raw={})

        data = doc if isinstance(doc, dict) else doc.__dict__
        return ScrapeResult(
            url=url,
            markdown=data.get("markdown"),
            raw_html=data.get("raw_html") or data.get("rawHtml"),
            links=data.get("links", []) or [],
            status="ok",
            raw=data,
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_html_extractor.py -v && lint-imports`
Expected: 12 passed, contracts kept

- [ ] **Step 7: Commit**

```bash
git add backend/app/clients/firecrawl.py backend/app/domain/extractors backend/tests
git commit -m "feat: add Firecrawl scraper and HTML signal extraction"
```

---

### Task 10: SerpApi reviews client with 90-day early stop

**Files:**
- Create: `backend/app/clients/serpapi_reviews.py`, `backend/tests/unit/test_serpapi_reviews.py`

**Interfaces:**
- Consumes: `ReviewProvider`, `ReviewRecord`, `ReviewResult` (Task 8)
- Produces: `SerpApiReviewProvider(ReviewProvider)` and pure
  `collect_recent_reviews(provider: ReviewProvider, data_id: str, days: int = 90, max_pages: int = 4) -> list[ReviewRecord]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_serpapi_reviews.py
from datetime import datetime, timedelta, UTC
from app.clients.protocols import ReviewRecord, ReviewResult
from app.clients.serpapi_reviews import collect_recent_reviews


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class PagedProvider:
    """Page 1 returns 8 regardless of `num`; later pages up to 20 (ADR-020)."""

    def __init__(self, pages: list[list[ReviewRecord]]) -> None:
        self.pages = pages
        self.call_count = 0

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        idx = self.call_count
        self.call_count += 1
        has_next = idx + 1 < len(self.pages)
        return ReviewResult(reviews=self.pages[idx],
                            next_page_token="tok" if has_next else None, raw={})


def test_stops_as_soon_as_reviews_pass_the_90_day_boundary():
    p = PagedProvider([
        [ReviewRecord(iso_date=_iso(5)) for _ in range(8)],
        [ReviewRecord(iso_date=_iso(200)) for _ in range(20)],   # all too old
        [ReviewRecord(iso_date=_iso(400)) for _ in range(20)],
    ])
    out = collect_recent_reviews(p, "cid1")
    assert len(out) == 8
    assert p.call_count == 2      # stopped after the first stale page — not 3


def test_keeps_paginating_while_reviews_are_recent():
    p = PagedProvider([
        [ReviewRecord(iso_date=_iso(3)) for _ in range(8)],
        [ReviewRecord(iso_date=_iso(30)) for _ in range(20)],
        [ReviewRecord(iso_date=_iso(300)) for _ in range(20)],
    ])
    out = collect_recent_reviews(p, "cid1")
    assert len(out) == 28


def test_respects_max_pages_ceiling():
    p = PagedProvider([[ReviewRecord(iso_date=_iso(1))] * 20 for _ in range(10)])
    collect_recent_reviews(p, "cid1", max_pages=4)
    assert p.call_count == 4      # a runaway business cannot drain the free tier


def test_reviews_without_dates_are_skipped_not_crashed():
    p = PagedProvider([[ReviewRecord(iso_date=None), ReviewRecord(iso_date=_iso(2))]])
    assert len(collect_recent_reviews(p, "cid1")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_serpapi_reviews.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/clients/serpapi_reviews.py
from datetime import datetime, timedelta, UTC
import serpapi
from app.clients.protocols import ReviewProvider, ReviewRecord, ReviewResult
from app.core.config import get_settings


class SerpApiReviewProvider:
    def __init__(self) -> None:
        self._key = get_settings().serpapi_key

    def reviews(self, data_id: str, page_token: str | None = None) -> ReviewResult:
        params = {
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "sort_by": "newestFirst",   # MANDATORY — the default qualityScore
                                        # ordering returns an arbitrary slice of
                                        # history and corrupts velocity (ADR-020)
            "num": 20,
            "api_key": self._key,
        }
        if page_token:
            params["next_page_token"] = page_token
        raw = serpapi.search(**params).as_dict()

        return ReviewResult(
            reviews=[
                ReviewRecord(
                    rating=r.get("rating"), iso_date=r.get("iso_date"),
                    snippet=r.get("snippet") or r.get("extracted_snippet"),
                    author=(r.get("user") or {}).get("name"),
                )
                for r in raw.get("reviews", [])
            ],
            next_page_token=(raw.get("serpapi_pagination") or {}).get("next_page_token"),
            raw=raw,
        )


def collect_recent_reviews(provider: ReviewProvider, data_id: str,
                           days: int = 90, max_pages: int = 4) -> list[ReviewRecord]:
    """Page newest-first, stopping at the first page with nothing recent."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    collected: list[ReviewRecord] = []
    token: str | None = None

    for _ in range(max_pages):
        result = provider.reviews(data_id, token)
        recent = [
            r for r in result.reviews
            if r.iso_date and datetime.fromisoformat(r.iso_date) >= cutoff
        ]
        collected.extend(recent)
        if not recent or not result.next_page_token:
            break
        token = result.next_page_token

    return collected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_serpapi_reviews.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/clients/serpapi_reviews.py backend/tests/unit/test_serpapi_reviews.py
git commit -m "feat: add SerpApi review provider with 90-day early stop"
```

---

### Task 11: Error taxonomy, retry policy, and the Stage base

**Files:**
- Create: `backend/app/core/errors.py`, `backend/app/pipeline/base.py`, `backend/tests/unit/test_stage_base.py`

**Interfaces:**
- Consumes: `BusinessStatus` (Task 2)
- Produces:
  - Exceptions `TransientError`, `BusinessPermanentError`, `RunPermanentError`
  - `classify_http_error(status_code: int) -> type[Exception]`
  - `Stage` ABC with `name: str`, `consumes: BusinessStatus`, `produces: BusinessStatus`, abstract `process(business, session) -> None`, concrete `run(session, run_id, limit) -> StageReport`
  - `StageReport(processed: int, failed: int, aborted: bool, reason: str | None)`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_stage_base.py
import pytest
from app.core.errors import (
    TransientError, BusinessPermanentError, RunPermanentError, classify_http_error)


@pytest.mark.parametrize("code,expected", [
    (429, TransientError),
    (500, TransientError),
    (502, TransientError),
    (402, RunPermanentError),        # Firecrawl out of credits — abort the run
    (401, RunPermanentError),        # bad key — do not burn 200 businesses
    (403, RunPermanentError),
    (404, BusinessPermanentError),   # dead site — this is data, not failure
])
def test_http_errors_map_to_the_four_way_taxonomy(code, expected):
    assert classify_http_error(code) is expected
```

```python
# continued — stage behaviour
from app.pipeline.base import Stage, StageReport
from app.models.business import Business, BusinessStatus


class ExplodingStage(Stage):
    name = "test"
    consumes = BusinessStatus.DISCOVERED
    produces = BusinessStatus.SITE_SCRAPED

    def __init__(self, blow_up_on: set[str]) -> None:
        self.blow_up_on = blow_up_on

    def process(self, business, session):
        if business.cid in self.blow_up_on:
            raise ValueError("parser exploded")


def test_one_bad_business_does_not_stop_the_others(session):
    for cid in ["a", "b", "c"]:
        session.add(Business(cid=cid, name=cid, status=BusinessStatus.DISCOVERED))
    session.commit()

    report = ExplodingStage(blow_up_on={"b"}).run(session, run_id=None, limit=10)

    assert report.processed == 2 and report.failed == 1
    b = session.query(Business).filter_by(cid="b").one()
    assert b.status is BusinessStatus.FAILED
    assert b.failed_stage == "test"
    assert "parser exploded" in b.error_message
    # a and c advanced normally
    assert session.query(Business).filter_by(cid="a").one().status \
        is BusinessStatus.SITE_SCRAPED


def test_run_permanent_error_aborts_immediately(session):
    for cid in ["a", "b", "c", "d", "e", "f"]:
        session.add(Business(cid=cid, name=cid, status=BusinessStatus.DISCOVERED))
    session.commit()

    class OutOfCredits(Stage):
        name = "test"
        consumes = BusinessStatus.DISCOVERED
        produces = BusinessStatus.SITE_SCRAPED
        def process(self, business, session):
            raise RunPermanentError("out of credits")

    report = OutOfCredits().run(session, run_id=None, limit=10)
    assert report.aborted is True
    assert report.processed == 0
    # The circuit breaker exists so a dead API key cannot cost 200 failures.
    assert report.failed <= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_stage_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.errors'`

- [ ] **Step 3: Write the error taxonomy**

```python
# backend/app/core/errors.py
class TransientError(Exception):
    """Retry with backoff: timeout, 429, 5xx."""


class BusinessPermanentError(Exception):
    """Not an error — data. Dead domain, 404. Business continues with
    reduced coverage rather than being marked failed."""


class RunPermanentError(Exception):
    """Abort the whole run: bad key, out of credits, quota exceeded."""


def classify_http_error(status_code: int) -> type[Exception]:
    if status_code in (401, 402, 403):
        return RunPermanentError
    if status_code == 429 or status_code >= 500:
        return TransientError
    return BusinessPermanentError
```

- [ ] **Step 4: Write the Stage base**

```python
# backend/app/pipeline/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.core.errors import TransientError, BusinessPermanentError, RunPermanentError
from app.models.business import Business, BusinessStatus

log = structlog.get_logger()
CIRCUIT_BREAKER_THRESHOLD = 5


@dataclass
class StageReport:
    processed: int = 0
    failed: int = 0
    aborted: bool = False
    reason: str | None = None


class Stage(ABC):
    """Template Method: retry, error capture, and status advancement are
    written once here; subclasses supply only `process`."""

    name: str
    consumes: BusinessStatus
    produces: BusinessStatus

    @abstractmethod
    def process(self, business: Business, session) -> None: ...

    def select(self, session, run_id: int | None, limit: int) -> list[Business]:
        q = session.query(Business).filter(Business.status == self.consumes)
        return q.limit(limit).all()

    @retry(retry=retry_if_exception_type(TransientError),
           stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)
    def _process_with_retry(self, business: Business, session) -> None:
        self.process(business, session)

    def run(self, session, run_id: int | None, limit: int = 500) -> StageReport:
        report = StageReport()
        consecutive_fatal = 0

        for business in self.select(session, run_id, limit):
            try:
                self._process_with_retry(business, session)
                business.status = self.produces
                session.commit()          # Unit of Work per business (ADR-009)
                report.processed += 1
                consecutive_fatal = 0

            except RunPermanentError as exc:
                session.rollback()
                consecutive_fatal += 1
                report.failed += 1
                if consecutive_fatal >= CIRCUIT_BREAKER_THRESHOLD:
                    report.aborted = True
                    report.reason = str(exc)
                    log.error("stage.aborted", stage=self.name, reason=str(exc))
                    break

            except BusinessPermanentError:
                business.status = self.produces      # data, not failure
                session.commit()
                report.processed += 1

            except Exception as exc:
                session.rollback()
                business.status = BusinessStatus.FAILED
                business.failed_stage = self.name
                business.error_message = str(exc)[:500]
                business.attempt_count += 1
                session.commit()
                report.failed += 1
                log.warning("stage.business_failed", stage=self.name,
                            cid=business.cid, error=str(exc))

        return report
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_stage_base.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/errors.py backend/app/pipeline/base.py backend/tests
git commit -m "feat: add error taxonomy, retry policy, and Stage template method"
```

---

### Task 12: The `discover` stage

**Files:**
- Create: `backend/app/pipeline/discover.py`, `backend/app/services/search_plan.py`, `backend/tests/integration/test_discover.py`

**Interfaces:**
- Consumes: `SearchProvider` (Task 8), `segment_for` (Task 3), `validate_phone` (Task 3), `Business`, `Run`, `RunBusiness`, `SearchQuery`, `RawPayload`, `ApiCall` (Task 2)
- Produces: `SearchPlan(vertical: str, search_terms: list[str], locations: list[str], pages_per_query: int)`, `build_search_plan(vertical: str, state: str | None, location: str | None, config: dict) -> SearchPlan`, and `DiscoverStage(provider: SearchProvider)` with `discover(session, run_id, plan) -> StageReport`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_discover.py
from app.clients.fakes import FakeSearchProvider
from app.pipeline.discover import DiscoverStage
from app.services.search_plan import SearchPlan
from app.models.business import Business, BusinessStatus, Segment

PLAN = SearchPlan(vertical="hvac", search_terms=["hvac contractor"],
                  locations=["Houston, TX"], pages_per_query=1)


def test_inserts_businesses_with_segment_and_validated_phone(session):
    stage = DiscoverStage(FakeSearchProvider())
    stage.discover(session, run_id=None, plan=PLAN)

    air_tech = session.query(Business).filter_by(
        cid="16433610908791049931").one()
    assert air_tech.segment is Segment.ENTERPRISE     # 6,445 reviews
    assert air_tech.phone == "+18326805546"
    assert air_tech.phone_is_valid is True
    assert air_tech.status is BusinessStatus.DISCOVERED


def test_prefilter_is_only_has_a_website(session):
    """ADR-022: ratingCount is a label, never a gate."""
    DiscoverStage(FakeSearchProvider()).discover(session, run_id=None, plan=PLAN)

    # Heights A/C has 72 reviews and a website — it must survive.
    heights = session.query(Business).filter_by(cid="6096296143558169934").one()
    assert heights.status is BusinessStatus.DISCOVERED
    assert heights.segment is Segment.EMERGING

    filtered = session.query(Business).filter_by(
        status=BusinessStatus.FILTERED_OUT).all()
    assert all(b.website is None for b in filtered)


def test_rediscovery_does_not_reinsert_or_reset_status(session):
    """The dedupe mechanism from ADR-013."""
    stage = DiscoverStage(FakeSearchProvider())
    stage.discover(session, run_id=None, plan=PLAN)
    first_count = session.query(Business).count()

    b = session.query(Business).filter_by(cid="16433610908791049931").one()
    b.status = BusinessStatus.SCORED
    session.commit()

    stage.discover(session, run_id=None, plan=PLAN)
    assert session.query(Business).count() == first_count
    assert session.query(Business).filter_by(
        cid="16433610908791049931").one().status is BusinessStatus.SCORED


def test_raw_payload_and_actual_credits_are_recorded(session):
    from app.models.derived import RawPayload, ApiCall
    DiscoverStage(FakeSearchProvider()).discover(session, run_id=None, plan=PLAN)

    assert session.query(RawPayload).count() >= 20      # ADR-003
    call = session.query(ApiCall).filter_by(provider="serper").first()
    assert call.credits == 3                            # self-reported (ADR-021)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_discover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.discover'`

- [ ] **Step 3: Write the search plan builder**

```python
# backend/app/services/search_plan.py
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchPlan:
    vertical: str
    search_terms: list[str]
    locations: list[str]
    pages_per_query: int = 5

    @property
    def queries(self) -> list[str]:
        # Serper resolves natural-language locations (ADR-021) — no centroids.
        return [f"{term} in {loc}"
                for loc in self.locations for term in self.search_terms]


def build_search_plan(vertical: str, state: str | None, location: str | None,
                      verticals_cfg: dict, locations_cfg: dict,
                      pages_per_query: int = 5) -> SearchPlan:
    terms = verticals_cfg[vertical]["search_terms"]
    if location:
        locations = [location]
    elif state:
        locations = locations_cfg[state]["metros"]
    else:
        raise ValueError("one of state or location is required")
    return SearchPlan(vertical, terms, locations, pages_per_query)
```

- [ ] **Step 4: Write the stage**

```python
# backend/app/pipeline/discover.py
import structlog
from app.clients.protocols import SearchProvider, PlaceRecord
from app.domain.segments import segment_for
from app.domain.phone import validate_phone
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, ApiCall
from app.models.run import RunBusiness, SearchQuery
from app.pipeline.base import StageReport
from app.services.search_plan import SearchPlan

log = structlog.get_logger()


class DiscoverStage:
    name = "discover"

    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    def discover(self, session, run_id: int | None,
                 plan: SearchPlan) -> StageReport:
        report = StageReport()

        for query in plan.queries:
            for page in range(1, plan.pages_per_query + 1):
                result = self._provider.search(query, page=page)

                session.add(ApiCall(run_id=run_id, provider="serper",
                                    endpoint="maps", credits=result.credits,
                                    status_code=200))
                session.add(SearchQuery(run_id=run_id, term=query,
                                        location=None,
                                        result_count=len(result.records)))
                if not result.records:
                    break

                for record in result.records:
                    self._upsert(session, run_id, record, plan.vertical, report)

                session.commit()

        return report

    def _upsert(self, session, run_id: int | None, record: PlaceRecord,
                vertical: str, report: StageReport) -> None:
        existing = session.query(Business).filter_by(cid=record.cid).one_or_none()

        if existing is not None:
            # ON CONFLICT DO NOTHING: status is untouched, so this business
            # falls out of every downstream stage query (ADR-013).
            if run_id is not None:
                session.merge(RunBusiness(run_id=run_id,
                                          business_id=existing.id, is_new=False))
            return

        phone = validate_phone(record.phone_number)
        business = Business(
            cid=record.cid, place_id=record.place_id, fid=record.fid,
            name=record.title, address=record.address,
            lat=record.latitude, lng=record.longitude,
            phone=phone, phone_is_valid=phone is not None,
            website=record.website,
            rating=record.rating, review_count=record.rating_count,
            segment=segment_for(record.rating_count),
            primary_category=record.type, types=record.types,
            opening_hours=record.opening_hours,
            booking_links=record.booking_links,
            vertical=vertical,
            # The ONLY prefilter is "has a website" (ADR-022).
            status=(BusinessStatus.DISCOVERED if record.website
                    else BusinessStatus.FILTERED_OUT),
            first_seen_run_id=run_id,
        )
        session.add(business)
        session.flush()

        session.add(RawPayload(business_id=business.id, source="serper_maps",
                               url=None, payload=record.raw))
        if run_id is not None:
            session.add(RunBusiness(run_id=run_id, business_id=business.id,
                                    is_new=True))
        report.processed += 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_discover.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/discover.py backend/app/services/search_plan.py backend/tests/integration/test_discover.py
git commit -m "feat: add discover stage with cid dedupe and website-only prefilter"
```

---

### Task 13: The `extract_signals` stage

**Files:**
- Create: `backend/app/domain/extractors/serper.py`, `backend/app/pipeline/extract_signals.py`, `backend/tests/unit/test_serper_extractor.py`, `backend/tests/integration/test_extract_signals_stage.py`

**Interfaces:**
- Consumes: `parse_opening_hours` (Task 4), `classify_booking_links` (Task 5), `extract_html_signals` (Task 9), `Business`, `Signals`, `ManualFacts` (Task 2)
- Produces: pure `extract_serper_signals(opening_hours, booking_links, segment) -> dict[str, Any]`, and `ExtractSignalsStage(Stage)` consuming `SITE_SCRAPED` and producing `SIGNALS_EXTRACTED`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_serper_extractor.py
from app.domain.extractors.serper import extract_serper_signals


def test_royal_air_signals():
    s = extract_serper_signals(
        opening_hours={**{d: "8 AM–5 PM" for d in
                          ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
                       "Saturday": "Closed", "Sunday": "Closed"},
        booking_links=["http://www.royalairhouston.com/appointment-service-request/"],
        segment="enterprise",
    )
    assert s["closed_weekends"] is True
    assert s["closes_before_6pm"] is True
    assert s["is_24_7"] is False
    assert s["booking_vendor"] == "own"
    assert s["has_booking_link"] is True
    assert s["is_phone_only"] is False


def test_phone_only_business_has_no_booking_link_key():
    s = extract_serper_signals(opening_hours=None, booking_links=None,
                               segment="emerging")
    assert s["is_phone_only"] is True
    assert s["has_booking_link"] is False
    assert s["hours_parse_failed"] is True
```

```python
# backend/tests/integration/test_extract_signals_stage.py
from app.models.business import Business, BusinessStatus
from app.models.derived import Signals
from app.models.manual import ManualFacts
from app.pipeline.extract_signals import ExtractSignalsStage


def test_manual_facts_override_derived_values(session):
    """ADR-008: signals is rebuildable, manual_facts is not. Manual wins."""
    b = Business(cid="c1", name="A", status=BusinessStatus.SITE_SCRAPED,
                 opening_hours={"Monday": "8 AM–5 PM"}, booking_links=None)
    session.add(b)
    session.flush()
    session.add(ManualFacts(business_id=b.id, estimated_employees=22,
                            has_office_admin=True))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)

    sig = session.query(Signals).filter_by(business_id=b.id).one()
    assert sig.estimated_employees == 22
    assert sig.employee_est_source == "manual_apollo"
    assert b.status is BusinessStatus.SIGNALS_EXTRACTED


def test_rerunning_the_stage_does_not_wipe_manual_facts(session):
    b = Business(cid="c2", name="B", status=BusinessStatus.SITE_SCRAPED)
    session.add(b); session.flush()
    session.add(ManualFacts(business_id=b.id, estimated_employees=15))
    session.commit()

    ExtractSignalsStage().run(session, run_id=None)
    b.status = BusinessStatus.SITE_SCRAPED       # simulate the enrichment loop
    session.commit()
    ExtractSignalsStage().run(session, run_id=None)

    assert session.query(Signals).filter_by(
        business_id=b.id).one().estimated_employees == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_serper_extractor.py tests/integration/test_extract_signals_stage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the Serper extractor**

```python
# backend/app/domain/extractors/serper.py
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
```

- [ ] **Step 4: Write the stage**

```python
# backend/app/pipeline/extract_signals.py
from app.domain.extractors.serper import extract_serper_signals
from app.domain.extractors.html import extract_html_signals
from app.models.business import BusinessStatus
from app.models.derived import Signals, RawPayload
from app.models.manual import ManualFacts
from app.pipeline.base import Stage

EXTRACTOR_VERSION = "1"


class ExtractSignalsStage(Stage):
    name = "extract_signals"
    consumes = BusinessStatus.SITE_SCRAPED
    produces = BusinessStatus.SIGNALS_EXTRACTED

    def process(self, business, session) -> None:
        values = extract_serper_signals(
            business.opening_hours, business.booking_links,
            str(business.segment) if business.segment else None,
        )

        scrape = (session.query(RawPayload)
                  .filter_by(business_id=business.id, source="firecrawl")
                  .order_by(RawPayload.fetched_at.desc()).first())
        payload = scrape.payload if scrape else {}
        values.update(extract_html_signals(payload.get("raw_html"),
                                           payload.get("markdown")))
        values["website_status"] = payload.get("status", "none")

        # Manual facts overlay LAST — they always win (ADR-008).
        manual = session.query(ManualFacts).filter_by(
            business_id=business.id).one_or_none()
        if manual is not None:
            if manual.estimated_employees is not None:
                values["estimated_employees"] = manual.estimated_employees
                values["employee_est_source"] = "manual_apollo"
            if manual.has_office_admin is not None:
                values["has_office_admin"] = manual.has_office_admin
            if manual.owner_growth_focused is not None:
                values["owner_growth_focused"] = manual.owner_growth_focused

        existing = session.query(Signals).filter_by(
            business_id=business.id).one_or_none()
        if existing is None:
            session.add(Signals(business_id=business.id,
                                extractor_version=EXTRACTOR_VERSION, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.extractor_version = EXTRACTOR_VERSION
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_serper_extractor.py tests/integration/test_extract_signals_stage.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/extractors/serper.py backend/app/pipeline/extract_signals.py backend/tests
git commit -m "feat: add extract_signals stage with manual-facts overlay"
```

---

### Task 14: The `score` stage

**Files:**
- Create: `backend/app/pipeline/score.py`, `backend/app/services/rulesets.py`, `backend/tests/integration/test_score_stage.py`

**Interfaces:**
- Consumes: `evaluate`, `Ruleset` (Task 6), `load_ruleset` (Task 7), `Signals`, `Score` (Task 2)
- Produces: `read_ruleset_file(path: Path) -> Ruleset` (does the file I/O the domain must not), `ScoreStage(ruleset: Ruleset)` consuming `SIGNALS_EXTRACTED`, producing `SCORED`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_score_stage.py
from pathlib import Path
from app.models.business import Business, BusinessStatus
from app.models.derived import Signals, Score
from app.pipeline.score import ScoreStage
from app.services.rulesets import read_ruleset_file

RULESET = read_ruleset_file(Path("config/rulesets/hvac_v1.yaml"))


def _royal_air(session) -> Business:
    b = Business(cid="c1", name="Royal Air", status=BusinessStatus.SIGNALS_EXTRACTED)
    session.add(b); session.flush()
    session.add(Signals(business_id=b.id, booking_vendor="own",
                        has_booking_link=True, is_phone_only=False,
                        closed_weekends=True, closes_before_6pm=True,
                        has_chat_widget=False, runs_google_ads=True))
    session.commit()
    return b


def test_writes_a_score_with_reasons_and_quadrant(session):
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)

    s = session.query(Score).filter_by(business_id=b.id).one()
    assert s.ruleset_version == "hvac_v1"
    assert s.quadrant == "go_now"
    assert s.coverage < 1.0                    # dormant review rules skipped
    assert any(r["rule"] == "closed_weekends" and r["matched"]
               for r in s.reasons)
    assert b.status is BusinessStatus.SCORED


def test_rescoring_with_the_same_ruleset_updates_rather_than_duplicates(session):
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()
    ScoreStage(RULESET).run(session, run_id=None)

    assert session.query(Score).filter_by(business_id=b.id).count() == 1


def test_a_second_ruleset_version_adds_a_row_rather_than_overwriting(session):
    """ADR-005: tuning must never destroy the evidence of the last attempt."""
    from dataclasses import replace
    b = _royal_air(session)
    ScoreStage(RULESET).run(session, run_id=None)
    b.status = BusinessStatus.SIGNALS_EXTRACTED
    session.commit()
    ScoreStage(replace(RULESET, version="hvac_v2")).run(session, run_id=None)

    versions = {s.ruleset_version
                for s in session.query(Score).filter_by(business_id=b.id)}
    assert versions == {"hvac_v1", "hvac_v2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_score_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.rulesets'`

- [ ] **Step 3: Write the loader service and the stage**

```python
# backend/app/services/rulesets.py
from pathlib import Path
import yaml
from app.domain.rules.loader import load_ruleset
from app.domain.rules.models import Ruleset


def read_ruleset_file(path: Path) -> Ruleset:
    """File I/O lives here so app/domain stays pure."""
    return load_ruleset(yaml.safe_load(path.read_text()))
```

```python
# backend/app/pipeline/score.py
from dataclasses import asdict
from app.domain.rules.engine import evaluate
from app.domain.rules.models import Ruleset
from app.models.business import BusinessStatus
from app.models.derived import Signals, Score
from app.pipeline.base import Stage

_NON_SIGNAL_COLUMNS = {"business_id", "extracted_at", "extractor_version"}


class ScoreStage(Stage):
    name = "score"
    consumes = BusinessStatus.SIGNALS_EXTRACTED
    produces = BusinessStatus.SCORED

    def __init__(self, ruleset: Ruleset) -> None:
        self._ruleset = ruleset

    def process(self, business, session) -> None:
        row = session.query(Signals).filter_by(business_id=business.id).one()
        signals = {
            c.name: getattr(row, c.name)
            for c in row.__table__.columns
            if c.name not in _NON_SIGNAL_COLUMNS and getattr(row, c.name) is not None
        }

        result = evaluate(signals, self._ruleset)

        existing = session.query(Score).filter_by(
            business_id=business.id,
            ruleset_version=self._ruleset.version).one_or_none()
        payload = dict(
            fit_score=result.fit_score, pain_score=result.pain_score,
            quadrant=result.quadrant, coverage=result.coverage,
            reasons=[asdict(r) for r in result.reasons],
        )
        if existing is None:
            session.add(Score(business_id=business.id,
                              ruleset_version=self._ruleset.version, **payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
```

Note the `is not None` filter: a signal that was never extracted must be
**absent** from the dict, not `None`, so `on_missing: skip` can distinguish
"unknown" from "false" (ADR-005).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_score_stage.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/score.py backend/app/services/rulesets.py backend/tests/integration/test_score_stage.py
git commit -m "feat: add score stage with per-ruleset-version upsert"
```

---

### Task 15: The `scrape_site` stage with stratified sampling

**Files:**
- Create: `backend/app/pipeline/scrape_site.py`, `backend/app/domain/sampling.py`, `backend/tests/unit/test_sampling.py`, `backend/tests/integration/test_scrape_site.py`

**Interfaces:**
- Consumes: `WebScraper` (Task 8), `Segment` (Task 3), `Stage` (Task 11)
- Produces: pure `stratify(items: list[T], key: Callable[[T], str | None], per_group: int) -> list[T]`, and `ScrapeSiteStage(scraper: WebScraper, per_segment: int)` consuming `DISCOVERED`, producing `SITE_SCRAPED`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_sampling.py
from app.domain.sampling import stratify


def test_takes_up_to_n_from_each_group():
    items = ([("a", i) for i in range(20)] + [("b", i) for i in range(3)]
             + [("c", i) for i in range(10)])
    out = stratify(items, key=lambda x: x[0], per_group=5)
    counts = {g: sum(1 for i in out if i[0] == g) for g in "abc"}
    assert counts == {"a": 5, "b": 3, "c": 5}


def test_preserves_input_order_within_a_group():
    items = [("a", 3), ("a", 1), ("a", 2)]
    assert stratify(items, key=lambda x: x[0], per_group=2) == [("a", 3), ("a", 1)]


def test_items_with_no_group_are_excluded():
    items = [("a", 1), (None, 2)]
    assert stratify(items, key=lambda x: x[0], per_group=5) == [("a", 1)]
```

```python
# backend/tests/integration/test_scrape_site.py
from app.clients.fakes import FakeWebScraper
from app.models.business import Business, BusinessStatus, Segment
from app.pipeline.scrape_site import ScrapeSiteStage


def test_scrapes_up_to_n_per_segment_not_top_n_overall(session):
    """ADR-022: ranking by score alone would concentrate every scrape in one
    segment and make the ICP question unanswerable."""
    for seg in [Segment.EMERGING, Segment.GROWTH,
                Segment.ESTABLISHED, Segment.ENTERPRISE]:
        for i in range(10):
            session.add(Business(cid=f"{seg}-{i}", name=f"{seg}{i}",
                                 segment=seg, website="https://example.com",
                                 status=BusinessStatus.DISCOVERED))
    session.commit()

    scraper = FakeWebScraper()
    ScrapeSiteStage(scraper, per_segment=3).run(session, run_id=None)

    scraped = session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).all()
    assert len(scraped) == 12
    for seg in [Segment.EMERGING, Segment.GROWTH,
                Segment.ESTABLISHED, Segment.ENTERPRISE]:
        assert sum(1 for b in scraped if b.segment is seg) == 3


def test_dead_site_advances_with_website_status_dead_not_failed(session):
    """A dead domain is data, not a failure (spec section 10, kind 2)."""
    class DeadScraper:
        def scrape(self, url):
            from app.clients.protocols import ScrapeResult
            return ScrapeResult(url=url, status="dead", raw={})

    session.add(Business(cid="d1", name="Dead", segment=Segment.GROWTH,
                         website="https://gone.example",
                         status=BusinessStatus.DISCOVERED))
    session.commit()

    ScrapeSiteStage(DeadScraper(), per_segment=5).run(session, run_id=None)

    b = session.query(Business).filter_by(cid="d1").one()
    assert b.status is BusinessStatus.SITE_SCRAPED
    assert b.failed_stage is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_sampling.py tests/integration/test_scrape_site.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the sampler**

```python
# backend/app/domain/sampling.py
from collections import defaultdict
from typing import Callable, TypeVar

T = TypeVar("T")


def stratify(items: list[T], key: Callable[[T], str | None],
             per_group: int) -> list[T]:
    """Take up to `per_group` from each group, preserving input order.

    Deliberately not a global top-N: every segment must be represented so
    outcomes can answer the ICP question (ADR-022).
    """
    taken: dict[str, int] = defaultdict(int)
    out: list[T] = []
    for item in items:
        group = key(item)
        if group is None or taken[group] >= per_group:
            continue
        taken[group] += 1
        out.append(item)
    return out
```

- [ ] **Step 4: Write the stage**

```python
# backend/app/pipeline/scrape_site.py
from app.clients.protocols import WebScraper
from app.domain.sampling import stratify
from app.models.business import Business, BusinessStatus
from app.models.derived import RawPayload, ApiCall
from app.pipeline.base import Stage

PAGE_ALLOWLIST = ("/about", "/contact", "/services", "/team")
MAX_PAGES = 5


class ScrapeSiteStage(Stage):
    name = "scrape_site"
    consumes = BusinessStatus.DISCOVERED
    produces = BusinessStatus.SITE_SCRAPED

    def __init__(self, scraper: WebScraper, per_segment: int = 15) -> None:
        self._scraper = scraper
        self._per_segment = per_segment

    def select(self, session, run_id: int | None, limit: int) -> list[Business]:
        candidates = (session.query(Business)
                      .filter(Business.status == self.consumes,
                              Business.website.isnot(None))
                      .order_by(Business.review_count.desc().nullslast())
                      .all())
        return stratify(candidates,
                        key=lambda b: str(b.segment) if b.segment else None,
                        per_group=self._per_segment)

    def process(self, business: Business, session) -> None:
        home = self._scraper.scrape(business.website)
        session.add(RawPayload(business_id=business.id, source="firecrawl",
                               url=business.website,
                               payload=home.model_dump(),
                               raw_text=home.raw_html))
        session.add(ApiCall(provider="firecrawl", endpoint="scrape",
                            credits=1, status_code=200))

        if home.status != "ok":
            return      # dead site: advance with reduced coverage, not FAILED

        # Use the returned links rather than guessing paths (ADR-012).
        targets = [
            link for link in home.links
            if any(p in link.lower() for p in PAGE_ALLOWLIST)
        ][: MAX_PAGES - 1]

        for url in targets:
            page = self._scraper.scrape(url)
            session.add(RawPayload(business_id=business.id, source="firecrawl",
                                   url=url, payload=page.model_dump(),
                                   raw_text=page.raw_html))
            session.add(ApiCall(provider="firecrawl", endpoint="scrape",
                                credits=1, status_code=200))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_sampling.py tests/integration/test_scrape_site.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/scrape_site.py backend/app/domain/sampling.py backend/tests
git commit -m "feat: add scrape_site stage with stratified segment sampling"
```

---

### Task 16: The `fetch_reviews` enrichment stage

**Files:**
- Create: `backend/app/pipeline/fetch_reviews.py`, `backend/tests/integration/test_fetch_reviews.py`

**Interfaces:**
- Consumes: `ReviewProvider`, `collect_recent_reviews` (Task 10), `Review`, `Signals`, `ApiCall` (Task 2)
- Produces: pure `count_missed_call_complaints(snippets: list[str]) -> tuple[int, list[str]]` in `app/domain/extractors/complaints.py`, and `FetchReviewsStage(provider, top_n, monthly_ceiling)` selecting `SCORED` businesses and resetting them to `SITE_SCRAPED`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_complaints.py
from app.domain.extractors.complaints import count_missed_call_complaints


def test_matches_real_missed_call_phrasings():
    count, quotes = count_missed_call_complaints([
        "Called 3 times, no answer, went with someone else",
        "Left two voicemails over a week, never heard back",
        "Nobody answered the phone after hours",
        "Great service, technician was on time",       # not a complaint
    ])
    assert count == 3
    assert len(quotes) == 3
    assert "Called 3 times" in quotes[0]


def test_no_complaints_returns_zero_and_empty_quotes():
    assert count_missed_call_complaints(["Excellent work"]) == (0, [])
```

```python
# backend/tests/integration/test_fetch_reviews.py
from datetime import datetime, timedelta, UTC
from app.clients.protocols import ReviewRecord
from app.clients.fakes import FakeReviewProvider
from app.models.business import Business, BusinessStatus, Segment
from app.models.derived import Score, Review
from app.pipeline.fetch_reviews import FetchReviewsStage


def _recent(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _scored(session, cid: str, fit: int) -> Business:
    b = Business(cid=cid, name=cid, segment=Segment.GROWTH,
                 status=BusinessStatus.SCORED)
    session.add(b); session.flush()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=50, quadrant="nurture",
                      coverage=0.6, reasons=[]))
    session.commit()
    return b


def test_enriches_only_the_top_n_by_fit_score(session):
    for i in range(10):
        _scored(session, f"c{i}", fit=i * 10)

    provider = FakeReviewProvider([ReviewRecord(iso_date=_recent(5),
                                                snippet="nobody answered")])
    FetchReviewsStage(provider, top_n=3).run(session, run_id=None)

    assert len(provider.calls) == 3
    enriched = session.query(Business).filter_by(
        status=BusinessStatus.SITE_SCRAPED).all()
    assert {b.cid for b in enriched} == {"c9", "c8", "c7"}


def test_resets_status_so_signals_and_score_rerun(session):
    """The enrichment loop from ADR-020 — no new machinery, just a status
    reset back to a stage input."""
    b = _scored(session, "c1", fit=90)
    FetchReviewsStage(FakeReviewProvider([]), top_n=1).run(session, run_id=None)
    assert session.query(Business).filter_by(cid="c1").one().status \
        is BusinessStatus.SITE_SCRAPED


def test_does_not_re_enrich_a_business_that_already_has_reviews(session):
    b = _scored(session, "c1", fit=90)
    session.add(Review(business_id=b.id, rating=5, published_at=datetime.now(UTC),
                       text="ok", source="serpapi"))
    session.commit()

    provider = FakeReviewProvider([])
    FetchReviewsStage(provider, top_n=5).run(session, run_id=None)
    assert provider.calls == []


def test_monthly_ceiling_stops_the_stage(session):
    """The free tier resets monthly and does not roll over; exceeding it
    silently degrades later runs to basic tier (ADR-020)."""
    for i in range(5):
        _scored(session, f"c{i}", fit=i * 10)
    provider = FakeReviewProvider([])
    report = FetchReviewsStage(provider, top_n=5,
                               monthly_ceiling=4).run(session, run_id=None)
    assert len(provider.calls) <= 2      # 2 calls/business against a 4 ceiling
    assert report.reason is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_complaints.py tests/integration/test_fetch_reviews.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the complaint matcher**

```python
# backend/app/domain/extractors/complaints.py
import re

PATTERNS = [
    r"\bno\s+answer\b", r"\bnobody\s+answered\b", r"\bno\s+one\s+answered\b",
    r"\bnever\s+(?:called|heard)\s+back\b", r"\bleft\s+(?:a\s+)?(?:two\s+)?voicemails?\b",
    r"\bcalled\s+\w+\s+times\b", r"\bcouldn'?t\s+(?:get|reach)\b",
    r"\bwent\s+to\s+voicemail\b", r"\bdidn'?t\s+(?:answer|call\s+back)\b",
]
_RE = re.compile("|".join(PATTERNS), re.IGNORECASE)


def count_missed_call_complaints(snippets: list[str]) -> tuple[int, list[str]]:
    """Keyword matching, deliberately not an LLM in v1. Precision must be
    measured against real reviews before deciding an LLM pass is warranted
    (spec section 14)."""
    quotes = [s for s in snippets if s and _RE.search(s)]
    return len(quotes), quotes
```

- [ ] **Step 4: Write the stage**

```python
# backend/app/pipeline/fetch_reviews.py
from datetime import datetime
import structlog
from app.clients.protocols import ReviewProvider
from app.clients.serpapi_reviews import collect_recent_reviews
from app.domain.extractors.complaints import count_missed_call_complaints
from app.models.business import Business, BusinessStatus
from app.models.derived import Score, Review, Signals, ApiCall
from app.pipeline.base import StageReport

log = structlog.get_logger()
CALLS_PER_BUSINESS = 2      # page 1 returns 8, page 2 up to 20 (ADR-020)


class FetchReviewsStage:
    name = "fetch_reviews"

    def __init__(self, provider: ReviewProvider, top_n: int = 25,
                 monthly_ceiling: int = 250) -> None:
        self._provider = provider
        self._top_n = top_n
        self._ceiling = monthly_ceiling

    def _spent_this_month(self, session) -> int:
        start = datetime.utcnow().replace(day=1, hour=0, minute=0,
                                          second=0, microsecond=0)
        return (session.query(ApiCall)
                .filter(ApiCall.provider == "serpapi",
                        ApiCall.created_at >= start).count())

    def run(self, session, run_id: int | None) -> StageReport:
        report = StageReport()
        spent = self._spent_this_month(session)

        candidates = (session.query(Business)
                      .join(Score, Score.business_id == Business.id)
                      .outerjoin(Review, Review.business_id == Business.id)
                      .filter(Business.status == BusinessStatus.SCORED,
                              Review.id.is_(None))       # not already enriched
                      .order_by(Score.fit_score.desc())
                      .limit(self._top_n).all())

        for business in candidates:
            if spent + CALLS_PER_BUSINESS > self._ceiling:
                report.reason = (f"SerpApi monthly ceiling reached "
                                 f"({spent}/{self._ceiling})")
                log.warning("fetch_reviews.ceiling_reached", spent=spent)
                break

            reviews = collect_recent_reviews(self._provider, business.cid)
            spent += CALLS_PER_BUSINESS
            session.add(ApiCall(run_id=run_id, provider="serpapi",
                                endpoint="google_maps_reviews",
                                credits=CALLS_PER_BUSINESS, status_code=200))

            for r in reviews:
                session.add(Review(
                    business_id=business.id, rating=r.rating, text=r.snippet,
                    author=r.author,
                    published_at=datetime.fromisoformat(r.iso_date)
                    if r.iso_date else None,
                    source="serpapi"))

            count, quotes = count_missed_call_complaints(
                [r.snippet or "" for r in reviews])
            sig = session.query(Signals).filter_by(
                business_id=business.id).one_or_none()
            if sig is not None:
                sig.missed_call_complaints_90d = count
                sig.complaint_quotes = quotes
                sig.review_velocity_90d = round(len(reviews) / 3, 1)

            # Loop back so extract_signals and score re-run over richer data.
            business.status = BusinessStatus.SITE_SCRAPED
            session.commit()
            report.processed += 1

        return report
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_complaints.py tests/integration/test_fetch_reviews.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/fetch_reviews.py backend/app/domain/extractors/complaints.py backend/tests
git commit -m "feat: add review enrichment stage with monthly budget ceiling"
```

---

### Task 17: CLI, CSV export, and the end-to-end run

**Files:**
- Create: `backend/cli.py`, `backend/app/services/export.py`, `backend/tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: every stage (Tasks 12–16), `build_search_plan` (Task 12), `read_ruleset_file` (Task 14)
- Produces: Typer commands `discover`, `scrape`, `extract`, `score`, `enrich`, `run-all`, `export`; and `export_leads(session, quadrant: str | None, min_fit: int, path: Path) -> int`

- [ ] **Step 1: Write the failing end-to-end test**

```python
# backend/tests/integration/test_end_to_end.py
import csv
from pathlib import Path
from app.clients.fakes import FakeSearchProvider, FakeWebScraper, FakeReviewProvider
from app.clients.protocols import ReviewRecord
from app.models.business import Business, BusinessStatus
from app.models.derived import Score
from app.pipeline.discover import DiscoverStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.score import ScoreStage
from app.services.search_plan import SearchPlan
from app.services.rulesets import read_ruleset_file
from app.services.export import export_leads

PLAN = SearchPlan(vertical="hvac", search_terms=["hvac contractor"],
                  locations=["Houston, TX"], pages_per_query=1)
RULESET = read_ruleset_file(Path("config/rulesets/hvac_v1.yaml"))


def test_full_pipeline_produces_scored_leads_and_a_csv(session, tmp_path):
    DiscoverStage(FakeSearchProvider()).discover(session, None, PLAN)
    ScrapeSiteStage(FakeWebScraper(), per_segment=5).run(session, None)
    ExtractSignalsStage().run(session, None)
    ScoreStage(RULESET).run(session, None)

    scored = session.query(Business).filter_by(status=BusinessStatus.SCORED).all()
    assert len(scored) > 0
    assert session.query(Score).count() == len(scored)

    out = tmp_path / "leads.csv"
    count = export_leads(session, quadrant=None, min_fit=0, path=out)
    assert count == len(scored)

    rows = list(csv.DictReader(out.open()))
    assert {"name", "phone", "website", "segment", "fit_score",
            "pain_score", "quadrant", "coverage", "top_reasons"} <= set(rows[0])
    # Invalid phones must never appear as if they were phone numbers.
    assert all(r["phone"] == "" or r["phone"].startswith("+1") for r in rows)


def test_pipeline_is_idempotent_when_rerun(session):
    for _ in range(2):
        DiscoverStage(FakeSearchProvider()).discover(session, None, PLAN)
        ScrapeSiteStage(FakeWebScraper(), per_segment=5).run(session, None)
        ExtractSignalsStage().run(session, None)
        ScoreStage(RULESET).run(session, None)

    cids = [b.cid for b in session.query(Business).all()]
    assert len(cids) == len(set(cids))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_end_to_end.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.export'`

- [ ] **Step 3: Write the exporter**

```python
# backend/app/services/export.py
import csv
from pathlib import Path
from app.models.business import Business
from app.models.derived import Score


def export_leads(session, quadrant: str | None, min_fit: int,
                 path: Path, ruleset_version: str = "hvac_v1") -> int:
    q = (session.query(Business, Score)
         .join(Score, Score.business_id == Business.id)
         .filter(Score.ruleset_version == ruleset_version,
                 Score.fit_score >= min_fit))
    if quadrant:
        q = q.filter(Score.quadrant == quadrant)
    rows = q.order_by((Score.fit_score * Score.pain_score).desc()).all()

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "name", "phone", "website", "address", "segment", "review_count",
            "fit_score", "pain_score", "quadrant", "coverage", "top_reasons"])
        writer.writeheader()
        for business, score in rows:
            matched = [r["label"] for r in score.reasons if r["matched"]]
            writer.writerow({
                "name": business.name,
                # Never emit an unvalidated phone (ADR-013).
                "phone": business.phone if business.phone_is_valid else "",
                "website": business.website or "",
                "address": business.address or "",
                "segment": str(business.segment) if business.segment else "",
                "review_count": business.review_count or "",
                "fit_score": score.fit_score, "pain_score": score.pain_score,
                "quadrant": score.quadrant, "coverage": score.coverage,
                "top_reasons": " | ".join(matched[:3]),
            })
    return len(rows)
```

- [ ] **Step 4: Add the per-run budget guard**

Spec section 10 requires a cost ceiling checked *between* businesses, because
a single dropdown change can 10x a run's size. The monthly SerpApi ceiling
(Task 16) is a different constraint and does not cover this.

```python
# backend/tests/unit/test_budget.py
import pytest
from app.services.budget import spend_usd, BudgetExceeded, check_budget
from app.models.derived import ApiCall


def test_spend_sums_cost_across_providers(session):
    session.add(ApiCall(provider="serper", endpoint="maps",
                        credits=3, cost_usd=0.003, status_code=200))
    session.add(ApiCall(provider="firecrawl", endpoint="scrape",
                        credits=1, cost_usd=0.002, status_code=200))
    session.commit()
    assert spend_usd(session, run_id=None) == pytest.approx(0.005)


def test_check_budget_raises_once_the_ceiling_is_passed(session):
    session.add(ApiCall(provider="serper", endpoint="maps",
                        credits=1, cost_usd=5.0, status_code=200))
    session.commit()
    with pytest.raises(BudgetExceeded):
        check_budget(session, run_id=None, ceiling_usd=1.0)


def test_no_ceiling_means_no_check(session):
    check_budget(session, run_id=None, ceiling_usd=None)   # must not raise
```

```python
# backend/app/services/budget.py
from sqlalchemy import func
from app.models.derived import ApiCall


class BudgetExceeded(Exception):
    # Raised between businesses so a run stops rather than overspending.
    pass


def spend_usd(session, run_id: int | None) -> float:
    q = session.query(func.coalesce(func.sum(ApiCall.cost_usd), 0.0))
    if run_id is not None:
        q = q.filter(ApiCall.run_id == run_id)
    return float(q.scalar())


def check_budget(session, run_id: int | None,
                 ceiling_usd: float | None) -> None:
    if ceiling_usd is None:
        return
    spent = spend_usd(session, run_id)
    if spent > ceiling_usd:
        raise BudgetExceeded(f"spent ${spent:.2f} of ${ceiling_usd:.2f} ceiling")
```

Run: `cd backend && pytest tests/unit/test_budget.py -v`
Expected: 3 passed

- [ ] **Step 5: Add outcome recording to the CLI**

`outcomes` is the ground truth that makes the rules improvable (ADR-006).
Plan 1 has no dashboard, so it needs a CLI path or the table stays empty and
the feedback loop never starts.

```python
# backend/tests/integration/test_outcomes.py
from app.services.outcomes import record_outcome
from app.models.business import Business, BusinessStatus
from app.models.manual import Outcome


def test_record_outcome_upserts_by_business(session):
    b = Business(cid="c1", name="A", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()

    record_outcome(session, cid="c1", status="contacted", notes="emailed")
    record_outcome(session, cid="c1", status="replied")

    rows = session.query(Outcome).filter_by(business_id=b.id).all()
    assert len(rows) == 1
    assert rows[0].status == "replied"
    assert rows[0].notes == "emailed"      # earlier notes are preserved
```

```python
# backend/app/services/outcomes.py
from datetime import datetime
from app.models.business import Business
from app.models.manual import Outcome

VALID = {"new", "contacted", "replied", "booked", "won", "lost"}


def record_outcome(session, cid: str, status: str,
                   notes: str | None = None) -> None:
    if status not in VALID:
        raise ValueError(f"status must be one of {sorted(VALID)}")
    business = session.query(Business).filter_by(cid=cid).one()
    row = session.query(Outcome).filter_by(business_id=business.id).one_or_none()
    if row is None:
        row = Outcome(business_id=business.id, source="manual")
        session.add(row)
    row.status = status
    if notes:
        row.notes = notes
    if status == "contacted" and row.contacted_at is None:
        row.contacted_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.commit()
```

Run: `cd backend && pytest tests/integration/test_outcomes.py -v`
Expected: 1 passed

- [ ] **Step 6: Write the CLI**

```python
# backend/cli.py
from pathlib import Path
import typer, yaml
from app.core.db import get_session
from app.clients.serper import SerperClient
from app.clients.firecrawl import FirecrawlScraper
from app.clients.serpapi_reviews import SerpApiReviewProvider
from app.core.config import get_settings
from app.pipeline.discover import DiscoverStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.score import ScoreStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.services.search_plan import build_search_plan
from app.services.rulesets import read_ruleset_file
from app.services.export import export_leads
from app.services.outcomes import record_outcome
from app.services.budget import spend_usd

app = typer.Typer()
CONFIG = Path("config")


def _plan(vertical: str, state: str | None, location: str | None, pages: int):
    return build_search_plan(
        vertical, state, location,
        yaml.safe_load((CONFIG / "verticals.yaml").read_text()),
        yaml.safe_load((CONFIG / "locations.yaml").read_text()),
        pages_per_query=pages,
    )


def _ruleset(vertical: str):
    cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    return read_ruleset_file(CONFIG / "rulesets" / f"{cfg[vertical]['ruleset']}.yaml")


@app.command()
def discover(vertical: str, state: str = None, location: str = None,
             pages: int = 5) -> None:
    with get_session() as s:
        report = DiscoverStage(SerperClient()).discover(
            s, None, _plan(vertical, state, location, pages))
        typer.echo(f"discovered: {report.processed}")


@app.command()
def scrape(per_segment: int = None) -> None:
    n = per_segment or get_settings().stratified_per_segment
    with get_session() as s:
        typer.echo(ScrapeSiteStage(FirecrawlScraper(), per_segment=n)
                   .run(s, None))


@app.command()
def extract() -> None:
    with get_session() as s:
        typer.echo(ExtractSignalsStage().run(s, None))


@app.command()
def score(vertical: str = "hvac") -> None:
    with get_session() as s:
        typer.echo(ScoreStage(_ruleset(vertical)).run(s, None))


@app.command()
def enrich(top_n: int = None) -> None:
    settings = get_settings()
    with get_session() as s:
        typer.echo(FetchReviewsStage(
            SerpApiReviewProvider(), top_n=top_n or settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling).run(s, None))


@app.command("run-all")
def run_all(vertical: str, state: str = None, location: str = None,
            pages: int = 5) -> None:
    """Discover -> scrape -> extract -> score -> enrich -> extract -> score."""
    discover(vertical, state, location, pages)
    scrape()
    extract()
    score(vertical)
    enrich()
    extract()      # the ADR-020 loop: re-derive over the richer data
    score(vertical)


@app.command("export")
def export_cmd(out: Path = Path("leads.csv"), quadrant: str = None,
               min_fit: int = 0) -> None:
    with get_session() as s:
        typer.echo(f"exported {export_leads(s, quadrant, min_fit, out)} -> {out}")


@app.command()
def outcome(cid: str, status: str, notes: str = None) -> None:
    # Record what happened: new|contacted|replied|booked|won|lost
    with get_session() as s:
        record_outcome(s, cid, status, notes)
        typer.echo(f"{cid} -> {status}")


@app.command()
def spend(run_id: int = None) -> None:
    with get_session() as s:
        typer.echo(f"${spend_usd(s, run_id):.2f}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_end_to_end.py -v`
Expected: 2 passed

- [ ] **Step 8: Run the full suite and all quality gates**

Run: `cd backend && pytest -v && lint-imports && mypy app && ruff check app`
Expected: all pass, `Contracts: 1 kept, 0 broken`

- [ ] **Step 9: Real smoke run against live APIs**

```bash
cd backend
python -m cli discover hvac --location "Houston, TX" --pages 1
python -m cli scrape --per-segment 2
python -m cli extract && python -m cli score
python -m cli export --out leads.csv
head -5 leads.csv
```

Expected: a CSV with real Houston HVAC businesses, ranked, with populated
`fit_score`, `pain_score`, `quadrant`, `coverage`, and `top_reasons`.

**Sanity-check three things before declaring success:** every `phone` is
either empty or `+1`-prefixed; `segment` is populated across more than one
band; and `coverage` is below 1.0 for un-enriched leads.

- [ ] **Step 10: Commit**

```bash
git add backend/cli.py backend/app/services backend/tests
git commit -m "feat: add CLI, CSV export, budget guard, and outcome recording"
```

---

## Definition of Done

- [ ] `pytest` green; `lint-imports` reports `1 kept, 0 broken`; `mypy app` clean
- [ ] `python -m cli run-all hvac --location "Houston, TX"` completes end to end
- [ ] `leads.csv` contains ranked real businesses with evidence in `top_reasons`
- [ ] No invalid phone number appears in the `phone` column
- [ ] `api_calls` records Serper's self-reported `credits`
- [ ] `python -m cli outcome <cid> contacted` writes to `outcomes`
- [ ] `python -m cli spend` reports run cost from `api_calls`
- [ ] Every task committed separately

## Deliberately Out of Scope

FastAPI, APScheduler, the Next.js dashboard, Docker deployment, contact
resolvers, and email sending. These belong to Plan 2 — see spec §13 for the
seams already in place.
