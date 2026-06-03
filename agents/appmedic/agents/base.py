"""Agent base class.

Each agent = a job (system prompt) + scoped tools + memory access. The `reason`
method has two backends:
  - mock:  deterministic logic, runs with zero credentials (used to verify the
           architecture end-to-end). Implemented per-agent.
  - adk:   real Gemini-on-Agent-Builder call (wired when GEMINI_API_KEY is set).

The base records each agent's own run telemetry to the MCP so the Evaluator can
later grade it from real traces (AppMedic observing itself).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from ..dynatrace.tools import AGENT_TOOLS
from ..memory import LessonStore


class Agent(ABC):
    name: str = "agent"
    task_type: str = "generic"
    role: str = ""  # system-prompt headline; the agent's job in one line

    def __init__(self, store: LessonStore):
        self.store = store
        self.tools = AGENT_TOOLS.get(self.name, [])

    def lessons_context(self) -> str:
        """Lessons this agent reads before acting (Reflexion memory)."""
        return self.store.as_context(self.name, self.task_type)

    def narrate(self, observation: dict, instruction: str, fallback: str) -> str:
        """Produce this agent's finding via Gemini, or the deterministic fallback."""
        from .. import llm
        return llm.reason(self.role, self.lessons_context(), observation, instruction, fallback)

    def run(self, case_file: CaseFile, mcp: MockMCP) -> None:
        from ..otel_trace import agent_span
        from .. import agentic, config
        self._mcp = mcp  # available to finalize() for deterministic backfill
        start = time.perf_counter()
        with agent_span(self.name, case_file.incident_id) as span:
            # Genuine tool-calling path: if the agent exposes a tool catalog and
            # live LLM is on, let Gemini decide which Dynatrace tools to call.
            result = None
            if config.USE_LIVE_LLM and hasattr(self, "tool_callables"):
                sink: dict = {}
                res = agentic.run_agent(
                    self.role, self.lessons_context(), self.instruction,
                    self.observe(case_file), self.tool_callables(mcp, sink))
                if res is not None:
                    result = (res.tool_calls, self.finalize(case_file, sink, res.text))
            # Deterministic fallback (and the default mock path).
            tool_calls, summary = result if result else self.reason(case_file, mcp)
            latency_ms = int((time.perf_counter() - start) * 1000)
            if span is not None:
                span.set_attribute("tool_calls", tool_calls)
                span.set_attribute("latency_ms", latency_ms)
        mcp.record_agent_trace(self.name, tool_calls, latency_ms, summary)

    @abstractmethod
    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        """Do the agent's work. Return (number_of_tool_calls, decision_summary).

        Must append exactly one Entry to the case_file.
        """
        raise NotImplementedError
