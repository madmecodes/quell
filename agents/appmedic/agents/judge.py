"""Judge: quantify business impact and forecast the breach."""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent


class Judge(Agent):
    name = "judge"
    task_type = "impact"
    role = (
        "Quantify the impact of the root cause across all dimensions: real users "
        "affected, carts/journeys at risk, revenue at risk, and forecast how long "
        "until an SLA breach. Output the business stakes in plain numbers."
    )
    instruction = (
        "Quantify the business impact for the affected segment: how many real users and "
        "carts are at risk, how much revenue is at risk, and how long until an SLA "
        "breach. Use the business-impact and forecast tools, then state the stakes.")

    # ---- genuine tool-calling path ----

    def observe(self, case_file: CaseFile) -> str:
        d = case_file.latest("detection")
        seg = d.data.get("segment", "all") if d else "all"
        rc = case_file.latest("root_cause")
        cause = rc.summary if rc else "a backend slowdown"
        return f"Segment '{seg}' is affected by: {cause}"

    def tool_callables(self, mcp: MockMCP, sink: dict) -> list:
        def business_impact(segment: str) -> dict:
            """Get users affected, carts at risk, and revenue at risk (INR) for a segment.
            Args: segment: the affected user segment, e.g. 'Android / IN'."""
            bi = mcp.business_impact(segment)
            sink["impact"] = bi
            return bi

        def forecast_breach(metric: str) -> dict:
            """Forecast how long until an SLA/error-budget breach for a metric.
            Args: metric: e.g. 'error_budget' or 'checkout_conversion'."""
            f = mcp.davis_forecast(metric)
            sink["forecast"] = f
            return f

        return [business_impact, forecast_breach]

    def finalize(self, case_file: CaseFile, sink: dict, text: str) -> str:
        d = case_file.latest("detection")
        segment = d.data.get("segment", "all") if d else "all"
        impact = sink.get("impact") or self._mcp.business_impact(segment)
        forecast = sink.get("forecast") or self._mcp.davis_forecast("error_budget")
        if impact["users_affected"] == 0:
            summary = "No measurable business impact."
            case_file.append(self.name, "impact", summary, impact)
            return summary
        revenue_lakh = impact["revenue_at_risk_inr"] / 100000
        summary = (f"Impact: {impact['users_affected']} users, {impact['carts_at_risk']} carts, "
                   f"INR {revenue_lakh:.1f}L at risk. Forecast SLA breach in {forecast['breach_eta']}.")
        case_file.append(self.name, "impact", summary,
                         {**impact, "breach_eta": forecast["breach_eta"], "llm_rationale": text})
        return summary

    # ---- deterministic fallback ----

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        detection = case_file.latest("detection")
        segment = detection.data.get("segment", "all") if detection else "all"

        impact = mcp.business_impact(segment)              # tool call 1
        mcp.davis_forecast("checkout_conversion")          # tool call 2 (list analyzers, conceptually)
        forecast = mcp.davis_forecast("error_budget")      # tool call 3

        if impact["users_affected"] == 0:
            summary = "No measurable business impact."
            case_file.append(self.name, "impact", summary, impact)
            return 3, summary

        revenue_lakh = impact["revenue_at_risk_inr"] / 100000
        fallback = (
            f"Impact: {impact['users_affected']} users, {impact['carts_at_risk']} carts, "
            f"INR {revenue_lakh:.1f}L at risk. Forecast SLA breach in {forecast['breach_eta']}."
        )
        summary = self.narrate(
            {**impact, "breach_eta": forecast["breach_eta"]},
            "Quantify the business impact in plain numbers (users, carts, INR at risk, breach ETA).",
            fallback)
        case_file.append(self.name, "impact", summary, {
            **impact,
            "breach_eta": forecast["breach_eta"],
        })
        return 3, summary
