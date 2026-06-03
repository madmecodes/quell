"""Watcher: detect degraded real-user experience from RUM, segmented."""

from __future__ import annotations

from ..case_file import CaseFile
from ..dynatrace.mock_mcp import MockMCP
from .base import Agent


class Watcher(Agent):
    name = "watcher"
    task_type = "experience_detection"
    role = (
        "Watch real-user monitoring data. Detect when a user segment is having a "
        "degraded experience (low apdex, rage-clicks, broken journeys) and report "
        "which segment and journey, before any alert fires."
    )
    instruction = (
        "Determine whether any user segment is having a degraded experience. Inspect "
        "real-user metrics by segment and check for active problems, then report which "
        "segment and journey is affected, or that all segments are healthy.")

    # ---- genuine tool-calling path ----

    def observe(self, case_file: CaseFile) -> str:
        return "Investigate ShopWave's real-user experience across all segments right now."

    def tool_callables(self, mcp: MockMCP, sink: dict) -> list:
        def experience_by_segment() -> dict:
            """Get apdex, rage-click count and conversion for each user segment from RUM."""
            rum = mcp.rum_experience()
            bad = next((s for s in rum["segments"] if s.get("apdex", 1) < 0.7), None)
            sink["rum"] = rum
            sink["bad"] = bad
            return rum

        def active_problems() -> list:
            """List active Davis problems and the services they affect."""
            p = mcp.list_problems()
            sink["problems"] = p
            return p

        return [experience_by_segment, active_problems]

    def finalize(self, case_file: CaseFile, sink: dict, text: str) -> str:
        if "rum" not in sink:
            sink["rum"] = self._mcp.rum_experience()
            sink["bad"] = next((s for s in sink["rum"]["segments"] if s.get("apdex", 1) < 0.7), None)
        if "problems" not in sink:
            sink["problems"] = self._mcp.list_problems()
        bad, problems = sink.get("bad"), sink.get("problems", [])
        if not bad:
            summary = "All segments healthy. No degraded experience detected."
            case_file.append(self.name, "detection", summary, {"healthy": True})
            return summary
        summary = (f"Degraded experience: segment {bad['segment']} on {bad.get('journey','')} "
                   f"journey (apdex {bad['apdex']:.2f}, {bad['rage_clicks']} rage-clicks).")
        case_file.append(self.name, "detection", summary, {
            "segment": bad["segment"], "journey": bad.get("journey", ""),
            "apdex": bad["apdex"], "rage_clicks": bad["rage_clicks"],
            "linked_problem": problems[0]["id"] if problems else None,
            "suspect_service": problems[0]["affected_service"] if problems else None,
            "llm_rationale": text,
        })
        return summary

    # ---- deterministic fallback ----

    def reason(self, case_file: CaseFile, mcp: MockMCP) -> tuple[int, str]:
        problems = mcp.list_problems()          # tool call 1
        rum = mcp.rum_experience()              # tool call 2

        if rum["healthy"]:
            summary = "All segments healthy. No degraded experience detected."
            case_file.append(self.name, "detection", summary, {"healthy": True})
            return 2, summary

        bad = next(s for s in rum["segments"] if s.get("apdex", 1) < 0.7)
        fallback = (
            f"Degraded experience: segment {bad['segment']} on {bad['journey']} journey "
            f"(apdex {bad['apdex']:.2f}, {bad['rage_clicks']} rage-clicks) since {bad['started']}."
        )
        summary = self.narrate(
            {"segments": rum["segments"], "problems": problems},
            "Identify which user segment and journey is degraded and why it matters.",
            fallback)
        case_file.append(self.name, "detection", summary, {
            "segment": bad["segment"],
            "journey": bad["journey"],
            "apdex": bad["apdex"],
            "rage_clicks": bad["rage_clicks"],
            "linked_problem": problems[0]["id"] if problems else None,
            "suspect_service": problems[0]["affected_service"] if problems else None,
        })
        return 2, summary
