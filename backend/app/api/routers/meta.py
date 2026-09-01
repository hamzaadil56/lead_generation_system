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
    """Dropdown options for the New Search screen's location picker."""
    cfg = yaml.safe_load((CONFIG / "locations.yaml").read_text())
    return [{"code": code, "metros": v["metros"]} for code, v in cfg.items()]


@router.get("/rulesets")
def list_rulesets() -> list[dict[str, object]]:
    """Every ruleset on disk, with its threshold -- the UI needs it to
    explain why a lead landed in its quadrant."""
    out: list[dict[str, object]] = []
    for path in sorted((CONFIG / "rulesets").glob("*.yaml")):
        definition = read_ruleset_definition(path)
        out.append({
            "version": definition.get("version", path.stem),
            "vertical": definition.get("vertical"),
            "threshold": definition.get("threshold"),
            "fit_rule_count": len(definition.get("fit_rules", [])),
            "pain_rule_count": len(definition.get("pain_rules", [])),
        })
    return out
