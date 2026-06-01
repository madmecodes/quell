// OpenTelemetry trace setup for ShopWave -> Dynatrace.
// If DT_INGEST_TOKEN is set, spans are exported to the Dynatrace OTLP endpoint;
// otherwise they are dropped (the app still runs, useful for local dev).

const { NodeTracerProvider } = require("@opentelemetry/sdk-trace-node");
const { BatchSpanProcessor } = require("@opentelemetry/sdk-trace-base");
// Dynatrace's OTLP endpoint requires protobuf (not JSON), so use the proto exporter.
const { OTLPTraceExporter } = require("@opentelemetry/exporter-trace-otlp-proto");
const { Resource } = require("@opentelemetry/resources");
const { SemanticResourceAttributes } = require("@opentelemetry/semantic-conventions");
const { trace } = require("@opentelemetry/api");

// Ingest goes to the classic .live host; reads/Grail use the .apps host.
// Prefer DT_INGEST_BASE; otherwise derive .live from the .apps environment URL.
const DT_ENV = (process.env.DT_INGEST_BASE
  || (process.env.DT_ENVIRONMENT || "").replace(".apps.dynatrace.com", ".live.dynatrace.com")
  ).replace(/\/$/, "");
const DT_TOKEN = process.env.DT_INGEST_TOKEN || "";

function initTelemetry() {
  const provider = new NodeTracerProvider({
    resource: new Resource({
      [SemanticResourceAttributes.SERVICE_NAME]: "shopwave",
    }),
  });

  if (DT_ENV && DT_TOKEN) {
    const exporter = new OTLPTraceExporter({
      url: `${DT_ENV}/api/v2/otlp/v1/traces`,
      headers: { Authorization: `Api-Token ${DT_TOKEN}` },
    });
    provider.addSpanProcessor(new BatchSpanProcessor(exporter));
    console.log(`[otel] exporting spans to ${DT_ENV}/api/v2/otlp/v1/traces`);
  } else {
    console.log("[otel] DT_INGEST_TOKEN not set -- spans not exported (local mode)");
  }

  provider.register();
  _provider = provider;
  return trace.getTracer("shopwave");
}

// Flush pending spans before exit so short-lived runs do not lose data.
async function shutdownTelemetry() {
  if (!_provider) return;
  try {
    await _provider.forceFlush();
    await _provider.shutdown();
  } catch { /* best effort */ }
}

module.exports = { initTelemetry, shutdownTelemetry };
