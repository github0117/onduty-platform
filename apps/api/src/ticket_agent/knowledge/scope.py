from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Any


def scope_matches(
    restrictions: Mapping[str, Any],
    context: Mapping[str, str] | None,
) -> bool:
    if not restrictions:
        return True
    if not context:
        return False

    for key, allowed_value in restrictions.items():
        context_value = _context_value(context, key)
        if context_value is None:
            return False
        allowed = (
            {str(item) for item in allowed_value}
            if isinstance(allowed_value, list)
            else {str(allowed_value)}
        )
        if not any(
            _value_matches(key, context_value, candidate)
            for candidate in allowed
        ):
            return False
    return True


def _context_value(context: Mapping[str, str], key: str) -> str | None:
    if key in context:
        return context[key]
    if key.endswith("s") and key[:-1] in context:
        return context[key[:-1]]
    return None


def _value_matches(key: str, actual: str, expected: str) -> bool:
    if expected == "*" or fnmatchcase(actual, expected):
        return True
    if key in {"organization", "organizations", "org_unit", "org_units"}:
        normalized = expected.rstrip("/.")
        return actual == expected or actual.startswith(f"{normalized}/") or actual.startswith(
            f"{normalized}."
        )
    return actual == expected

