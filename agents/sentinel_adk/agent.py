"""Sentinel as a Google ADK (Agent Builder) application.

This is the hackathon-compliant artifact: agents built on Gemini via the Agent
Development Kit, using the official Dynatrace MCP server for their tools, composed
into a deterministic orchestrated pipeline. Deployable to Vertex AI Agent Engine.

The dashboard/demo uses the lightweight orchestrator in `sentinel/`; this module
is the same architecture expressed in ADK primitives for deployment.

Run locally:   adk run sentinel_adk
Deploy:        adk deploy agent_engine sentinel_adk --project sentinel-hack-2026 ...

Requires the OAuth client to include the scope `app-engine:apps:run` (the MCP
server requests it on connect) in addition to the storage:*:read scopes.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

WORKER_MODEL = os.environ.get("SENTINEL_WORKER_MODEL", "gemini-2.5-pro")
EVALUATOR_MODEL = os.environ.get("SENTINEL_EVALUATOR_MODEL", "gemini-2.5-flash")


def _load_env() -> dict[str, str]:
    """Pass the Dynatrace credentials to the MCP server subprocess.

    The MCP server reads OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET (no DT_ prefix)
    and DT_ENVIRONMENT. We source from the project .env if present.
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
    # map our names to what the MCP server expects
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
    )


# One shared toolset instance; each agent's instruction restricts what it uses.
_dt = dynatrace_toolset()

watcher = LlmAgent(
    model=WORKER_MODEL, name="watcher",
    description="Detects degraded real-user experience by segment.",
    instruction=(
        "You watch ShopWave's real-user telemetry in Dynatrace. Use execute_dql to "
        "query recent bizevents of type 'page.view' and find any user segment whose "
        "apdex dropped or rage-clicks spiked. Report the segment, journey, and when it "
        "began. If everything is healthy, say so and stop."),
    tools=[_dt],
)

tracer = LlmAgent(
    model=WORKER_MODEL, name="tracer",
    description="Pinpoints the failing service, span, and deploy.",
    instruction=(
        "Given the degraded segment from the watcher, use execute_dql over Dynatrace "
        "spans to find the service and span with abnormal latency or errors, and the "
        "deploy that correlates. Report a single most-likely root cause."),
    tools=[_dt],
)

judge = LlmAgent(
    model=WORKER_MODEL, name="judge",
    description="Quantifies business impact and forecasts the breach.",
    instruction=(
        "Use execute_dql over checkout bizevents to quantify users affected, carts at "
        "risk, and revenue at risk for the impacted segment. State the impact in plain "
        "numbers and the time until SLA breach."),
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

# The orchestrated pipeline. The human approval gate before the actuator is enforced
# by the deploying surface (the dashboard, or an Agent Engine approval step).
root_agent = SequentialAgent(
    name="sentinel",
    description="Detects, traces, quantifies, and prevents user-experience incidents.",
    sub_agents=[watcher, tracer, judge, actuator, scribe],
)
