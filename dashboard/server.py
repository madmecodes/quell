"""Sentinel operator dashboard.

A dependency-free (stdlib) web server that drives the orchestrator and surfaces
the two human gates. The pipeline runs in a background thread; the gate callbacks
block on threading.Events that the HTTP approve endpoints release. The frontend
polls /api/state and renders the live rescue, the approval buttons, and the
self-improvement scorecard.

    python3 server.py        # then open http://localhost:8090
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# make the agents package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from sentinel.agents.evaluator import Scorecard  # noqa: E402
from sentinel.case_file import CaseFile  # noqa: E402
from sentinel.dynatrace.mock_mcp import ChaosState  # noqa: E402
from sentinel.dynatrace.factory import make_dynatrace  # noqa: E402
from sentinel.memory import LessonStore  # noqa: E402
from sentinel.orchestrator import Orchestrator  # noqa: E402

STATIC = Path(__file__).parent / "static"


class RunSession:
    """One incident run, advanced by the human via HTTP."""

    _counter = 0

    def __init__(self, store: LessonStore):
        RunSession._counter += 1
        self.id = f"INC-{RunSession._counter:03d}"
        self.case: CaseFile | None = None
        self.scorecard: Scorecard | None = None
        self.pending: str | None = None       # "action" | "learning" | None
        self.done = False
        self.applied_lessons: list[str] = []
        self.applied_defs: list[str] = []

        self._action_event = threading.Event()
        self._action_ok = False
        self._learning_event = threading.Event()
        self._learning_approved: set[str] = set()

        chaos = ChaosState(active=True, fault="payment_latency", service="payment-svc",
                           span="razorpay.charge", segment="Android / IN", deploy="#847",
                           added_latency_ms=400)
        # Mock by default; set SENTINEL_USE_LIVE_DT=true to read real Grail data.
        self._orch = Orchestrator(make_dynatrace(chaos), store)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        result = self._orch.handle(self.id, self._gate_action, self._gate_learning)
        self.applied_lessons = result.applied_lessons
        self.applied_defs = result.applied_definition_edits
        self.done = True
        self.pending = None

    def _gate_action(self, case: CaseFile) -> bool:
        self.case = case
        self.pending = "action"
        self._action_event.wait()
        self.pending = None
        return self._action_ok

    def _gate_learning(self, card: Scorecard) -> set[str]:
        self.scorecard = card
        self.pending = "learning"
        self._learning_event.wait()
        self.pending = None
        return self._learning_approved

    def approve_action(self, ok: bool):
        self._action_ok = ok
        self._action_event.set()

    def approve_learning(self, agents: list[str]):
        self._learning_approved = set(agents)
        self._learning_event.set()

    def snapshot(self) -> dict:
        entries = []
        if self.case:
            entries = [{"step": e.step, "agent": e.agent, "kind": e.kind,
                        "summary": e.summary, "data": e.data} for e in self.case.entries()]
        card = None
        if self.scorecard:
            card = [{"agent": g.agent, "score": g.score, "notes": g.notes,
                     "lesson": g.proposed_lesson, "definition_edit": g.proposed_definition_edit}
                    for g in self.scorecard.grades]
        return {"id": self.id, "pending": self.pending, "done": self.done,
                "entries": entries, "scorecard": card,
                "applied_lessons": self.applied_lessons, "applied_defs": self.applied_defs}


STORE = LessonStore()
CURRENT: RunSession | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        global CURRENT
        if self.path == "/" or self.path == "/index.html":
            self._send(200, (STATIC / "index.html").read_bytes(), "text/html")
        elif self.path == "/api/state":
            self._json(CURRENT.snapshot() if CURRENT else {"id": None})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        global CURRENT
        if self.path == "/api/start":
            CURRENT = RunSession(STORE)
            self._json({"started": CURRENT.id})
        elif self.path == "/api/approve-action":
            if CURRENT:
                CURRENT.approve_action(bool(self._body().get("ok", True)))
            self._json({"ok": True})
        elif self.path == "/api/approve-learning":
            if CURRENT:
                CURRENT.approve_learning(self._body().get("agents", []))
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")


def main():
    import os
    port = int(os.environ.get("PORT", "8090"))
    print(f"[sentinel] dashboard on http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
