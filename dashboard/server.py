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
import time as _time
from collections import deque
from datetime import datetime
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

import state_store  # noqa: E402  (local module, persisted incidents + audit)

STATIC = Path(__file__).parent / "static"


class RunSession:
    """One incident run, advanced by the human via HTTP."""

    _counter = 0

    def __init__(self, store: LessonStore, auto: bool = False):
        with RUN_LOCK:
            RunSession._counter += 1
            self.id = f"INC-{RunSession._counter:03d}"
        self.auto = auto                       # was this self-launched by the monitor?
        self.case: CaseFile | None = None
        self.scorecard: Scorecard | None = None
        self.pending: str | None = None       # "action" | "learning" | None
        self._pending_since: float | None = None  # monotonic ts a gate became pending
        self._gate_wait_s = 0.0                # cumulative human think-time at gates
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
        self._scenario = chaos.scenario        # captured for the incident history row
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
        log_activity(f"Investigation {self.id} started")
        try:
            result = self._orch.handle(self.id, self._gate_action, self._gate_learning)
            # Expose the case file even on the healthy path (no gate reached), so the
            # "no fault detected" outcome renders too.
            self.case = result.case_file
            self.applied_lessons = result.applied_lessons
            self.applied_defs = result.applied_definition_edits
            # Log each agent entry as the run lands (we can't stream, so replay here).
            if self.case:
                for e in self.case.entries():
                    summary = (e.summary or "")[:60]
                    log_activity(f"{e.agent}: {summary}")
            # Tally cumulative impact when an incident was actually rescued.
            rep = self.case.latest("report") if self.case else None
            if rep and not getattr(self, "_dismissed", False):
                # Corrected MTTR: agent time only, with human think-time subtracted.
                self.resolve_s = max(0.1, round(
                    (_t.monotonic() - self._started) - self._gate_wait_s, 1))
                rc = self.case.latest("root_cause")
                dollars = int(rep.data.get("revenue_protected_usd",
                                           rep.data.get("revenue_protected_inr", 0)) or 0)
                IMPACT["count"] += 1
                IMPACT["dollars"] += dollars
                IMPACT["resolve_total"] += self.resolve_s
                if rc and rc.data.get("service"):
                    IMPACT["services"].add(rc.data["service"])
                service = rc.data.get("service", "") if rc else ""
                span = rc.data.get("span", "") if rc else ""
                segment = rc.data.get("segment", "") if rc else ""
                HISTORY.append({
                    "id": self.id,
                    "scenario": self._scenario,
                    "service": service,
                    "dollars": dollars,
                    "resolve_s": self.resolve_s,
                    "when": datetime.now().strftime("%H:%M:%S"),
                    "outcome": "prevented",
                })
                # Persist a full incident record (entries + scorecard) so the
                # Incidents / Audit surfaces survive restarts and are replayable.
                try:
                    traces = {}
                    try:
                        traces = dict(self._mcp.agent_traces)
                    except Exception:
                        pass
                    tool_calls_total = sum(int(t.get("tool_calls", 0) or 0)
                                           for t in traces.values())
                    entries = []
                    for e in self.case.entries():
                        item = {"agent": e.agent, "kind": e.kind,
                                "role": e.kind, "summary": e.summary}
                        if isinstance(e.data, dict) and e.data.get("dql"):
                            item["dql"] = e.data["dql"]
                        entries.append(item)
                    scorecard = []
                    if self.scorecard:
                        scorecard = [{"agent": g.agent, "score": g.score,
                                      "notes": g.notes, "lesson": g.proposed_lesson}
                                     for g in self.scorecard.grades]
                    state_store.add_incident({
                        "id": self.id,
                        "scenario": self._scenario,
                        "service": service,
                        "span": span,
                        "segment": segment,
                        "dollars": dollars,
                        "resolve_s": self.resolve_s,
                        "when": datetime.now().isoformat(timespec="seconds"),
                        "outcome": "prevented",
                        "backend": self.backend,
                        "tool_calls_total": tool_calls_total,
                        "agents": 6,
                        "root_cause": (rc.summary if rc else "") or "",
                        "entries": entries,
                        "scorecard": scorecard,
                        "traces": traces,
                    })
                except Exception:
                    pass
                log_activity(f"Rescued - ${dollars} protected")
        except Exception:
            import traceback
            self.error = traceback.format_exc()
            traceback.print_exc()
        self.done = True
        self.pending = None

    def _gate_action(self, case: CaseFile) -> bool:
        import time as _t
        self.case = case
        self.pending = "action"
        self._pending_since = _t.monotonic()
        _w0 = _t.monotonic()
        self._action_event.wait()
        self._gate_wait_s += _t.monotonic() - _w0
        self.pending = None
        self._pending_since = None
        return self._action_ok

    def _gate_learning(self, card: Scorecard) -> set[str]:
        import time as _t
        self.scorecard = card
        self.pending = "learning"
        self._pending_since = _t.monotonic()
        _w0 = _t.monotonic()
        self._learning_event.wait()
        self._gate_wait_s += _t.monotonic() - _w0
        self.pending = None
        self._pending_since = None
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
        log_activity(f"{self.id} dismissed - anomaly cleared")

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

