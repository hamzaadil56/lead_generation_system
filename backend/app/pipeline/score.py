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
