"""The central orchestrator: a deterministic pipeline with two human gates.

  Watcher -> Tracer -> Judge -> [GATE 1: approve action] -> Actuator -> Scribe
                                                                          |
                                          Evaluator (async, reads traces) +
                                                                          |
                                          [GATE 2: approve learning] -> memory + definition edits

Gates are injected callbacks so the same orchestrator drives both an automated
demo and the real dashboard (where a gate suspends the run until a human clicks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .agents.actuator import Actuator
from .agents.evaluator import Evaluator, Scorecard
from .agents.judge import Judge
from .agents.scribe import Scribe
from .agents.tracer import Tracer
from .agents.watcher import Watcher
from .case_file import CaseFile
from .dynatrace.mock_mcp import MockMCP
from .memory import LessonStore, new_lesson

# Gate 1: receives the case file, returns True to approve the action.
ApproveAction = Callable[[CaseFile], bool]
# Gate 2: receives the scorecard, returns the set of agent names whose proposed
# learning the human approved.
ApproveLearning = Callable[[Scorecard], set[str]]


@dataclass
class RunResult:
    case_file: CaseFile
    scorecard: Scorecard | None = None
    actioned: bool = False
    applied_lessons: list[str] = field(default_factory=list)
    applied_definition_edits: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, mcp: MockMCP, store: LessonStore):
        self.mcp = mcp
        self.store = store
        self.watcher = Watcher(store)
        self.tracer = Tracer(store)
        self.judge = Judge(store)
        self.actuator = Actuator(store)
        self.scribe = Scribe(store)
        self.evaluator = Evaluator(store)

    def handle(self, incident_id: str, approve_action: ApproveAction,
               approve_learning: ApproveLearning) -> RunResult:
        case = CaseFile(incident_id=incident_id)
        result = RunResult(case_file=case)

        # --- rescue pipeline (read-only sensing) ---
        self.watcher.run(case, self.mcp)
        if case.latest("detection").data.get("healthy"):
            return result  # nothing wrong; stop
        self.tracer.run(case, self.mcp)
        self.judge.run(case, self.mcp)

        # --- GATE 1: human approves the action ---
        if not approve_action(case):
            return result
        result.actioned = True

        # --- act + report (the only write steps) ---
        self.actuator.run(case, self.mcp)
        self.scribe.run(case, self.mcp)

        # --- Evaluator (async reflection) ---
        scorecard = self.evaluator.evaluate(case, self.mcp)
        result.scorecard = scorecard

        # --- GATE 2: human approves the learning ---
        approved = approve_learning(scorecard)
        for grade in scorecard.weak():
            if grade.agent not in approved:
                continue
            if grade.proposed_lesson:
                self.store.write(new_lesson(grade.agent, "root_cause", grade.proposed_lesson))
                result.applied_lessons.append(f"{grade.agent}: {grade.proposed_lesson}")
            if grade.proposed_definition_edit:
                result.applied_definition_edits.append(f"{grade.agent}: {grade.proposed_definition_edit}")

        return result
