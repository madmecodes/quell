// ShopWave: a small e-commerce store that emits real OpenTelemetry spans and
// business events to Dynatrace. The Chaos Panel injects faults on demand, which
// AppMedic then detects, traces, and prevents.

const { initTelemetry, shutdownTelemetry } = require("./otel");
const tracer = initTelemetry();

const express = require("express");
const { SpanStatusCode } = require("@opentelemetry/api");
const { getChaos, setChaos } = require("./chaos");
const { pageView, checkoutStarted, checkoutCompleted } = require("./bizevents");

const app = express();
app.use(express.json());
app.use(express.static(__dirname + "/public"));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Run a unit of work as a span tagged with the logical service it belongs to.
async function span(service, name, attrs, fn) {
  return tracer.startActiveSpan(name, async (s) => {
    s.setAttribute("shop.service", service);
    for (const [k, v] of Object.entries(attrs || {})) s.setAttribute(k, v);
    try {
      const out = await fn(s);
      s.setStatus({ code: SpanStatusCode.OK });
      return out;
    } catch (e) {
      s.setStatus({ code: SpanStatusCode.ERROR, message: String(e) });
      s.recordException(e);
      throw e;
    } finally {
      s.end();
    }
  });
}

app.get("/api/catalog", async (_req, res) => {
  await span("catalog-svc", "catalog.query", {}, () => sleep(15 + Math.random() * 15));
  res.json({ items: ["turbo-kit", "arena-pass", "crash-coin"] });
});

app.post("/api/cart", async (req, res) => {
  await span("cart-svc", "cart.add", { "cart.id": req.body?.cartId || "c0" },
    () => sleep(10 + Math.random() * 10));
  res.json({ ok: true });
});

app.post("/api/checkout", async (req, res) => {
  const chaos = getChaos();
  const { segment = "Web / US", userId = "u0", cartId = "c0", cartValueUsd = 2800 } = req.body || {};
  await checkoutStarted({ segment, userId, cartId, cartValueUsd });

  try {
    await span("payment-svc", "razorpay.charge", { "deploy.version": chaos.deploy, segment },
      async (s) => {
        let latency = 30 + Math.random() * 20;
        // Chaos: payment latency fault hits the targeted segment hard.
        if (chaos.active && chaos.fault === "payment_latency" && segment === chaos.segment) {
          latency += chaos.addedLatencyMs;
          if (chaos.addedLatencyMs >= 400) {
            s.addEvent("UpstreamTimeout");
          }
        }
        await sleep(latency);
        s.setAttribute("latency.ms", Math.round(latency));
      });
    await checkoutCompleted({ segment, userId, cartId, cartValueUsd });
    res.json({ ok: true });
  } catch {
    res.status(502).json({ ok: false });
  }
});

// Simulated page view with experience signals (apdex, rage clicks).
app.post("/api/pageview", async (req, res) => {
  const chaos = getChaos();
  const { segment = "Web / US", journey = "browse" } = req.body || {};
  const degraded = chaos.active && segment === chaos.segment && journey === "checkout";
  await pageView({
    segment, journey,
    apdex: degraded ? 0.55 + Math.random() * 0.1 : 0.9 + Math.random() * 0.08,
    rageClicks: degraded ? Math.round(8 + Math.random() * 6) : Math.round(Math.random() * 2),
    conversion: degraded ? 0.6 : 0.72,
  });
  res.json({ ok: true });
});

// Chaos Panel API.
app.get("/api/chaos", (_req, res) => res.json(getChaos()));
app.post("/api/chaos", (req, res) => res.json(setChaos(req.body || {})));

const PORT = process.env.PORT || 8080;
const server = app.listen(PORT, () => console.log(`[shopwave] listening on http://localhost:${PORT}`));

for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, async () => {
    await shutdownTelemetry();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000);
  });
}
