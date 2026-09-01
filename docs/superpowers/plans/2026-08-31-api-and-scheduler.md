# API and Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a FastAPI service and an in-process scheduler in front of the existing pipeline, so runs can be created, executed, and browsed over HTTP instead of only from the CLI.

**Architecture:** A thin HTTP layer over code that already works. Routers depend on Pydantic schemas and a new read-only `repositories/` layer; the run orchestration currently living inside `cli.py`'s `run_all` is extracted into `services/run_executor.py` so the CLI, the API, and APScheduler all drive the *same* code path. APScheduler runs in the FastAPI process and polls for `queued` runs — no Redis, no Celery, no separate worker.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, APScheduler 3.x, SQLAlchemy 2.x, pytest + `fastapi.testclient`, uvicorn, Docker.

**Spec:** `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md` (§8 Backend architecture, §9 Auth, §10 Error handling and operations, §12 Deployment)

**Predecessor:** Plan 1 (`docs/superpowers/plans/2026-08-29-lead-pipeline-core.md`) is complete and merged to `main`. Its five pipeline stages, rules engine, provider clients, and CLI all exist and are tested. **This plan adds to that code; it does not rewrite it.**

**Successor:** Plan 3 (the Next.js dashboard) consumes the API this plan builds. Nothing in this plan depends on Plan 3.

---

## Global Constraints

- **Python 3.12.** All code type-annotated. `mypy app` and `mypy cli.py` must stay clean — the project currently reports zero errors and that is a hard gate.
- **`app/domain/` must import nothing framework-related.** No `fastapi`, `sqlalchemy`, `httpx`, `firecrawl`, `serpapi`, `yaml`, `app.models`, `app.clients`, `app.repositories`. Enforced by `import-linter`. This is ADR-002 and is not negotiable.
- **`app/repositories/` is read-only.** It contains queries the API needs. It never writes, and the pipeline never calls it (ADR-024, written in Task 3).
- **Alembic owns all DDL.** This plan adds **no migration and no new columns.** If a task appears to need one, stop and report — every column it needs already exists.
- **FastAPI owns all database access.** Next.js never touches Postgres (ADR-009).
- **Every API call logs actual cost** to `api_calls`. This plan adds no new paid calls, but must not break the existing accounting.
- **`ratingCount` is a segment label only** — never a filter, never a scored signal (ADR-022). A `?sort=review_count` query parameter would violate this. Do not add one.
- **No duplicated orchestration.** After Task 5 there is exactly one implementation of the run sequence. If you find yourself copying the stage list, you are doing it wrong.
- **The pipeline's existing 181 tests must keep passing at every commit.**
- **Commit after every task.** Conventional commit messages (`feat:`, `test:`, `chore:`, `refactor:`).

---

## File Structure

**Created by this plan:**

```
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py               FastAPI factory, lifespan, /health, error handlers
│   │   ├── deps.py              get_db, require_api_key
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── runs.py          POST/GET /runs, POST /runs/preview
│   │       ├── leads.py         GET /leads, GET /leads/{cid}, GET /leads/export.csv
│   │       └── meta.py          GET /rulesets, GET /verticals, PUT outcome/manual-facts
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py            Page[T]
│   │   ├── runs.py              RunCreate, RunOut, PreviewOut
│   │   ├── leads.py             LeadOut, LeadDetailOut, ScoreOut, ReasonOut
│   │   └── manual.py            OutcomeIn, ManualFactsIn
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── leads.py             list_leads, get_lead_detail
│   │   └── runs.py              list_runs, get_run
│   ├── services/
│   │   ├── run_executor.py      execute_run  (extracted from cli.py)
│   │   └── preview.py           preview_search_plan
│   └── scheduler.py             four APScheduler jobs
├── tests/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── conftest.py          client fixture with DB + auth override
│   │   ├── test_health_and_auth.py
│   │   ├── test_runs_api.py
│   │   ├── test_leads_api.py
│   │   └── test_meta_api.py
│   └── unit/
│       ├── test_run_executor.py
│       ├── test_preview.py
│       └── test_scheduler_jobs.py
└── Dockerfile
```

**Modified by this plan:** `app/core/config.py` (one field), `cli.py` (`run_all` delegates), `.importlinter` (one new contract), `pyproject.toml` (dependencies), `docker-compose.yml` (api service), `docs/decisions/DECISIONS.md` (ADR-024, ADR-025).

---

## Interfaces this plan consumes from Plan 1

Every implementer needs these. They exist today and must not be changed.

```python
# app/core/db.py
@contextmanager
def get_session() -> Iterator[Session]: ...
SessionLocal = sessionmaker(bind=_engine)

# app/core/config.py
class Settings(BaseSettings):
    database_url: str
    serper_key: str
    firecrawl_key: str
    serpapi_key: str | None = None
    sentry_dsn: str | None = None
    enrichment_top_n: int = 25
    stratified_per_segment: int = 15
    serpapi_monthly_ceiling: int = 250
@lru_cache
def get_settings() -> Settings: ...

# app/services/search_plan.py
@dataclass(frozen=True)
class SearchPlan:
    vertical: str
    search_terms: list[str]
    locations: list[str]
    pages_per_query: int = 5
    @property
    def queries(self) -> list[str]: ...
def build_search_plan(vertical: str, state: str | None, location: str | None,
                      verticals_cfg: dict, locations_cfg: dict,
                      pages_per_query: int = 5) -> SearchPlan: ...

# app/services/budget.py
PROVIDER_PRICE_PER_CREDIT: dict[str, float]   # serper .001, firecrawl .002, serpapi 0.0
def spend_usd(session: Session, run_id: int | None) -> float: ...
def check_budget(session: Session, run_id: int | None, ceiling_usd: float | None) -> None: ...
class BudgetExceeded(Exception): ...

# app/services/export.py
def export_leads(session: Session, quadrant: str | None, min_fit: int,
                 path: Path, ruleset_version: str = "hvac_v1") -> int: ...

# app/services/outcomes.py
VALID = {"new", "contacted", "replied", "booked", "won", "lost"}
def record_outcome(session: Session, cid: str, status: str, ...) -> None: ...

# app/services/rulesets.py
def read_ruleset_definition(path: Path) -> dict[str, Any]: ...
def read_ruleset_file(path: Path) -> Ruleset: ...

# app/pipeline/*  — stage constructors
DiscoverStage(provider).discover(session, run_id, plan) -> StageReport
ScrapeSiteStage(scraper, per_segment=15).run(session, run_id, limit=500, budget_check=None)
ExtractSignalsStage().run(session, run_id, limit=500)
ScoreStage(ruleset).run(session, run_id, limit=500, budget_check=None)
FetchReviewsStage(provider, top_n=25, monthly_ceiling=250).run(session, run_id)

@dataclass
class StageReport:
    processed: int = 0
    failed: int = 0
    aborted: bool = False
    reason: str | None = None

# Models (app/models/) — all columns already exist
Run(id, status, source, search_plan, stats, max_cost_usd, estimated_cost,
    actual_cost, created_at, started_at, finished_at, error)
Business(id, cid, name, address, city, state, phone, phone_is_valid, website,
         rating, review_count, segment, vertical, status, ...)
Score(id, business_id, ruleset_version, fit_score, pain_score, quadrant,
      coverage, reasons, scored_at)   UNIQUE(business_id, ruleset_version)
Signals(business_id PK, has_booking_link, booking_vendor, is_phone_only, is_24_7,
        closes_before_6pm, closed_weekends, hours_parse_failed, segment,
        has_chat_widget, chat_vendor, has_contact_form, software_from_html,
        runs_google_ads, missed_call_complaints_90d, review_velocity_90d, ...)
Review(id, business_id, author, rating, text, published_at, source)
ApiCall(id, run_id, business_id, provider, endpoint, credits, cost_usd, ...)
```

`Run.status` is one of `queued | running | complete | failed`. `Run.source` is `ui | cli`.

---

## Task 1: FastAPI app, health check, and API-key auth

**Files:**
- Create: `backend/app/api/__init__.py`, `backend/app/api/app.py`, `backend/app/api/deps.py`, `backend/app/api/routers/__init__.py`
- Create: `backend/tests/api/__init__.py`, `backend/tests/api/conftest.py`, `backend/tests/api/test_health_and_auth.py`
- Modify: `backend/app/core/config.py`, `backend/pyproject.toml`

**Interfaces:**
- Consumes: `get_settings()`, `SessionLocal` from Plan 1
- Produces: `create_app() -> FastAPI`; `get_db() -> Iterator[Session]` (FastAPI dependency); `require_api_key(x_api_key: str | None = Header(None)) -> None`; `Settings.api_key: str | None`

- [ ] **Step 1: Add the dependencies**

Edit `backend/pyproject.toml`. Add to `dependencies`:

```toml
  "fastapi>=0.115", "uvicorn[standard]>=0.30", "apscheduler>=3.10",
```

Add to `[project.optional-dependencies]` `dev`:

```toml
  "types-pyyaml",
```

Then install:

```bash
cd backend && pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/api/conftest.py
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.deps import get_db

API_KEY = "test-key-do-not-use-in-prod"


@pytest.fixture
def client(session, monkeypatch):
    """A TestClient wired to the rolled-back test session.

    `get_db` is overridden rather than patched so every router shares the
    one transaction the `session` fixture rolls back after each test.
    """
    monkeypatch.setenv("API_KEY", API_KEY)
    from app.core.config import get_settings
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": API_KEY})
        yield c
    get_settings.cache_clear()


@pytest.fixture
def anon_client(client):
    """Same app, no API key header."""
    client.headers.pop("X-API-Key", None)
    return client
```

```python
# backend/tests/api/test_health_and_auth.py
def test_health_needs_no_api_key(anon_client):
    r = anon_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_a_protected_route_rejects_a_missing_key(anon_client):
    r = anon_client.get("/runs")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid or missing API key"


def test_a_protected_route_rejects_a_wrong_key(client):
    client.headers.update({"X-API-Key": "wrong"})
    assert client.get("/runs").status_code == 401


def test_a_protected_route_accepts_the_right_key(client):
    assert client.get("/runs").status_code == 200
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd backend && pytest tests/api/test_health_and_auth.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 4: Add the `api_key` setting**

Edit `backend/app/core/config.py`. Add one field to `Settings`, after `sentry_dsn`:

```python
    # Shared secret the Next.js server presents as X-API-Key. Optional so the
    # CLI and the test suite keep working without it; when unset, every
    # protected route returns 401 rather than silently allowing access.
    api_key: str | None = None
```

Also add `API_KEY=` to `backend/.env.example`, below `SERPAPI_KEY=`.

- [ ] **Step 5: Write the dependencies**

```python
# backend/app/api/deps.py
import secrets
from typing import Iterator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal


