"""Post incident alerts to Slack via chat.postMessage.

Real action surface for the Actuator: when SLACK_BOT_TOKEN and SLACK_CHANNEL are
set, a prevented-incident message is posted to the channel. No-ops otherwise so the
system runs without Slack configured.
"""

from __future__ import annotations

import json
import os
import urllib.request


def post(text: str) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL")
    if not token or not channel:
        return {"skipped": True}
    body = json.dumps({"channel": channel, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return {"ok": r.get("ok"), "error": r.get("error")}
    except Exception as e:  # network/credential issues never break a run
        return {"ok": False, "error": str(e)}
