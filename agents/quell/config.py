"""Live-path configuration (Vertex AI / Gemini).

The GCP project is taken from the environment (QUELL_GCP_PROJECT, falling back to
SENTINEL_GCP_PROJECT) and has no hardcoded default -- a missing/misconfigured
project must fail loudly rather than silently 403 against a non-existent project.
Verified working config:
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

# Resolve the project from the env. Accept the QUELL_* name first, then the
# SENTINEL_* name used by the deployment .env. No hardcoded default: a wrong or
# absent project should surface as a clear Vertex auth error, not a silent 403
# against a project that does not exist.
GCP_PROJECT = (
    os.environ.get("QUELL_GCP_PROJECT")
    or os.environ.get("SENTINEL_GCP_PROJECT")
    or ""
)
GCP_LOCATION = (
    os.environ.get("QUELL_GCP_LOCATION")
    or os.environ.get("SENTINEL_GCP_LOCATION")
    or "global"
)

# Worker agents (Watcher, Tracer, Judge, Actuator, Scribe). Swap to a Gemini 3
# id here once access is granted.
WORKER_MODEL = os.environ.get("QUELL_WORKER_MODEL", "gemini-2.5-pro")

# Evaluator: different model family/tier than the workers (bias mitigation).
EVALUATOR_MODEL = os.environ.get("QUELL_EVALUATOR_MODEL", "gemini-2.5-flash")

# Set true to use real Vertex/Gemini reasoning; false runs the deterministic mock.
USE_LIVE_LLM = os.environ.get("QUELL_USE_LIVE_LLM", "false").lower() == "true"