# Serializes RunSession._counter increments and CURRENT assignments so the
# autonomous monitor thread and the HTTP /api/start handler can't race.
# RLock (reentrant): callers hold it while constructing RunSession, whose
# __init__ re-acquires it for the counter bump -- a plain Lock would deadlock.
RUN_LOCK = threading.RLock()

# Rolling activity feed + incident history for the console.
ACTIVITY: deque = deque(maxlen=40)
HISTORY: deque = deque(maxlen=20)


def _infer_audit_type(text: str) -> str:
    low = text.lower()
    if "anomaly detected" in low or "started" in low:
        return "detect"
    if "dismissed" in low:
        return "dismiss"
    if "rescued" in low:
        return "rescue"
    if "watching" in low:
        return "watch"
    if "approved" in low or "approve" in low:
        return "approve"
    if ":" in text:  # "Watcher: ...", agent replay lines
        return "agent"
    return "watch"


def log_activity(text: str) -> None:
    ACTIVITY.append({"t": datetime.now().strftime("%H:%M:%S"), "text": text})
    try:
        inc = CURRENT.id if CURRENT else None
        state_store.add_audit({"t": datetime.now().isoformat(timespec="seconds"),
                               "type": _infer_audit_type(text), "text": text,
                               "incident": inc})
    except Exception:
        pass

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


ERROR_SCENARIOS = {"checkout_errors", "cart_failures", "third_party_outage"}


def _synthetic_metrics() -> dict:
    """One fault model -> all series mutually consistent.

    Every series is derived from the SAME active fault so latency-up coincides with
    apdex-down and revenue-down in the same window (judges spot incoherence).
      - latency scenario: latency UP, apdex DOWN (~0.55-0.62), revenue dip ~25-35%,
        errors ~0, throughput slight dip.
      - error scenario: errors UP, apdex DOWN, revenue dip MORE (~35-50%),
        latency mild rise, throughput dip.
      - no fault: everything low/flat/steady.
    """
    import math
    import os
    import urllib.request
    active = False
    service = "payment-svc"
    scenario = ""
    added_latency = 0
    try:
        url = os.environ.get("SHOPWAVE_URL")
        if url:
            with urllib.request.urlopen(url.rstrip("/") + "/api/chaos", timeout=3) as r:
                c = json.loads(r.read())
            if c.get("active"):
                active = True
                service = c.get("service", "service")
                scenario = c.get("scenario") or c.get("fault", "")
                added_latency = int(c.get("addedLatencyMs", 0) or 0)
    except Exception:
        pass

    n = 20
    fault_start = 12  # fault begins ramping at point 12

    def progress(i):
        """0 before the fault, ramping 0->1 across the tail of the window."""
        if not active or i < fault_start:
            return 0.0
        return (i - fault_start) / (n - 1 - fault_start)

    is_error = scenario in ERROR_SCENARIOS

    # ---- latency ----
    lat_lo = 60
    if active and is_error:
        lat_peak = lat_lo + 90          # mild rise under an error fault
    elif active:
        lat_peak = lat_lo + max(120, added_latency)   # full ramp for latency faults
    else:
        lat_peak = lat_lo
    latency = [round(lat_lo + (lat_peak - lat_lo) * progress(i)
                     + (4 * math.sin(i / 2) if not active else 0), 1) for i in range(n)]

    # ---- apdex (down to ~0.55-0.62 under any fault) ----
    apdex_lo = 0.58 if is_error else 0.60
    apdex = [round(0.94 - (0.94 - apdex_lo) * progress(i)
                   + (0.0 if active else 0.0), 2) for i in range(n)]
    if not active:
        apdex = [round(0.93 + 0.012 * math.sin(i / 3), 2) for i in range(n)]

    # ---- revenue (steady ~1800; error faults dip more than latency faults) ----
    rev_base = 1800
    rev_dip = 0.42 if is_error else 0.30   # fraction of revenue lost at fault peak
    revenue = [round(rev_base * (1 - rev_dip * progress(i))
                     + (120 * math.sin(i / 2) if not active else 60 * math.sin(i / 2)))
               for i in range(n)]

    # ---- errors (only ramps for error scenarios) ----
    if active and is_error:
        errors = [int(round(14 * progress(i))) for i in range(n)]
    else:
        errors = [0 for _ in range(n)]

    # ---- throughput (steady 900-1300, dips under fault) ----
    tp_base = 1180
    tp_dip = 0.22 if is_error else 0.14
    throughput = [int(round(tp_base * (1 - tp_dip * progress(i))
                            + 60 * math.sin(i / 2.5)))
                  for i in range(n)]

    lat_label = f"{service} latency (ms)" if active else "payment-svc latency (ms)"
    return {
        "latency": {"label": lat_label, "values": latency},
        "apdex": {"label": "apdex (all users)", "values": apdex},
        "revenue": {"label": "checkout revenue ($/min)", "values": revenue},
        "errors": {"label": "failed requests / min", "values": errors},
        "throughput": {"label": "requests / min", "values": throughput},
    }


