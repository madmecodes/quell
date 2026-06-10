"""Official-MCP-server-backed Dynatrace client.

This is the COMPLIANCE path for the Dynatrace track: instead of talking to the
Grail query API directly, every DQL read is routed through the official
``@dynatrace-oss/dynatrace-mcp-server`` (the same MCP server Dynatrace ships and
that an LLM agent would use). The server genuinely sits in the live read path of
the hosted console.

Design
------
``McpDynatraceClient`` SUBCLASSES :class:`DynatraceClient` and overrides ONLY
:meth:`execute_dql`. Every typed read method (``rum_experience``,
``worst_span``, ``davis_forecast``, ``metrics_series`` ...) is inherited
unchanged -- they all funnel through ``execute_dql``, so routing that one method
through the MCP server puts the official server in the loop for the entire read
surface while the write methods keep using the parent's platform APIs.

The MCP server is started ONCE as a persistent stdio subprocess
(``npx -y @dynatrace-oss/dynatrace-mcp-server``) with ``DT_ENVIRONMENT`` and
``DT_PLATFORM_TOKEN`` in the environment (the platform token carries the scopes
the server needs, including ``platform-management:environments:read``). On first
use we run the JSON-RPC ``initialize`` + ``notifications/initialized`` handshake
and a ``tools/list`` to confirm the ``execute_dql`` tool is present, then issue
``tools/call`` with ``name="execute_dql"`` and ``arguments={"dqlStatement": q}``.

Verified against server v1.8.7 (probed live):
  * tool name  : ``execute_dql``
  * arg key    : ``dqlStatement`` (required string); optional ``recordLimit``
  * result     : a ``content`` text block whose markdown contains a fenced
                 ```json ... ``` array of record dicts -- the actual records.

Anything that fails (server won't start, handshake breaks, tool errors, no JSON
records found) RAISES, so the factory's smoke test / per-call fallback can drop
back to the direct-DQL :class:`DynatraceClient` and the live console never
breaks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .live_client import DynatraceClient

MCP_COMMAND = ["npx", "-y", "@dynatrace-oss/dynatrace-mcp-server"]
DQL_TOOL = "execute_dql"
DQL_ARG = "dqlStatement"

# A fenced ```json ... ``` block inside the tool's text response carries records.
_JSON_FENCE = re.compile(r"```json\s*(.+?)\s*```", re.DOTALL)


@dataclass
class McpDynatraceClient(DynatraceClient):
    """DynatraceClient whose DQL goes through the official MCP server."""

    handshake_wait: float = 60.0   # max seconds to wait for initialize+tools/list
    call_timeout: float = 45.0     # max seconds to wait for a single execute_dql

    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _pending: dict = field(default_factory=dict, init=False, repr=False)
    _next_id: int = field(default=1, init=False, repr=False)
    _ready: bool = field(default=False, init=False, repr=False)

    # ---- subprocess lifecycle ----------------------------------------------

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None and self._ready:
            return
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._ready:
                return
            self._spawn()
            self._handshake()
            self._ready = True

    def _spawn(self) -> None:
        env = dict(os.environ)
        environment = self.environment or env.get("DT_ENVIRONMENT", "")
        token = env.get("DT_PLATFORM_TOKEN")
        if not environment:
            raise RuntimeError("DT_ENVIRONMENT is required for the MCP server")
        if not token:
            raise RuntimeError("DT_PLATFORM_TOKEN is required for the MCP server")
        env["DT_ENVIRONMENT"] = environment
        env["DT_PLATFORM_TOKEN"] = token
        # Telemetry to Dynatrace's own beacon is noisy and not needed for the path.
        env.setdefault("DT_MCP_DISABLE_TELEMETRY", "true")
        try:
            self._proc = subprocess.Popen(
                MCP_COMMAND,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:  # npx / node not installed
            raise RuntimeError(f"cannot launch MCP server (npx missing?): {e}") from e
        self._pending = {}
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    def _reader(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # non-JSON banner lines, ignore
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                self._pending[mid]["result"] = msg
                self._pending[mid]["event"].set()

    def _send(self, obj: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise RuntimeError("MCP server process is not running")
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def _rpc(self, method: str, params: dict, timeout: float) -> dict:
        """Send a JSON-RPC request and block for its matching response."""
        rid = self._next_id
        self._next_id += 1
        ev = threading.Event()
        self._pending[rid] = {"event": ev, "result": None}
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not ev.wait(timeout):
            self._pending.pop(rid, None)
            raise TimeoutError(f"MCP {method} timed out after {timeout}s")
        msg = self._pending.pop(rid)["result"]
        if msg.get("error"):
            raise RuntimeError(f"MCP {method} error: {msg['error']}")
        return msg.get("result", {})

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _handshake(self) -> None:
        self._next_id = 1
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "quell", "version": "1.0.0"},
            },
            timeout=self.handshake_wait,
        )
        self._notify("notifications/initialized")
        tools = self._rpc("tools/list", {}, timeout=self.handshake_wait)
        names = {t.get("name") for t in tools.get("tools", [])}
        if DQL_TOOL not in names:
            raise RuntimeError(
                f"MCP server does not expose '{DQL_TOOL}'; tools={sorted(n for n in names if n)}"
            )

    # ---- result parsing -----------------------------------------------------

    @staticmethod
    def _parse_records(result: dict) -> list[dict]:
        """Extract the list-of-dicts records from a tools/call result.

        The server returns records inside a fenced ```json``` block in a text
        content part. We pull that block and json.loads it. Falls back to a bare
        JSON array anywhere in the text if the fence is absent.
        """
        if result.get("isError"):
            raise RuntimeError(f"execute_dql returned an error: {result}")
        texts: list[str] = []
        for part in result.get("content", []):
            if part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
        blob = "\n".join(texts)
        if not blob:
            # Some servers may put structured output here instead.
            structured = result.get("structuredContent")
            if isinstance(structured, dict) and isinstance(structured.get("records"), list):
                return structured["records"]
            raise RuntimeError("execute_dql returned no parseable content")
        for m in _JSON_FENCE.finditer(blob):
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(data, list):
                return [r if isinstance(r, dict) else {"value": r} for r in data]
            if isinstance(data, dict) and isinstance(data.get("records"), list):
                return data["records"]
        # Last resort: a raw JSON array somewhere in the text.
        start, end = blob.find("["), blob.rfind("]")
        if 0 <= start < end:
            try:
                data = json.loads(blob[start : end + 1])
                if isinstance(data, list):
                    return [r if isinstance(r, dict) else {"value": r} for r in data]
            except json.JSONDecodeError:
                pass
        raise RuntimeError("execute_dql: could not locate JSON records in MCP response")

    # ---- the one overridden method -----------------------------------------

    def execute_dql(self, query: str, max_wait: float = 20.0) -> list[dict]:
        """Run DQL through the official MCP server's execute_dql tool.

        Same signature and return shape (list[dict]) as the parent so all
        inherited typed read methods work unchanged. Raises on any failure so
        the factory / caller can fall back to the direct client.
        """
        self._ensure_started()
        timeout = max(self.call_timeout, max_wait + 5.0)
        result = self._rpc(
            "tools/call",
            {"name": DQL_TOOL, "arguments": {DQL_ARG: query}},
            timeout=timeout,
        )
        return self._parse_records(result)

    # ---- cleanup ------------------------------------------------------------

    def close(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._ready = False

    def __del__(self):  # best-effort; subprocess is daemon-reaped anyway
        try:
            self.close()
        except Exception:
            pass
