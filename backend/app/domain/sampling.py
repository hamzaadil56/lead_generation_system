from collections import defaultdict
from typing import Callable, TypeVar

T = TypeVar("T")


def stratify(items: list[T], key: Callable[[T], str | None],
             per_group: int) -> list[T]:
    """Take up to `per_group` from each group, preserving input order.

    Deliberately not a global top-N: every segment must be represented so
    outcomes can answer the ICP question (ADR-022).
    """
    taken: dict[str, int] = defaultdict(int)
    out: list[T] = []
    for item in items:
        group = key(item)
        if group is None or taken[group] >= per_group:
            continue
        taken[group] += 1
        out.append(item)
    return out
