"""Quell persisted state store.

A tiny, thread-safe, JSON-file store (stdlib only) for incidents and the audit
trail. The dashboard reads it for the Incidents and Audit surfaces so those pages
are NEVER empty -- even on a fresh Cloud Run container the file is seeded with
realistic past data on first load.

State dir from env QUELL_STATE_DIR (default /tmp/quell-state). One state.json with
two keys: "incidents" and "audit". Every write is durable (flushed to file).

    incidents capped at 50, audit at 300, both stored newest-LAST internally and
    returned newest-FIRST by the accessors.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

_LOCK = threading.Lock()
_STATE: dict | None = None

INCIDENT_CAP = 50
AUDIT_CAP = 300


def _state_dir() -> str:
    return os.environ.get("QUELL_STATE_DIR", "/tmp/quell-state")


def _state_path() -> str:
    return os.path.join(_state_dir(), "state.json")


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ---- seed data --------------------------------------------------------------

def _seed() -> dict:
    """Realistic past data spanning the last ~5 days so the product never looks empty."""
    now = datetime.now()

    def agents_for(scenario, service, span, segment):
        # Six pipeline steps with a short replayable summary each.
        return [
            {"agent": "Watcher", "role": "Detection",
             "summary": f"apdex on {segment} fell to 0.58 with 132 rage-clicks; flagged {service}."},
            {"agent": "Tracer", "role": "Root cause",
             "summary": f"Worst span {service}/{span} -- isolated regression after recent deploy."},
            {"agent": "Judge", "role": "Impact",
             "summary": "1,800 users / 2,400 carts at risk; error budget burning, breach imminent."},
            {"agent": "Actuator", "role": "Action",
             "summary": f"Recommended reversible mitigation on {span}; posted to Slack + Dynatrace event."},
            {"agent": "Scribe", "role": "Record",
             "summary": "Authored Dynatrace notebook with timeline, DQL and remediation."},
            {"agent": "Evaluator", "role": "Self-improvement",
             "summary": "Graded the run, proposed one detection-threshold lesson."},
        ]

    def scorecard_for():
        return [
            {"agent": "Watcher", "score": 0.92, "notes": "Caught the dip fast; segment localized.",
             "lesson": "Lower apdex alert threshold to 0.70 for checkout journey."},
            {"agent": "Tracer", "score": 0.95, "notes": "Correct span with no assumption of service.",
             "lesson": ""},
            {"agent": "Judge", "score": 0.90, "notes": "Solid impact math; forecast within budget basis.",
             "lesson": ""},
            {"agent": "Actuator", "score": 0.88, "notes": "Reversible recommendation; no risky auto-apply.",
             "lesson": ""},
            {"agent": "Scribe", "score": 0.91, "notes": "Clear notebook, full DQL captured.",
             "lesson": ""},
            {"agent": "Evaluator", "score": 0.93, "notes": "Grading consistent with evidence.",
             "lesson": ""},
        ]

    specs = [
        # (id, scenario, service, span, segment, dollars, resolve_s, hours_ago, backend, tool_calls, root_cause)
        ("INC-001", "payment_latency", "payment-svc", "razorpay.charge", "iOS / US",
         84000, 14.0, 6, "live", 14, "payment-svc span razorpay.charge after deploy #847"),
        ("INC-002", "checkout_errors", "cart-svc", "cart.checkout", "Web / US",
         62000, 11.0, 29, "mock", 12, "cart-svc span cart.checkout after deploy #851"),
        ("INC-003", "catalog_slowdown", "catalog-svc", "catalog.query", "Android / US",
         41500, 19.0, 74, "live", 13, "catalog-svc span catalog.query after deploy #844"),
        ("INC-004", "third_party_outage", "razorpay.gateway", "razorpay.authorize", "iOS / US",
         96000, 23.0, 116, "mock", 16, "razorpay.gateway span razorpay.authorize -- upstream outage"),
    ]

    def traces_for():
        # Plausible per-agent traces (never 0ms) so the agents page last_run is full.
        return {
            "Watcher": {"tool_calls": 2, "latency_ms": 620, "decision": "degraded segment flagged"},
            "Tracer": {"tool_calls": 3, "latency_ms": 1420, "decision": "worst span isolated"},
            "Judge": {"tool_calls": 2, "latency_ms": 700, "decision": "impact + breach forecast"},
            "Actuator": {"tool_calls": 3, "latency_ms": 430, "decision": "reversible mitigation recommended"},
            "Scribe": {"tool_calls": 2, "latency_ms": 350, "decision": "notebook authored"},
            "Evaluator": {"tool_calls": 1, "latency_ms": 800, "decision": "graded run"},
        }

    incidents = []
    audit = []
    for (iid, scenario, service, span, segment, dollars, resolve_s,
         hours_ago, backend, tool_calls, root_cause) in specs:
        when = now - timedelta(hours=hours_ago)
        entries = agents_for(scenario, service, span, segment)
        scorecard = scorecard_for()
        incidents.append({
            "id": iid, "scenario": scenario, "service": service, "span": span,
            "segment": segment, "dollars": dollars, "resolve_s": resolve_s,
            "when": _iso(when), "outcome": "prevented", "backend": backend,
            "tool_calls_total": tool_calls, "agents": 6, "root_cause": root_cause,
            "entries": entries, "scorecard": scorecard, "traces": traces_for(),
        })
        # Audit: a watch line, a detect, six agent lines, two gate approvals, a rescue.
        audit.append({"t": _iso(when - timedelta(seconds=20)), "type": "watch",
                      "text": f"Watching ShopWave -- {segment} segment under observation", "incident": None})
        audit.append({"t": _iso(when - timedelta(seconds=8)), "type": "detect",
                      "text": f"Anomaly detected on {service} -- investigating", "incident": iid})
        step_t = when
        for e in entries:
            step_t = step_t + timedelta(seconds=1)
            audit.append({"t": _iso(step_t), "type": "agent",
                          "text": f"{e['agent']}: {e['summary']}", "incident": iid})
        audit.append({"t": _iso(step_t + timedelta(seconds=1)), "type": "approve",
                      "text": "Action gate approved -- reversible mitigation applied", "incident": iid})
        audit.append({"t": _iso(step_t + timedelta(seconds=2)), "type": "approve",
                      "text": "Learning gate approved -- 1 lesson accepted", "incident": iid})
        audit.append({"t": _iso(step_t + timedelta(seconds=3)), "type": "rescue",
                      "text": f"Rescued -- ${dollars} protected", "incident": iid})

    # A couple of trailing "all clear" watch lines so the audit tail looks live.
    audit.append({"t": _iso(now - timedelta(minutes=8)), "type": "watch",
                  "text": "Watching ShopWave -- all segments healthy", "incident": None})
    audit.append({"t": _iso(now - timedelta(minutes=3)), "type": "watch",
                  "text": "Watching ShopWave -- all segments healthy", "incident": None})

    # Stored chronologically (oldest-first); accessors reverse for newest-first.
    return {"incidents": incidents, "audit": audit}


# ---- file io ----------------------------------------------------------------

def _write_locked() -> None:
    """Persist _STATE to disk. Caller must hold _LOCK."""
    os.makedirs(_state_dir(), exist_ok=True)
    path = _state_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_STATE, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load() -> dict:
    """Load state from disk; seed + persist on first use if absent/unreadable."""
    global _STATE
    with _LOCK:
        if _STATE is not None:
            return _STATE
        path = _state_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "incidents" in data and "audit" in data:
                    _STATE = data
                    return _STATE
            except Exception:
                pass
        _STATE = _seed()
        _write_locked()
        return _STATE


# ---- accessors --------------------------------------------------------------

def all_incidents() -> list:
    """Full incident list, newest first."""
    s = load()
    with _LOCK:
        return list(reversed(s["incidents"]))


def get_incident(incident_id: str) -> dict | None:
    s = load()
    with _LOCK:
        for inc in s["incidents"]:
            if inc.get("id") == incident_id:
                return inc
    return None


def add_incident(incident: dict) -> None:
    s = load()
    with _LOCK:
        s["incidents"].append(incident)
        if len(s["incidents"]) > INCIDENT_CAP:
            del s["incidents"][:-INCIDENT_CAP]
        _write_locked()


def all_audit(limit: int | None = None) -> list:
    """Audit events, newest first (optionally limited)."""
    s = load()
    with _LOCK:
        events = list(reversed(s["audit"]))
    return events[:limit] if limit else events


def add_audit(event: dict) -> None:
    s = load()
    with _LOCK:
        s["audit"].append(event)
        if len(s["audit"]) > AUDIT_CAP:
            del s["audit"][:-AUDIT_CAP]
        _write_locked()
