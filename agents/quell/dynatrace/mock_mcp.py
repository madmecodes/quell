"""Mock Dynatrace MCP backend.

Simulates the ShopWave e-commerce world and exposes the SAME tool surface as the
real Dynatrace MCP server. In mock mode these return canned-but-coherent data
derived from a ChaosState. To go live, swap MockMCP for a client that calls the
real @dynatrace-oss/dynatrace-mcp-server tools (execute_dql, etc.) with identical
return shapes.

Tool surface mirrored here (subset of the real MCP):
  read:  execute_dql, generate_dql_from_natural_language, list_problems,
         find_entity_by_name, list_exceptions, list_davis_analyzers,
         execute_davis_analyzer, get_agent_traces (our self-observability)
  write: create_workflow_for_notification, send_event, send_slack_message,
         create_dynatrace_notebook
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChaosState:
    """The injected fault. The Chaos Panel in the demo app sets this."""

    active: bool = False
    fault: str = ""             # e.g. "payment_latency"
    service: str = ""           # e.g. "payment-svc"
    span: str = ""              # e.g. "razorpay.charge"
    segment: str = ""           # e.g. "Android / IN"
    deploy: str = ""            # e.g. "#847"
    added_latency_ms: int = 0   # e.g. 400
    # ground truth, used by the Evaluator to check if agents were correct
    @property
    def true_cause(self) -> str:
        return f"{self.service} span {self.span} +{self.added_latency_ms}ms after deploy {self.deploy}"


@dataclass
class MockMCP:
    chaos: ChaosState = field(default_factory=ChaosState)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    # in-memory record of the Quell agents' own run, for the Evaluator to query
    agent_traces: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ---- read tools ---------------------------------------------------------

    def list_problems(self) -> list[dict[str, Any]]:
        if not self.chaos.active:
            return []
        return [{
            "id": "P-1",
            "title": f"Response time degradation on {self.chaos.service}",
            "severity": "PERFORMANCE",
            "affected_segment": self.chaos.segment,
            "affected_service": self.chaos.service,
        }]

    def rum_experience(self) -> dict[str, Any]:
        """Real-user experience summary by segment (RUM). Watcher uses this."""
        baseline = {"segment": "all", "apdex": 0.94, "rage_clicks": 12, "conversion": 0.71}
        if not self.chaos.active:
            return {"healthy": True, "segments": [baseline]}
        degraded = {
            "segment": self.chaos.segment,
            "apdex": 0.58,
            "rage_clicks": 143,
            "conversion": 0.62,
            "journey": "checkout",
            "started": "14:02",
        }
        return {"healthy": False, "segments": [baseline, degraded]}

    def span_breakdown(self, service: str) -> dict[str, Any]:
        """Backend trace breakdown for a service. Tracer uses this."""
        spans = {
            "catalog.query": 22,
            "cart.read": 14,
            "payment.init": 31,
        }
        if self.chaos.active and self.chaos.service == service:
            spans[self.chaos.span] = 40 + self.chaos.added_latency_ms
        return {"service": service, "span_ms": spans, "recent_deploy": self.chaos.deploy or "none"}

    def list_exceptions(self, service: str) -> list[dict[str, Any]]:
        if self.chaos.active and self.chaos.service == service:
            return [{"type": "UpstreamTimeout", "span": self.chaos.span, "count": 87}]
        return []

    def business_impact(self, segment: str) -> dict[str, Any]:
        """Business events: revenue/carts at risk. Judge uses this."""
        if not self.chaos.active:
            return {"users_affected": 0, "carts_at_risk": 0, "revenue_at_risk_usd": 0}
        return {
            "users_affected": 1800,
            "carts_at_risk": 2400,
            "revenue_at_risk_usd": 84000,
            "segment": segment,
        }

    def davis_forecast(self, metric: str) -> dict[str, Any]:
        """Davis AI analyzer: forecast a breach. Judge uses this."""
        if not self.chaos.active:
            return {"metric": metric, "breach_eta": None}
        return {"metric": metric, "breach_eta": "~1h", "trend": "degrading"}

    def get_agent_traces(self, incident_id: str) -> dict[str, Any]:
        """Quell observing itself: the agents' own run telemetry.

        In production this is execute_dql over Quell's own OTel spans in
        Dynatrace. The Evaluator queries this to grade the agents on real data.
        """
        return self.agent_traces

    # ---- write tools --------------------------------------------------------

    def create_workflow_for_notification(self, name: str, action: str) -> dict[str, Any]:
        rec = {"tool": "create_workflow", "name": name, "action": action}
        self.actions_taken.append(rec)
        return {"ok": True, "workflow_id": "wf-101", **rec}

    def send_event(self, title: str, properties: dict[str, Any]) -> dict[str, Any]:
        rec = {"tool": "send_event", "title": title, "properties": properties}
        self.actions_taken.append(rec)
        return {"ok": True, **rec}

    def send_slack_message(self, channel: str, text: str) -> dict[str, Any]:
        rec = {"tool": "send_slack_message", "channel": channel, "text": text}
        self.actions_taken.append(rec)
        return {"ok": True, **rec}

    def create_dynatrace_notebook(self, title: str, markdown: str) -> dict[str, Any]:
        rec = {"tool": "create_notebook", "title": title}
        self.actions_taken.append(rec)
        return {"ok": True, "notebook_id": "nb-77", **rec}

    # ---- self-observability helper -----------------------------------------

    def record_agent_trace(self, agent: str, tool_calls: int, latency_ms: int, decision: str) -> None:
        self.agent_traces[agent] = {
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "decision": decision,
        }
