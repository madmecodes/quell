"""Evaluator: grade the agents from their OWN Dynatrace traces, then recommend.

Runs async AFTER the rescue pipeline completes (off the hot path). Reads each
agent's run telemetry (tool calls, latency, decision) and produces a scorecard
with two kinds of improvement per weak agent:
  1. a verbal LESSON  -> written to that agent's episodic memory (Reflexion)
  2. a DEFINITION edit -> a recommended change to the agent's system prompt/tools

Both are only APPLIED after the human approves at Gate 2. The Evaluator must run
on a DIFFERENT model than the graded agents to avoid self-preference bias; in
mock mode it is deterministic rubric logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent

# expected tool-call budget per agent; over budget => efficiency ding
EFFICIENCY_BUDGET = {"watcher": 2, "tracer": 3, "judge": 3, "actuator": 3, "scribe": 1}


@dataclass
class AgentGrade:
    agent: str
    score: float                       # 0..1
    notes: str
    proposed_lesson: str | None = None
    proposed_definition_edit: str | None = None


@dataclass
class Scorecard:
    incident_id: str
    grades: list[AgentGrade] = field(default_factory=list)

    def weak(self) -> list[AgentGrade]:
        return [g for g in self.grades if g.proposed_lesson or g.proposed_definition_edit]


class Evaluator(Agent):
    name = "evaluator"
    task_type = "evaluation"
    role = (
        "Grade every agent in the run using their own execution traces. Score "
        "correctness and efficiency, and for any weak agent propose a concrete "
        "lesson (for its memory) and a definition edit (for the human to apply)."
    )

    def evaluate(self, case_file: CaseFile, mcp: MockMCP) -> Scorecard:
        traces = mcp.get_agent_traces(case_file.incident_id)   # tool call: read own traces
        card = Scorecard(incident_id=case_file.incident_id)

        for agent, budget in EFFICIENCY_BUDGET.items():
            trace = traces.get(agent)
            if not trace:
                continue
            score = 1.0
            notes = []

            over = trace["tool_calls"] - budget
            if over > 0:
                score -= 0.15 * over
                notes.append(f"used {trace['tool_calls']} tool calls (budget {budget})")

            grade = AgentGrade(agent=agent, score=round(max(score, 0.0), 2),
                               notes="; ".join(notes) or "within budget, on target")

            # Tracer-specific: if it inspected services one-by-one, teach it to use
            # the single cross-service scan to find the worst span in one query.
            if agent == "tracer" and over > 0:
                grade.proposed_lesson = (
                    "Use scan_all_spans to find the worst span across all services in one "
                    "query, instead of inspecting each service individually."
                )
                grade.proposed_definition_edit = (
                    "Add to Tracer's instructions: 'Call scan_all_spans once and trust its "
                    "ranked result; only inspect a single service if the scan is ambiguous.'"
                )
            card.grades.append(grade)

        case_file.append(self.name, "evaluation",
                         f"Graded {len(card.grades)} agents; {len(card.weak())} improvement(s) proposed.",
                         {"grades": [g.__dict__ for g in card.grades]})
        return card

    def reason(self, case_file, mcp):  # not used; evaluator uses evaluate()
        raise NotImplementedError("Evaluator runs via evaluate(), not the pipeline reason().")
