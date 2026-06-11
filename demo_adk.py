#!/usr/bin/env python3
"""Quell on Google's Agent Development Kit (ADK) -- live, with the Dynatrace MCP server.

Runs the real ADK application from `agents/quell_adk/agent.py`: a SequentialAgent
(Watcher -> Tracer -> Judge), each a Gemini LlmAgent whose ONLY tool is the
official Dynatrace MCP server's `execute_dql`. The agents query live Grail and
report -- this single clip proves ADK + partner MCP + Gemini together.

Run:    python3 demo_adk.py
        QUELL_WORKER_MODEL=gemini-3.1-pro-preview python3 demo_adk.py   # Gemini 3
Needs:  node/npx, google-adk, and DT_ENVIRONMENT + DT_PLATFORM_TOKEN + a Vertex
        project (SENTINEL_GCP_PROJECT) in ./.env
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agents"))


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()
# Gemini via Vertex AI.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault(
    "GOOGLE_CLOUD_PROJECT",
    os.environ.get("SENTINEL_GCP_PROJECT") or os.environ.get("QUELL_GCP_PROJECT", ""))
os.environ.setdefault(
    "GOOGLE_CLOUD_LOCATION",
    os.environ.get("SENTINEL_GCP_LOCATION") or os.environ.get("QUELL_GCP_LOCATION", "global"))

MODEL = os.environ.get("QUELL_WORKER_MODEL", "gemini-2.5-pro")


def _rule(c: str = "=") -> str:
    return c * 64


async def main() -> int:
    from quell_adk.agent import root_agent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    print(_rule())
    print("  QUELL on Google ADK (Agent Development Kit) -- live")
    print(_rule())
    print("  Runtime  : google-adk  SequentialAgent(watcher -> tracer -> judge)")
    print("  Model    :", MODEL, "(Gemini on Vertex AI)")
    print("  Tools    : official Dynatrace MCP server -> execute_dql (live Grail)")
    print("  Tenant   :", os.environ.get("DT_ENVIRONMENT", "(unset)"))
    print(_rule("-"))

    runner = InMemoryRunner(agent=root_agent, app_name="quell")
    session = await runner.session_service.create_session(app_name="quell", user_id="demo")
    message = types.Content(
        role="user",
        parts=[types.Part(text="Investigate the current ShopWave user experience and report your finding.")])

    async for event in runner.run_async(
            user_id="demo", session_id=session.id, new_message=message):
        author = getattr(event, "author", None) or "agent"
        content = getattr(event, "content", None)
        if not content:
            continue
        for part in (getattr(content, "parts", None) or []):
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)
            text = getattr(part, "text", None)
            if fc is not None:
                args = dict(getattr(fc, "args", {}) or {})
                dql = args.get("dqlStatement") or args.get("dql") or args
                print(f"  [{author}]  calls Dynatrace MCP -> {fc.name}")
                if isinstance(dql, str):
                    print(f"             DQL> {dql[:110]}")
            elif fr is not None:
                print(f"  [{author}]  <- {getattr(fr,'name','execute_dql')} returned live Grail records")
            elif text and text.strip():
                print(f"  [{author}]  concludes: {text.strip()}")
    print(_rule("-"))
    print("  Built with ADK + Gemini + the official Dynatrace MCP server.")
    print("  Deployable to Vertex AI Agent Engine:  adk deploy agent_engine quell_adk")
    print(_rule())
    # ADK's MCPToolset leaves the npx subprocess open and asyncio's shutdown blocks
    # on it, so the process would hang after printing. Exit hard for a clean demo end.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
