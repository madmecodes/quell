# Quell — Architecture

Quell is a multi-agent system that catches a degraded user experience in a live
app, traces the cause, quantifies the business impact, and prevents it — with a
human in the loop — then improves its own agents. These diagrams render on GitHub.

---

## 1. The big picture — two halves

The **patient** (ShopWave, a live store) emits telemetry. The **doctor** (Quell,
six AI agents) reads that telemetry through Dynatrace, reasons with Gemini, and acts.

```mermaid
flowchart LR
  subgraph P["THE PATIENT — ShopWave (live store)"]
    FE["Storefront + Chaos Panel"]
    API["APIs: catalog, cart, payment"]
    TG["Traffic generator"]
  end

  subgraph DT["DYNATRACE (Grail)"]
    RUM["RUM / user experience"]
    SP["Spans / traces"]
    BIZ["Business events"]
  end

  subgraph D["THE DOCTOR — Quell"]
    ORCH["Orchestrator"]
    AGENTS["6 agents: Watcher, Tracer, Judge,\nActuator, Scribe, Evaluator"]
    UI["Operator console (2 human gates)"]
  end

  GEM["Gemini on Vertex AI\n(reasoning)"]

  FE -->|OTel| DT
  API -->|OTel spans| DT
  TG --> API
  DT -->|MCP / DQL read| ORCH
  ORCH --> AGENTS
  AGENTS <-->|reason / pick tools| GEM
  AGENTS -->|MCP write: workflow, event, Slack| DT
  ORCH <--> UI
```

---

## 2. The incident lifecycle (what happens, in order)

```mermaid
sequenceDiagram
  actor You
  participant Shop as ShopWave
  participant DT as Dynatrace
  participant AM as Quell agents
  participant Gem as Gemini

  You->>Shop: Inject fault (slow payment, Android/IN)
  Shop->>DT: telemetry now shows degraded experience
  You->>AM: "Detect & prevent incident"
  AM->>DT: Watcher reads RUM (which segment is hurting?)
  AM->>Gem: reason over the data
  AM->>DT: Tracer reads spans (which service/deploy?)
  AM->>DT: Judge reads business events (revenue at risk?)
  AM-->>You: GATE 1 — here's the fix, approve?
  You->>AM: Approve rollback
  AM->>DT: Actuator: create workflow + event + Slack
  AM->>DT: Scribe: write prevented-incident report
  AM->>DT: Evaluator reads agents' OWN traces, grades them
  AM-->>You: GATE 2 — approve what each agent learns?
  You->>AM: Approve learning
  Note over AM: lesson saved to memory → next run is faster
```

---

## 3. The orchestrated pipeline + the immutable Case File

One central orchestrator runs the agents in order. Each agent reads the shared
**Case File**, appends exactly one finding, and hands it on. Two human gates sit in
the flow. This is orchestration (one controller), not choreography (agents messaging
each other) — chosen for traceability and control.

```mermaid
flowchart TD
  START([Incident detected]) --> W[Watcher<br/>degraded segment]
  W --> T[Tracer<br/>service + span + deploy]
  T --> J[Judge<br/>users, carts, revenue at risk]
  J --> G1{{"GATE 1 — human approves action"}}
  G1 -->|approve| A[Actuator<br/>rollback + notify]
  G1 -->|reject| STOP1([stop])
  A --> S[Scribe<br/>prevented-incident report]
  S --> E[Evaluator<br/>grade agents from their own traces]
  E --> G2{{"GATE 2 — human approves learning"}}
  G2 -->|approve| MEM[(Memory + definition edits)]
  G2 -->|reject| DONE([done])
  MEM --> DONE

  CF[["Case File (immutable, append-only)<br/>each agent appends one entry = audit trail"]]
  W -.appends.-> CF
  T -.appends.-> CF
  J -.appends.-> CF
  A -.appends.-> CF
  S -.appends.-> CF
```

---

## 4. Inside one agent — the genuine tool-calling loop

Watcher, Tracer and Judge are real tool-using agents. Gemini is given a catalog of
Dynatrace tools and decides which to call and when. The conclusion is grounded in
the actual tool results (never the model's free text), with a deterministic backfill
so the handoff never breaks.

```mermaid
flowchart TD
  OBS["observation\n(e.g. 'Android/IN checkout is degraded')"] --> LLM
  LLM{"Gemini\ndecides next step"}
  LLM -->|call a tool| TOOLS["Dynatrace tools (scoped):\nexecute_dql, span_breakdown,\nlist_exceptions, ..."]
  TOOLS -->|results written to sink| LLM
  LLM -->|enough info| FIN["finalize()"]
  FIN --> GROUND["ground summary in verified tool results\n+ backfill if a tool was skipped"]
  GROUND --> ENTRY["append one Case File entry\n(service, span, deploy, ...)"]
```

---

## 5. The self-improvement loop (two human-gated channels)

The Evaluator runs *after* the rescue, off the hot path. It grades each agent from
its own Dynatrace traces and proposes improvements — applied only after the human
approves at Gate 2.

```mermaid
flowchart LR
  RUN["completed run\n(agents' own spans in Dynatrace)"] --> EV["Evaluator\n(different model than the agents)"]
  EV --> SC["scorecard per agent\n(correctness, efficiency)"]
  SC --> G2{{"GATE 2 — human approves"}}
  G2 --> L1["Memory: verbal lesson\n→ read on next run (Reflexion)"]
  G2 --> L2["Definition: recommended\nprompt/tool edit for the human"]
  L1 --> NEXT["next run: agent is faster + smarter"]
```

Two guardrails: the Evaluator runs on a **different model** than the agents it grades
(no self-preference bias), and **nothing is written to memory without the human gate**
(no self-poisoning).

---

## 6. Mock vs Live — the same agents, swappable backend

The agents call a typed tool surface. A factory returns either the mock backend
(deterministic, zero credentials — used for the demo) or the live Dynatrace client
(real OAuth token + async Grail DQL). The agents are identical either way.

```mermaid
flowchart TD
  AG["Agents (unchanged)"] --> FAC{"factory\nQUELL_USE_LIVE_DT?"}
  FAC -->|false default| MOCK["MockMCP\nsimulated ShopWave world"]
  FAC -->|true| LIVE["DynatraceClient\nOAuth token + Grail DQL + writes"]
  AG --> LLMSW{"QUELL_USE_LIVE_LLM?"}
  LLMSW -->|false| DET["deterministic reasoning"]
  LLMSW -->|true| GEM["Gemini tool-calling"]
```

---

## 7. Deployment topology

```mermaid
flowchart LR
  GH["GitHub\nmadmecodes/quell"]
  subgraph GCP["Google Cloud (project sentinel-hack-2026)"]
    CR1["Cloud Run: quell-dashboard\n(operator console + agents)"]
    CR2["Cloud Run: shopwave\n(demo store)"]
    VAI["Vertex AI: Gemini 2.5-pro / flash"]
    AE["Agent Engine (ADK app, optional)"]
  end
  DTN["Dynatrace tenant xqs90163\n(Grail + MCP server)"]

  GH -->|source deploy| CR1
  GH -->|source deploy| CR2
  CR1 --> VAI
  CR1 <--> DTN
  CR2 -->|OTel| DTN
```

---

## The one-line summary

> ShopWave is the patient. Dynatrace is the senses. Gemini is the brain. The six
> agents are the medical team. You sign off twice — before the fix, and before the
> system changes itself.
