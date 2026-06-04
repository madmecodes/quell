"""Quell as a Google ADK (Agent Builder) application.

This is the hackathon-compliant artifact: agents built on Gemini via the Agent
Development Kit, using the official Dynatrace MCP server for their tools, composed
into a deterministic orchestrated pipeline. Deployable to Vertex AI Agent Engine.

The dashboard/demo uses the lightweight orchestrator in `quell/`; this module
is the same architecture expressed in ADK primitives for deployment.

Run locally:   adk run quell_adk
Deploy:        adk deploy agent_engine quell_adk --project quell-hack-2026 ...

Requires the OAuth client to include the scope `app-engine:apps:run` (the MCP
server requests it on connect) in addition to the storage:*:read scopes.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

WORKER_MODEL = os.environ.get("QUELL_WORKER_MODEL", "gemini-2.5-pro")
EVALUATOR_MODEL = os.environ.get("QUELL_EVALUATOR_MODEL", "gemini-2.5-flash")


def _load_env() -> dict[str, str]:
    """Pass the Dynatrace credentials to the MCP server subprocess.

    Prefer the platform token (DT_PLATFORM_TOKEN) - it carries the admin user's
    Grail bucket access, so the MCP server reads real data. The platform token also
    needs the scope `platform-management:environments:read` for the server's startup
    check. Sources from the project .env if present.
    """
    env = dict(os.environ)
    dotenv = Path(__file__).resolve().parents[2] / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k, v)
    # The MCP server reads DT_ENVIRONMENT + DT_PLATFORM_TOKEN. If only an OAuth
    # client is available, fall back to OAUTH_CLIENT_ID/SECRET.
    if not env.get("DT_PLATFORM_TOKEN"):
        env.setdefault("OAUTH_CLIENT_ID", env.get("DT_OAUTH_CLIENT_ID", ""))
        env.setdefault("OAUTH_CLIENT_SECRET", env.get("DT_OAUTH_CLIENT_SECRET", ""))
    return env


def dynatrace_toolset() -> MCPToolset:
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@dynatrace-oss/dynatrace-mcp-server"],
                env=_load_env(),
            ),
            timeout=60,
        ),
        # Restrict to DQL so the agents run their one query and conclude, rather
        # than exploring all 20 tools (smartscape, etc.) for many minutes.
        tool_filter=["execute_dql"],
    )


# One shared toolset instance; each agent's instruction restricts what it uses.
_dt = dynatrace_toolset()

watcher = LlmAgent(
    model=WORKER_MODEL, name="watcher",
    description="Detects degraded real-user experience by segment.",
    instruction=(
        "Call execute_dql EXACTLY ONCE with this query:\n"
        "fetch bizevents, from:now()-30m | filter `event.type` == \"page.view\" "
        "| summarize apdex = avg(apdex), rage = sum(rage_clicks), by:{segment, journey} "
        "| sort apdex asc | limit 5\n"
        "Then report, in ONE sentence, the worst segment and journey (lowest apdex). "
        "Do not call any other tool. Do not run more queries."),
    tools=[_dt],
)

tracer = LlmAgent(
    model=WORKER_MODEL, name="tracer",
    description="Pinpoints the failing service, span, and deploy.",
    instruction=(
        "Call execute_dql EXACTLY ONCE with this query:\n"
        "fetch spans, from:now()-30m | filter `shop.service` == \"payment-svc\" "
        "| summarize ms = avg(duration)/1000000, deploy = takeAny(`deploy.version`), "
        "by:{`span.name`} | sort ms desc | limit 5\n"
        "Then report, in ONE sentence, the slowest span, its latency in ms, and the deploy. "
        "Do not run more queries."),
    tools=[_dt],
)

judge = LlmAgent(
    model=WORKER_MODEL, name="judge",
    description="Quantifies business impact and forecasts the breach.",
    instruction=(
        "Call execute_dql EXACTLY ONCE with this query:\n"
        "fetch bizevents, from:now()-30m | filter `event.type` == \"checkout.started\" "
        "| summarize users = countDistinct(user_id), carts = count(), revenue = sum(cart_value_usd)\n"
        "Then report, in ONE sentence, the users, carts, and revenue (USD) at risk. "
        "Do not run more queries."),
    tools=[_dt],
)

actuator = LlmAgent(
    model=WORKER_MODEL, name="actuator",
    description="Executes the approved, reversible preventive fix.",
    instruction=(
        "Only after a human has approved the plan, execute the preventive fix: create "
        "a Dynatrace workflow to roll back the implicated deploy, send an event marking "
        "the action, and notify the ops channel. Keep the action reversible."),
    tools=[_dt],
)

scribe = LlmAgent(
    model=WORKER_MODEL, name="scribe",
    description="Writes the prevented-incident report.",
    instruction=(
        "Summarize the whole incident into a prevented-incident report: detection, root "
        "cause, impact, action taken, and impact avoided. Persist it as a Dynatrace "
        "notebook."),
    tools=[_dt],
)

# The orchestrated investigation pipeline on the ADK (Agent Builder) runtime:
# Watcher -> Tracer -> Judge reason over real Dynatrace data through the MCP server,
# up to the human approval gate (the gate + Actuator/Scribe run on the dashboard).
# actuator and scribe are defined above for the full deployment variant; ADK
# enforces single-parent, so the runnable root is the read-only investigation.
root_agent = SequentialAgent(
    name="quell",
    description="Detects, traces, and quantifies a user-experience incident from live "
                "Dynatrace data, before the human approval gate.",
    sub_agents=[watcher, tracer, judge],
)
