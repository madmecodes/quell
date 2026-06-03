"""End-to-end AppMedic demo in mock mode (no credentials needed).

Injects a fault via the Chaos Panel, runs the 6-agent pipeline through both human
gates, and shows the rescue plus the self-improvement loop across two runs.

    python3 run_demo.py
"""

from __future__ import annotations

from appmedic.agents.evaluator import Scorecard
from appmedic.case_file import CaseFile
from appmedic.dynatrace.mock_mcp import ChaosState, MockMCP
from appmedic.memory import LessonStore
from appmedic.orchestrator import Orchestrator

LINE = "-" * 70


def show_case(case: CaseFile) -> None:
    for e in case.entries():
        print(f"  [{e.step}] {e.agent:<9} {e.summary}")


def auto_approve_action(case: CaseFile) -> bool:
    impact = case.latest("impact")
    print(f"\n  >> GATE 1 (action): {impact.summary if impact else ''}")
    print("     human clicks APPROVE")
    return True


def auto_approve_learning(card: Scorecard) -> set[str]:
    print("\n  >> GATE 2 (learning): scorecard")
    for g in card.grades:
        flag = "  <- improvement proposed" if (g.proposed_lesson or g.proposed_definition_edit) else ""
        print(f"     {g.agent:<9} score {g.score:<4} {g.notes}{flag}")
    approved = {g.agent for g in card.weak()}
    if approved:
        print(f"     human APPROVES learning for: {', '.join(sorted(approved))}")
    return approved


def main() -> None:
    store = LessonStore()
    chaos = ChaosState(
        active=True, fault="payment_latency", service="payment-svc",
        span="razorpay.charge", segment="Android / IN", deploy="#847",
        added_latency_ms=400,
    )

    print(LINE)
    print("RUN 1  (Tracer has no lessons yet)")
    print(LINE)
    mcp = MockMCP(chaos=chaos)
    orch = Orchestrator(mcp, store)
    r1 = orch.handle("INC-001", auto_approve_action, auto_approve_learning)
    print("\n  Case file:")
    show_case(r1.case_file)
    print(f"\n  Tracer tool calls this run: {mcp.get_agent_traces('INC-001')['tracer']['tool_calls']}")
    if r1.applied_lessons:
        print("  Lessons written to memory:")
        for le in r1.applied_lessons:
            print(f"    - {le}")
    if r1.applied_definition_edits:
        print("  Definition edits recommended (human-approved):")
        for de in r1.applied_definition_edits:
            print(f"    - {de}")

    print("\n" + LINE)
    print("RUN 2  (same fault recurs; Tracer now reads its lesson first)")
    print(LINE)
    print(f"  Tracer memory now contains:\n    {store.as_context('tracer', 'root_cause') or '(none)'}")
    mcp2 = MockMCP(chaos=chaos)
    orch2 = Orchestrator(mcp2, store)
    r2 = orch2.handle("INC-002", auto_approve_action, auto_approve_learning)
    print("\n  Case file:")
    show_case(r2.case_file)

    t1 = mcp.get_agent_traces("INC-001")["tracer"]["tool_calls"]
    t2 = mcp2.get_agent_traces("INC-002")["tracer"]["tool_calls"]
    s1 = next(g.score for g in r1.scorecard.grades if g.agent == "tracer")
    s2 = next(g.score for g in r2.scorecard.grades if g.agent == "tracer")
    print("\n" + LINE)
    print("SELF-IMPROVEMENT RESULT")
    print(LINE)
    print(f"  Tracer tool calls : run1={t1}  ->  run2={t2}")
    print(f"  Tracer score      : run1={s1}  ->  run2={s2}")
    print("  Same incident, fewer steps, higher score -- the agent learned.")


if __name__ == "__main__":
    main()
