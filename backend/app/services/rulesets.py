from pathlib import Path
import yaml
from app.domain.rules.loader import load_ruleset
from app.domain.rules.models import Ruleset


def read_ruleset_file(path: Path) -> Ruleset:
    """File I/O lives here so app/domain stays pure."""
    return load_ruleset(yaml.safe_load(path.read_text()))
