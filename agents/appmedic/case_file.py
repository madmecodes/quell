"""The Case File: the single immutable, append-only object passed down the pipeline.

Every agent reads the current state, appends exactly one finding, and hands it on.
Entries are frozen, so the Case File is also the audit trail of a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Entry:
    """One immutable finding written by one agent."""

    step: int
    agent: str
    kind: str  # detection | root_cause | impact | decision | action | report | evaluation
    summary: str  # one-line human-readable headline
    data: dict[str, Any]
    at: str  # ISO timestamp


@dataclass
class CaseFile:
    """Append-only container. The list grows; existing entries never change."""

    incident_id: str
    opened_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    _entries: list[Entry] = field(default_factory=list)

    def append(self, agent: str, kind: str, summary: str, data: dict[str, Any]) -> Entry:
        entry = Entry(
            step=len(self._entries) + 1,
            agent=agent,
            kind=kind,
            summary=summary,
            data=data,
            at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[Entry, ...]:
        """Immutable snapshot of everything written so far."""
        return tuple(self._entries)

    def latest(self, kind: str) -> Entry | None:
        for entry in reversed(self._entries):
            if entry.kind == kind:
                return entry
        return None

    def find(self, agent: str) -> Entry | None:
        for entry in self._entries:
            if entry.agent == agent:
                return entry
        return None
