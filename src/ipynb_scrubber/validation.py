from __future__ import annotations

from collections.abc import Collection
from typing import Any

from .exceptions import ScrubberError


def reject_unknown_keys(
    data: dict[str, Any],
    valid: Collection[str],
    label: str,
) -> None:
    """Raise if ``data`` carries a key outside ``valid``.

    A silently dropped typo means a misspelled ``clear-tag`` scrubs nothing.

    Raises:
        ScrubberError: If any key is unrecognised.
    """
    unknown = sorted(set(data) - set(valid))
    if unknown:
        raise ScrubberError(
            f'Unknown {label}(s): {", ".join(unknown)}. '
            f'Valid {label}s: {", ".join(sorted(valid))}',
        )


def reject_wrong_type(key: str, value: Any, expected: type) -> None:
    """Raise unless ``value`` is the type ``key`` is declared to hold.

    TOML values arrive untyped and go straight to a dataclass.

    Raises:
        ScrubberError: If ``value`` is not an ``expected``.
    """
    if not isinstance(value, expected):
        raise ScrubberError(
            f'{key} must be {expected.__name__}, but got '
            f'{type(value).__name__}: {value!r}',
        )
