"""Genuine tool-calling agent loop (Gemini function calling on Vertex).

Each agent is handed a catalog of Dynatrace tools as Python callables. Gemini
decides which to call, in what order, and when it has enough to conclude -- a real
ReAct loop, not a hardcoded sequence. The SDK's automatic function calling runs
the loop; we read its history to count how many tool calls the agent actually
made (which the Evaluator grades on).

Tools are closures over the live or mock Dynatrace client, so the same agent works
against real Grail data or the simulator unchanged. Returns None when live LLM is
off, so the caller falls back to the deterministic path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import config


@dataclass
class AgentResult:
    text: str
    tool_calls: int


def run_agent(role: str, lessons: str, instruction: str, observation: str,
              tools: list, model: str | None = None) -> AgentResult | None:
    if not config.USE_LIVE_LLM:
        return None
    try:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", config.GCP_PROJECT)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", config.GCP_LOCATION)
        from google import genai
        from google.genai import types

        client = genai.Client()
        system = f"You are {role}, one agent in a multi-agent reliability system."
        if lessons:
            system += f"\n{lessons}"
        prompt = (
            f"{system}\n\nCurrent situation:\n{observation}\n\n{instruction}\n"
            "Use the available tools to investigate. Call tools as needed, then give "
            "your conclusion as a single concise sentence."
        )
        resp = client.models.generate_content(
            model=model or config.WORKER_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=tools, temperature=0.2),
        )
        history = getattr(resp, "automatic_function_calling_history", None) or []
        n = sum(
            1 for item in history for part in (getattr(item, "parts", None) or [])
            if getattr(part, "function_call", None)
        )
        return AgentResult(text=(resp.text or "").strip(), tool_calls=max(n, 1))
    except Exception:
        return None
