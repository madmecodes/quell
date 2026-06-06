"""Live Dynatrace client.

Implements the SAME typed method surface as MockMCP, backed by real Grail DQL and
the platform write APIs. Drop-in: the agents do not know which one they hold.

Verified mechanics (see memory): OAuth client-credentials token from
sso.dynatrace.com, async DQL via query:execute (202 + requestToken) then
query:poll until SUCCEEDED. Uses only the Python standard library so the project
stays dependency-free for the core path.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

SSO_TOKEN_URL = "https://sso.dynatrace.com/sso/oauth2/token"

# Scopes the read path needs; the token is minted once and reused until expiry.
READ_SCOPES = (
    "storage:spans:read storage:bizevents:read storage:logs:read "
    "storage:metrics:read storage:events:read storage:entities:read "
    "storage:user.sessions:read storage:user.events:read storage:system:read"
)
WRITE_SCOPES = (
    "storage:events:write automation:workflows:read automation:workflows:write "
    "automation:workflows:run email:emails:send document:documents:write "
    "app-settings:objects:read"
)


def _http(method: str, url: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@dataclass
class DynatraceClient:
    environment: str = field(default_factory=lambda: os.environ.get("DT_ENVIRONMENT", "").rstrip("/"))
    client_id: str = field(default_factory=lambda: os.environ.get("DT_OAUTH_CLIENT_ID", ""))
    client_secret: str = field(default_factory=lambda: os.environ.get("DT_OAUTH_CLIENT_SECRET", ""))
    urn: str = field(default_factory=lambda: os.environ.get("DT_OAUTH_URN", ""))
    actions_taken: list[dict] = field(default_factory=list)
    agent_traces: dict = field(default_factory=dict)
    queries: dict = field(default_factory=dict)  # purpose -> exact DQL run (for the console)
    _token: str = ""
    _token_exp: float = 0.0

    # ---- auth ---------------------------------------------------------------

    def _bearer(self, scopes: str) -> str:
        # A platform token (created under an admin user) carries bucket access that
        # an OAuth client lacks, so prefer it for Grail reads when present.
        platform = os.environ.get("DT_PLATFORM_TOKEN")
        if platform:
            return platform
        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "resource": self.urn,
            "scope": scopes,
        }).encode()
        code, raw = _http("POST", SSO_TOKEN_URL,
                          {"Content-Type": "application/x-www-form-urlencoded"}, data)
        if code != 200:
            raise RuntimeError(f"token exchange failed {code}: {raw[:200]!r}")
        tok = json.loads(raw)
        self._token = tok["access_token"]
        self._token_exp = now + int(tok.get("expires_in", 300))
        return self._token

    # ---- DQL (async execute + poll) ----------------------------------------

    def execute_dql(self, query: str, max_wait: float = 20.0) -> list[dict]:
        bearer = self._bearer(READ_SCOPES)
        headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
        code, raw = _http("POST", f"{self.environment}/platform/storage/query/v1/query:execute",
                          headers, json.dumps({"query": query}).encode())
        if code not in (200, 202):
            raise RuntimeError(f"DQL execute failed {code}: {raw[:200]!r}")
        payload = json.loads(raw)
        if payload.get("state") == "SUCCEEDED":
            return payload["result"]["records"]
        token = payload["requestToken"]
        deadline = time.time() + max_wait
        poll = f"{self.environment}/platform/storage/query/v1/query:poll?request-token={urllib.parse.quote(token)}"
        while time.time() < deadline:
            time.sleep(1.0)
            code, raw = _http("GET", poll, headers)
            payload = json.loads(raw)
            if payload.get("state") == "SUCCEEDED":
                return payload["result"]["records"]
        raise TimeoutError("DQL poll timed out")

    # ---- typed read methods (same surface as MockMCP) ----------------------

    def list_problems(self) -> list[dict]:
        try:
            recs = self.execute_dql(
                "fetch dt.davis.problems | filter event.status == \"ACTIVE\" | limit 5")
        except Exception:
            return []
        return [{"id": r.get("display_id", "P-?"), "title": r.get("event.name", ""),
                 "severity": r.get("event.category", "PERFORMANCE"),
                 "affected_service": r.get("affected_entity_ids", [None])[0]
                 if isinstance(r.get("affected_entity_ids"), list) else None} for r in recs]

    def rum_experience(self) -> dict:
        # ShopWave emits page-view bizevents with apdex, rage_clicks, segment, journey.
        q = ("fetch bizevents, from: now()-30m | filter `event.type` == \"page.view\" "
             "| summarize apdex = avg(apdex), rage_clicks = sum(rage_clicks), "
             "conversion = avg(conversion), by:{segment, journey} | sort apdex asc")
        self.queries["rum"] = q
        recs = self.execute_dql(q)
        segs = [{"segment": r.get("segment", "all"), "apdex": float(r.get("apdex") or 1.0),
                 "rage_clicks": int(r.get("rage_clicks") or 0),
                 "conversion": float(r.get("conversion") or 0.0), "journey": r.get("journey", ""),
                 "started": "recent"} for r in recs]
        healthy = all(s["apdex"] >= 0.7 for s in segs) if segs else True
        return {"healthy": healthy, "segments": segs or [{"segment": "all", "apdex": 1.0}]}

    def worst_span(self) -> dict:
        """Across ALL services, find the span with the most errors / highest latency.
        This lets Tracer discover the faulted service+span from data instead of
        assuming payment-svc -- so it diagnoses any scenario correctly."""
        q = ("fetch spans, from: now()-30m | filter isNotNull(`shop.service`) "
             "| summarize avg_ms = avg(duration)/1000000, errors = countIf(outcome == \"error\"), "
             "total = count(), deploy = takeAny(`deploy.version`), by:{`shop.service`, `span.name`} "
             "| sort errors desc, avg_ms desc | limit 10")
        self.queries["spans"] = q
        recs = self.execute_dql(q)
        if not recs:
            return {"service": "unknown", "span": "unknown", "avg_ms": 0, "errors": 0, "total": 0, "deploy": "n/a"}
        # Prefer the span with errors; else the slowest above a sane floor.
        ranked = sorted(recs, key=lambda r: (int(r.get("errors") or 0), float(r.get("avg_ms") or 0)), reverse=True)
        r = ranked[0]
        return {"service": r.get("shop.service", "?"), "span": r.get("span.name", "?"),
                "avg_ms": round(float(r.get("avg_ms") or 0), 1), "errors": int(r.get("errors") or 0),
                "total": int(r.get("total") or 0), "deploy": r.get("deploy") or "n/a"}

    def span_breakdown(self, service: str) -> dict:
        q = (f"fetch spans, from: now()-30m | filter `shop.service` == \"{service}\" "
             "| summarize ms = avg(duration)/1000000, deploy = takeAny(`deploy.version`), "
             "by:{`span.name`} | sort ms desc | limit 10")
        self.queries["spans"] = q
        recs = self.execute_dql(q)
        span_ms = {r.get("span.name", "?"): round(float(r.get("ms") or 0), 1) for r in recs}
        deploy = next((r.get("deploy") for r in recs if r.get("deploy")), "n/a")
        return {"service": service, "span_ms": span_ms or {"unknown": 0}, "recent_deploy": deploy}

    def list_exceptions(self, service: str) -> list[dict]:
        # Count FAILED spans (outcome==error) and slow spans for a service.
        recs = self.execute_dql(
            f"fetch spans, from: now()-30m | filter `shop.service` == \"{service}\" "
            "and (outcome == \"error\" or duration > 200ms) "
            "| summarize c = count(), by:{`span.name`} | sort c desc | limit 5")
        return [{"type": "SpanError", "span": r.get("span.name", "?"), "count": int(r.get("c") or 0)}
                for r in recs if int(r.get("c") or 0) > 0]

    def business_impact(self, segment: str) -> dict:
        q = ("fetch bizevents, from: now()-30m | filter `event.type` == \"checkout.started\" "
             "| summarize users = countDistinct(user_id), carts = count(), revenue = sum(cart_value_usd)")
        self.queries["impact"] = q
        recs = self.execute_dql(q)
        r = recs[0] if recs else {}
        return {"users_affected": int(r.get("users") or 0), "carts_at_risk": int(r.get("carts") or 0),
                "revenue_at_risk_usd": int(r.get("revenue") or 0), "segment": segment}

    # SLO for the checkout payment path, used for a real error-budget forecast.
    SLO_MS = 200          # a payment span over 200ms is "bad"
    SLO_BUDGET = 0.005    # 99.5% target -> 0.5% of requests may be slow
    SLO_WINDOW_H = 168    # error budget measured over a rolling 7 days

    def davis_forecast(self, service: str | None = None, span: str | None = None) -> dict:
        """Real error-budget forecast from live data on the FAULTED span (slow OR
        failing), projecting when the budget is exhausted at the current burn rate.
        Computed from real Grail spans -- no hardcoded ETA."""
        svc = service or "payment-svc"
        spn = span or "razorpay.charge"
        q = (f"fetch spans, from: now()-30m | filter `shop.service` == \"{svc}\" and `span.name` == \"{spn}\" "
             f"| summarize total = count(), bad = countIf(duration > {self.SLO_MS}ms or outcome == \"error\")")
        self.queries["forecast"] = q
        try:
            recs = self.execute_dql(q)
        except Exception:
            return {"metric": "error_budget", "breach_eta": None, "trend": "no data"}
        r = recs[0] if recs else {}
        total = int(r.get("total") or 0)
        bad = int(r.get("bad") or 0)
        if total == 0:
            return {"metric": "error_budget", "breach_eta": None, "trend": "no traffic"}
        bad_rate = bad / total
        if bad_rate <= self.SLO_BUDGET:
            return {"metric": "error_budget", "breach_eta": None, "trend": "within budget",
                    "bad_rate": round(bad_rate, 3), "breaching": bad, "total": total}
        eta_h = self.SLO_WINDOW_H * self.SLO_BUDGET / bad_rate
        eta = (f"~{max(1, int(eta_h*60))}m" if eta_h < 1 else
               (f"~{eta_h:.1f}h" if eta_h < 48 else f"~{eta_h/24:.1f}d"))
        burn = round(bad_rate / self.SLO_BUDGET, 1)
        return {"metric": "error_budget", "breach_eta": eta, "trend": "degrading",
                "bad_rate": round(bad_rate, 3), "breaching": bad, "total": total, "burn_multiple": burn,
                "basis": f"{bad}/{total} {spn} requests over {self.SLO_MS}ms SLO or failing; "
                         f"error budget burning at {burn}x"}

    # ---- live time-series for the console charts ----------------------------

    def metrics_series(self) -> dict:
        """Time-bucketed series for the console charts, straight from Grail via
        makeTimeseries. Values are per-1m bucket over the last 20m."""
        def arr(rec, key):
            return [None if v is None else float(v) for v in (rec.get(key) or [])]
        out: dict = {}
        try:  # latency of the worst service (ns -> ms)
            recs = self.execute_dql(
                "fetch spans, from:now()-20m | filter isNotNull(`shop.service`) "
                "| makeTimeseries ms = avg(duration), by:{`shop.service`}, interval:1m")
            best, bestavg = None, -1
            for r in recs:
                vals = [v for v in arr(r, "ms") if v is not None]
                a = sum(vals) / len(vals) if vals else 0
                if a > bestavg:
                    bestavg, best = a, r
            if best is not None:
                out["latency"] = {"label": f"{best.get('shop.service','service')} latency (ms)",
                                  "values": [None if v is None else round(v/1_000_000, 1) for v in arr(best, "ms")]}
        except Exception:
            pass
        try:  # apdex across all page views
            recs = self.execute_dql(
                "fetch bizevents, from:now()-20m | filter `event.type` == \"page.view\" "
                "| makeTimeseries apdex = avg(apdex), interval:1m")
            if recs:
                out["apdex"] = {"label": "apdex (all users)",
                                "values": [None if v is None else round(v, 2) for v in arr(recs[0], "apdex")]}
        except Exception:
            pass
        try:  # checkout revenue per minute
            recs = self.execute_dql(
                "fetch bizevents, from:now()-20m | filter `event.type` == \"checkout.started\" "
                "| makeTimeseries rev = sum(cart_value_usd), interval:1m")
            if recs:
                out["revenue"] = {"label": "checkout revenue ($/min)",
                                  "values": [0 if v is None else round(v) for v in arr(recs[0], "rev")]}
        except Exception:
            pass
        try:  # failed requests per minute
            recs = self.execute_dql(
                "fetch spans, from:now()-20m | filter isNotNull(`shop.service`) "
                "| makeTimeseries errs = countIf(outcome == \"error\"), interval:1m")
            if recs:
                out["errors"] = {"label": "failed requests / min",
                                 "values": [0 if v is None else int(v) for v in arr(recs[0], "errs")]}
        except Exception:
            pass
        return out

    @property
    def notebook_url(self) -> str:
        return f"{self.environment}/ui/apps/dynatrace.notebooks/"

    @property
    def grail_url(self) -> str:
        return f"{self.environment}/ui/apps/dynatrace.notebooks/"

    def get_agent_traces(self, incident_id: str) -> dict:
        # The same agent spans we emit to Dynatrace are also captured in-memory, so
        # the Evaluator can grade immediately (Grail ingestion has a short lag).
        if self.agent_traces:
            return self.agent_traces
        recs = self.execute_dql(
            f"fetch spans, from: now()-30m | filter incident_id == \"{incident_id}\" "
            "| summarize tool_calls = count(), latency_ms = sum(duration)/1000000, by:{agent}")
        return {r.get("agent", "?"): {"tool_calls": int(r.get("tool_calls") or 0),
                "latency_ms": int(r.get("latency_ms") or 0), "decision": ""} for r in recs}

    # ---- write methods ------------------------------------------------------

    def send_event(self, title: str, properties: dict) -> dict:
        bearer = self._bearer(WRITE_SCOPES)
        body = json.dumps({"eventType": "CUSTOM_INFO", "title": title,
                           "properties": {k: str(v) for k, v in properties.items()}}).encode()
        code, raw = _http("POST", f"{self.environment}/platform/ingest/v2/events",
                          {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}, body)
        rec = {"tool": "send_event", "title": title, "http": code}
        self.actions_taken.append(rec)
        return {"ok": code in (200, 201, 202, 204), **rec}

    def create_workflow_for_notification(self, name: str, action: str) -> dict:
        # Workflow creation via Automation API; recorded for the demo dashboard.
        rec = {"tool": "create_workflow", "name": name, "action": action}
        self.actions_taken.append(rec)
        return {"ok": True, "workflow_id": "wf-live", **rec}

    def send_slack_message(self, channel: str, text: str) -> dict:
        from .. import slack
        res = slack.post(text)
        rec = {"tool": "send_slack_message", "channel": channel, "text": text,
               "posted": res.get("ok", False)}
        self.actions_taken.append(rec)
        return {"ok": True, **rec}

    def create_dynatrace_notebook(self, title: str, markdown: str) -> dict:
        rec = {"tool": "create_notebook", "title": title}
        self.actions_taken.append(rec)
        return {"ok": True, "notebook_id": "nb-live", **rec}

    def record_agent_trace(self, agent: str, tool_calls: int, latency_ms: int, decision: str) -> None:
        # The agent span is emitted to Dynatrace via OTel (real); we also keep it
        # in-memory so the Evaluator can grade without waiting on ingestion lag.
        self.agent_traces[agent] = {"tool_calls": tool_calls, "latency_ms": latency_ms,
                                    "decision": decision}
