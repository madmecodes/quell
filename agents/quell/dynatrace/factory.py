"""Choose the Dynatrace backend at runtime.

Default is the mock (deterministic, no data dependency) so the demo always runs.
Set QUELL_USE_LIVE_DT=true (with .env credentials loaded and ShopWave telemetry
flowing) to point the agents at the real Grail.

Live read path selection
------------------------
When live, there are two read backends, both exposing the identical typed method
surface so the agents are unchanged:

  * Direct DQL (``DynatraceClient``) -- talks to the Grail query API directly.
  * Official MCP (``McpDynatraceClient``) -- routes every DQL through the
    official ``@dynatrace-oss/dynatrace-mcp-server``. This is the compliance
    path for the Dynatrace track and is selected with QUELL_USE_MCP=true.

The MCP path is best-effort and SAFE: we construct it and run a one-line smoke
read; if either the subprocess/handshake or the smoke read fails, we silently
fall back to the direct ``DynatraceClient`` so the live console never breaks.
"""

from __future__ import annotations

import os

from .mock_mcp import ChaosState, MockMCP


def make_dynatrace(chaos: ChaosState | None = None):
    if os.environ.get("QUELL_USE_LIVE_DT", "false").lower() == "true":
        from .live_client import DynatraceClient

        # Compliance path: put the official Dynatrace MCP server in the live read
        # loop when asked, but never at the cost of the demo -- any failure falls
        # back to the direct-DQL client below.
        if os.environ.get("QUELL_USE_MCP", "false").lower() == "true":
            try:
                from .mcp_client import McpDynatraceClient

                client = McpDynatraceClient()
                # One-line smoke read THROUGH the MCP server. If this returns,
                # the official server genuinely served live data.
                client.execute_dql("fetch bizevents, from:now()-5m | summarize n=count()")
                print("[quell] Dynatrace read path: official MCP server (execute_dql)")
                return client
            except Exception as e:  # subprocess, handshake, tool, or parse failure
                print(f"[quell] MCP read path unavailable ({e}); falling back to direct DQL")

        return DynatraceClient()
    return MockMCP(chaos=chaos or ChaosState())