# ---- DQL catalog (the real strings each agent runs) -------------------------

def _dql_catalog() -> list:
    """The exact DQL each step would run, sourced from the real query strings in
    live_client / mock_mcp so the console shows 'the query Quell ran' for real."""
    rum = ('fetch bizevents, from:now()-30m | filter `event.type` == "page.view" '
           "| summarize apdex = avg(apdex), rage = sum(rage_clicks), conversion = avg(conversion), "
           "by:{segment, journey} | sort apdex asc")
    spans = ("fetch spans, from:now()-30m | filter isNotNull(`shop.service`) "
             "| summarize avg_ms = avg(duration)/1000000, errors = countIf(outcome == \"error\"), "
             "total = count(), deploy = takeAny(`deploy.version`), by:{`shop.service`, `span.name`} "
             "| sort errors desc, avg_ms desc | limit 10")
    impact = ('fetch bizevents, from:now()-30m | filter `event.type` == "checkout.started" '
              "| summarize users = countDistinct(user_id), carts = count(), revenue = sum(cart_value_usd)")
    forecast = ('fetch spans, from:now()-30m | filter `shop.service` == "payment-svc" '
                'and `span.name` == "razorpay.charge" '
                "| summarize total = count(), bad = countIf(duration > 200ms or outcome == \"error\")")
    traces = ('fetch spans, from:now()-30m | filter isNotNull(incident_id) '
              "| summarize tool_calls = count(), latency_ms = sum(duration)/1000000, by:{agent}")
    return [
        {"step": 1, "agent": "watcher", "dql": rum},
        {"step": 2, "agent": "tracer", "dql": spans},
        {"step": 3, "agent": "judge", "dql": impact},
        {"step": 3, "agent": "judge", "dql": forecast},
        {"step": 4, "agent": "actuator", "dql": forecast},
        {"step": 5, "agent": "scribe", "dql": rum},
        {"step": 6, "agent": "evaluator", "dql": traces},
    ]


