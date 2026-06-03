# Deploy & wire-up

Everything runs locally in mock mode with zero credentials. This guide covers
going fully live (real Gemini + real Dynatrace) and deploying the ADK app to
Vertex AI Agent Engine.

## Status of credentials

| Piece | State |
|-------|-------|
| GCP project `appmedic-hack-2026`, Vertex AI, ADC | done, verified |
| Gemini (`gemini-2.5-pro` / `gemini-2.5-flash`, global endpoint) | verified |
| Dynatrace OAuth client + Grail DQL reads (`live_client`) | verified |
| Dynatrace env `xqs90163` | `https://xqs90163.apps.dynatrace.com` |

## Two manual Dynatrace steps to populate and fully integrate

### 1. Ingest token (so ShopWave streams telemetry into Dynatrace)
Environment > Settings > Access Tokens > Generate new token, scopes:
`openTelemetryTrace.ingest`, `bizevents.ingest`, `logs.ingest`, `metrics.ingest`.
Then:
```
echo 'DT_INGEST_TOKEN=dt0c01.XXXX' >> .env
```

### 2. One scope on the OAuth client (only for the official MCP server)
Account Management > Identity & access management > OAuth clients > appmedic-mcp >
add scope `app-engine:apps:run`. Our own `live_client` does not need this.

## Run locally

```bash
# mock mode (no creds): the architecture, both gates, self-improvement
./run_all.sh                       # ShopWave :8080  +  dashboard :8090
cd agents && python3 run_demo.py   # CLI end-to-end with the learning loop

# live Gemini reasoning
APPMEDIC_USE_LIVE_LLM=true python3 agents/run_demo.py

# live Dynatrace reads (after ingest token + traffic so Grail has data)
cd shopwave && node traffic.js &           # generate real telemetry
APPMEDIC_USE_LIVE_DT=true APPMEDIC_USE_LIVE_LLM=true python3 ../agents/run_demo.py
```

## Deploy the ADK app to Vertex AI Agent Engine

```bash
cd agents
pip install -r appmedic_adk/requirements.txt
adk run appmedic_adk          # run the agent graph locally against the MCP server
adk deploy agent_engine appmedic_adk \
  --project appmedic-hack-2026 --region us-central1 \
  --staging_bucket gs://<your-bucket>
```

The deployed agent uses the official Dynatrace MCP server for its tools and Gemini
for reasoning. The hosted Agent Engine endpoint is the submission's "hosted
project" URL; the dashboard is the operator UI.

## Swapping to Gemini 3
Request access in Vertex AI Model Garden, then set in `.env`:
```
APPMEDIC_WORKER_MODEL=gemini-3-pro-preview
```
