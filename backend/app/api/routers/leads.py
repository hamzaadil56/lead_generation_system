import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.leads import (DEFAULT_RULESET, LeadFilters,
                                    get_lead_detail, list_leads)
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
               vertical: str | None = None,
               state: str | None = None,
               min_fit: int = Query(0, ge=0, le=100),
               min_pain: int = Query(0, ge=0, le=100),
               outcome_status: str | None = None,
               ruleset_version: str = DEFAULT_RULESET,
               db: Session = Depends(get_db)) -> Response:
    """Reuses the CLI's exporter so the CSV the UI downloads is byte-identical
    to the one `python -m cli export` writes.

    Takes EVERY filter `GET /leads` takes, and validates them identically.
    FastAPI silently ignores query params an endpoint does not declare, so a
    filter missing here does not fail -- it exports the unfiltered table under
    a URL that says otherwise, which is how "1 lead on screen, 10 in the file"
    shipped.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "leads.csv"
        export_leads(db, quadrant, min_fit, path,
                     ruleset_version=ruleset_version,
                     vertical=vertical, state=state, min_pain=min_pain,
                     outcome_status=outcome_status)
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
