from typing import Any, Callable

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    # A missing signal (None) is "unknown", not zero: "unknown >= 10" is not
    # true, so these four short-circuit to False rather than raising or
    # coercing. Only reachable via on_missing="zero", where _applicable lets
    # an absent signal through unguarded.
    "gte":      lambda a, b: False if a is None else a >= b,
    "lte":      lambda a, b: False if a is None else a <= b,
    "gt":       lambda a, b: False if a is None else a > b,
    "lt":       lambda a, b: False if a is None else a < b,
    "eq":       lambda a, b: a == b,
    "neq":      lambda a, b: a != b,
    "in":       lambda a, b: a in b,
    "not_in":   lambda a, b: a not in b,
    "is_true":  lambda a, _: a is True,
    "is_false": lambda a, _: a is False,
    "is_null":  lambda a, _: a is None,
    "not_null": lambda a, _: a is not None,
}

# Deliberately a fixed table, not an expression language (ADR-005).
# If a rule cannot be expressed here, add a SIGNAL, not an operator.
