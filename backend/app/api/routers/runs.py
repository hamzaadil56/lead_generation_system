from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
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

    The plan is resolved and thrown away: this endpoint stores the
    *request*, and `execute_run` rebuilds the plan at execution time.
    Resolving it here is validation, and it has to be the same path
    preview takes. Create used to check only the vertical, so
    `{"vertical":"hvac","state":"ZZ"}` returned 201 while
    `POST /runs/preview` -- three lines below, same body -- returned 400;
    the queued run was then claimed ~30 seconds later and landed `failed`
    with a stored traceback (I2). Going through `build_search_plan`
    (here, via the preview service) rather than re-implementing the checks
    is the point: queue time was the third caller of that function and the
    only one not using it.
    """
    verticals_cfg, locations_cfg = _configs()
    # One call does both jobs. It raises `SearchPlanError` (-> 400) on an
    # unknown vertical or state, and it returns the estimate the confirm
    # screen shows -- which `create_run` used to recompute the configs for
    # and then throw away, leaving `Run.estimated_cost` null forever and
    # the estimate-vs-actual comparison the column exists for impossible
    # (I4). It reads only: `preview_search_plan` cannot reach a provider.
    preview = preview_search_plan(db, body.vertical, body.state,
                                  body.location, body.pages, verticals_cfg,
                                  locations_cfg)

    run = Run(status="queued", source="ui",
              search_plan={"vertical": body.vertical, "state": body.state,
                           "location": body.location, "pages": body.pages},
              # `is not None`, not `or`: the schema bounds this field
              # `gt=0` today, but `or` would quietly swallow a 0 if that
              # ever relaxes -- and "spend nothing" is a real request.
              max_cost_usd=(body.max_cost_usd if body.max_cost_usd is not None
                            else get_settings().default_run_max_cost_usd),
              estimated_cost=preview.estimated_cost_usd,
              created_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunOut.model_validate(run)


@router.post("/preview", response_model=PreviewOut)
def preview_run(body: RunCreate, db: Session = Depends(get_db)) -> PreviewOut:
    """What this run would search and cost. Spends nothing.

    No vertical pre-check: `preview_search_plan` calls `build_search_plan`,
    which validates the vertical and the state, with the same message and
    the same 400. The duplicate check that used to sit here was deferred
    item 5; it goes now that create validates the same way, leaving one
    validation path for both endpoints.
    """
    verticals_cfg, locations_cfg = _configs()
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
