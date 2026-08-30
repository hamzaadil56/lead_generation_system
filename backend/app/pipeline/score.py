from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.core.errors import RulesetVersionConflict
from app.domain.rules.engine import evaluate
from app.domain.rules.models import Ruleset
from app.models.business import BusinessStatus
from app.models.derived import Score, Signals
from app.models.manual import Ruleset as RulesetRow
from app.pipeline.base import Stage

_NON_SIGNAL_COLUMNS = {"business_id", "extracted_at", "extractor_version"}


class ScoreStage(Stage):
    name = "score"
    consumes = BusinessStatus.SIGNALS_EXTRACTED
    produces = BusinessStatus.SCORED

    def __init__(self, ruleset: Ruleset,
                 definition: dict[str, Any] | None = None) -> None:
        self._ruleset = ruleset
        self._definition = definition

    def run(self, session, run_id, limit: int = 500, budget_check=None):
        # ADR-005 wants the rules stored as versioned DATA. The `rulesets`
        # table existed in the model and the migration but nothing ever
        # wrote a row, so scoring read a mutable YAML file and editing it
        # silently overwrote every prior Score row for that version --
        # destroying exactly the comparison ADR-005 exists to protect (I5).
        if self._definition is not None:
            self._register_ruleset(session)
        return super().run(session, run_id, limit, budget_check)

    def _register_ruleset(self, session) -> None:
        assert self._definition is not None
        version = self._ruleset.version
        existing = session.query(RulesetRow).filter_by(
            version=version).one_or_none()

        if existing is None:
            session.add(RulesetRow(
                version=version,
                name=str(self._definition.get("name", version)),
                vertical=self._ruleset.vertical,
                definition=self._definition,
                is_active=True,
                created_at=datetime.utcnow()))
            session.commit()
            return

        if existing.definition != self._definition:
            raise RulesetVersionConflict(
                f"ruleset version {version!r} is already recorded with "
                f"different content. Scoring against it would overwrite "
                f"every Score row written under the old definition. Bump "
                f"the `version` field in the ruleset file (e.g. to "
                f"{version}_b) and re-run `score`.")

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
