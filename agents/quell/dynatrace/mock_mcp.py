"""Mock Dynatrace MCP backend.

Simulates the ShopWave world and exposes the SAME typed surface as the live
DynatraceClient. It is scenario-aware: the data it returns reflects whichever fault
the Chaos Panel injected (slow payments, checkout errors, catalog slowdown, cart
failures, external outage), so the deterministic / fallback path diagnoses the
correct, scenario-specific root cause -- not a fixed script.

`queries` holds the DQL each step would run, so the console can show "the exact
query Quell ran" even in mock mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SLO_MS = 200


@dataclass
class ChaosState:
    """The injected fault. Mirrors ShopWave's /api/chaos."""

    active: bool = False
    fault: str = ""             # legacy alias of scenario
    scenario: str = ""          # payment_latency | checkout_errors | catalog_slowdown | cart_failures | third_party_outage
    service: str = ""           # e.g. payment-svc
    span: str = ""              # e.g. razorpay.charge
    segment: str = ""           # e.g. iOS / US
    journey: str = "checkout"   # which journey degrades (browse|checkout)
    deploy: str = ""            # e.g. #847
    added_latency_ms: int = 0
    error_rate: float = 0.0

    def __post_init__(self):
        if not self.scenario and self.fault:
            self.scenario = self.fault

    @property
    def true_cause(self) -> str:
        return f"{self.service} span {self.span} after deploy {self.deploy}"


