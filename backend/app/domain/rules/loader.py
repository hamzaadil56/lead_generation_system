from typing import Any
from app.domain.rules.models import Rule, Ruleset, Track


def load_ruleset(raw: dict[str, Any]) -> Ruleset:
    """Pure: takes already-parsed YAML. File I/O belongs in app/services."""
    def rules(key: str, track: Track) -> list[Rule]:
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
