# Quell — 3-Minute Demo Video Script & Shot List

One-line pitch (use at the end): **Quell is an autonomous multi-agent platform that detects, diagnoses, and prevents production incidents on live Dynatrace telemetry before they hit revenue — with humans in the loop only at the gates that matter.**

## Setup before recording

- Browser, two tabs:
  - Tab 1 — Console: `https://quell-dashboard-908906947513.us-central1.run.app`
  - Tab 2 — Store: `https://shopwave-908906947513.us-central1.run.app`
- Slack open in a third window (or picture-in-picture), pinned to the alerts channel.
- Console scrolled to top (hero). Confirm ShopWave self-traffic is running so charts are live and green.
- Have one fault scenario chosen on the store but NOT injected yet (e.g. checkout-service latency / 5xx).
- Screen recording at 1080p+, 30fps. No emojis on screen, no cursor jitter.
- Rehearse the auto-detect timing once: after injection, Quell auto-detects in ~15s. Do not press Detect.

---

## 0:00–0:18 — Cold open: the hero and the stakes

Screen: Console hero, top of page. Slow scroll showing the live Dynatrace charts (green/healthy) and the service-topology map.

Narration:
> "This is Quell. It watches a live store running on Dynatrace Grail, and its job is to stop incidents before they cost money. Right now everything is healthy — real OpenTelemetry, real charts, real service topology. Watch what happens when something breaks."

Show: cursor rests briefly on the topology map so the viewer registers the connected services, then on the green latency/error-rate charts.

---

## 0:18–0:35 — Inject the fault on the live store (do NOT press Detect)

Screen: Switch to Tab 2 (ShopWave store). Click the fault-injection control, select the scenario, inject it. Briefly show the store degrading (slow checkout / errors).

Narration:
> "I'm going to break the live store myself — injecting a checkout fault directly into ShopWave. I am not going to tell Quell. I'm not pressing 'Detect'. Quell has to notice on its own."

Show: the injection confirmation on the store. Then cut back to Tab 1 (Console) and just wait.

---

## 0:35–0:55 — Autonomous detection (the strongest beat)

Screen: Console. Hold on the live Dynatrace charts. Within ~15s the latency/error-rate line breaches the threshold and the **"Anomaly detected"** banner appears autonomously.

Narration:
> "No human touched Quell. Within about fifteen seconds the Watcher agent reads live DQL from Dynatrace, the chart breaches, and Quell raises the anomaly on its own. That's the whole point — autonomous detection, not a button."

Show: the breaching chart line crossing the threshold, then the auto "Anomaly detected" banner lighting up. Let it land for a beat.

---

## 0:55–1:25 — Diagnosis: discover the faulted service across all services

Screen: Console agent timeline. Show the Watcher → Tracer hand-off. Expand a step to reveal the **exact DQL** query and the tool call.

Narration:
> "Now the agents go to work. The Tracer queries every service in the topology with live DQL — it doesn't know in advance where the fault is. It correlates across all services and pinpoints the faulted one. Everything you see is the real query and the real tool call, nothing scripted."

Show: the service-topology map highlighting the **blast radius** — the faulted service and its dependents lighting up. Hover the faulted node.

---

## 1:25–1:50 — Quantify: revenue at risk + error-budget burn

Screen: Console impact panel / the Judge agent step. Show revenue-at-risk figure and the error-budget burn forecast.

Narration:
> "The Judge quantifies it in business terms — revenue at risk right now, and the error-budget burn forecast if we do nothing. This is what turns a chart spike into a decision a human can actually make."

Show: the impact wall numbers (revenue at risk, burn-rate forecast, affected services count). Let the numbers be readable for 2–3 seconds.

---

## 1:50–2:20 — Prevention with two human approval gates

Screen: Console. The Actuator proposes a remediation. **Gate 1** approval prompt appears.

Narration:
> "Quell never acts blindly. The Actuator proposes a fix, and it pauses at the first human approval gate. I approve."

Action: Click **Approve** on Gate 1.

Narration (continued):
> "It validates, then pauses again at a second gate before it actually applies the change. Two gates — propose, then commit. I approve again."

Action: Click **Approve** on Gate 2. Show the remediation executing and the charts beginning to recover.

---

## 2:20–2:35 — Real Slack alert fires

Screen: Cut to Slack window. The real alert message lands in the channel.

Narration:
> "And this isn't a demo notification — Quell fires a real Slack alert to the on-call channel, with the service, the impact, and the action taken. The team is in the loop the whole way."

Show: the Slack message expanded — service name, revenue impact, remediation summary.

---

## 2:35–2:50 — Self-improvement (4 → 2 tool calls)

Screen: Back to Console. Show the Evaluator / self-improvement panel: the run that took 4 tool calls, and the next run reduced to 2.

Narration:
> "After every incident the Evaluator critiques the run and tightens the playbook. The same diagnosis that took four tool calls now takes two. Quell gets cheaper and faster every time it runs."

Show: the 4 → 2 metric clearly, side by side or before/after.

---

## 2:50–3:00 — Close + pitch

Screen: Pull back to the console hero, charts now recovered to green, topology healthy again.

Narration:
> "Detected on its own, diagnosed on live telemetry, prevented at a human gate, and improved for next time. Quell — autonomous incident prevention on real Dynatrace data. It's open source, MIT, and live right now."

On-screen lower-third (text overlay, no emojis):
- Console: quell-dashboard-908906947513.us-central1.run.app
- Store: shopwave-908906947513.us-central1.run.app
- Repo: github.com/madmecodes/quell (MIT)
- Stack: Gemini 2.5 Pro/Flash on Vertex AI · Google ADK (Agent Builder) · official Dynatrace MCP · Cloud Run

Final line (voice):
> "Quell — it stops incidents before they cost you."

---

## Director's notes / risk hedges

- The auto-detect beat (0:35–0:55) is the money shot. If detection runs slightly slower or faster than 15s, keep narrating the live charts — do not cut away, the unscripted wait is the proof.
- If for any reason auto-detect stalls on the take, have a backup take ready; never press Detect on camera — pressing it destroys the core claim.
- Keep the exact-DQL visible on screen for at least 2 seconds at 0:55–1:25 — judges weight "real queries" heavily (tech audit 0.78).
- Lead with the live, autonomous, end-to-end run (narrative audit 0.85 is your strength). Spend the most screen time on detect → diagnose → approve → Slack.
- Underweight beats: live-scenarios and compliance scored low in audit — do not dwell on scenario variety or governance claims; show one clean scenario end to end instead.
- Six agents named once is enough: Watcher (detect), Tracer (locate), Judge (quantify), Actuator (remediate), Scribe (alert/record), Evaluator (self-improve). Don't enumerate them on screen mid-action — it slows the pace.
- Total spoken word count is tuned for ~3:00 at a calm pace. If running long, trim the director's-note pauses, not the narration.
