"""Actuator: execute the approved fix via Dynatrace write tools.

Runs only AFTER the human approves at Gate 1. Holds the one reversible action
(the compensation / undo) so a bad fix can be rolled back.
"""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent


class Actuator(Agent):
    name = "actuator"
    task_type = "remediation"
    role = (
        "Execute the approved preventive fix using Dynatrace workflows and events, "
        "and notify the owning team. Keep the action reversible."
    )

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        root = case_file.latest("root_cause")
        impact = case_file.latest("impact")
        deploy = root.data.get("deploy", "unknown") if root else "unknown"
        service = root.data.get("service", "unknown") if root else "unknown"

        workflow = mcp.create_workflow_for_notification(           # write 1
            name=f"rollback-{deploy}",
            action=f"rollback {service} to pre-{deploy} revision",
        )
        mcp.send_event(                                            # write 2
            title=f"Preventive rollback of {deploy}",
            properties={"service": service, "reason": "predicted SLA breach"},
        )
        revenue = impact.data.get("revenue_at_risk_inr", 0) if impact else 0
        mcp.send_slack_message(                                    # write 3
            channel="#ops",
            text=(f"AppMedic: rolled back {deploy} on {service}. "
                  f"Prevented ~INR {revenue/100000:.1f}L impact. Approved by on-call."),
        )

        summary = f"Rolled back {deploy} on {service}; ops notified. Action is reversible."
        case_file.append(self.name, "action", summary, {
            "workflow_id": workflow["workflow_id"],
            "rolled_back": deploy,
            "service": service,
            "reversible": True,
        })
        return 3, summary