def get_db() -> Iterator[Session]:
    """One session per request, always closed.

    Overridden in tests so every router shares the rolled-back fixture
    session.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """Single-user auth (spec section 9): Next.js holds the key server-side.

    `compare_digest` rather than `==` so the check is not timing-variable.
    A missing configured key fails closed -- an unset API_KEY must not mean
    "no auth required".
    """
    configured = get_settings().api_key
    if not configured or not x_api_key or not secrets.compare_digest(
            x_api_key, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid or missing API key")
```

- [ ] **Step 6: Write the app factory**

```python
# backend/app/api/app.py
import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.requests import Request

from app.api.deps import require_api_key

log = structlog.get_logger()


def create_app() -> FastAPI:
    """Build the FastAPI app.

    A factory rather than a module-level singleton so tests can construct a
    fresh app with its own dependency overrides.
    """
    app = FastAPI(title="Lead Generation API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Unauthenticated on purpose: the container healthcheck calls it."""
        return {"status": "ok"}

    @app.exception_handler(ValueError)
    def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """A bad vertical or state reaches the router as ValueError from
        build_search_plan. That is a client mistake, not a 500."""
        log.warning("api.bad_request", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    from app.api.routers import leads, meta, runs
    for router in (runs.router, leads.router, meta.router):
        app.include_router(router, dependencies=[Depends(require_api_key)])

    return app


app = create_app()
```

- [ ] **Step 7: Create the router package with empty routers**

Tasks 7–9 fill these in. They must exist now so `create_app` imports cleanly.

```python
# backend/app/api/routers/__init__.py
```

```python
# backend/app/api/routers/runs.py
from fastapi import APIRouter

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def list_runs_endpoint() -> list[dict]:
    return []
```

```python
# backend/app/api/routers/leads.py
from fastapi import APIRouter

router = APIRouter(prefix="/leads", tags=["leads"])
```

```python
# backend/app/api/routers/meta.py
from fastapi import APIRouter

router = APIRouter(tags=["meta"])
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
cd backend && pytest tests/api/ -v
```

Expected: 4 passed

- [ ] **Step 9: Verify nothing else broke**

```bash
cd backend && pytest -q && mypy app && lint-imports
```

Expected: 185 passed, mypy clean, `Contracts: 1 kept, 0 broken`

- [ ] **Step 10: Commit**

```bash
git add backend/app/api backend/app/core/config.py backend/.env.example \
        backend/tests/api backend/pyproject.toml
git commit -m "feat: add FastAPI app factory, health check, and API-key auth"
```

---

## Task 2: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/__init__.py`, `backend/app/schemas/common.py`, `backend/app/schemas/runs.py`, `backend/app/schemas/leads.py`, `backend/app/schemas/manual.py`
- Test: `backend/tests/unit/test_schemas.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — these are pure DTOs
- Produces: `Page[T]`, `RunCreate`, `RunOut`, `PreviewOut`, `LeadOut`, `LeadDetailOut`, `ScoreOut`, `ReasonOut`, `OutcomeIn`, `ManualFactsIn`

These are Data Transfer Objects (spec §8, PoEAA table). They exist so the API's shape is decoupled from the ORM: a column rename must not silently change the JSON contract Plan 3 depends on.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas.common import Page
from app.schemas.leads import LeadOut
from app.schemas.manual import OutcomeIn
from app.schemas.runs import RunCreate


def test_run_create_requires_one_of_state_or_location():
    with pytest.raises(ValidationError, match="state or location"):
        RunCreate(vertical="hvac")


def test_run_create_accepts_a_location_alone():
    r = RunCreate(vertical="hvac", location="Houston, TX")
    assert r.pages == 5 and r.max_cost_usd is None


def test_run_create_rejects_a_non_positive_page_count():
    with pytest.raises(ValidationError):
        RunCreate(vertical="hvac", location="Houston, TX", pages=0)


def test_outcome_in_rejects_an_unknown_status():
    with pytest.raises(ValidationError):
        OutcomeIn(status="definitely_not_a_status")


def test_outcome_in_accepts_every_valid_status():
    from app.services.outcomes import VALID
    for s in VALID:
        assert OutcomeIn(status=s).status == s


def test_page_reports_whether_more_rows_exist():
    p = Page[LeadOut](items=[], total=25, page=1, page_size=10)
    assert p.pages == 3 and p.has_next is True

    last = Page[LeadOut](items=[], total=25, page=3, page_size=10)
    assert last.has_next is False


def test_page_of_zero_rows_has_one_page_not_zero():
    """A UI that renders `page 1 of 0` looks broken."""
    p = Page[LeadOut](items=[], total=0, page=1, page_size=10)
    assert p.pages == 1 and p.has_next is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_schemas.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas'`

- [ ] **Step 3: Write the common page envelope**

```python
# backend/app/schemas/common.py
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envelope for every list endpoint.

    `pages` is at least 1 so a UI never renders "page 1 of 0" on an empty
    result set.
    """
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))   # ceil division

    @property
    def has_next(self) -> bool:
        return self.page < self.pages
```

- [ ] **Step 4: Write the run schemas**

```python
# backend/app/schemas/runs.py
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunCreate(BaseModel):
    """What the UI posts to start a run.

    Mirrors `build_search_plan`'s arguments, which raises ValueError when
    neither state nor location is given -- caught here instead so the
    client gets a 422 naming the field rather than a 400 from deeper in.
    """
    vertical: str
    state: str | None = None
    location: str | None = None
    pages: int = Field(default=5, ge=1, le=20)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def one_of_state_or_location(self) -> Self:
        if not self.state and not self.location:
            raise ValueError("one of state or location is required")
        return self


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    source: str
    search_plan: dict[str, Any]
    stats: dict[str, Any] | None
    max_cost_usd: float | None
    estimated_cost: float | None
    actual_cost: float | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class PreviewOut(BaseModel):
    """The confirm screen (spec section 9, screen 1). Nothing is spent until
    the user posts the run itself."""
    vertical: str
    queries: list[str]
    search_count: int
    estimated_results: int
    estimated_cost_usd: float
    recently_run_queries: list[str]
```

- [ ] **Step 5: Write the lead schemas**

```python
# backend/app/schemas/leads.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReasonOut(BaseModel):
    """One rule's contribution, straight from Score.reasons."""
    id: str
    label: str
    track: str
    points: int
    matched: bool
    applicable: bool


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ruleset_version: str
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    scored_at: datetime


class LeadOut(BaseModel):
    """One row in the leads table. Deliberately flat -- the table renders it
    directly."""
    model_config = ConfigDict(from_attributes=True)

    cid: str
    name: str
    city: str | None
    state: str | None
    website: str | None
    phone: str | None          # blank unless phone_is_valid (ADR-013)
    segment: str | None
    review_count: int | None
    fit_score: int
    pain_score: int
    quadrant: str
    coverage: float
    outcome_status: str | None


class EvidenceOut(BaseModel):
    """A verbatim review quote, for outreach copy (spec section 9)."""
    text: str
    rating: int | None
    published_at: datetime | None


class LeadDetailOut(BaseModel):
    lead: LeadOut
    score: ScoreOut | None
    reasons: list[ReasonOut]
    signals: dict[str, object]
    evidence: list[EvidenceOut]
```

- [ ] **Step 6: Write the manual-input schemas**

```python
# backend/app/schemas/manual.py
from pydantic import BaseModel, Field, field_validator

from app.services.outcomes import VALID


class OutcomeIn(BaseModel):
    # `notes`, not `note`: passed straight through to
    # record_outcome(session, cid, status, notes=...).
    status: str
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def known_status(cls, v: str) -> str:
        if v not in VALID:
            raise ValueError(f"status must be one of {sorted(VALID)}")
        return v


class ManualFactsIn(BaseModel):
    """Fields a human fills in by hand (ADR-008). All optional: the form
    saves whatever the user knows so far.

    Every field here is a real `manual_facts` column -- verified against
    `app/models/manual.py`. Do NOT add a field the table lacks; this plan
    creates no migrations.
    """
    estimated_employees: int | None = Field(default=None, ge=0, le=100000)
    technician_count: int | None = Field(default=None, ge=0, le=10000)
    has_office_admin: bool | None = None
    owner_growth_focused: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
```

Create an empty `backend/app/schemas/__init__.py`.

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_schemas.py -v
```

Expected: 7 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas backend/tests/unit/test_schemas.py
git commit -m "feat: add Pydantic DTOs for runs, leads, and manual input"
```

---

## Task 3: The leads repository

**Files:**
- Create: `backend/app/repositories/__init__.py`, `backend/app/repositories/leads.py`
- Test: `backend/tests/unit/test_leads_repository.py`
- Modify: `backend/.importlinter`, `docs/decisions/DECISIONS.md`

**Interfaces:**
- Consumes: `Business`, `Score`, `Signals`, `Review`, `Outcome` models; `LeadOut`, `LeadDetailOut`, `ReasonOut`, `ScoreOut`, `EvidenceOut` from Task 2
- Produces:
  ```python
  @dataclass(frozen=True)
  class LeadFilters:
      quadrant: str | None = None
      vertical: str | None = None
      state: str | None = None
      min_fit: int = 0
      min_pain: int = 0
      outcome_status: str | None = None
      ruleset_version: str = "hvac_v1"

  def list_leads(session: Session, filters: LeadFilters,
                 page: int = 1, page_size: int = 50) -> tuple[list[LeadOut], int]
  def get_lead_detail(session: Session, cid: str,
                      ruleset_version: str = "hvac_v1") -> LeadDetailOut | None
  ```

- [ ] **Step 1: Record the architectural decision**

Append to `docs/decisions/DECISIONS.md`:

```markdown
## ADR-024 — A read-only `repositories/` layer, for the API only

**Context.** The spec's dependency rule is `api -> services -> repositories
-> database`, but Plan 1 built no repositories: each pipeline stage queries
the session directly. Adding the layer now meant either refactoring five
reviewed, working stages or leaving the codebase with two data-access styles.

**Decision.** Introduce `app/repositories/` for the API's **read** paths
only — filtered, paginated queries the UI needs. The pipeline's
stage-scoped writes stay exactly as they are. `repositories/` never writes,
and `app/pipeline/` never imports it.

**Why.** The two have genuinely different shapes. A stage reads "every row
in status X" and writes it forward; the API reads "page 3 of go_now leads in
Texas, sorted by fit x pain". Forcing both through one abstraction would
serve neither. The alternative — refactoring the pipeline — would rewrite
the data access of code that had just passed review, with 181 tests to
rework, for no behavioural gain.

**Consequences.** Two data-access styles coexist, which is a real cost and
is why this ADR exists rather than a silent convention. An `import-linter`
contract enforces the split so it cannot erode. If the pipeline ever needs a
filtered read, that is the signal to revisit.
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_leads_repository.py
from datetime import datetime

from app.models.business import Business, BusinessStatus
from app.models.derived import Review, Score, Signals
from app.repositories.leads import LeadFilters, get_lead_detail, list_leads


def _business(session, cid, name, *, state="TX", fit=80, pain=70,
              quadrant="go_now", phone_valid=True, vertical="hvac"):
    b = Business(cid=cid, name=name, state=state, city="Houston",
                 phone="+17135551234", phone_is_valid=phone_valid,
                 website=f"https://{cid}.example.com", review_count=300,
                 vertical=vertical, status=BusinessStatus.SCORED)
    session.add(b)
    session.flush()
    session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                      fit_score=fit, pain_score=pain, quadrant=quadrant,
                      coverage=0.8, reasons=[
                          {"id": "uses_fsm", "label": "Uses field service software",
                           "track": "fit", "points": 30, "matched": True,
                           "applicable": True}]))
    session.commit()
    return b


def test_list_leads_returns_only_the_requested_quadrant(session):
    _business(session, "c1", "Go Now Air", quadrant="go_now")
    _business(session, "c2", "Cold Air", quadrant="cold", fit=10, pain=10)

    rows, total = list_leads(session, LeadFilters(quadrant="go_now"))

    assert total == 1
    assert [r.name for r in rows] == ["Go Now Air"]


def test_list_leads_orders_by_fit_times_pain_descending(session):
    _business(session, "c1", "Low", fit=50, pain=50)     # 2500
    _business(session, "c2", "High", fit=90, pain=90)    # 8100
    _business(session, "c3", "Mid", fit=70, pain=70)     # 4900

    rows, _ = list_leads(session, LeadFilters())

    assert [r.name for r in rows] == ["High", "Mid", "Low"]


def test_list_leads_never_emits_an_unvalidated_phone(session):
    """ADR-013: Serper's phoneNumber is unreliable, so an unvalidated number
    must not reach the UI where someone would dial it."""
    _business(session, "c1", "Bad Phone", phone_valid=False)

    rows, _ = list_leads(session, LeadFilters())

    assert rows[0].phone is None


def test_list_leads_paginates_without_losing_rows(session):
    for i in range(7):
        _business(session, f"c{i}", f"Air {i}", fit=50 + i, pain=50)

    p1, total = list_leads(session, LeadFilters(), page=1, page_size=3)
    p2, _ = list_leads(session, LeadFilters(), page=2, page_size=3)
    p3, _ = list_leads(session, LeadFilters(), page=3, page_size=3)

    assert total == 7
    assert [len(p1), len(p2), len(p3)] == [3, 3, 1]
    names = {r.name for r in p1 + p2 + p3}
    assert len(names) == 7           # no row appears twice or goes missing


def test_list_leads_filters_by_ruleset_version(session):
    """Scores are keyed (business_id, ruleset_version). Without this filter a
    business scored under two versions would appear twice (ADR-005)."""
    b = _business(session, "c1", "Two Versions")
    session.add(Score(business_id=b.id, ruleset_version="hvac_v2",
                      fit_score=10, pain_score=10, quadrant="cold",
                      coverage=0.5, reasons=[]))
    session.commit()

    rows, total = list_leads(session, LeadFilters(ruleset_version="hvac_v1"))

    assert total == 1
    assert rows[0].fit_score == 80


def test_list_leads_applies_min_fit_and_min_pain_together(session):
    _business(session, "c1", "Both High", fit=90, pain=90)
    _business(session, "c2", "Fit Only", fit=90, pain=10)
    _business(session, "c3", "Pain Only", fit=10, pain=90)

    rows, total = list_leads(session, LeadFilters(min_fit=60, min_pain=60))

    assert total == 1 and rows[0].name == "Both High"


def test_get_lead_detail_returns_reasons_signals_and_evidence(session):
    b = _business(session, "c1", "Detailed Air")
    session.add(Signals(business_id=b.id, closes_before_6pm=True,
                        has_chat_widget=False))
    session.add(Review(business_id=b.id, rating=1, text="nobody ever answers",
                       published_at=datetime(2026, 8, 1), source="serpapi"))
    session.commit()

    detail = get_lead_detail(session, "c1")

    assert detail is not None
    assert detail.lead.name == "Detailed Air"
    assert detail.score is not None and detail.score.fit_score == 80
    assert [r.id for r in detail.reasons] == ["uses_fsm"]
    assert detail.signals["closes_before_6pm"] is True
    assert detail.signals["has_chat_widget"] is False
    assert [e.text for e in detail.evidence] == ["nobody ever answers"]


def test_get_lead_detail_returns_none_for_an_unknown_cid(session):
    assert get_lead_detail(session, "no-such-cid") is None


def test_get_lead_detail_works_for_a_business_with_no_score_yet(session):
    """A business mid-pipeline has no Score row. The detail screen must still
    render rather than 500."""
    session.add(Business(cid="c9", name="Unscored", status=BusinessStatus.DISCOVERED))
    session.commit()

    detail = get_lead_detail(session, "c9")

    assert detail is not None and detail.score is None and detail.reasons == []
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_leads_repository.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.repositories'`

- [ ] **Step 4: Write the repository**

```python
# backend/app/repositories/leads.py
"""Read-only queries for the API (ADR-024). Never writes."""
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.derived import Review, Score, Signals
from app.models.manual import Outcome
from app.schemas.leads import (EvidenceOut, LeadDetailOut, LeadOut, ReasonOut,
                               ScoreOut)

DEFAULT_RULESET = "hvac_v1"

# Signals columns that are bookkeeping, not signals the UI should render.
_NON_SIGNAL_COLUMNS = {"business_id", "extracted_at", "extractor_version"}


@dataclass(frozen=True)
class LeadFilters:
    quadrant: str | None = None
    vertical: str | None = None
    state: str | None = None
    min_fit: int = 0
    min_pain: int = 0
    outcome_status: str | None = None
    ruleset_version: str = DEFAULT_RULESET


def _row_to_lead(business: Business, score: Score,
                 outcome_status: str | None) -> LeadOut:
    return LeadOut(
        cid=business.cid,
        name=business.name,
        city=business.city,
        state=business.state,
        website=business.website,
        # ADR-013: an unvalidated Serper phone number must never reach a
        # human who might dial it.
        phone=business.phone if business.phone_is_valid else None,
        segment=str(business.segment) if business.segment else None,
        review_count=business.review_count,
        fit_score=score.fit_score,
        pain_score=score.pain_score,
        quadrant=score.quadrant,
        coverage=score.coverage,
        outcome_status=outcome_status,
    )


def _filtered(session: Session, filters: LeadFilters):
    q = (session.query(Business, Score, Outcome.status)
         .join(Score, Score.business_id == Business.id)
         .outerjoin(Outcome, Outcome.business_id == Business.id)
         .filter(Score.ruleset_version == filters.ruleset_version,
                 Score.fit_score >= filters.min_fit,
                 Score.pain_score >= filters.min_pain))
    if filters.quadrant:
        q = q.filter(Score.quadrant == filters.quadrant)
    if filters.vertical:
        q = q.filter(Business.vertical == filters.vertical)
    if filters.state:
        q = q.filter(Business.state == filters.state)
    if filters.outcome_status:
        q = q.filter(Outcome.status == filters.outcome_status)
    return q


def list_leads(session: Session, filters: LeadFilters, page: int = 1,
               page_size: int = 50) -> tuple[list[LeadOut], int]:
    """One page of leads plus the unpaginated total.

    Ordered by fit x pain descending: the spec's primary sort, and the only
    ordering that respects both tracks without blending them into one stored
    number (ADR-004). NOT ordered by review_count -- ADR-022 forbids
    ratingCount acting as anything but a label.
    """
    q = _filtered(session, filters)
    total = q.with_entities(func.count()).order_by(None).scalar() or 0
    rows = (q.order_by((Score.fit_score * Score.pain_score).desc(),
                       Business.id)
             .offset((page - 1) * page_size)
             .limit(page_size)
             .all())
    return [_row_to_lead(b, s, o) for b, s, o in rows], total


def get_lead_detail(session: Session, cid: str,
                    ruleset_version: str = DEFAULT_RULESET
                    ) -> LeadDetailOut | None:
    """Everything the lead detail screen shows, or None if the cid is unknown.

    A business with no Score yet (still mid-pipeline) returns a detail with
    `score=None` rather than 404 -- it exists, it just is not scored.
    """
    business = session.query(Business).filter_by(cid=cid).one_or_none()
    if business is None:
        return None

    score = (session.query(Score)
             .filter_by(business_id=business.id,
                        ruleset_version=ruleset_version)
             .one_or_none())
    outcome = (session.query(Outcome)
               .filter_by(business_id=business.id).one_or_none())

    if score is not None:
        lead = _row_to_lead(business, score, outcome.status if outcome else None)
        reasons = [ReasonOut(**r) for r in (score.reasons or [])]
        score_out: ScoreOut | None = ScoreOut.model_validate(score)
    else:
        lead = LeadOut(
            cid=business.cid, name=business.name, city=business.city,
            state=business.state, website=business.website,
            phone=business.phone if business.phone_is_valid else None,
            segment=str(business.segment) if business.segment else None,
            review_count=business.review_count,
            fit_score=0, pain_score=0, quadrant="cold", coverage=0.0,
            outcome_status=outcome.status if outcome else None)
        reasons = []
        score_out = None

    sig = session.query(Signals).filter_by(business_id=business.id).one_or_none()
    signals: dict[str, object] = {}
    if sig is not None:
        signals = {c.name: getattr(sig, c.name)
                   for c in sig.__table__.columns
                   if c.name not in _NON_SIGNAL_COLUMNS}

    evidence = [
        EvidenceOut(text=r.text or "", rating=r.rating,
                    published_at=r.published_at)
        for r in (session.query(Review)
                  .filter_by(business_id=business.id)
                  .order_by(Review.published_at.desc().nullslast())
                  .limit(10).all())
        if r.text
    ]

    return LeadDetailOut(lead=lead, score=score_out, reasons=reasons,
                         signals=signals, evidence=evidence)
```

Create an empty `backend/app/repositories/__init__.py`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_leads_repository.py -v
```

Expected: 9 passed

- [ ] **Step 6: Add the import-linter contract**

Append to `backend/.importlinter`:

```ini
[importlinter:contract:repositories-are-api-only]
name = The pipeline never reads through repositories (ADR-024)
type = forbidden
source_modules =
    app.pipeline
    app.domain
forbidden_modules =
    app.repositories
```

- [ ] **Step 7: Verify everything**

```bash
cd backend && pytest -q && mypy app && lint-imports
```

Expected: 194 passed, mypy clean, `Contracts: 2 kept, 0 broken`

- [ ] **Step 8: Commit**

```bash
git add backend/app/repositories backend/tests/unit/test_leads_repository.py \
        backend/.importlinter docs/decisions/DECISIONS.md
git commit -m "feat: add read-only leads repository with ADR-024 layering contract"
```

---

## Task 4: The runs repository

**Files:**
- Create: `backend/app/repositories/runs.py`
- Test: `backend/tests/unit/test_runs_repository.py`

**Interfaces:**
- Consumes: `Run` model, `RunOut` from Task 2
- Produces:
  ```python
  def list_runs(session: Session, status: str | None = None,
                page: int = 1, page_size: int = 50) -> tuple[list[RunOut], int]
  def get_run(session: Session, run_id: int) -> RunOut | None
  def claim_next_queued_run(session: Session) -> int | None
  ```

`claim_next_queued_run` is what the scheduler polls with in Task 10. It lives here because it is a query, and it is the one write-adjacent function in the repositories layer — it flips exactly one row's status under a lock so two pollers cannot claim the same run.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_runs_repository.py
from datetime import datetime

from app.models.run import Run
from app.repositories.runs import claim_next_queued_run, get_run, list_runs


def _run(session, status="queued", source="ui", created=None):
    r = Run(status=status, source=source,
            search_plan={"vertical": "hvac", "location": "Houston, TX"},
            created_at=created or datetime(2026, 8, 31, 12, 0))
    session.add(r)
    session.commit()
    return r


def test_list_runs_returns_newest_first(session):
    _run(session, created=datetime(2026, 8, 1))
    _run(session, created=datetime(2026, 8, 20))
    _run(session, created=datetime(2026, 8, 10))

    rows, total = list_runs(session)

    assert total == 3
    assert [r.created_at.day for r in rows] == [20, 10, 1]


def test_list_runs_filters_by_status(session):
    _run(session, status="queued")
    _run(session, status="complete")

    rows, total = list_runs(session, status="complete")

    assert total == 1 and rows[0].status == "complete"


def test_get_run_returns_none_for_an_unknown_id(session):
    assert get_run(session, 999999) is None


def test_get_run_returns_the_run(session):
    r = _run(session)
    assert get_run(session, r.id).id == r.id


def test_claim_next_queued_run_takes_the_oldest_and_marks_it_running(session):
    old = _run(session, created=datetime(2026, 8, 1))
    _run(session, created=datetime(2026, 8, 20))

    claimed = claim_next_queued_run(session)

    assert claimed == old.id
    session.expire_all()
    assert session.query(Run).filter_by(id=old.id).one().status == "running"


def test_claim_next_queued_run_returns_none_when_nothing_is_queued(session):
    _run(session, status="complete")
    assert claim_next_queued_run(session) is None


def test_a_claimed_run_is_not_claimed_again(session):
    """The scheduler polls every 30s. A run claimed by one tick must not be
    picked up by the next while it is still executing."""
    _run(session)

    first = claim_next_queued_run(session)
    second = claim_next_queued_run(session)

    assert first is not None and second is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_runs_repository.py -v
```

Expected: FAIL with `ImportError: cannot import name 'claim_next_queued_run'`

- [ ] **Step 3: Write the repository**

```python
# backend/app/repositories/runs.py
"""Read queries for runs, plus the scheduler's claim (ADR-024)."""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.run import Run
from app.schemas.runs import RunOut


def list_runs(session: Session, status: str | None = None, page: int = 1,
              page_size: int = 50) -> tuple[list[RunOut], int]:
    q = session.query(Run)
    if status:
        q = q.filter(Run.status == status)
    total = q.with_entities(func.count()).order_by(None).scalar() or 0
    rows = (q.order_by(Run.created_at.desc().nullslast(), Run.id.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return [RunOut.model_validate(r) for r in rows], total


def get_run(session: Session, run_id: int) -> RunOut | None:
    row = session.query(Run).filter_by(id=run_id).one_or_none()
    return RunOut.model_validate(row) if row else None


def claim_next_queued_run(session: Session) -> int | None:
    """Take the oldest `queued` run and mark it `running`, atomically.

    `with_for_update(skip_locked=True)` is what makes the claim safe: a
    second poller skips the locked row instead of blocking on it or, worse,
    claiming the same run. The spec's known limitation -- two FastAPI
    instances double-executing -- is exactly what this prevents, so the
    Postgres advisory lock it mentions is not needed yet.
    """
    row = (session.query(Run)
           .filter(Run.status == "queued")
           .order_by(Run.created_at.asc().nullsfirst(), Run.id.asc())
           .with_for_update(skip_locked=True)
           .first())
    if row is None:
        return None
    row.status = "running"
    row.started_at = datetime.utcnow()
    session.commit()
    return row.id
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_runs_repository.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/runs.py backend/tests/unit/test_runs_repository.py
git commit -m "feat: add runs repository with a lock-safe queued-run claim"
```

---

## Task 5: Extract run orchestration into a service

**Files:**
- Create: `backend/app/services/run_executor.py`
- Modify: `backend/cli.py` (replace `run_all`'s body with a delegation)
- Test: `backend/tests/unit/test_run_executor.py`

**Interfaces:**
- Consumes: every stage from Plan 1; `check_budget`, `BudgetExceeded`; `build_search_plan`; `read_ruleset_file`
- Produces:
  ```python
  @dataclass
  class RunResult:
      run_id: int
      status: str                    # "complete" | "failed"
      stages: list[tuple[str, StageReport]]
      error: str | None = None

  def execute_run(run_id: int, *, providers: Providers | None = None,
                  session_factory=get_session) -> RunResult

  @dataclass
  class Providers:
      search: SearchProvider
      scraper: WebScraper
      reviews: ReviewProvider
  ```

**This is the most important task in the plan.** `cli.py`'s `run_all` currently holds the only implementation of the run sequence — the seven stages, the budget checks between them, and the terminal-state handling. The API and the scheduler both need that exact behaviour. Copying it would create the "same thing done three different ways" that Plan 1's final review flagged. Extract it once; every caller uses it.

**Behaviour that must be preserved exactly** (read `cli.py`'s current `run_all` before you start):

1. Stage order is discover → scrape → extract → score → enrich → extract → score. The second extract/score pass is not optional — it is how review-derived signals reach a score (ADR-020).
2. `check_budget` runs **before each stage**, and the two spending stages also check per business via their `budget_check` parameter.
3. `BudgetExceeded` → `Run.status = "failed"`, `Run.error` set, `finished_at` set, and the run stops. It is *not* re-raised as a crash.
4. Any other exception → same terminal write, then **re-raise** so the failure stays visible.
5. A stage reporting `aborted=True` stops the run and marks it failed.
6. Businesses not reached keep their status, so the run is resumable.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_run_executor.py
import pytest

from app.clients.fakes import FakeReviewProvider, FakeSearchProvider, FakeWebScraper
from app.models.business import Business
from app.models.derived import ApiCall, Score
from app.models.run import Run
from app.services.run_executor import Providers, execute_run


@pytest.fixture
def providers():
    return Providers(search=FakeSearchProvider(), scraper=FakeWebScraper(),
                     reviews=FakeReviewProvider([]))


@pytest.fixture
def queued_run(session):
    r = Run(status="queued", source="ui",
            search_plan={"vertical": "hvac", "state": None,
                         "location": "Houston, TX", "pages": 1})
    session.add(r)
    session.commit()
    return r


def _factory(session):
    """A session_factory that hands back the rolled-back test session."""
    from contextlib import contextmanager

    @contextmanager
    def f():
        yield session
    return f


def test_execute_run_walks_every_stage_in_order(session, queued_run, providers):
    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "complete"
    assert [name for name, _ in result.stages] == [
        "discover", "scrape", "extract", "score", "enrich", "extract", "score"]


def test_execute_run_produces_scored_businesses(session, queued_run, providers):
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    assert session.query(Score).count() > 0


def test_execute_run_marks_the_run_complete_with_a_finish_time(
        session, queued_run, providers):
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "complete"
    assert run.finished_at is not None
    assert run.actual_cost is not None


def test_execute_run_stops_and_fails_when_the_budget_is_exceeded(
        session, queued_run, providers):
    """A ceiling already blown before the first stage must stop the run
    without calling a single provider."""
    session.add(ApiCall(provider="serper", endpoint="maps", credits=1,
                        cost_usd=99.0, status_code=200, run_id=queued_run.id))
    queued_run.max_cost_usd = 0.01
    session.commit()

    result = execute_run(queued_run.id, providers=providers,
                         session_factory=_factory(session))

    assert result.status == "failed"
    assert "budget" in (result.error or "").lower()
    assert providers.search.calls == []
    session.expire_all()
    assert session.query(Run).filter_by(id=queued_run.id).one().status == "failed"


def test_execute_run_reraises_a_non_budget_failure_after_marking_the_run(
        session, queued_run):
    """A crash must still move the Run to a terminal state, but must NOT be
    swallowed -- the traceback has to stay visible."""
    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("provider exploded")

    providers = Providers(search=Boom(), scraper=FakeWebScraper(),
                          reviews=FakeReviewProvider([]))

    with pytest.raises(RuntimeError, match="provider exploded"):
        execute_run(queued_run.id, providers=providers,
                    session_factory=_factory(session))

    session.expire_all()
    run = session.query(Run).filter_by(id=queued_run.id).one()
    assert run.status == "failed"
    assert run.finished_at is not None
    assert "discover" in (run.error or "")


def test_execute_run_leaves_unreached_businesses_resumable(
        session, queued_run, providers):
    """Businesses the run never got to must keep their status, so a second
    run continues rather than starting over."""
    execute_run(queued_run.id, providers=providers,
                session_factory=_factory(session))

    from app.models.business import BusinessStatus
    statuses = {b.status for b in session.query(Business).all()}
    assert BusinessStatus.FAILED not in statuses


def test_execute_run_raises_for_an_unknown_run_id(session, providers):
    with pytest.raises(ValueError, match="no such run"):
        execute_run(999999, providers=providers,
                    session_factory=_factory(session))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_run_executor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.run_executor'`

- [ ] **Step 3: Read the code you are extracting**

```bash
cd backend && sed -n '/def run_all/,/^@app.command/p' cli.py
```

Do not skip this. The comments in that function record why each branch exists — they came out of a review that found the stranded-`Run` bug.

- [ ] **Step 4: Write the service**

```python
# backend/app/services/run_executor.py
"""The one implementation of a full pipeline run.

The CLI, the API, and the scheduler all call `execute_run`. There is no
second copy of the stage list -- Plan 1's final review found duplicated
logic across stages written by different implementers, and this is the seam
where that would happen again.
"""
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import structlog
import yaml

from app.clients.protocols import ReviewProvider, SearchProvider, WebScraper
from app.core.config import get_settings
from app.core.db import get_session
from app.models.run import Run
from app.pipeline.base import StageReport
from app.pipeline.discover import DiscoverStage
from app.pipeline.extract_signals import ExtractSignalsStage
from app.pipeline.fetch_reviews import FetchReviewsStage
from app.pipeline.score import ScoreStage
from app.pipeline.scrape_site import ScrapeSiteStage
from app.services.budget import BudgetExceeded, check_budget
from app.services.rulesets import read_ruleset_file
from app.services.search_plan import build_search_plan

log = structlog.get_logger()
CONFIG = Path("config")


@dataclass
class Providers:
    """The three paid adapters, injected so tests can pass fakes."""
    search: SearchProvider
    scraper: WebScraper
    reviews: ReviewProvider


@dataclass
class RunResult:
    run_id: int
    status: str
    stages: list[tuple[str, StageReport]] = field(default_factory=list)
    error: str | None = None


def _live_providers() -> Providers:
    from app.clients.firecrawl import FirecrawlScraper
    from app.clients.serpapi_reviews import SerpApiReviewProvider
    from app.clients.serper import SerperClient
    return Providers(search=SerperClient(), scraper=FirecrawlScraper(),
                     reviews=SerpApiReviewProvider())


def _terminal(session_factory, run_id: int, status: str,
              error: str | None) -> None:
    """Move the Run to a terminal state. Called on every exit path -- a run
    stranded at `running` with no finished_at is invisible to monitoring."""
    with session_factory() as s:
        run = s.query(Run).filter_by(id=run_id).one()
        run.status = status
        run.error = error
        run.finished_at = datetime.utcnow()
        from app.services.budget import spend_usd
        run.actual_cost = spend_usd(s, run_id)
        s.commit()


def execute_run(run_id: int, *, providers: Providers | None = None,
                session_factory: Callable = get_session) -> RunResult:
    """Run every stage for `run_id`, in order, under its budget ceiling."""
    providers = providers or _live_providers()
    settings = get_settings()

    with session_factory() as s:
        run = s.query(Run).filter_by(id=run_id).one_or_none()
        if run is None:
            raise ValueError(f"no such run: {run_id}")
        plan_args = dict(run.search_plan)
        ceiling = run.max_cost_usd
        if run.status != "running":
            run.status = "running"
            run.started_at = run.started_at or datetime.utcnow()
            s.commit()

    vertical = plan_args["vertical"]
    verticals_cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    locations_cfg = yaml.safe_load((CONFIG / "locations.yaml").read_text())
    plan = build_search_plan(vertical, plan_args.get("state"),
                             plan_args.get("location"),
                             verticals_cfg, locations_cfg,
                             pages_per_query=plan_args.get("pages", 5))
    ruleset = read_ruleset_file(
        CONFIG / "rulesets" / f"{verticals_cfg[vertical]['ruleset']}.yaml")

    def budget_check(s) -> None:
        check_budget(s, run_id, ceiling)

    def _discover(s) -> StageReport:
        return DiscoverStage(providers.search).discover(
            s, run_id, plan, budget_check=budget_check)

    def _scrape(s) -> StageReport:
        return ScrapeSiteStage(
            providers.scraper,
            per_segment=settings.stratified_per_segment).run(
                s, run_id, budget_check=budget_check)

    def _extract(s) -> StageReport:
        return ExtractSignalsStage().run(s, run_id)

    def _score(s) -> StageReport:
        return ScoreStage(ruleset).run(s, run_id)

    def _enrich(s) -> StageReport:
        return FetchReviewsStage(
            providers.reviews, top_n=settings.enrichment_top_n,
            monthly_ceiling=settings.serpapi_monthly_ceiling).run(s, run_id)

    # The ADR-020 loop: enrich, then re-derive signals and re-score over the
    # richer data. Dropping the second extract/score pass silently leaves
    # review-derived signals unscored.
    stages: list[tuple[str, Callable]] = [
        ("discover", _discover), ("scrape", _scrape), ("extract", _extract),
        ("score", _score), ("enrich", _enrich), ("extract", _extract),
        ("score", _score),
    ]

    result = RunResult(run_id=run_id, status="complete")

    for name, fn in stages:
        try:
            with session_factory() as s:
                check_budget(s, run_id, ceiling)
                report = fn(s)
                s.commit()
        except BudgetExceeded as exc:
            log.warning("run.budget_exceeded", run_id=run_id, stage=name)
            result.status, result.error = "failed", f"budget: {exc}"
            _terminal(session_factory, run_id, "failed", result.error)
            return result
        except Exception:
            # Terminal state first, then re-raise: the crash must stay
            # visible, but the Run must not be stranded at `running`.
            err = f"{name} failed: {traceback.format_exc()[-2000:]}"
            _terminal(session_factory, run_id, "failed", err)
            raise

        result.stages.append((name, report))
        if report.aborted:
            log.error("run.stage_aborted", run_id=run_id, stage=name,
                      reason=report.reason)
            result.status = "failed"
            result.error = f"{name} aborted: {report.reason}"
            _terminal(session_factory, run_id, "failed", result.error)
            return result

    _terminal(session_factory, run_id, "complete", None)
    return result
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_run_executor.py -v
```

Expected: 8 passed

`DiscoverStage.discover` does accept `budget_check` — verified while writing this plan:

```python
def discover(self, session: Session, run_id: int | None, plan: SearchPlan,
             budget_check: Callable[[Session], None] | None = None) -> StageReport
```

`ScrapeSiteStage.run` and `ScoreStage.run` take it too. `ExtractSignalsStage.run` and `FetchReviewsStage.run` do not — they spend nothing per business, so they need no per-business check.

- [ ] **Step 6: Make the CLI delegate**

Replace `run_all`'s body in `backend/cli.py`. Keep the command, its options, and its docstring; replace the orchestration with a call to the service:

```python
@app.command("run-all")
def run_all(vertical: str, state: str | None = None, location: str | None = None,
            pages: int = 5,
            max_cost: float | None = typer.Option(
                None, "--max-cost",
                help="Cost ceiling in USD for this run. Unset means no limit.")
            ) -> None:
    """Discover -> scrape -> extract -> score -> enrich -> extract -> score.

    Creates the Run row, then hands off to `execute_run`, which is the same
    code path the API and the scheduler use. Orchestration lives there so
    there is exactly one implementation of the stage sequence.
    """
    with get_session() as s:
        run = Run(status="queued", source="cli",
                  search_plan={"vertical": vertical, "state": state,
                               "location": location, "pages": pages},
                  max_cost_usd=max_cost, created_at=datetime.utcnow())
        s.add(run)
        s.commit()
        run_id = run.id

    result = execute_run(run_id)
    for name, report in result.stages:
        typer.echo(f"{name}: processed={report.processed} failed={report.failed}")
    if result.status == "failed":
        typer.echo(result.error or "run failed", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"run {run_id} complete")
```

Add `from app.services.run_executor import execute_run` to `cli.py`'s imports, and remove any imports that are now unused (`traceback`, `Callable`, `check_budget`, `BudgetExceeded` — check what is actually still referenced before deleting).

- [ ] **Step 7: Verify the CLI's own tests still pass**

```bash
cd backend && pytest tests/integration/test_cli.py -v
```

Expected: all pass. If a CLI test asserted on orchestration internals rather than observable behaviour, fix the *test* to assert on the Run row and the stage output — but say so in your report rather than quietly rewriting it.

- [ ] **Step 8: Verify everything**

```bash
cd backend && pytest -q && mypy app cli.py && lint-imports
```

Expected: 209 passed, mypy clean, 2 contracts kept

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/run_executor.py backend/cli.py \
        backend/tests/unit/test_run_executor.py backend/tests/integration/test_cli.py
git commit -m "refactor: extract run orchestration into a service shared by CLI and API"
```

---

## Task 6: The search-plan preview service

**Files:**
- Create: `backend/app/services/preview.py`
- Test: `backend/tests/unit/test_preview.py`

**Interfaces:**
- Consumes: `build_search_plan`, `SearchPlan`, `PROVIDER_PRICE_PER_CREDIT`, `SearchQuery` model
- Produces:
  ```python
  def preview_search_plan(session: Session, vertical: str, state: str | None,
                          location: str | None, pages: int,
                          verticals_cfg: dict, locations_cfg: dict,
                          recent_days: int = 30) -> PreviewOut
  ```

This backs the confirm screen (spec §9, screen 1): the user sees the expansion, an estimated cost, and a warning about searches already run recently — **before** anything is spent.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_preview.py
from datetime import datetime, timedelta

from app.models.run import SearchQuery
from app.services.preview import preview_search_plan

VERTICALS = {"hvac": {"search_terms": ["hvac contractor", "ac repair"],
                      "ruleset": "hvac_v1"}}
LOCATIONS = {"TX": {"metros": ["Houston, TX", "Dallas, TX", "Austin, TX"]}}


def test_preview_expands_terms_times_locations(session):
    p = preview_search_plan(session, "hvac", "TX", None, 5,
                            VERTICALS, LOCATIONS)

    assert p.search_count == 6            # 2 terms x 3 metros
    assert len(p.queries) == 6
    assert "hvac contractor in Houston, TX" in p.queries


def test_preview_estimates_cost_from_the_serper_price(session):
    """Serper bills per search; the estimate must move with page count, or a
    user cannot tell a $0.03 run from a $0.30 one."""
    cheap = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                                VERTICALS, LOCATIONS)
    dear = preview_search_plan(session, "hvac", None, "Houston, TX", 10,
                               VERTICALS, LOCATIONS)

    assert dear.estimated_cost_usd > cheap.estimated_cost_usd
    assert cheap.estimated_cost_usd > 0


def test_preview_estimates_results_from_pages(session):
    p = preview_search_plan(session, "hvac", None, "Houston, TX", 2,
                            VERTICALS, LOCATIONS)
    # 2 terms x 1 location x 2 pages x 20 results per page
    assert p.estimated_results == 80


def test_preview_flags_queries_run_in_the_last_30_days(session):
    session.add(SearchQuery(term="hvac contractor", location="Houston, TX",
                            executed_at=datetime.utcnow() - timedelta(days=3),
                            result_count=20))
    session.commit()

    p = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                            VERTICALS, LOCATIONS)

    assert p.recently_run_queries == ["hvac contractor in Houston, TX"]


def test_preview_does_not_flag_an_old_query(session):
    session.add(SearchQuery(term="hvac contractor", location="Houston, TX",
                            executed_at=datetime.utcnow() - timedelta(days=90),
                            result_count=20))
    session.commit()

    p = preview_search_plan(session, "hvac", None, "Houston, TX", 1,
                            VERTICALS, LOCATIONS)

    assert p.recently_run_queries == []


def test_preview_spends_nothing(session):
    """The confirm screen must not call a provider. If this ever fails, the
    preview has started costing money."""
    from app.models.derived import ApiCall
    before = session.query(ApiCall).count()

    preview_search_plan(session, "hvac", "TX", None, 5, VERTICALS, LOCATIONS)

    assert session.query(ApiCall).count() == before
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_preview.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.preview'`

- [ ] **Step 3: Confirm the `SearchQuery` columns**

```bash
cd backend && grep -n "class SearchQuery" -A 12 app/models/run.py
```

Expected — and already verified while writing this plan:

```python
class SearchQuery(Base):
    __tablename__ = "search_queries"
    id: Mapped[int]
    run_id: Mapped[int | None]
    term: Mapped[str]                  # "hvac contractor"
    location: Mapped[str | None]       # "Houston, TX"
    executed_at: Mapped[datetime]
    result_count: Mapped[int]
```

**There is no `query` column.** Term and location are stored separately, which is why the next step matches on the pair and rebuilds the display string rather than comparing against a stored sentence.

- [ ] **Step 4: Write the service**

```python
# backend/app/services/preview.py
"""Cost and scope preview for the confirm screen (spec section 9).

Reads only. Calling a provider here would defeat the point: the user is
deciding whether to spend, and the preview must not spend.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.run import SearchQuery
from app.schemas.runs import PreviewOut
from app.services.budget import PROVIDER_PRICE_PER_CREDIT
from app.services.search_plan import build_search_plan

# Serper's /maps returns 20 places per page (ADR-021, confirmed against the
# real Houston response). Used only for the estimate shown to the user.
RESULTS_PER_PAGE = 20

# One Serper search costs 1 credit per page requested.
CREDITS_PER_PAGE = 1


def preview_search_plan(session: Session, vertical: str, state: str | None,
                        location: str | None, pages: int,
                        verticals_cfg: dict, locations_cfg: dict,
                        recent_days: int = 30) -> PreviewOut:
    plan = build_search_plan(vertical, state, location, verticals_cfg,
                             locations_cfg, pages_per_query=pages)
    queries = plan.queries

    credits = len(queries) * pages * CREDITS_PER_PAGE
    cost = credits * PROVIDER_PRICE_PER_CREDIT.get("serper", 0.0)

    # `search_queries` stores term and location in SEPARATE columns -- there
    # is no combined `query` column -- so the recency check compares the
    # (term, location) pairs and rebuilds the display string the same way
    # SearchPlan.queries does.
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    executed = {(term, loc) for term, loc in
                session.query(SearchQuery.term, SearchQuery.location)
                .filter(SearchQuery.executed_at >= cutoff).distinct().all()}
    recent = [f"{term} in {loc}"
              for loc in plan.locations for term in plan.search_terms
              if (term, loc) in executed]

    return PreviewOut(
        vertical=vertical,
        queries=queries,
        search_count=len(queries),
        estimated_results=len(queries) * pages * RESULTS_PER_PAGE,
        estimated_cost_usd=round(cost, 4),
        recently_run_queries=sorted(recent),
    )
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_preview.py -v
```

Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/preview.py backend/tests/unit/test_preview.py
git commit -m "feat: add search-plan preview with cost estimate and recency warning"
```

---

## Task 7: The runs router

**Files:**
- Modify: `backend/app/api/routers/runs.py`
- Test: `backend/tests/api/test_runs_api.py`

**Interfaces:**
- Consumes: `RunCreate`, `RunOut`, `PreviewOut`, `Page`, `list_runs`, `get_run`, `preview_search_plan`
- Produces: `POST /runs`, `GET /runs`, `GET /runs/{run_id}`, `POST /runs/preview`

`POST /runs` creates the run **queued** and returns immediately. It does not execute it — the scheduler (Task 10) picks it up. A synchronous run would hold an HTTP connection open for minutes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_runs_api.py
from app.models.run import Run


def test_post_runs_creates_a_queued_run_and_returns_it(client, session):
    r = client.post("/runs", json={"vertical": "hvac",
                                   "location": "Houston, TX", "pages": 2})

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    assert body["source"] == "ui"
    assert body["search_plan"]["location"] == "Houston, TX"
    assert session.query(Run).filter_by(id=body["id"]).one().status == "queued"


def test_post_runs_does_not_execute_the_run(client, session):
    """Execution belongs to the scheduler. A synchronous run would hold the
    connection open for minutes and time out behind any proxy."""
    from app.models.business import Business

    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})

    assert session.query(Business).count() == 0


def test_post_runs_rejects_a_plan_with_neither_state_nor_location(client):
    r = client.post("/runs", json={"vertical": "hvac"})
    assert r.status_code == 422


def test_post_runs_stores_the_cost_ceiling(client, session):
    r = client.post("/runs", json={"vertical": "hvac",
                                   "location": "Houston, TX",
                                   "max_cost_usd": 1.5})
    assert r.json()["max_cost_usd"] == 1.5


def test_get_runs_returns_a_page_envelope(client):
    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})

    body = client.get("/runs").json()

    assert body["total"] == 1
    assert body["page"] == 1
    assert len(body["items"]) == 1


def test_get_runs_filters_by_status(client, session):
    client.post("/runs", json={"vertical": "hvac", "location": "Houston, TX"})
    session.query(Run).update({"status": "complete"})
    session.commit()

    assert client.get("/runs?status=complete").json()["total"] == 1
    assert client.get("/runs?status=queued").json()["total"] == 0


def test_get_run_by_id_returns_404_for_an_unknown_run(client):
    assert client.get("/runs/999999").status_code == 404


def test_get_run_by_id_returns_the_run(client):
    created = client.post("/runs", json={"vertical": "hvac",
                                         "location": "Houston, TX"}).json()

    r = client.get(f"/runs/{created['id']}")

    assert r.status_code == 200 and r.json()["id"] == created["id"]


def test_preview_returns_the_expansion_without_creating_a_run(client, session):
    r = client.post("/runs/preview", json={"vertical": "hvac",
                                           "state": "TX", "pages": 1})

    assert r.status_code == 200
    body = r.json()
    assert body["search_count"] == len(body["queries"]) > 0
    assert body["estimated_cost_usd"] > 0
    assert session.query(Run).count() == 0


def test_preview_rejects_an_unknown_vertical(client):
    r = client.post("/runs/preview", json={"vertical": "not_a_vertical",
                                           "location": "Houston, TX"})
    assert r.status_code in (400, 422)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/api/test_runs_api.py -v
```

Expected: FAIL — `POST /runs` returns 405, `GET /runs` returns `[]` not a page envelope

- [ ] **Step 3: Write the router**

```python
# backend/app/api/routers/runs.py
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.run import Run
from app.repositories.runs import get_run, list_runs
from app.schemas.common import Page
from app.schemas.runs import PreviewOut, RunCreate, RunOut
from app.services.preview import preview_search_plan

router = APIRouter(prefix="/runs", tags=["runs"])
CONFIG = Path("config")


def _configs() -> tuple[dict, dict]:
    return (yaml.safe_load((CONFIG / "verticals.yaml").read_text()),
            yaml.safe_load((CONFIG / "locations.yaml").read_text()))


@router.post("", response_model=RunOut, status_code=201)
def create_run(body: RunCreate, db: Session = Depends(get_db)) -> RunOut:
    """Queue a run. The scheduler executes it within ~30s.

    Deliberately does not execute inline: a full run takes minutes, which no
    HTTP client or proxy will hold open.
    """
    verticals_cfg, _ = _configs()
    if body.vertical not in verticals_cfg:
        raise HTTPException(status_code=400,
                            detail=f"unknown vertical: {body.vertical}")

    run = Run(status="queued", source="ui",
              search_plan={"vertical": body.vertical, "state": body.state,
                           "location": body.location, "pages": body.pages},
              max_cost_usd=body.max_cost_usd, created_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunOut.model_validate(run)


@router.post("/preview", response_model=PreviewOut)
def preview_run(body: RunCreate, db: Session = Depends(get_db)) -> PreviewOut:
    """What this run would search and cost. Spends nothing."""
    verticals_cfg, locations_cfg = _configs()
    if body.vertical not in verticals_cfg:
        raise HTTPException(status_code=400,
                            detail=f"unknown vertical: {body.vertical}")
    return preview_search_plan(db, body.vertical, body.state, body.location,
                               body.pages, verticals_cfg, locations_cfg)


@router.get("", response_model=Page[RunOut])
def list_runs_endpoint(status: str | None = None,
                       page: int = Query(1, ge=1),
                       page_size: int = Query(50, ge=1, le=200),
                       db: Session = Depends(get_db)) -> Page[RunOut]:
    items, total = list_runs(db, status=status, page=page, page_size=page_size)
    return Page[RunOut](items=items, total=total, page=page, page_size=page_size)


@router.get("/{run_id}", response_model=RunOut)
def get_run_endpoint(run_id: int, db: Session = Depends(get_db)) -> RunOut:
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no such run: {run_id}")
    return run
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && pytest tests/api/test_runs_api.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routers/runs.py backend/tests/api/test_runs_api.py
git commit -m "feat: add runs router with queue-only creation and cost preview"
```

---

## Task 8: The leads router

**Files:**
- Modify: `backend/app/api/routers/leads.py`
- Test: `backend/tests/api/test_leads_api.py`

**Interfaces:**
- Consumes: `LeadFilters`, `list_leads`, `get_lead_detail`, `export_leads`, `Page`, `LeadOut`, `LeadDetailOut`
- Produces: `GET /leads`, `GET /leads/{cid}`, `GET /leads/export.csv`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_leads_api.py
import pytest

from app.models.business import Business, BusinessStatus
from app.models.derived import Score


@pytest.fixture
def leads(session):
    for cid, name, fit, pain, quad, state in [
            ("c1", "Go Now Air", 90, 90, "go_now", "TX"),
            ("c2", "Nurture Air", 90, 20, "nurture", "TX"),
            ("c3", "Cold Air", 20, 20, "cold", "CA")]:
        b = Business(cid=cid, name=name, state=state, city="Houston",
                     phone="+17135551234", phone_is_valid=True,
                     website=f"https://{cid}.example.com", review_count=100,
                     vertical="hvac", status=BusinessStatus.SCORED)
        session.add(b)
        session.flush()
        session.add(Score(business_id=b.id, ruleset_version="hvac_v1",
                          fit_score=fit, pain_score=pain, quadrant=quad,
                          coverage=0.8, reasons=[]))
    session.commit()


def test_get_leads_returns_every_lead_by_default(client, leads):
    body = client.get("/leads").json()
    assert body["total"] == 3


def test_get_leads_filters_by_quadrant(client, leads):
    body = client.get("/leads?quadrant=go_now").json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Go Now Air"


def test_get_leads_filters_by_state(client, leads):
    assert client.get("/leads?state=CA").json()["total"] == 1


def test_get_leads_orders_by_fit_times_pain(client, leads):
    names = [i["name"] for i in client.get("/leads").json()["items"]]
    assert names[0] == "Go Now Air"


def test_get_leads_rejects_an_oversized_page_size(client, leads):
    """An unbounded page_size is a denial-of-service on our own database."""
    assert client.get("/leads?page_size=100000").status_code == 422


def test_get_leads_returns_an_empty_page_rather_than_404(client):
    body = client.get("/leads").json()
    assert body["total"] == 0 and body["items"] == []


def test_get_lead_detail_returns_reasons_and_signals(client, leads):
    r = client.get("/leads/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["lead"]["name"] == "Go Now Air"
    assert body["score"]["fit_score"] == 90
    assert "reasons" in body and "signals" in body and "evidence" in body


def test_get_lead_detail_404s_for_an_unknown_cid(client, leads):
    assert client.get("/leads/nope").status_code == 404


def test_export_returns_a_csv_attachment(client, leads):
    r = client.get("/leads/export.csv?quadrant=go_now")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("name,phone,website")
    assert len(lines) == 2                      # header + one go_now lead


def test_export_of_an_empty_filter_returns_a_header_only_csv(client, leads):
    r = client.get("/leads/export.csv?quadrant=low_fit")
    assert r.status_code == 200
    assert len(r.text.strip().splitlines()) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/api/test_leads_api.py -v
```

Expected: FAIL with 404 on every route

- [ ] **Step 3: Write the router**

```python
# backend/app/api/routers/leads.py
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.leads import DEFAULT_RULESET, LeadFilters, get_lead_detail, list_leads
from app.schemas.common import Page
from app.schemas.leads import LeadDetailOut, LeadOut
from app.services.export import export_leads

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=Page[LeadOut])
def list_leads_endpoint(
        quadrant: str | None = None,
        vertical: str | None = None,
        state: str | None = None,
        min_fit: int = Query(0, ge=0, le=100),
        min_pain: int = Query(0, ge=0, le=100),
        outcome_status: str | None = None,
        ruleset_version: str = DEFAULT_RULESET,
        page: int = Query(1, ge=1),
        # Capped at 200: an unbounded page_size lets one request pull the
        # whole table into memory.
        page_size: int = Query(50, ge=1, le=200),
        db: Session = Depends(get_db)) -> Page[LeadOut]:
    filters = LeadFilters(quadrant=quadrant, vertical=vertical, state=state,
                          min_fit=min_fit, min_pain=min_pain,
                          outcome_status=outcome_status,
                          ruleset_version=ruleset_version)
    items, total = list_leads(db, filters, page=page, page_size=page_size)
    return Page[LeadOut](items=items, total=total, page=page,
                         page_size=page_size)


@router.get("/export.csv")
def export_csv(quadrant: str | None = None,
               min_fit: int = Query(0, ge=0, le=100),
               ruleset_version: str = DEFAULT_RULESET,
               db: Session = Depends(get_db)) -> Response:
    """Reuses the CLI's exporter so the CSV the UI downloads is byte-identical
    to the one `python -m cli export` writes."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "leads.csv"
        export_leads(db, quadrant, min_fit, path,
                     ruleset_version=ruleset_version)
        content = path.read_text(encoding="utf-8")
    return Response(
        content=content, media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="leads.csv"'})


@router.get("/{cid}", response_model=LeadDetailOut)
def get_lead_endpoint(cid: str, ruleset_version: str = DEFAULT_RULESET,
                      db: Session = Depends(get_db)) -> LeadDetailOut:
    detail = get_lead_detail(db, cid, ruleset_version=ruleset_version)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no such lead: {cid}")
    return detail
```

Route order matters: `/export.csv` is declared before `/{cid}`, or FastAPI matches `export.csv` as a `cid`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && pytest tests/api/test_leads_api.py -v
```

Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routers/leads.py backend/tests/api/test_leads_api.py
git commit -m "feat: add leads router with filtering, detail, and CSV export"
```

---

## Task 9: Outcomes, manual facts, and metadata

**Files:**
- Modify: `backend/app/api/routers/meta.py`
- Test: `backend/tests/api/test_meta_api.py`

**Interfaces:**
- Consumes: `record_outcome`, `VALID`, `read_ruleset_definition`, `OutcomeIn`, `ManualFactsIn`, `ManualFacts` model
- Produces: `PUT /leads/{cid}/outcome`, `PUT /leads/{cid}/manual-facts`, `GET /rulesets`, `GET /verticals`

`GET /verticals` exists because Plan 3's New Search screen needs the dropdown options, and hardcoding them in the frontend would let the two drift.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_meta_api.py
import pytest

from app.models.business import Business, BusinessStatus
from app.models.manual import ManualFacts, Outcome


@pytest.fixture
def lead(session):
    b = Business(cid="c1", name="Test Air", status=BusinessStatus.SCORED)
    session.add(b)
    session.commit()
    return b


def test_put_outcome_records_the_status(client, session, lead):
    r = client.put("/leads/c1/outcome", json={"status": "contacted"})

    assert r.status_code == 200
    assert session.query(Outcome).filter_by(business_id=lead.id).one().status == "contacted"


def test_put_outcome_updates_rather_than_duplicating(client, session, lead):
    client.put("/leads/c1/outcome", json={"status": "contacted"})
    client.put("/leads/c1/outcome", json={"status": "won"})

    rows = session.query(Outcome).filter_by(business_id=lead.id).all()
    assert len(rows) == 1 and rows[0].status == "won"


def test_put_outcome_rejects_an_unknown_status(client, lead):
    r = client.put("/leads/c1/outcome", json={"status": "vibes"})
    assert r.status_code == 422


def test_put_outcome_404s_for_an_unknown_lead(client):
    r = client.put("/leads/nope/outcome", json={"status": "won"})
    assert r.status_code == 404


def test_put_manual_facts_stores_the_values(client, session, lead):
    r = client.put("/leads/c1/manual-facts",
                   json={"estimated_employees": 25, "runs_google_ads": True})

    assert r.status_code == 200
    facts = session.query(ManualFacts).filter_by(business_id=lead.id).one()
    assert facts.estimated_employees == 25


def test_put_manual_facts_updates_rather_than_duplicating(client, session, lead):
    client.put("/leads/c1/manual-facts", json={"estimated_employees": 10})
    client.put("/leads/c1/manual-facts", json={"estimated_employees": 30})

    rows = session.query(ManualFacts).filter_by(business_id=lead.id).all()
    assert len(rows) == 1 and rows[0].estimated_employees == 30


def test_put_manual_facts_rejects_a_negative_headcount(client, lead):
    r = client.put("/leads/c1/manual-facts", json={"estimated_employees": -5})
    assert r.status_code == 422


def test_get_verticals_lists_the_configured_verticals(client):
    body = client.get("/verticals").json()
    assert "hvac" in [v["name"] for v in body]


def test_get_rulesets_returns_version_and_thresholds(client):
    body = client.get("/rulesets").json()
    assert any(r["version"] == "hvac_v1" for r in body)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/api/test_meta_api.py -v
```

Expected: FAIL with 404 on every route

- [ ] **Step 3: Confirm the models and the service signature**

```bash
cd backend && cat app/models/manual.py && grep -n "def record_outcome" -A 20 app/services/outcomes.py
```

Already verified while writing this plan:

- `ManualFacts` columns are `business_id`, `estimated_employees`, `technician_count`, `has_office_admin`, `owner_growth_focused`, `notes`, `updated_at`. **There is no `runs_google_ads` column** — that signal is derived from HTML, not entered by hand.
- `Outcome` columns are `id`, `business_id`, `status`, `source`, `notes`, `contacted_at`, `updated_at`.
- `record_outcome(session, cid, status, notes=None)` — the keyword is `notes`. It **already upserts** by `business_id`, sets `contacted_at` on the first `contacted`, and **commits internally**. Call it; do not reimplement it and do not commit again after it.

- [ ] **Step 4: Write the router**

```python
# backend/app/api/routers/meta.py
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.business import Business
from app.models.manual import ManualFacts
from app.schemas.manual import ManualFactsIn, OutcomeIn
from app.services.outcomes import record_outcome
from app.services.rulesets import read_ruleset_definition

router = APIRouter(tags=["meta"])
CONFIG = Path("config")


def _business_or_404(db: Session, cid: str) -> Business:
    business = db.query(Business).filter_by(cid=cid).one_or_none()
    if business is None:
        raise HTTPException(status_code=404, detail=f"no such lead: {cid}")
    return business


@router.put("/leads/{cid}/outcome")
def put_outcome(cid: str, body: OutcomeIn,
                db: Session = Depends(get_db)) -> dict[str, str]:
    """The feedback loop (ADR-006). What actually happened is the only data
    that can settle the open ICP hypothesis."""
    _business_or_404(db, cid)
    # record_outcome commits internally and already upserts by business_id,
    # so the router neither re-implements the upsert nor commits again.
    record_outcome(db, cid, body.status, notes=body.notes)
    return {"status": body.status}


@router.put("/leads/{cid}/manual-facts")
def put_manual_facts(cid: str, body: ManualFactsIn,
                     db: Session = Depends(get_db)) -> dict[str, str]:
    """Manual data lives in its own permanent table (ADR-008) so re-running
    the pure stages never erases what a human typed."""
    business = _business_or_404(db, cid)
    facts = (db.query(ManualFacts)
             .filter_by(business_id=business.id).one_or_none())
    if facts is None:
        facts = ManualFacts(business_id=business.id)
        db.add(facts)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(facts, field, value)
    db.commit()
    return {"cid": cid}


@router.get("/verticals")
def list_verticals() -> list[dict[str, object]]:
    """Dropdown options for the New Search screen. Served from config so the
    UI and the pipeline cannot drift apart."""
    cfg = yaml.safe_load((CONFIG / "verticals.yaml").read_text())
    return [{"name": name, "search_terms": v["search_terms"],
             "ruleset": v["ruleset"]} for name, v in cfg.items()]


@router.get("/states")
def list_states() -> list[dict[str, object]]:
    cfg = yaml.safe_load((CONFIG / "locations.yaml").read_text())
    return [{"code": code, "metros": v["metros"]} for code, v in cfg.items()]


@router.get("/rulesets")
def list_rulesets() -> list[dict[str, object]]:
    """Every ruleset on disk, with its thresholds -- the UI needs them to
    explain why a lead landed in its quadrant."""
    out: list[dict[str, object]] = []
    for path in sorted((CONFIG / "rulesets").glob("*.yaml")):
        definition = read_ruleset_definition(path)
        out.append({
            "version": definition.get("version", path.stem),
            "fit_threshold": definition.get("fit_threshold"),
            "pain_threshold": definition.get("pain_threshold"),
            "rule_count": len(definition.get("rules", [])),
        })
    return out
```

If `record_outcome` does not accept a `note` keyword, match its real signature and drop the argument — do not change the service.

If `ManualFacts` does not have a `notes` column, remove `notes` from `ManualFactsIn` in `app/schemas/manual.py` rather than adding a column. **This plan creates no migrations.**

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && pytest tests/api/test_meta_api.py -v
```

Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routers/meta.py backend/tests/api/test_meta_api.py \
        backend/app/schemas/manual.py
git commit -m "feat: add outcome, manual-facts, and metadata endpoints"
```

---

## Task 10: The APScheduler jobs

**Files:**
- Create: `backend/app/scheduler.py`
- Modify: `backend/app/api/app.py` (lifespan)
- Test: `backend/tests/unit/test_scheduler_jobs.py`

**Interfaces:**
- Consumes: `claim_next_queued_run`, `execute_run`, `Run`, `Business`
- Produces:
  ```python
  def poll_queued_runs() -> int | None
  def reset_stuck_runs(max_age_hours: int = 1) -> int
  def retry_failed_businesses(max_attempts: int = 3) -> int
  def refresh_stale_businesses(older_than_days: int = 90) -> int
  def build_scheduler() -> BackgroundScheduler
  ```

Four jobs, from spec §8:

| Job | Interval | What it does |
|---|---|---|
| `poll_queued_runs` | 30s | Claim one `queued` run and execute it |
| `reset_stuck_runs` | on startup | `running` for >1h → back to `queued` |
| `retry_failed_businesses` | nightly | `FAILED` rows under an attempt cap → back to `DISCOVERED` |
| `refresh_stale_businesses` | monthly | Rows not updated in 90 days → back to `DISCOVERED` |

Each job takes its own session and must never raise into the scheduler thread — an unhandled exception there kills the job silently for the rest of the process's life.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_scheduler_jobs.py
from datetime import datetime, timedelta

import pytest

from app.models.business import Business, BusinessStatus
from app.models.run import Run


@pytest.fixture
def patched(monkeypatch, session):
    """Point every job at the rolled-back test session."""
    from contextlib import contextmanager
    import app.scheduler as sched

    @contextmanager
    def factory():
        yield session

    monkeypatch.setattr(sched, "get_session", factory)
    return sched


def test_reset_stuck_runs_requeues_a_run_running_too_long(patched, session):
    session.add(Run(status="running", source="ui", search_plan={},
                    started_at=datetime.utcnow() - timedelta(hours=5)))
    session.commit()

    assert patched.reset_stuck_runs(max_age_hours=1) == 1
    session.expire_all()
    assert session.query(Run).one().status == "queued"


def test_reset_stuck_runs_leaves_a_fresh_run_alone(patched, session):
    session.add(Run(status="running", source="ui", search_plan={},
                    started_at=datetime.utcnow() - timedelta(minutes=5)))
    session.commit()

    assert patched.reset_stuck_runs(max_age_hours=1) == 0
    session.expire_all()
    assert session.query(Run).one().status == "running"


def test_retry_failed_businesses_resets_them_under_the_cap(patched, session):
    session.add(Business(cid="c1", name="Failed Air",
                         status=BusinessStatus.FAILED, attempt_count=1))
    session.commit()

    assert patched.retry_failed_businesses(max_attempts=3) == 1
    session.expire_all()
    assert session.query(Business).one().status == BusinessStatus.DISCOVERED


def test_retry_failed_businesses_gives_up_at_the_cap(patched, session):
    """Without a cap, a permanently broken row is retried forever, and every
    retry that reaches a provider costs money."""
    session.add(Business(cid="c1", name="Hopeless Air",
                         status=BusinessStatus.FAILED, attempt_count=3))
    session.commit()

    assert patched.retry_failed_businesses(max_attempts=3) == 0
    session.expire_all()
    assert session.query(Business).one().status == BusinessStatus.FAILED


def test_refresh_stale_businesses_only_touches_old_rows(patched, session):
    session.add(Business(cid="old", name="Old Air", status=BusinessStatus.SCORED,
                         updated_at=datetime.utcnow() - timedelta(days=200)))
    session.add(Business(cid="new", name="New Air", status=BusinessStatus.SCORED,
                         updated_at=datetime.utcnow()))
    session.commit()

    assert patched.refresh_stale_businesses(older_than_days=90) == 1
    session.expire_all()
    by_cid = {b.cid: b.status for b in session.query(Business).all()}
    assert by_cid["old"] == BusinessStatus.DISCOVERED
    assert by_cid["new"] == BusinessStatus.SCORED


def test_poll_queued_runs_returns_none_when_nothing_is_queued(patched, session):
    assert patched.poll_queued_runs() is None


def test_poll_queued_runs_executes_the_claimed_run(patched, session, monkeypatch):
    session.add(Run(status="queued", source="ui",
                    search_plan={"vertical": "hvac", "location": "Houston, TX"}))
    session.commit()

    executed: list[int] = []
    monkeypatch.setattr(patched, "execute_run",
                        lambda run_id, **kw: executed.append(run_id))

    claimed = patched.poll_queued_runs()

    assert claimed is not None and executed == [claimed]


def test_a_job_never_raises_into_the_scheduler_thread(patched, session, monkeypatch):
    """An exception escaping a job kills it for the life of the process. It
    must be logged and swallowed instead."""
    session.add(Run(status="queued", source="ui", search_plan={}))
    session.commit()

    def boom(run_id, **kw):
        raise RuntimeError("stage exploded")

    monkeypatch.setattr(patched, "execute_run", boom)

    patched.poll_queued_runs()          # must not raise
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && pytest tests/unit/test_scheduler_jobs.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: Write the scheduler**

```python
# backend/app/scheduler.py
"""In-process scheduling (ADR-010). One container, no Redis, no Celery.

Every job swallows its own exceptions. An exception escaping into an
APScheduler worker thread removes the job for the remaining life of the
process, and nothing would say so.
"""
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.db import get_session
from app.models.business import Business, BusinessStatus
from app.models.run import Run
from app.repositories.runs import claim_next_queued_run
from app.services.run_executor import execute_run

log = structlog.get_logger()


def poll_queued_runs() -> int | None:
    """Claim one queued run and execute it. Returns the run id, or None."""
    try:
        with get_session() as s:
            run_id = claim_next_queued_run(s)
        if run_id is None:
            return None
        log.info("scheduler.run_claimed", run_id=run_id)
        execute_run(run_id)
        return run_id
    except Exception:
        # execute_run has already written the terminal Run state; this only
        # stops the exception from killing the polling job.
        log.exception("scheduler.poll_failed")
        return None


def reset_stuck_runs(max_age_hours: int = 1) -> int:
    """A run left `running` past the cutoff goes back to `queued`.

    Covers the case where the process died mid-run: without this the run is
    stranded and the poller will never look at it again.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        with get_session() as s:
            rows = (s.query(Run)
                    .filter(Run.status == "running",
                            Run.started_at.isnot(None),
                            Run.started_at < cutoff).all())
            for run in rows:
                run.status = "queued"
                run.started_at = None
            s.commit()
            if rows:
                log.warning("scheduler.reset_stuck_runs", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.reset_stuck_runs_failed")
        return 0


def retry_failed_businesses(max_attempts: int = 3) -> int:
    """Send FAILED businesses back to the start of the pipeline, under a cap.

    The cap matters: without it a permanently broken row is retried nightly
    forever, and each retry that reaches a provider costs money.
    """
    try:
        with get_session() as s:
            rows = (s.query(Business)
                    .filter(Business.status == BusinessStatus.FAILED,
                            Business.attempt_count < max_attempts).all())
            for business in rows:
                business.status = BusinessStatus.DISCOVERED
                business.failed_stage = None
                business.error_message = None
            s.commit()
            if rows:
                log.info("scheduler.retry_failed", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.retry_failed_businesses_failed")
        return 0


def refresh_stale_businesses(older_than_days: int = 90) -> int:
    """Re-walk businesses whose data has aged out (spec section 5, Refresh)."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        with get_session() as s:
            rows = (s.query(Business)
                    .filter(Business.status == BusinessStatus.SCORED,
                            Business.updated_at < cutoff).all())
            for business in rows:
                business.status = BusinessStatus.DISCOVERED
            s.commit()
            if rows:
                log.info("scheduler.refresh_stale", count=len(rows))
            return len(rows)
    except Exception:
        log.exception("scheduler.refresh_stale_businesses_failed")
        return 0


def build_scheduler() -> BackgroundScheduler:
    """Wire the four jobs. `max_instances=1` on the poller stops a slow run
    from being started twice while the first is still going."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(poll_queued_runs, "interval", seconds=30,
                      id="poll_queued_runs", max_instances=1,
                      coalesce=True, replace_existing=True)
    scheduler.add_job(retry_failed_businesses, "cron", hour=3, minute=0,
                      id="retry_failed_businesses", replace_existing=True)
    scheduler.add_job(refresh_stale_businesses, "cron", day=1, hour=4, minute=0,
                      id="refresh_stale_businesses", replace_existing=True)
    return scheduler
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && pytest tests/unit/test_scheduler_jobs.py -v
```

Expected: 8 passed

- [ ] **Step 5: Start the scheduler with the app**

Modify `backend/app/api/app.py`. Add the lifespan and pass it to `FastAPI`:

```python
from contextlib import asynccontextmanager
from typing import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the scheduler with the app; stop it cleanly on shutdown.

    `reset_stuck_runs` runs once at startup rather than on a timer: the
    condition it fixes is created by a process dying, so startup is exactly
    when to check.
    """
    from app.scheduler import build_scheduler, reset_stuck_runs

    scheduler = None
    if not app.state.disable_scheduler:
        reset_stuck_runs()
        scheduler = build_scheduler()
        scheduler.start()
        log.info("scheduler.started")
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
```

Change the factory signature and the `FastAPI(...)` call:

```python
def create_app(*, disable_scheduler: bool = False) -> FastAPI:
    app = FastAPI(title="Lead Generation API", version="1.0.0",
                  lifespan=lifespan)
    app.state.disable_scheduler = disable_scheduler
    ...
```

Then in `backend/tests/api/conftest.py`, change the one line that builds the app:

```python
    app = create_app(disable_scheduler=True)
```

A background scheduler inside the test suite would execute real runs against real providers. It must be off.

- [ ] **Step 6: Verify everything**

```bash
cd backend && pytest -q && mypy app cli.py && lint-imports
```

Expected: all pass, mypy clean, 2 contracts kept

- [ ] **Step 7: Commit**

```bash
git add backend/app/scheduler.py backend/app/api/app.py \
        backend/tests/unit/test_scheduler_jobs.py backend/tests/api/conftest.py
git commit -m "feat: add in-process APScheduler with run polling and maintenance jobs"
```

---

## Task 11: Containerise the API

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`
- Modify: `docker-compose.yml`, `docs/decisions/DECISIONS.md`, `docs/DEVELOPMENT-LOG.md`

**Interfaces:**
- Consumes: everything above
- Produces: a runnable `api` service on port 8000 with a working healthcheck

One image, multiple entrypoints (ADR-017): the same image runs the API or the CLI depending on the command.

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so a source change does not invalidate the layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . && pip cache purge

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini cli.py ./
COPY config ./config

EXPOSE 8000

# ADR-017: one image, several entrypoints. Override `command` to run the CLI:
#   docker compose run --rm api python -m cli run-all hvac --location "Houston, TX"
CMD ["uvicorn", "app.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

```
# backend/.dockerignore
.venv
.mypy_cache
.ruff_cache
.pytest_cache
.import_linter_cache
__pycache__
*.egg-info
tests
.env
```

- [ ] **Step 2: Add the api service to compose**

Replace `docker-compose.yml` with:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: leadgen
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    environment:
      # `db` not `localhost`: inside the compose network the container
      # reaches Postgres by service name.
      DATABASE_URL: postgresql+psycopg://postgres:dev@db:5432/leadgen
      SERPER_KEY: ${SERPER_KEY:-}
      FIRECRAWL_KEY: ${FIRECRAWL_KEY:-}
      SERPAPI_KEY: ${SERPAPI_KEY:-}
      API_KEY: ${API_KEY:-}
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
      interval: 15s
      timeout: 5s
      retries: 5

volumes: { pgdata: }
```

- [ ] **Step 3: Build and verify the container answers**

```bash
docker compose build api
docker compose up -d db api
sleep 15
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"}`

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/runs
```

Expected: `401` (no API key)

```bash
docker compose logs api | grep -i "scheduler.started"
```

Expected: one line confirming the scheduler started.

- [ ] **Step 4: Run the migrations inside the container**

```bash
docker compose run --rm api alembic upgrade head
```

Expected: migration applies cleanly against the `db` service.

- [ ] **Step 5: Record the decisions**

Append to `docs/decisions/DECISIONS.md`:

```markdown
## ADR-025 — The API queues runs; the scheduler executes them

**Context.** `POST /runs` could execute the pipeline inline and return when
it finished. A full run takes minutes.

**Decision.** `POST /runs` creates the run with `status="queued"` and returns
201 immediately. APScheduler polls every 30 seconds, claims one queued run
with `SELECT ... FOR UPDATE SKIP LOCKED`, and calls `execute_run`.

**Why.** No HTTP client, proxy, or platform load balancer will hold a
connection open for a multi-minute run. Queueing also makes the run
inspectable while it happens -- the UI polls `GET /runs/{id}` -- and makes a
crashed process recoverable, because `reset_stuck_runs` requeues anything
left `running` at startup. `SKIP LOCKED` is what makes a second API instance
safe, which the spec had listed as a known limitation requiring an advisory
lock.

**Consequences.** A run does not start the instant it is created; worst case
it waits 30 seconds. The UI must poll rather than block. `Run.status` is now
load-bearing for scheduling, not just for display.
```

- [ ] **Step 6: Update the development log**

In `docs/DEVELOPMENT-LOG.md`, add the API commands to the section 5 table and note that the scheduler now executes queued runs. Keep it short — the log is a plain-language overview, not a changelog.

- [ ] **Step 7: Final verification**

```bash
cd backend && pytest -q && mypy app cli.py && lint-imports
docker compose down
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore docker-compose.yml \
        docs/decisions/DECISIONS.md docs/DEVELOPMENT-LOG.md
git commit -m "feat: containerise the API with a healthcheck and compose service"
```

---

## Self-Review

**1. Spec coverage**

| Spec requirement | Task |
|---|---|
| §8 `api/routers/` — runs, businesses, rulesets | 7, 8, 9 |
| §8 `schemas/` Pydantic DTOs | 2 |
| §8 `repositories/` | 3, 4 (scoped by ADR-024) |
| §8 services shared by CLI and API | 5 |
| §8 APScheduler: 30s queued runs, monthly refresh, nightly retry, startup reset | 10 |
| §9 Auth — `X-API-Key`, FastAPI never publicly browsable | 1 |
| §9 screen 1 — expansion, estimated cost, recency warning | 6, 7 |
| §9 screen 3 — filters, CSV export | 8 |
| §9 screen 4 — score breakdown, evidence, manual forms | 8, 9 |
| §10 budget guard, terminal run states | 5 |
| §10 `/health` | 1 |
| §12 Docker deployment | 11 |

**Gaps, deliberately left:** Ruleset compare (spec §9 screen 5) is display-only and marked "cut from v1 if time is tight" — `GET /rulesets` in Task 9 provides the data if Plan 3 wants it. Sentry wiring is one line in `app.py` and is not worth a task; add it when there is a DSN. `contacts` is a v2 table (ADR-007) with nothing to serve.

**2. Placeholder scan:** none. Every code step contains runnable code; every test step contains real assertions.

**3. Type consistency:** `LeadFilters`, `Page[T]`, `RunOut`, `LeadOut`, `PreviewOut`, `Providers`, `RunResult` are defined once and referenced with matching names throughout. `DEFAULT_RULESET` is defined in `repositories/leads.py` and imported by the router rather than redeclared.

**4. Checked every assumption against the real code.** Three were wrong and are fixed above:

| Assumption | Reality | Fixed in |
|---|---|---|
| `SearchQuery` has a `query` column | It has `term` and `location` separately | Task 6 — matches on the pair and rebuilds the string |
| `ManualFacts` has `runs_google_ads` | It does not; that signal comes from HTML | Task 2 — schema now mirrors the real columns |
| `record_outcome(note=...)` | The keyword is `notes`, and it commits internally | Tasks 2 and 9 |

One assumption held: `DiscoverStage.discover`, `ScrapeSiteStage.run`, and `ScoreStage.run` all accept `budget_check`.

This is the same failure mode Plan 1 hit three times — a plan written from memory of an interface rather than from the interface. Every signature quoted in this plan has now been read from the source.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-31-api-and-scheduler.md`.
