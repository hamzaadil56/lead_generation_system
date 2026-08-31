from dataclasses import dataclass


@dataclass(frozen=True)
class SearchPlan:
    vertical: str
    search_terms: list[str]
    locations: list[str]
    pages_per_query: int = 5

    @property
    def queries(self) -> list[str]:
        # Serper resolves natural-language locations (ADR-021) — no centroids.
        return [f"{term} in {loc}"
                for loc in self.locations for term in self.search_terms]


def build_search_plan(vertical: str, state: str | None, location: str | None,
                      verticals_cfg: dict, locations_cfg: dict,
                      pages_per_query: int = 5) -> SearchPlan:
    """Turn a vertical/state/location into a `SearchPlan`.

    This is the one place the CLI, the API router, and the scheduler (via
    `execute_run`) all resolve a plan -- normalisation and validation belong
    here, once, not copied into each caller. `location` is a free-text
    string handed straight to the provider (Serper resolves it server-side,
    per ADR-021), so it is passed through untouched; only `vertical` and
    `state` are keys into local config files and need to match them.
    """
    if vertical not in verticals_cfg:
        raise ValueError(f"unknown vertical: {vertical}")
    terms = verticals_cfg[vertical]["search_terms"]
    if location:
        locations = [location]
    elif state:
        locations = _resolve_metros(state, locations_cfg)
    else:
        raise ValueError("one of state or location is required")
    return SearchPlan(vertical, terms, locations, pages_per_query)


def _resolve_metros(state: str, locations_cfg: dict) -> list[str]:
    """`config/locations.yaml` keys states however its author wrote them
    (lowercase, `tx:`), but a caller naturally types the two-letter
    abbreviation the way it is normally written (`TX`). Try an exact match
    first -- so a config that does use uppercase keys, as some unit test
    fixtures do, still works with zero indirection -- then fall back to a
    case-insensitive match so `"TX"`, `"tx"`, and `"Tx"` all resolve to the
    same entry."""
    if state in locations_cfg:
        return locations_cfg[state]["metros"]
    by_lower = {k.lower(): v for k, v in locations_cfg.items()}
    entry = by_lower.get(state.lower())
    if entry is None:
        raise ValueError(f"unknown state: {state}")
    return entry["metros"]
