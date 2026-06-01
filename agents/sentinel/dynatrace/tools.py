"""Per-agent tool scoping. This mapping IS the safety boundary.

Only the Actuator and Scribe hold write tools. Everyone else is read-only, so a
reasoning mistake upstream can never mutate production. The human approval gate
sits immediately before the Actuator.
"""

# Real Dynatrace MCP tool names, scoped per agent.
AGENT_TOOLS: dict[str, list[str]] = {
    "watcher": [
        "execute_dql",                       # read RUM / sessions
        "generate_dql_from_natural_language",
        "list_problems",
    ],
    "tracer": [
        "execute_dql",                       # read spans
        "generate_dql_from_natural_language",
        "find_entity_by_name",
        "list_exceptions",
    ],
    "judge": [
        "execute_dql",                       # read business events
        "list_davis_analyzers",
        "execute_davis_analyzer",            # forecast
    ],
    "actuator": [
        "create_workflow_for_notification",  # WRITE
        "send_event",                        # WRITE
        "send_slack_message",                # WRITE
    ],
    "scribe": [
        "create_dynatrace_notebook",         # WRITE
        "send_slack_message",                # WRITE
    ],
    "evaluator": [
        "execute_dql",                       # read Sentinel's OWN agent traces
    ],
}

WRITE_TOOLS = {
    "create_workflow_for_notification",
    "send_event",
    "send_slack_message",
    "create_dynatrace_notebook",
}


def can_write(agent: str) -> bool:
    return any(tool in WRITE_TOOLS for tool in AGENT_TOOLS.get(agent, []))
