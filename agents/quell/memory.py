"""Episodic lesson memory (Reflexion-style).

Each agent has a namespaced store of verbal lessons learned from past runs.
- Agents READ their top lessons at the start of a run and inject them as context.
- The Evaluator WRITES a lesson only after the human approves it at Gate 2.

This is learning without fine-tuning: corrections become retrievable text.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

STORE_DIR = Path(__file__).parent / "memory_store"


@dataclass
class Lesson:
    agent: str
    task_type: str
    text: str
    importance: float  # 0..1, used for ranking
    at: str


class LessonStore:
    """One JSON file per agent namespace. Append-only in spirit; supports prune."""

    def __init__(self, store_dir: Path = STORE_DIR):
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent: str) -> Path:
        return self.store_dir / f"{agent}.json"

    def read(self, agent: str, task_type: str | None = None, k: int = 3) -> list[Lesson]:
        path = self._path(agent)
        if not path.exists():
            return []
        raw = json.loads(path.read_text())
        lessons = [Lesson(**item) for item in raw]
        if task_type:
            lessons = [le for le in lessons if le.task_type == task_type]
        # rank by importance then recency, return top-k
        lessons.sort(key=lambda le: (le.importance, le.at), reverse=True)
        return lessons[:k]

    def write(self, lesson: Lesson) -> None:
        """Persist a lesson. Call this ONLY after the human-approval gate."""
        path = self._path(lesson.agent)
        existing = json.loads(path.read_text()) if path.exists() else []
        existing.append(asdict(lesson))
        path.write_text(json.dumps(existing, indent=2))

    def as_context(self, agent: str, task_type: str | None = None, k: int = 3) -> str:
        """Render an agent's lessons as a prompt block it reads before acting."""
        lessons = self.read(agent, task_type, k)
        if not lessons:
            return ""
        bullets = "\n".join(f"- {le.text}" for le in lessons)
        return f"Lessons learned from past incidents:\n{bullets}"


def new_lesson(agent: str, task_type: str, text: str, importance: float = 0.7) -> Lesson:
    return Lesson(
        agent=agent,
        task_type=task_type,
        text=text,
        importance=importance,
        at=datetime.now(timezone.utc).isoformat(),
    )
