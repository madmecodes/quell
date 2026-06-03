"""Scribe: write the rescue report and seal the audit trail."""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent


class Scribe(Agent):
    name = "scribe"
    task_type = "report"
    role = (
        "Write the prevented-incident report from the full case file: what would "
        "have broken, who was affected, the action taken, and the impact avoided. "
        "Persist it as the immutable record of this run."
    )

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        detection = case_file.latest("detection")
        root = case_file.latest("root_cause")
        impact = case_file.latest("impact")
        action = case_file.latest("action")

        revenue = impact.data.get("revenue_at_risk_inr", 0) if impact else 0
        carts = impact.data.get("carts_at_risk", 0) if impact else 0

        markdown = "\n".join([
            f"# Prevented Incident: {case_file.incident_id}",
            f"- Detection: {detection.summary if detection else 'n/a'}",
            f"- Root cause: {root.summary if root else 'n/a'}",
            f"- Impact: {impact.summary if impact else 'n/a'}",
            f"- Action: {action.summary if action else 'n/a'}",
            f"- Outcome: {carts} carts rescued, INR {revenue/100000:.1f}L protected.",
        ])
        notebook = mcp.create_dynatrace_notebook(                 # write 1
            title=f"AppMedic rescue {case_file.incident_id}", markdown=markdown,
        )

        summary = f"Rescued. {carts} carts, INR {revenue/100000:.1f}L protected. Report: {notebook['notebook_id']}."
        case_file.append(self.name, "report", summary, {
            "notebook_id": notebook["notebook_id"],
            "carts_rescued": carts,
            "revenue_protected_inr": revenue,
            "markdown": markdown,
        })
        return 1, summary
