from __future__ import annotations

import re

from collections.abc import Callable, Collection
from typing import Any

import yaml

from .exceptions import ScrubberError

#: What an option name may look like: nothing YAML would quote as a bare key.
TAG_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]*')

#: What YAML tags a scalar it reads as text. Asked of YAML's own resolver, not
#: a word list kept here, so the answer is the one PyYAML gives on a header.
_STRING_TAG = 'tag:yaml.org,2002:str'

#: One resolver for the whole module: it carries no per-document state, and a
#: name is checked on every options instance a config override derives.
#: Annotated because PyYAML's stubs leave ``resolve`` untyped, which would make
#: the tag it returns -- and so every comparison against it -- ``Any``.
_resolve: Callable[[type[yaml.Node], str, tuple[bool, bool]], str] = (
    yaml.resolver.Resolver().resolve
)


def is_plain_name(name: str) -> bool:
    """Whether ``name`` is spelled the way an option header key must be."""
    return TAG_NAME.fullmatch(name) is not None


def reads_back_as_text(name: str) -> bool:
    """Whether YAML reads ``name`` off an option header as this same text.

    The alternative is YAML resolving it to a bool or None.
    """
    return _resolve(yaml.ScalarNode, name, (True, False)) == _STRING_TAG


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
