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
    terms = verticals_cfg[vertical]["search_terms"]
    if location:
        locations = [location]
    elif state:
        locations = locations_cfg[state]["metros"]
    else:
        raise ValueError("one of state or location is required")
    return SearchPlan(vertical, terms, locations, pages_per_query)
