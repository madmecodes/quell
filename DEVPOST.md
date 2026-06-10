# Quell

Autonomous multi-agent incident prevention, built on Dynatrace.

- Console: https://quell-dashboard-908906947513.us-central1.run.app
- Live store (ShopWave): https://shopwave-908906947513.us-central1.run.app
- Repo: https://github.com/madmecodes/quell (MIT)

---

## Inspiration

Most observability platforms tell you what already broke. By the time a human reads the alert, customers have already hit errors and revenue is already gone. We wanted to invert that loop: an agent that lives inside the telemetry, catches a degradation while it is still forming, traces it to the exact faulted service, puts a number on what it will cost if ignored, and prevents it before the page goes out.

The hard part is not the agents. It is the ground truth. An agent reasoning about an incident is only as good as the signals it can see. That is where Dynatrace is the entire foundation: without live Grail data, our agents are blind. Every decision Quell makes traces back to a real DQL query against real RUM, spans, and business events.

## What it does

Quell is an autonomous incident-prevention platform with two halves:

1. **ShopWave** — a real, deployed e-commerce store that generates its own traffic and emits OpenTelemetry to Dynatrace. It exposes five injectable fault scenarios (latency, error spikes, dependency failure, and more) so the system can be exercised against genuine degradations, not mocks.

2. **The orchestrator** — six Gemini agents that run an end-to-end prevention loop:
   - **Watcher** detects a degradation forming in the live signal.
   - **Tracer** discovers which service is at fault by querying across all services from live DQL — it does not assume; it finds.
   - **Judge** quantifies the blast radius: revenue at risk and an error-budget burn forecast.
   - **Actuator** prepares and executes the remediation behind two human approval gates.
   - **Scribe** writes the incident record and fires real Slack alerts.
   - **Evaluator** scores the run and feeds improvements back in — across runs the loop self-optimized from four tool calls down to two.

The console shows live charts, a service topology, and the exact DQL each agent ran, so every conclusion is auditable back to its query.

## How we built it

**Technologies**
- **Gemini 2.5 Pro / Flash on Vertex AI** — reasoning and orchestration across the six agents (Pro for judgment-heavy steps, Flash for fast detection/tracing).
- **Google Cloud Agent Builder / ADK** — the multi-agent runtime and tool wiring.
- **Official Dynatrace MCP server** — the agents' single source of truth; every observation, trace, and forecast comes from MCP-mediated DQL.
- **OpenTelemetry** — ShopWave instrumentation emitting RUM, spans, and business events.
- **Cloud Run** — hosts both the console and the store.

**Data sources** — live Dynatrace Grail: RUM for user-facing degradation, distributed spans for fault localization across services, and bizevents for revenue-at-risk and error-budget math. Nothing is synthetic at decision time; the agents read what is actually in Grail.

## Challenges

- **Fault localization across a fleet.** Detecting "something is wrong" is easy; pinpointing the one faulted service among many from live spans without hardcoding is not. Tracer had to discover the culprit purely from DQL.
- **Making remediation safe.** Autonomous action needs guardrails. We landed on two explicit human approval gates so the agents propose and quantify, but a human authorizes irreversible action.
- **Grounding every claim.** We forced each agent to surface the exact DQL behind its conclusion, so the system stays auditable and never hand-waves.
- **Tuning Gemini model tiers** to keep the loop fast and cheap without losing judgment quality.

## Accomplishments

- An end-to-end loop that goes from live signal to prevented incident, not just detection.
- A **self-improving** agent system: the Evaluator drove the loop from four tool calls to two across runs.
- A fully **live, hosted** demo — real store, real traffic, real Dynatrace data, real Slack alerts — not a recorded walkthrough.
- Quantified business impact (revenue at risk, error-budget burn) attached to every incident, turning telemetry into a decision.

## What we learned

- **Dynatrace is the core, not a data feed.** The agents are only as smart as the Grail signals behind them; the MCP server is what makes autonomous reasoning trustworthy.
- **DQL transparency builds trust.** Showing the exact query under each agent decision was the difference between "a black box said so" and an auditable system.
- **Forecasting beats alerting.** Error-budget burn forecasting changes the conversation from "it broke" to "here is what it will cost if we wait."
- **Approval gates make autonomy shippable.** Humans tolerate aggressive automation when they hold the final switch on irreversible actions.

## What's next

- More fault scenarios and noisier, multi-fault conditions to stress Tracer's localization.
- Tighter remediation library so Actuator can prevent a wider class of incidents.
- Confidence-scored auto-remediation for low-risk, fully reversible fixes (skip a gate when the math is overwhelming).
- Deeper Grail coverage: SLO objects, log events, and cross-tenant topology.

---

## How Quell maps to the four criteria

**Technological Implementation** — Six coordinated Gemini agents on Vertex AI, orchestrated with Google ADK / Agent Builder, reading live Dynatrace Grail through the official MCP server, with autonomous fault discovery across services and a measured self-optimization (4 to 2 tool calls). Deployed on Cloud Run with a real OTel-instrumented store.

**Design** — A console that shows live charts, service topology, and the exact DQL behind every agent decision, plus two human approval gates and real Slack alerts. The system is auditable end to end: every conclusion is traceable to its query.

**Potential Impact** — Quell prevents incidents instead of reporting them, and attaches revenue-at-risk and error-budget burn to each one. That moves observability spend from after-the-fact triage to measurable loss avoidance — directly relevant to any production team running on Dynatrace.

**Quality of Idea** — Putting autonomous agents *inside* the telemetry, grounded entirely in Dynatrace Grail, with safe human gates and a self-improving loop, reframes monitoring from "watch and alert" to "predict and prevent."

**Dynatrace is the core.** Watcher cannot detect, Tracer cannot localize, and Judge cannot forecast without live Grail data through the MCP server. Remove Dynatrace and the agents are blind. It is not a data source bolted on — it is the ground truth the entire system reasons from.

---

Built with Gemini 2.5 Pro/Flash on Vertex AI, Google Cloud Agent Builder (ADK), the official Dynatrace MCP server, OpenTelemetry, and Cloud Run. MIT licensed.
