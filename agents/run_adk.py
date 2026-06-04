"""Run Quell on the Google ADK (Agent Builder) runtime, live.

This is the hackathon-compliant path: the agents execute on the ADK runtime,
powered by Gemini on Vertex AI, using the OFFICIAL Dynatrace MCP server for their
tools. By default it runs the read-only investigation pipeline (Watcher -> Tracer
-> Judge) over real Grail data.

Requires:
  - gcloud ADC (Vertex), QUELL_GCP_PROJECT
  - .env with DT_ENVIRONMENT + DT_PLATFORM_TOKEN (token needs the storage:*:read
    scopes AND platform-management:environments:read for the MCP server)

    python3 run_adk.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

# load .env
_dotenv = Path(__file__).resolve().parent.parent / ".env"
if _dotenv.exists():
    for line in _dotenv.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
_gcp_project = os.environ.get("QUELL_GCP_PROJECT") or os.environ.get("SENTINEL_GCP_PROJECT", "")
if _gcp_project:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _gcp_project)
os.environ.setdefault(
    "GOOGLE_CLOUD_LOCATION",
    os.environ.get("QUELL_GCP_LOCATION") or os.environ.get("SENTINEL_GCP_LOCATION", "global"),
)

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from quell_adk.agent import root_agent  # noqa: E402


async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="quell")
    session = await runner.session_service.create_session(app_name="quell", user_id="oncall")
    prompt = ("A user segment's checkout is degrading on ShopWave. Investigate the live "
              "Dynatrace data: which segment, the failing service/span/deploy, and the "
              "business and error-budget impact.")
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    print("Running Quell on ADK (Agent Builder) + Gemini + Dynatrace MCP server...\n")
    async for ev in runner.run_async(user_id="oncall", session_id=session.id, new_message=msg):
        who = ev.author or "?"
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if getattr(p, "text", None):
                    print(f"[{who}] {p.text.strip()}\n")
                if getattr(p, "function_call", None):
                    print(f"[{who}] -> tool: {p.function_call.name}")


if __name__ == "__main__":
    import os
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=180))
    except asyncio.TimeoutError:
        print("\n[run_adk] stopped at 180s safety cap")
    finally:
        os._exit(0)
