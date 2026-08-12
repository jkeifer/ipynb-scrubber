"""What can happen to a cell, said as a value rather than as an option."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Omit:
    """Drop the cell from the output entirely."""


@dataclass(frozen=True)
class Keep:
    """Leave the cell's source untouched."""


@dataclass(frozen=True)
class Clear:
    """Replace the cell's source with ``text``, below any ``header`` kept."""

    text: str
    header: str = ''


@dataclass(frozen=True)
class Note:
    """Save ``body`` under ``note_id`` and replace the cell's source with ``text``.

    ``body`` drops the cell's own option header: one carrying ``text`` holds the
    scaffolding the student must fill in, so filing it alongside the answer
    would give the exercise away.
    """

    note_id: str
    text: str
    body: str
    header: str = ''


#: What can happen to a cell that survives into the output. ``apply`` accepts
#: exactly these, so "an omitted cell is never rewritten" is a type.
CellRewrite = Keep | Clear | Note

CellAction = Omit | CellRewrite
