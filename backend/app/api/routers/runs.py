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
