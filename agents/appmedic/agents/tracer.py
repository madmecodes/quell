"""Tracer: follow the degraded segment into the backend and pinpoint the cause."""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent

# Candidate services Tracer inspects, in priority order. A lesson in memory can
# reorder this in a real run; kept explicit here so the Evaluator can grade order.
CANDIDATE_SERVICES = ["payment-svc", "catalog-svc", "cart-svc"]


class Tracer(Agent):
    name = "tracer"
    task_type = "root_cause"
    role = (
        "Take the degraded segment from the Watcher, follow the affected sessions "
        "into the backend, and pinpoint the exact service, span, and recent deploy "
        "responsible. Report a single most-likely root cause."
    )
    instruction = (
        "Find the single service and span causing the slowdown, and the deploy that "
        "introduced it. Inspect candidate services' spans; you do not need to inspect "
        "every service if the cause is already clear. Then check exceptions on the "
        "implicated service to confirm.")

    # ---- genuine tool-calling path: Gemini chooses which tools to call ----

    def observe(self, case_file: CaseFile) -> str:
        d = case_file.latest("detection")
        seg = d.data.get("segment", "unknown") if d else "unknown"
        suspect = d.data.get("suspect_service") if d else None
        hint = f" The linked problem implicates '{suspect}'." if suspect else ""
        return f"The '{seg}' segment has a degraded checkout experience.{hint}"

    def tool_callables(self, mcp: MockMCP, sink: dict) -> list:
        def list_candidate_services() -> list:
            """List the backend services that can be inspected for the slow checkout."""
            return CANDIDATE_SERVICES

        def inspect_service_spans(service: str) -> dict:
            """Get average latency in milliseconds for each span of a backend service.
            Args: service: the service name, e.g. 'payment-svc'."""
            b = mcp.span_breakdown(service)
            span_ms = b["span_ms"]
            slow = max(span_ms, key=span_ms.get)
            cand = {"service": service, "span": slow, "ms": span_ms[slow],
                    "deploy": b.get("recent_deploy", "n/a")}
            if sink.get("worst") is None or cand["ms"] > sink["worst"]["ms"]:
                sink["worst"] = cand
            return b

        def check_exceptions(service: str) -> list:
            """List exceptions/errors observed on a backend service.
            Args: service: the service name to check."""
            ex = mcp.list_exceptions(service)
            sink["exceptions"] = ex
            return ex

        return [list_candidate_services, inspect_service_spans, check_exceptions]

    def finalize(self, case_file: CaseFile, sink: dict, text: str) -> str:
        # Guarantee the structured handoff even if the LLM skipped the inspect tool:
        # backfill deterministically so downstream agents always get real data.
        worst = sink.get("worst")
        if worst is None:
            d = case_file.latest("detection")
            suspect = (d.data.get("suspect_service") if d else None) or CANDIDATE_SERVICES[0]
            b = self._mcp.span_breakdown(suspect)
            slow = max(b["span_ms"], key=b["span_ms"].get)
            worst = {"service": suspect, "span": slow, "ms": b["span_ms"][slow],
                     "deploy": b.get("recent_deploy", "n/a")}
        # Ground the reported summary in verified tool data, not the LLM's free text
        # (which can hallucinate span/deploy names).
        summary = (f"Root cause: {worst['service']} span {worst['span']} at "
                   f"{worst['ms']}ms after deploy {worst['deploy']}.")
        case_file.append(self.name, "root_cause", summary, {
            "service": worst["service"], "span": worst["span"],
            "latency_ms": worst["ms"], "deploy": worst["deploy"],
            "exceptions": sink.get("exceptions", []),
            "llm_rationale": text,
        })
        return summary

    # ---- deterministic fallback (mock / offline) ----

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        detection = case_file.latest("detection")
        if not detection or detection.data.get("healthy"):
            summary = "No degradation to trace."
            case_file.append(self.name, "root_cause", summary, {})
            return 1, summary

        # Memory at work: if Tracer has learned to start from the linked problem,
        # it inspects the implicated service first instead of scanning all of them.
        learned = "implicated service first" in self.lessons_context()
        suspect = detection.data.get("suspect_service")
        services = [suspect] if (learned and suspect) else CANDIDATE_SERVICES

        tool_calls = 0
        worst = None
        for service in services:
            breakdown = mcp.span_breakdown(service)   # tool call
            tool_calls += 1
            slowest_span = max(breakdown["span_ms"], key=breakdown["span_ms"].get)
            slowest_ms = breakdown["span_ms"][slowest_span]
            if worst is None or slowest_ms > worst["ms"]:
                worst = {
                    "service": service,
                    "span": slowest_span,
                    "ms": slowest_ms,
                    "deploy": breakdown["recent_deploy"],
                }

        exceptions = mcp.list_exceptions(worst["service"])  # tool call
        tool_calls += 1

        fallback = (
            f"Root cause: {worst['service']} span {worst['span']} at {worst['ms']}ms "
            f"after deploy {worst['deploy']}"
            + (f"; {exceptions[0]['count']} {exceptions[0]['type']} errors." if exceptions else ".")
        )
        summary = self.narrate(
            {"slowest": worst, "exceptions": exceptions, "inspected": services},
            "State the single most likely root cause: service, span, and the deploy that caused it.",
            fallback)
        case_file.append(self.name, "root_cause", summary, {
            "service": worst["service"],
            "span": worst["span"],
            "latency_ms": worst["ms"],
            "deploy": worst["deploy"],
            "exceptions": exceptions,
        })
        return tool_calls, summary
