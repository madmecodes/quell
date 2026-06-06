# Quell - 3 minute demo script

Goal: show an autonomous multi-agent system that catches a real user-experience
incident on live Dynatrace data, prevents it under human control, and improves
itself - across multiple fault types, with live telemetry on screen.

## Live URLs (record against these)
- ShopWave store: https://shopwave-908906947513.us-central1.run.app
- Quell console: https://quell-dashboard-908906947513.us-central1.run.app  (runs live)

The hosted console reads real Grail and reasons with real Gemini. ShopWave
self-generates continuous traffic, so Dynatrace always has live data.

## Beat 1 - the problem (0:00-0:30)
"When an app degrades, you find out from angry users or the cloud bill. Monitoring
says a server is at 200ms; it can't tell you real shoppers just abandoned checkout
and how much revenue that costs. Quell can - and it fixes it before they leave."
Show ShopWave: a real store with live traffic; the console's live Dynatrace charts.

## Beat 2 - inject a fault (0:30-0:55)
On ShopWave, open Operations and pick a scenario (e.g. "Checkout failing -
payment-svc 5xx") and Inject. As an iOS/US shopper, add to cart and check out -
the payment visibly hangs ("Payment is taking longer than usual..."), then fails.
"A bad deploy is failing checkout for iOS users. No human has touched the console."

## Beat 3 - Quell detects autonomously (0:55-1:40)
Switch to the console. Within ~15s the banner reads "Anomaly detected - Quell
launched this investigation autonomously." Narrate the agents streaming in:
- Watcher: degraded experience, iOS / US.
- Tracer: discovered the cause across ALL services - payment-svc razorpay.charge,
  63 failing requests, deploy #894. Expand "the exact DQL Quell ran" - it's a real
  query against your Grail tenant.
- Judge: 461 users, $15,541 at risk, error budget burning 30x.
Point at the live charts spiking. "This isn't a script - it discovered the faulted
service from real telemetry. Pick a different scenario and it diagnoses a different
root cause."

## Beat 4 - human approves, fix applied (1:40-2:10)
Gate 1 appears. "Autonomy with oversight - it never touches production without you."
Click "Approve rollback". The Actuator rolls back #894, and a prevented-incident
summary posts to Slack (#incidents). Scribe: "Rescued. 365 carts, $12,369 protected."

## Beat 5 - it improves itself (2:10-2:40)
Gate 2: the Evaluator's scorecard, graded from each agent's own Dynatrace traces.
"Tracer used 4 tool calls - inefficient. Approve the lesson." Apply learning, run
again: Tracer now uses the one-shot cross-service scan - 4 calls down to 2.
"It learned, with a human in the loop. Two approvals: the fix, and the learning."

## Beat 6 - close (2:40-3:00)
"Gemini on Agent Builder, the Dynatrace MCP as its senses and hands, watching - and
improving - itself. Five fault types, real diagnosis, real revenue, live the whole
way through. Quell: the on-call shift where nothing breaks."

## Local fully-live run (optional B-roll)
```bash
cd shopwave && SELF_TRAFFIC=true node server.js &     # continuous telemetry
# inject a scenario via the store, then:
cd agents && QUELL_USE_LIVE_DT=true QUELL_USE_LIVE_LLM=true python3 run_demo.py
```
