import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.derived import Score
from app.repositories.leads import LeadFilters, filtered_leads


def export_leads(session: Session, quadrant: str | None, min_fit: int,
                 path: Path, ruleset_version: str = "hvac_v1", *,
                 vertical: str | None = None, state: str | None = None,
                 min_pain: int = 0,
                 outcome_status: str | None = None) -> int:
    """Write the filtered set to `path` and return how many rows it holds.

    Filtering and ordering are `filtered_leads` -- the same predicate and the
    same `fit x pain DESC` order `GET /leads` pages -- so "export the filtered
    set" cannot drift from what the screen shows. Keyword-only for the four
    filters added after the fact, because `cli.py` calls this positionally.
    """
    filters = LeadFilters(quadrant=quadrant, vertical=vertical, state=state,
                          min_fit=min_fit, min_pain=min_pain,
                          outcome_status=outcome_status,
                          ruleset_version=ruleset_version)
    rows = (filtered_leads(session, filters)
            .order_by((Score.fit_score * Score.pain_score).desc(), Business.id)
            .all())

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "name", "phone", "website", "address", "segment", "review_count",
            "fit_score", "pain_score", "quadrant", "coverage", "top_reasons"])
        writer.writeheader()
        for business, score, _outcome_status in rows:
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
