# AppMedic - 3 minute demo script

Goal: show a multi-agent system that catches a real user-experience incident,
prevents it under human control, and improves itself - all observed in Dynatrace.

## Setup (before recording)
```bash
./run_all.sh                      # ShopWave :8080, AppMedic console :8090
cd shopwave && node traffic.js    # steady real traffic (optional, for live mode)
```
Have two tabs open: ShopWave (8080) and the AppMedic console (8090).

## Beat 1 - the problem (0:00-0:30)
"Teams find out their app is broken from angry users or the cloud bill. Monitoring
tells you a server is at 200ms; it can't tell you 2,400 real users just abandoned
checkout because of it. AppMedic can - and it fixes it before they leave."

Show ShopWave: a live store, traffic flowing, Dynatrace receiving telemetry.

## Beat 2 - inject the fault (0:30-0:50)
On ShopWave, click the Chaos Panel: "Inject: slow payment (Android / IN)".
"A bad deploy just slowed the payment service - but only for Android users in
India. No alert has fired yet."

## Beat 3 - AppMedic detects, traces, quantifies (0:50-1:40)
On the AppMedic console, click "Detect & prevent incident". Narrate the agents:
- Watcher: degraded checkout experience, Android / IN, apdex 0.58.
- Tracer: root cause - payment-svc razorpay.charge span +400ms, deploy #847.
- Judge: 1,800 users, 2,400 carts, $8,400 at risk, SLA breach in ~1h.
"Front-end pain, back-end cause, business impact - one chain. Only Dynatrace has
all three signals."

## Beat 4 - human approves, fix applied (1:40-2:10)
Gate 1 appears. "AppMedic never touches production on its own."
Click "Approve rollback". Actuator rolls back #847, notifies ops; Scribe reports:
"Rescued. 2,400 carts, $8,400 protected." Show the metric recover on ShopWave.

## Beat 5 - it improves itself (2:10-2:45)
Gate 2: the Evaluator's scorecard, graded from each agent's own Dynatrace traces.
"Tracer scored 0.85 - it scanned every service. We approve the lesson."
Click "Apply approved learning". Run a second incident: Tracer now goes straight
to the implicated service - 4 tool calls down to 2, score 1.0.
"The agent learned, with a human in the loop. Two checkpoints: approve the action,
approve the learning."

## Beat 6 - close (2:45-3:00)
"Gemini on Agent Builder, the Dynatrace MCP as its senses and hands, observing
even itself. AppMedic: the on-call shift where nothing breaks."
