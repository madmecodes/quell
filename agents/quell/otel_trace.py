"""Quell observing itself.

Emits one OpenTelemetry span per agent run, tagged with the incident id and agent
name, exported to the same Dynatrace tenant the agents monitor. This is what makes
the Evaluator's "grade agents from their own Dynatrace traces" real: the agent
spans land in Grail and can be queried back via DQL
(`fetch spans | filter incident_id == ...`).

Exports only when DT_ENVIRONMENT and DT_INGEST_TOKEN are set; otherwise every call
is a no-op so the system runs anywhere. Safe to import in mock mode.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

_tracer = None
_initialised = False


def _init():
    global _tracer, _initialised
    if _initialised:
        return _tracer
    _initialised = True
    # Ingest is on the classic .live host; prefer DT_INGEST_BASE, else derive it.
    env = (os.environ.get("DT_INGEST_BASE")
           or (os.environ.get("DT_ENVIRONMENT") or "").replace(".apps.dynatrace.com",
                                                               ".live.dynatrace.com")).rstrip("/")
    token = os.environ.get("DT_INGEST_TOKEN") or ""
    if not env or not token:
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider = TracerProvider(resource=Resource.create({"service.name": "quell"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=f"{env}/api/v2/otlp/v1/traces",
            headers={"Authorization": f"Api-Token {token}"},
        )))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("quell")
    except Exception:
        _tracer = None
    return _tracer


@contextmanager
def agent_span(agent: str, incident_id: str):
    """Wrap an agent run in a span carrying the agent name and incident id."""
    tracer = _init()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(f"agent.{agent}") as span:
        span.set_attribute("agent", agent)
        span.set_attribute("incident_id", incident_id)
        yield span
