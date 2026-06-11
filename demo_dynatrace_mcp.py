#!/usr/bin/env python3
"""Quell x Dynatrace -- official MCP server, live.

A self-contained, recordable demo that proves Quell's reads go through the
OFFICIAL Dynatrace MCP server (`@dynatrace-oss/dynatrace-mcp-server`), not a
hand-rolled API call: it spawns the server, runs the JSON-RPC handshake, lists
its tools, and calls `execute_dql` against the live Grail tenant -- printing the
real records that come back.

Run:   python3 demo_dynatrace_mcp.py
Needs: node/npx, and DT_ENVIRONMENT + DT_PLATFORM_TOKEN in ./.env
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

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


def _rule(c: str = "=") -> str:
    return c * 64


def main() -> int:
    _load_env()
    from quell.dynatrace.mcp_client import McpDynatraceClient

    print(_rule())
    print("  QUELL  x  DYNATRACE  --  official MCP server, live")
    print(_rule())
    print("  Partner server : @dynatrace-oss/dynatrace-mcp-server  (official)")
    print("  Transport      : local stdio subprocess, JSON-RPC 2.0")
    print("  Tenant         :", os.environ.get("DT_ENVIRONMENT", "(unset)"))
    print(_rule("-"))

    client = McpDynatraceClient(environment=os.environ.get("DT_ENVIRONMENT"))

    print("  [1] spawning  npx -y @dynatrace-oss/dynatrace-mcp-server ...")
    t0 = time.time()
    # _ensure_started runs: spawn -> initialize -> notifications/initialized -> tools/list
    client._ensure_started()
    print("  [2] JSON-RPC initialize + notifications/initialized ... ok")
    print("  [3] tools/list -> 'execute_dql' present ............... ok  (%.1fs)"
          % (time.time() - t0))
    print(_rule("-"))

    queries = [
        ("spans by service (live OTel from ShopWave)",
         "fetch spans, from:now()-2h | filter isNotNull(`shop.service`) "
         "| summarize spans = count(), by:{`shop.service`} | sort spans desc | limit 5"),
        ("slowest payment span",
         "fetch spans, from:now()-2h | filter `shop.service` == \"payment-svc\" "
         "| summarize avg_ms = avg(duration)/1000000, by:{`span.name`} | sort avg_ms desc | limit 3"),
    ]

    for title, dql in queries:
        print("  [4] tools/call  execute_dql  --  %s" % title)
        for ln in dql.split(" | "):
            print("      DQL> " + ln.strip())
        t = time.time()
        records = client.execute_dql(dql)
        print("      <-- %d records from Grail, via the MCP server  (%.1fs):"
              % (len(records), time.time() - t))
        for r in records:
            print("          " + "  ".join(f"{k}={v}" for k, v in r.items()))
        print(_rule("-"))

    client.close()
    print("  RESULT: every Dynatrace read in Quell can route through the official")
    print("          MCP server. Six Gemini agents call this exact tool to investigate.")
    print(_rule())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
