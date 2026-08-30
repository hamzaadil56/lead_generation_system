from collections import defaultdict
from typing import Callable, TypeVar

T = TypeVar("T")


def stratify(items: list[T], key: Callable[[T], str | None],
             per_group: int,
             already_taken: dict[str, int] | None = None) -> list[T]:
    """Take up to `per_group` from each group, preserving input order.

    Deliberately not a global top-N: every segment must be represented so
    outcomes can answer the ICP question (ADR-022).

    `already_taken` seeds the per-group counters with what a previous run
    consumed, which makes `per_group` bound the SAMPLE rather than one
    batch. Without it, each invocation took a fresh `per_group` from
    whatever was left, so the size of the stratified sample -- and the
    Firecrawl bill -- was bounded only by how many times the command was
    run (I6).
    """
    taken: dict[str, int] = defaultdict(int)
    if already_taken:
        taken.update(already_taken)
    out: list[T] = []
    for item in items:
        group = key(item)
        if group is None or taken[group] >= per_group:
            continue
        taken[group] += 1
        out.append(item)
    return out