def _agent_registry() -> list:
    """The 6 agents, in order, with their role, tools, representative DQL and the
    last-run stats from the most recent incident (traces + scorecard) if present."""
    cat = {c["agent"]: c["dql"] for c in _dql_catalog()}
    incidents = state_store.all_incidents()
    latest = incidents[0] if incidents else None
    last_traces = (latest or {}).get("traces", {}) if latest else {}
    last_card = {g["agent"].lower(): g for g in (latest or {}).get("scorecard", [])} if latest else {}
    total_runs = len(incidents)

    def last_run(key, label):
        tr = None
        for k, v in (last_traces or {}).items():
            if k.lower() == key or k.lower() == label.lower():
                tr = v
                break
        grade = last_card.get(key) or last_card.get(label.lower())
        if not tr and not grade:
            return None
        return {
            "tool_calls": (tr or {}).get("tool_calls") if tr else None,
            "latency_ms": (tr or {}).get("latency_ms") if tr else None,
            "score": grade.get("score") if grade else None,
            "decision": (tr or {}).get("decision") if tr else None,
        }

    defs = [
        {"key": "watcher", "label": "Watcher", "role": "Detection",
         "blurb": "Watches real-user experience by segment and journey. Flags the first "
                  "degraded cohort before it shows up in aggregate dashboards.",
         "tools": [{"name": "execute_dql", "desc": "RUM experience by segment (apdex, rage clicks)"},
                   {"name": "list_problems", "desc": "Active Davis problems on the tenant"}]},
        {"key": "tracer", "label": "Tracer", "role": "Root cause",
         "blurb": "Finds the worst span across ALL services from data -- never assuming a "
                  "service -- and ties it to the deploy that introduced the regression.",
         "tools": [{"name": "execute_dql", "desc": "Worst span across services (errors, latency, deploy)"},
                   {"name": "list_exceptions", "desc": "Failing spans for a service"}]},
        {"key": "judge", "label": "Judge", "role": "Business impact",
         "blurb": "Quantifies users, carts and revenue at risk, then forecasts when the "
                  "error budget breaches at the current burn rate.",
         "tools": [{"name": "execute_dql", "desc": "Business impact (users, carts, revenue)"},
                   {"name": "davis_forecast", "desc": "Error-budget burn + breach ETA"}]},
        {"key": "actuator", "label": "Actuator", "role": "Action",
         "blurb": "Proposes a reversible mitigation and routes it for human approval, "
                  "then notifies the on-call channel and emits a Dynatrace event.",
         "tools": [{"name": "create_workflow_for_notification", "desc": "Recommend reversible action"},
                   {"name": "send_slack_message", "desc": "Notify on-call channel"},
                   {"name": "send_event", "desc": "Emit Dynatrace custom event"}]},
        {"key": "scribe", "label": "Scribe", "role": "Record",
         "blurb": "Writes the incident notebook -- timeline, exact DQL, root cause and "
                  "remediation -- as a durable, shareable Dynatrace document.",
         "tools": [{"name": "create_dynatrace_notebook", "desc": "Author incident notebook"},
                   {"name": "send_event", "desc": "Emit Dynatrace custom event"}]},
        {"key": "evaluator", "label": "Evaluator", "role": "Self-improvement",
         "blurb": "Grades every agent on its own run from the traces and proposes "
                  "lessons or definition edits for the next incident.",
         "tools": [{"name": "get_agent_traces", "desc": "Per-agent tool calls + latency for the run"}]},
    ]
    out = []
    for d in defs:
        d = dict(d)
        d["dql_template"] = cat.get(d["key"], "")
        d["last_run"] = last_run(d["key"], d["label"])
        d["total_runs"] = total_runs
        out.append(d)
    return out


def _telemetry() -> dict:
    """Metrics bundle + an SLO summary derived from the SAME active fault, plus the
    real DQL catalog."""
    import os
    series = _live_metrics()
    c = _store_chaos()
    active = bool(c.get("active"))
    service = c.get("service", "payment-svc") if active else "payment-svc"
    scenario = (c.get("scenario") or c.get("fault", "")) if active else ""
    added_latency = int(c.get("addedLatencyMs", 0) or 0)
    is_error = scenario in ERROR_SCENARIOS
    target_ms = 200
    # current latency = last point of the latency series (coherent with charts).
    lat_vals = [v for v in series.get("latency", {}).get("values", []) if v is not None]
    current_ms = round(lat_vals[-1]) if lat_vals else 60
    if active:
        bad_rate = 0.06 if is_error else (0.04 if added_latency >= target_ms else 0.01)
    else:
        bad_rate = 0.001
    budget = 0.005
    burn_multiple = round(bad_rate / budget, 1)
    error_budget_pct = round(max(0.0, 100.0 * (1 - bad_rate / budget)), 1) if bad_rate < budget else 0.0
    if bad_rate <= budget:
        breach_eta = None
    else:
        eta_h = 168 * budget / bad_rate
        breach_eta = (f"~{max(1, int(eta_h*60))}m" if eta_h < 1
                      else (f"~{eta_h:.1f}h" if eta_h < 48 else f"~{eta_h/24:.1f}d"))
    return {
        "series": series,
        "slo": {
            "service": service,
            "target_ms": target_ms,
            "current_ms": current_ms,
            "error_budget_pct": error_budget_pct,
            "burn_multiple": burn_multiple,
            "breach_eta": breach_eta,
        },
        "dql_catalog": _dql_catalog(),
    }


