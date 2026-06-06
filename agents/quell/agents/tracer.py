"""Tracer: follow the degradation into the backend and pinpoint the cause.

Discovers the faulted service+span from telemetry (a cross-service scan) rather
than assuming payment-svc, so it diagnoses any scenario correctly. Keeps the
self-improvement story: unlearned it inspects each service (4 tool calls); after a
lesson it uses the one-shot scan (2 calls).
"""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent

CANDIDATE_SERVICES = ["payment-svc", "catalog-svc", "cart-svc"]


class Tracer(Agent):
    name = "tracer"
    task_type = "root_cause"
    role = (
        "Follow the degraded experience into the backend and pinpoint the exact "
        "service, span, and recent deploy responsible across ALL services. Report a "
        "single most-likely root cause."
    )
    instruction = (
        "Call scan_all_spans ONCE to find the worst span (most errors / highest latency) "
        "across every service, then check_exceptions on that service to confirm. Do not "
        "inspect services one at a time. Report the service, span, deploy, and whether it "
        "is slow or failing.")

    # ---- genuine tool-calling path ----

    def observe(self, case_file: CaseFile) -> str:
        d = case_file.latest("detection")
        seg = d.data.get("segment", "unknown") if d else "unknown"
        journey = d.data.get("journey", "checkout") if d else "checkout"
        return f"The '{seg}' segment has a degraded {journey} experience. Find the backend cause."

    def tool_callables(self, mcp: MockMCP, sink: dict) -> list:
        def scan_all_spans() -> dict:
            """Find the single worst span across ALL services (most errors / highest
            latency) and the deploy on it. Use this once to locate the root cause."""
            w = mcp.worst_span()
            sink["worst"] = w
            return w

        def inspect_service(service: str) -> dict:
            """Get average latency per span for ONE service. Args: service name."""
            b = mcp.span_breakdown(service)
            slow = max(b["span_ms"], key=b["span_ms"].get)
            cand = {"service": service, "span": slow, "avg_ms": b["span_ms"][slow],
                    "errors": 0, "deploy": b.get("recent_deploy", "n/a")}
            if sink.get("worst") is None or cand["avg_ms"] > sink["worst"].get("avg_ms", 0):
                sink["worst"] = cand
            return b

        def check_exceptions(service: str) -> list:
            """List failing/slow spans on a service. Args: service name."""
            ex = mcp.list_exceptions(service)
            sink["exceptions"] = ex
            return ex

        return [scan_all_spans, inspect_service, check_exceptions]

    def finalize(self, case_file: CaseFile, sink: dict, text: str) -> str:
        worst = sink.get("worst")
        if worst is None:
            worst = self._mcp.worst_span()
        return self._record(case_file, worst, sink.get("exceptions", []), text)

    def _record(self, case_file, worst, exceptions, rationale):
        errs = int(worst.get("errors", 0) or 0)
        ms = worst.get("avg_ms", worst.get("ms", 0))
        nature = (f"{errs} failing requests" if errs else f"{ms:.0f}ms latency")
        summary = (f"Root cause: {worst['service']} span {worst['span']} "
                   f"({nature}) after deploy {worst.get('deploy', 'n/a')}.")
        case_file.append(self.name, "root_cause", summary, {
            "service": worst["service"], "span": worst["span"],
            "latency_ms": ms, "errors": errs, "deploy": worst.get("deploy", "n/a"),
            "exceptions": exceptions, "dql": self._mcp.queries.get("spans"),
            "llm_rationale": rationale,
        })
        return summary

    # ---- deterministic fallback ----

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        detection = case_file.latest("detection")
        if not detection or detection.data.get("healthy"):
            summary = "No degradation to trace."
            case_file.append(self.name, "root_cause", summary, {})
            return 1, summary

        learned = "scan_all_spans" in self.lessons_context()
        tool_calls = 0
        if learned:
            worst = mcp.worst_span(); tool_calls += 1            # one-shot scan
        else:
            worst = None
            for service in CANDIDATE_SERVICES:                  # inspect each service
                b = mcp.span_breakdown(service); tool_calls += 1
                slow = max(b["span_ms"], key=b["span_ms"].get)
                cand = {"service": service, "span": slow, "avg_ms": b["span_ms"][slow],
                        "errors": 0, "deploy": b.get("recent_deploy", "n/a")}
                if worst is None or cand["avg_ms"] > worst["avg_ms"]:
                    worst = cand
        exceptions = mcp.list_exceptions(worst["service"]); tool_calls += 1
        if exceptions:
            worst["errors"] = exceptions[0]["count"]
        summary = self._record(case_file, worst, exceptions, "")
        return tool_calls, summary
