"""Judge: quantify business impact and forecast the breach on the faulted span."""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent


class Judge(Agent):
    name = "judge"
    task_type = "impact"
    role = (
        "Quantify the impact of the root cause: real users affected, carts at risk, "
        "revenue at risk, and forecast how long until the error budget is exhausted on "
        "the faulted span. Output the business stakes in plain numbers."
    )
    instruction = (
        "Quantify the business impact for the affected segment (users, carts, USD at risk) "
        "and forecast the error-budget breach on the faulted span. Use the two tools, then "
        "state the stakes in plain numbers.")

    @staticmethod
    def _fault(case_file):
        rc = case_file.latest("root_cause")
        d = rc.data if rc else {}
        return d.get("service"), d.get("span")

    # ---- genuine tool-calling path ----

    def observe(self, case_file: CaseFile) -> str:
        d = case_file.latest("detection")
        seg = d.data.get("segment", "all") if d else "all"
        rc = case_file.latest("root_cause")
        return f"Segment '{seg}' is affected by: {rc.summary if rc else 'a backend fault'}"

    def tool_callables(self, mcp: MockMCP, sink: dict) -> list:
        service, span = self._fault(sink.get("_case"))

        def business_impact(segment: str) -> dict:
            """Users affected, carts at risk, and revenue at risk (USD) for a segment.
            Args: segment: e.g. 'iOS / US'."""
            bi = mcp.business_impact(segment)
            sink["impact"] = bi
            return bi

        def forecast_breach() -> dict:
            """Forecast when the error budget is exhausted on the faulted span."""
            f = mcp.davis_forecast(service, span)
            sink["forecast"] = f
            return f

        return [business_impact, forecast_breach]

    def finalize(self, case_file: CaseFile, sink: dict, text: str) -> str:
        d = case_file.latest("detection")
        segment = d.data.get("segment", "all") if d else "all"
        service, span = self._fault(case_file)
        impact = sink.get("impact") or self._mcp.business_impact(segment)
        forecast = sink.get("forecast") or self._mcp.davis_forecast(service, span)
        return self._record(case_file, impact, forecast, text)

    def _record(self, case_file, impact, forecast, rationale):
        if impact["users_affected"] == 0:
            summary = "No measurable business impact."
            case_file.append(self.name, "impact", summary, impact)
            return summary
        summary = (f"Impact: {impact['users_affected']} users, {impact['carts_at_risk']} carts, "
                   f"${impact['revenue_at_risk_usd']:,.0f} at risk.")
        if forecast.get("burn_multiple"):
            summary += (f" Error budget burning {forecast['burn_multiple']}x "
                        f"({forecast['breaching']}/{forecast['total']} requests slow or failing) "
                        f"-> exhausts in {forecast['breach_eta']}.")
        elif forecast.get("breach_eta"):
            summary += f" Forecast SLA breach in {forecast['breach_eta']}."
        case_file.append(self.name, "impact", summary,
                         {**impact, **forecast, "dql": self._mcp.queries.get("forecast"),
                          "llm_rationale": rationale})
        return summary

    # ---- deterministic fallback ----

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        d = case_file.latest("detection")
        segment = d.data.get("segment", "all") if d else "all"
        service, span = self._fault(case_file)
        impact = mcp.business_impact(segment)                  # tool call 1
        forecast = mcp.davis_forecast(service, span)           # tool call 2
        summary = self._record(case_file, impact, forecast, "")
        return 2, summary
