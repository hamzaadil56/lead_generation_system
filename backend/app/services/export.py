import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.derived import Score


def export_leads(session: Session, quadrant: str | None, min_fit: int,
                 path: Path, ruleset_version: str = "hvac_v1") -> int:
    q = (session.query(Business, Score)
         .join(Score, Score.business_id == Business.id)
         .filter(Score.ruleset_version == ruleset_version,
                 Score.fit_score >= min_fit))
    if quadrant:
        q = q.filter(Score.quadrant == quadrant)
    rows = q.order_by((Score.fit_score * Score.pain_score).desc()).all()

    with path.open("w", newline="", encoding="utf-8") as fh:
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
