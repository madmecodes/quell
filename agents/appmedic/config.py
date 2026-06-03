"""Live-path configuration (Vertex AI / Gemini).

Verified working for project appmedic-hack-2026:
  - host:   aiplatform.googleapis.com
  - region: global   (us-central1 returns 404 for these models)
  - models: gemini-2.5-pro, gemini-2.5-flash  (gemini-3-* not yet allowlisted)

The Evaluator MUST run on a different model than the worker agents to avoid
self-preference bias, so it is pinned to flash while the workers use pro.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load the project .env (if present) into os.environ without overriding
    anything already set. Keeps the live path zero-config: creds and flags in
    .env are picked up automatically."""
    root = Path(__file__).resolve().parents[2]
    dotenv = root / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

GCP_PROJECT = os.environ.get("APPMEDIC_GCP_PROJECT", "appmedic-hack-2026")
GCP_LOCATION = os.environ.get("APPMEDIC_GCP_LOCATION", "global")

# Worker agents (Watcher, Tracer, Judge, Actuator, Scribe). Swap to a Gemini 3
# id here once access is granted.
WORKER_MODEL = os.environ.get("APPMEDIC_WORKER_MODEL", "gemini-2.5-pro")

# Evaluator: different model family/tier than the workers (bias mitigation).
EVALUATOR_MODEL = os.environ.get("APPMEDIC_EVALUATOR_MODEL", "gemini-2.5-flash")

# Set true to use real Vertex/Gemini reasoning; false runs the deterministic mock.
USE_LIVE_LLM = os.environ.get("APPMEDIC_USE_LIVE_LLM", "false").lower() == "true"
