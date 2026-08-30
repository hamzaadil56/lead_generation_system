from pathlib import Path
from typing import Any

import yaml

from app.domain.rules.loader import load_ruleset
from app.domain.rules.models import Ruleset


def read_ruleset_definition(path: Path) -> dict[str, Any]:
    """The raw, parsed YAML — the provenance record stored in `rulesets`."""
    definition: dict[str, Any] = yaml.safe_load(path.read_text())
    return definition


def read_ruleset_file(path: Path) -> Ruleset:
    """File I/O lives here so app/domain stays pure."""
    return load_ruleset(read_ruleset_definition(path))
