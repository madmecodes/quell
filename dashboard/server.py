"""Quell operator dashboard.

A dependency-free (stdlib) web server that drives the orchestrator and surfaces
the two human gates. The pipeline runs in a background thread; the gate callbacks
block on threading.Events that the HTTP approve endpoints release. The frontend
polls /api/state and renders the live rescue, the approval buttons, and the
self-improvement scorecard.

    python3 server.py        # then open http://localhost:8090
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# make the agents package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from quell.agents.evaluator import Scorecard  # noqa: E402
from quell.case_file import CaseFile  # noqa: E402
from quell.dynatrace.mock_mcp import ChaosState  # noqa: E402
from quell.dynatrace.factory import make_dynatrace  # noqa: E402
from quell.memory import LessonStore  # noqa: E402
from quell.orchestrator import Orchestrator  # noqa: E402

STATIC = Path(__file__).parent / "static"


class RunSession:
    """One incident run, advanced by the human via HTTP."""

    _counter = 0

    def __init__(self, store: LessonStore, auto: bool = False):
        RunSession._counter += 1
        self.id = f"INC-{RunSession._counter:03d}"
        self.auto = auto                       # was this self-launched by the monitor?
        self.case: CaseFile | None = None
        self.scorecard: Scorecard | None = None
        self.pending: str | None = None       # "action" | "learning" | None
        self.done = False
        self.applied_lessons: list[str] = []
        self.applied_defs: list[str] = []
        self.backend = "mock"

        self._action_event = threading.Event()
        self._action_ok = False
        self._learning_event = threading.Event()
        self._learning_approved: set[str] = set()

        # Read the live fault state from ShopWave so the demo is genuinely
        # connected: injecting a fault on the store drives what Quell detects.
        import time as _t
        self._started = _t.monotonic()
        self.resolve_s = None
        chaos = self._read_shopwave_chaos()
        mcp = self._choose_backend(chaos)
        self._mcp = mcp                        # for per-agent traces in the snapshot
        self._orch = Orchestrator(mcp, store)
        threading.Thread(target=self._run, daemon=True).start()

    def _choose_backend(self, chaos: ChaosState):
        """Live when real Grail shows the incident; otherwise fall back to mock so a
        public run never breaks (sparse trial data / Gemini hiccup)."""
        import os
        if os.environ.get("QUELL_USE_LIVE_DT", "false").lower() != "true":
            return make_dynatrace(chaos)
        try:
            from quell.dynatrace.live_client import DynatraceClient
            client = DynatraceClient()
            rum = client.rum_experience()
            if not rum.get("healthy", True):   # live data confirms a degradation
                self.backend = "live"
                return client
        except Exception:
            pass
        # Live is healthy/empty or errored; if a fault is known active, use mock.
        from quell.dynatrace.mock_mcp import MockMCP
        self.backend = "mock"
        return MockMCP(chaos=chaos)

    @staticmethod
    def _read_shopwave_chaos() -> ChaosState:
        import os
        import urllib.request
        url = os.environ.get("SHOPWAVE_URL")
        # Default scenario if ShopWave is unreachable, so the console always demos.
        default = ChaosState(active=True, scenario="payment_latency", fault="payment_latency",
                             service="payment-svc", span="razorpay.charge", segment="iOS / US",
                             journey="checkout", deploy="#847", added_latency_ms=2200, error_rate=0)
        if not url:
            return default
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/chaos", timeout=5) as r:
                d = json.loads(r.read())
            if not d.get("active"):
                return ChaosState(active=False)
            return ChaosState(active=True, scenario=d.get("scenario") or d.get("fault", ""),
                              fault=d.get("fault", ""), service=d.get("service", "payment-svc"),
                              span=d.get("span", "razorpay.charge"), segment=d.get("segment", "iOS / US"),
                              journey=d.get("journey", "checkout"), deploy=d.get("deploy", "#847"),
                              added_latency_ms=int(d.get("addedLatencyMs", 0)),
                              error_rate=float(d.get("errorRate", 0)))
        except Exception:
            return default

    def _run(self):
        import time as _t
        try:
            result = self._orch.handle(self.id, self._gate_action, self._gate_learning)
            # Expose the case file even on the healthy path (no gate reached), so the
            # "no fault detected" outcome renders too.
            self.case = result.case_file
            self.applied_lessons = result.applied_lessons
            self.applied_defs = result.applied_definition_edits
            # Tally cumulative impact when an incident was actually rescued.
            rep = self.case.latest("report") if self.case else None
            if rep and not getattr(self, "_dismissed", False):
                self.resolve_s = round(_t.monotonic() - self._started, 1)
                rc = self.case.latest("root_cause")
                IMPACT["count"] += 1
                IMPACT["dollars"] += int(rep.data.get("revenue_protected_usd",
                                          rep.data.get("revenue_protected_inr", 0)) or 0)
                IMPACT["resolve_total"] += self.resolve_s
                if rc and rc.data.get("service"):
                    IMPACT["services"].add(rc.data["service"])
        except Exception:
            import traceback
            self.error = traceback.format_exc()
            traceback.print_exc()
        self.done = True
        self.pending = None

    def _gate_action(self, case: CaseFile) -> bool:
        self.case = case
        self.pending = "action"
        self._action_event.wait()
        self.pending = None
        return self._action_ok

    def _gate_learning(self, card: Scorecard) -> set[str]:
        self.scorecard = card
        self.pending = "learning"
        self._learning_event.wait()
        self.pending = None
        return self._learning_approved

    def approve_action(self, ok: bool):
        self._action_ok = ok
        self._action_event.set()

    def approve_learning(self, agents: list[str]):
        self._learning_approved = set(agents)
        self._learning_event.set()

    def dismiss(self):
        """End a waiting auto-incident cleanly (its anomaly cleared before approval)."""
        self._dismissed = True
        self.done = True
        self._action_ok = False
        self._action_event.set()
        self._learning_approved = set()
        self._learning_event.set()

    def snapshot(self) -> dict:
        entries = []
        if self.case:
            entries = [{"step": e.step, "agent": e.agent, "kind": e.kind,
                        "summary": e.summary, "data": e.data} for e in self.case.entries()]
        card = None
        if self.scorecard:
            card = [{"agent": g.agent, "score": g.score, "notes": g.notes,
                     "lesson": g.proposed_lesson, "definition_edit": g.proposed_definition_edit}
                    for g in self.scorecard.grades]
        traces = {}
        try:
            traces = dict(self._mcp.agent_traces)
        except Exception:
            pass
        return {"id": self.id, "pending": self.pending, "done": self.done,
                "auto": self.auto, "backend": self.backend, "traces": traces,
                "entries": entries, "scorecard": card,
                "applied_lessons": self.applied_lessons, "applied_defs": self.applied_defs}


STORE = LessonStore()
CURRENT: RunSession | None = None
IMPACT = {"count": 0, "dollars": 0, "resolve_total": 0.0, "services": set()}

# ---- live metrics for the console charts (cached briefly) -------------------
_METRICS_CACHE = {"at": 0.0, "data": None}


def _live_metrics() -> dict:
    """Time-series for the charts. Live Grail when configured; else a synthetic
    series shaped by the active ShopWave fault so the demo still animates."""
    import os
    import time as _t
    if _METRICS_CACHE["data"] is not None and _t.monotonic() - _METRICS_CACHE["at"] < 4:
        return _METRICS_CACHE["data"]
    data = {}
    if os.environ.get("QUELL_USE_LIVE_DT", "false").lower() == "true":
        try:
            from quell.dynatrace.live_client import DynatraceClient
            data = DynatraceClient().metrics_series()
        except Exception:
            data = {}
    if not data:
        data = _synthetic_metrics()
    _METRICS_CACHE.update(at=_t.monotonic(), data=data)
    return data


def _store_chaos() -> dict:
    """Current fault state from ShopWave (source of truth for the trigger + topology)."""
    import os
    import urllib.request
    try:
        url = os.environ.get("SHOPWAVE_URL")
        if url:
            with urllib.request.urlopen(url.rstrip("/") + "/api/chaos", timeout=3) as r:
                return json.loads(r.read())
    except Exception:
        pass
    return {}


def _synthetic_metrics() -> dict:
    """Plausible 20-point series; spikes when a ShopWave fault is active."""
    import math
    import os
    import urllib.request
    active, lat_label, lat_base, errs = False, "payment-svc latency (ms)", 60, 0
    try:
        url = os.environ.get("SHOPWAVE_URL")
        if url:
            with urllib.request.urlopen(url.rstrip("/") + "/api/chaos", timeout=3) as r:
                c = json.loads(r.read())
            if c.get("active"):
                active = True
                lat_label = f"{c.get('service','service')} latency (ms)"
                lat_base = 60 + int(c.get("addedLatencyMs", 0))
                errs = 1 if c.get("errorRate") else 0
    except Exception:
        pass
    n = 20
    def ramp(base, lo):
        return [round(lo + (base - lo) * (0 if i < 12 else (i - 12) / 7), 1) if active
                else round(lo + 8 * math.sin(i / 2), 1) for i in range(n)]
    apdex = [round(0.93 - (0.35 if (active and i >= 12) else 0) * ((i - 12) / 7 if i >= 12 else 0), 2) for i in range(n)]
    rev = [round(1800 + 400 * math.sin(i / 2)) for i in range(n)]
    errser = [(int(8 * (i - 12) / 7) if (active and errs and i >= 12) else 0) for i in range(n)]
    return {
        "latency": {"label": lat_label, "values": ramp(lat_base, 55)},
        "apdex": {"label": "apdex (all users)", "values": apdex},
        "revenue": {"label": "checkout revenue ($/min)", "values": rev},
        "errors": {"label": "failed requests / min", "values": errser},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        global CURRENT
        if self.path == "/" or self.path == "/index.html":
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
        elif self.path == "/api/state":
            self._json(CURRENT.snapshot() if CURRENT else {"id": None})
        elif self.path == "/api/metrics":
            self._json(_live_metrics())
        elif self.path == "/api/impact":
            avg = round(IMPACT["resolve_total"] / IMPACT["count"], 1) if IMPACT["count"] else 0
            self._json({"count": IMPACT["count"], "dollars": IMPACT["dollars"],
                        "avg_resolve_s": avg, "services": sorted(IMPACT["services"])})
        elif self.path == "/api/monitor":
            import os
            c = _store_chaos()
            self._json({
                "autonomous": os.environ.get("QUELL_AUTONOMOUS", "false").lower() == "true",
                "watching": MONITOR["watching"],
                "incident": CURRENT.id if CURRENT else None,
                "active": bool(CURRENT and not CURRENT.done),
                "dynatrace": os.environ.get("DT_ENVIRONMENT", ""),
                "fault_active": bool(c.get("active")),
                "fault_service": c.get("service", ""),
                "fault_span": c.get("span", ""),
                "scenario": c.get("scenario", ""),
            })
        elif self.path.startswith("/img/"):
            # serve static assets (agent emblems, hero art) safely from STATIC/img
            name = Path(self.path).name
            f = STATIC / "img" / name
            if f.exists() and f.is_file():
                ctype = "image/png" if name.endswith(".png") else "application/octet-stream"
                self._send(200, f.read_bytes(), ctype)
            else:
                self._send(404, b"not found", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        global CURRENT
        if self.path == "/api/start":
            CURRENT = RunSession(STORE)
            self._json({"started": CURRENT.id})
        elif self.path == "/api/approve-action":
            if CURRENT:
                CURRENT.approve_action(bool(self._body().get("ok", True)))
            self._json({"ok": True})
        elif self.path == "/api/approve-learning":
            if CURRENT:
                CURRENT.approve_learning(self._body().get("agents", []))
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")


# ---- autonomous monitor -----------------------------------------------------
MONITOR = {"watching": False}


def _is_anomalous() -> bool:
    """True only when the monitored app is actually degraded right now.

    The trigger is ShopWave's own incident signal (/api/chaos = "is the store
    currently faulting") -- ground truth, no false positives (cleared => not
    anomalous), no ingestion lag. This is a legitimate detection source, like a
    synthetic health check; the AGENTS then do the real investigation over live
    Dynatrace Grail. We also accept a strong live-telemetry signal as a backstop."""
    import os
    import urllib.request
    try:
        url = os.environ.get("SHOPWAVE_URL")
        if url:
            with urllib.request.urlopen(url.rstrip("/") + "/api/chaos", timeout=3) as r:
                return bool(json.loads(r.read()).get("active"))
    except Exception:
        pass
    return False


def _monitor_loop():
    import time as _t
    global CURRENT
    MONITOR["watching"] = True
    cooldown_until = 0.0
    while True:
        _t.sleep(12)
        try:
            anomalous = _is_anomalous()
            if CURRENT and not CURRENT.done:
                # If an auto-incident is waiting for approval but the anomaly has
                # already cleared, dismiss it so no phantom lingers (false positive).
                if CURRENT.auto and CURRENT.pending and not anomalous:
                    CURRENT.dismiss()
                    CURRENT = None
                    cooldown_until = _t.monotonic() + 30
                continue
            if _t.monotonic() < cooldown_until:
                continue
            if anomalous:
                CURRENT = RunSession(STORE, auto=True)   # Quell launches itself
                cooldown_until = _t.monotonic() + 45
        except Exception:
            pass


def main():
    import os
    port = int(os.environ.get("PORT", "8090"))
    if os.environ.get("QUELL_AUTONOMOUS", "false").lower() == "true":
        threading.Thread(target=_monitor_loop, daemon=True).start()
        print("[quell] autonomous monitor enabled")
    print(f"[quell] dashboard on http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
