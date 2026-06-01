"""Choose the Dynatrace backend at runtime.

Default is the mock (deterministic, no data dependency) so the demo always runs.
Set SENTINEL_USE_LIVE_DT=true (with .env credentials loaded and ShopWave telemetry
flowing) to point the agents at the real Grail via DynatraceClient. Both expose
the identical method surface, so the agents are unchanged.
"""

from __future__ import annotations

import os

from .mock_mcp import ChaosState, MockMCP


def make_dynatrace(chaos: ChaosState | None = None):
    if os.environ.get("SENTINEL_USE_LIVE_DT", "false").lower() == "true":
        from .live_client import DynatraceClient
        return DynatraceClient()
    return MockMCP(chaos=chaos or ChaosState())
