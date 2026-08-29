from typing import Any, Callable

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "gte":      lambda a, b: a >= b,
    "lte":      lambda a, b: a <= b,
    "gt":       lambda a, b: a > b,
    "lt":       lambda a, b: a < b,
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
