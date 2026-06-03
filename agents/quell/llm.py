"""Gemini reasoning layer (Vertex AI).

Agents gather telemetry deterministically via tools, then ask Gemini to reason
over it and produce their finding. This keeps tool/data handling reliable while
the analysis itself is real LLM reasoning. When USE_LIVE_LLM is false (or the SDK
is unavailable), agents fall back to their deterministic summary so the system
always runs.
"""

from __future__ import annotations

import json
import os

from . import config

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", config.GCP_PROJECT)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", config.GCP_LOCATION)
    from google import genai  # imported lazily so mock mode needs no SDK
    _client = genai.Client()
    return _client


def reason(role: str, lessons: str, observation: dict, instruction: str,
           fallback: str, model: str | None = None) -> str:
    """Ask Gemini to produce a one-line finding from the observation.

    Returns `fallback` verbatim when live LLM is disabled or any error occurs, so
    a run never breaks on the model.
    """
    if not config.USE_LIVE_LLM:
        return fallback
    try:
        client = _get_client()
        prompt = (
            f"You are {role}, one agent in a multi-agent reliability system.\n"
            f"{lessons}\n" if lessons else f"You are {role}.\n"
        )
        prompt += (
            f"\nTelemetry observed (JSON):\n{json.dumps(observation, indent=2)}\n\n"
            f"{instruction}\n"
            "Respond with a single concise sentence, no preamble."
        )
        resp = client.models.generate_content(
            model=model or config.WORKER_MODEL, contents=prompt)
        text = (resp.text or "").strip()
        return text or fallback
    except Exception:
        return fallback