@dataclass
class MockMCP:
    chaos: ChaosState = field(default_factory=ChaosState)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    agent_traces: dict[str, dict[str, Any]] = field(default_factory=dict)
    queries: dict[str, str] = field(default_factory=dict)

    # ---- read tools ---------------------------------------------------------

    def list_problems(self) -> list[dict[str, Any]]:
        if not self.chaos.active:
            return []
        return [{
            "id": "P-1",
            "title": f"Degradation on {self.chaos.service}",
            "severity": "PERFORMANCE",
            "affected_segment": self.chaos.segment,
            "affected_service": self.chaos.service,
        }]

    def rum_experience(self) -> dict[str, Any]:
        """Real-user experience by segment (Watcher uses this)."""
        self.queries["rum"] = (
            'fetch bizevents, from:now()-30m | filter `event.type` == "page.view" '
            "| summarize apdex = avg(apdex), rage = sum(rage_clicks), by:{segment, journey} "
            "| sort apdex asc")
        baseline = {"segment": "Web / US", "apdex": 0.94, "rage_clicks": 11, "conversion": 0.72,
                    "journey": "browse", "started": "recent"}
        if not self.chaos.active:
            return {"healthy": True, "segments": [baseline]}
        degraded = {
            "segment": self.chaos.segment, "apdex": 0.58, "rage_clicks": 132,
            "conversion": 0.58, "journey": self.chaos.journey, "started": "recent",
        }
        return {"healthy": False, "segments": [baseline, degraded]}

    def worst_span(self) -> dict[str, Any]:
        """Across ALL services, the span with the most errors / highest latency.
        This is how Tracer discovers the faulted service without assuming one."""
        self.queries["spans"] = (
            "fetch spans, from:now()-30m | filter isNotNull(`shop.service`) "
            "| summarize avg_ms = avg(duration)/1000000, errors = countIf(outcome == \"error\"), "
            "total = count(), deploy = takeAny(`deploy.version`), by:{`shop.service`, `span.name`} "
            "| sort errors desc, avg_ms desc | limit 10")
        if not self.chaos.active:
            return {"service": "payment-svc", "span": "razorpay.charge", "avg_ms": 42.0,
                    "errors": 0, "total": 120, "deploy": "stable"}
        total = 120
        errors = int(self.chaos.error_rate * total)
        avg_ms = 42.0 + self.chaos.added_latency_ms
        return {"service": self.chaos.service, "span": self.chaos.span, "avg_ms": round(avg_ms, 1),
                "errors": errors, "total": total, "deploy": self.chaos.deploy or "#847"}

    def span_breakdown(self, service: str) -> dict[str, Any]:
        """Per-span latency for one service (Tracer fallback uses this)."""
        self.queries["spans"] = (
            f'fetch spans, from:now()-30m | filter `shop.service` == "{service}" '
            "| summarize ms = avg(duration)/1000000, by:{`span.name`} | sort ms desc")
        spans = {"catalog.query": 22, "cart.read": 14, "payment.init": 31}
        if self.chaos.active and self.chaos.service == service:
            spans[self.chaos.span] = 42 + self.chaos.added_latency_ms
        return {"service": service, "span_ms": spans, "recent_deploy": self.chaos.deploy or "stable"}

    def list_exceptions(self, service: str) -> list[dict[str, Any]]:
        if self.chaos.active and self.chaos.service == service and self.chaos.error_rate > 0:
            return [{"type": "SpanError", "span": self.chaos.span,
                     "count": int(self.chaos.error_rate * 120)}]
        return []

    def business_impact(self, segment: str) -> dict[str, Any]:
        self.queries["impact"] = (
            'fetch bizevents, from:now()-30m | filter `event.type` == "checkout.started" '
            "| summarize users = countDistinct(user_id), carts = count(), revenue = sum(cart_value_usd)")
        if not self.chaos.active:
            return {"users_affected": 0, "carts_at_risk": 0, "revenue_at_risk_usd": 0, "segment": segment}
        return {"users_affected": 1800, "carts_at_risk": 2400, "revenue_at_risk_usd": 84000, "segment": segment}

    def davis_forecast(self, service: str | None = None, span: str | None = None) -> dict[str, Any]:
        svc = service or self.chaos.service or "payment-svc"
        spn = span or self.chaos.span or "razorpay.charge"
        self.queries["forecast"] = (
            f'fetch spans, from:now()-30m | filter `shop.service` == "{svc}" and `span.name` == "{spn}" '
            f"| summarize total = count(), bad = countIf(duration > {SLO_MS}ms or outcome == \"error\")")
        if not self.chaos.active:
            return {"metric": "error_budget", "breach_eta": None, "trend": "within budget"}
        total = 120
        slow = total if self.chaos.added_latency_ms >= SLO_MS else 0
        bad = max(slow, int(self.chaos.error_rate * total))
        bad_rate = bad / total
        burn = round(bad_rate / 0.005, 1)
        eta_h = max(0.3, 168 * 0.005 / bad_rate) if bad_rate else None
        eta = f"~{eta_h:.1f}h" if eta_h and eta_h < 48 else (f"~{eta_h/24:.1f}d" if eta_h else None)
        return {"metric": "error_budget", "breach_eta": eta, "trend": "degrading",
                "bad_rate": round(bad_rate, 3), "breaching": bad, "total": total,
                "burn_multiple": burn,
                "basis": f"{bad}/{total} {spn} requests over SLO or failing; burning {burn}x"}

    def get_agent_traces(self, incident_id: str) -> dict[str, Any]:
        return self.agent_traces

    # ---- write tools --------------------------------------------------------

    def create_workflow_for_notification(self, name: str, action: str) -> dict[str, Any]:
        # Mirrors the live path: this is a RECOMMENDED reversible action, not a real
        # auto-created Automation workflow -- so no fake workflow id is claimed.
        rec = {"tool": "recommend_workflow", "name": name, "action": action,
               "recommended_action": action,
               "description": f"Recommended reversible action (not auto-created): {action}",
               "created": False}
        self.actions_taken.append(rec)
        return {"ok": True, "workflow_id": None, "created": False,
                "recommended_action": action, **rec}

    def send_event(self, title: str, properties: dict[str, Any]) -> dict[str, Any]:
        rec = {"tool": "send_event", "title": title, "properties": properties}
        self.actions_taken.append(rec)
        return {"ok": True, **rec}

    def send_slack_message(self, channel: str, text: str) -> dict[str, Any]:
        from .. import slack
        res = slack.post(text)
        rec = {"tool": "send_slack_message", "channel": channel, "text": text,
               "posted": res.get("ok", False)}
        self.actions_taken.append(rec)
        return {"ok": True, **rec}

    def create_dynatrace_notebook(self, title: str, markdown: str) -> dict[str, Any]:
        # Mock path: no real API call, so posted:false mirrors the live fallback shape.
        rec = {"tool": "create_notebook", "title": title, "posted": False}
        self.actions_taken.append(rec)
        return {"ok": True, "notebook_id": "nb-77", "notebook_url": "", "posted": False, **rec}

    # ---- self-observability helper -----------------------------------------

    def record_agent_trace(self, agent: str, tool_calls: int, latency_ms: int, decision: str) -> None:
        self.agent_traces[agent] = {"tool_calls": tool_calls, "latency_ms": latency_ms, "decision": decision}