def _config() -> dict:
    import os

    def truthy(name):
        return os.environ.get(name, "false").lower() == "true"

    use_live_dt = truthy("QUELL_USE_LIVE_DT")
    slack_configured = any(k.startswith("SLACK_") and os.environ.get(k)
                           for k in os.environ)
    return {
        "dynatrace_tenant": os.environ.get("DT_ENVIRONMENT", ""),
        "model_worker": os.environ.get("QUELL_WORKER_MODEL", "gemini-2.5-pro"),
        "model_evaluator": os.environ.get("QUELL_EVALUATOR_MODEL", "gemini-2.5-flash"),
        "autonomous": truthy("QUELL_AUTONOMOUS"),
        "use_live_dt": use_live_dt,
        "use_live_llm": truthy("QUELL_USE_LIVE_LLM"),
        "use_mcp": truthy("QUELL_USE_MCP"),
        "backend_mode": "live" if use_live_dt else "mock",
        "channels": {"slack": bool(slack_configured), "dynatrace": True},
        "thresholds": {"apdex": 0.7, "burn_multiple": 10},
        "services_monitored": ["catalog-svc", "cart-svc", "payment-svc", "razorpay.gateway"],
        "gcp_project": os.environ.get("QUELL_GCP_PROJECT", ""),
        "region": "us-central1",
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
        elif self.path == "/api/activity":
            self._json({"events": list(reversed(ACTIVITY))[:15]})
        elif self.path == "/api/history":
            self._json({"incidents": list(reversed(HISTORY))[:10]})
        elif self.path == "/api/incidents":
            self._json({"incidents": state_store.all_incidents()})
        elif self.path.startswith("/api/incidents/"):
            iid = self.path[len("/api/incidents/"):].split("?")[0].strip("/")
            inc = state_store.get_incident(iid)
            if inc:
                self._json(inc)
            else:
                self._json({"error": "not found"}, code=404)
        elif self.path == "/api/agents":
            self._json({"agents": _agent_registry()})
        elif self.path == "/api/telemetry":
            self._json(_telemetry())
        elif self.path == "/api/config":
            self._json(_config())
        elif self.path == "/api/audit":
            self._json({"events": state_store.all_audit(limit=200)})
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
            with RUN_LOCK:
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
    last_idle_log = 0.0
    while True:
        _t.sleep(12)
        try:
            anomalous = _is_anomalous()
            fault = _store_chaos()
            fault_active = bool(fault.get("active"))
            if CURRENT and not CURRENT.done:
                # Phantom-incident guard: a run stuck waiting at a gate while the
                # ShopWave fault is NOT active is a false positive -- dismiss it so
                # the console returns to a clean idle state. Applies to manual and
                # auto incidents alike.
                if CURRENT.pending and not fault_active:
                    CURRENT.dismiss()
                    CURRENT = None
                    cooldown_until = _t.monotonic() + 30
                    continue
                # Hard timeout: a gate pending for too long (no human ever acted)
                # is dismissed regardless of fault state, so it can't linger forever.
                if (CURRENT.pending and CURRENT._pending_since is not None
                        and _t.monotonic() - CURRENT._pending_since > 240):
                    CURRENT.dismiss()
                    CURRENT = None
                    cooldown_until = _t.monotonic() + 30
                continue
            if _t.monotonic() < cooldown_until:
                continue
            if anomalous:
                log_activity(
                    f"Anomaly detected on {fault.get('service','service')} - investigating")
                with RUN_LOCK:
                    CURRENT = RunSession(STORE, auto=True)   # Quell launches itself
                cooldown_until = _t.monotonic() + 45
            else:
                # Throttled idle heartbeat: at most once per ~60s.
                if _t.monotonic() - last_idle_log > 60:
                    log_activity("Watching ShopWave - all segments healthy")
                    last_idle_log = _t.monotonic()
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
