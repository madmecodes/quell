// ShopWave: a small e-commerce store that emits real OpenTelemetry spans and
// business events to Dynatrace. The Chaos Panel injects one of several fault
// scenarios; each targets a different service/span, so Quell's agents diagnose a
// genuinely different root cause each time. Spans carry shop.service, span.name,
// deploy.version, segment, latency.ms and an outcome (ok|error) attribute.

const { initTelemetry, shutdownTelemetry } = require("./otel");
const tracer = initTelemetry();

const express = require("express");
const { SpanStatusCode } = require("@opentelemetry/api");
const { getChaos, setChaos, faultFor } = require("./chaos");
const { pageView, checkoutStarted, checkoutCompleted } = require("./bizevents");

const app = express();
app.use(express.json());
app.use(express.static(__dirname + "/public"));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Run a unit of work as a span tagged with its logical service. Sets outcome=ok
// on success, outcome=error if fn throws (so Quell can query error counts).
async function span(service, name, attrs, fn) {
  return tracer.startActiveSpan(name, async (s) => {
    s.setAttribute("shop.service", service);
    s.setAttribute("deploy.version", getChaos().deploy || "stable");
    for (const [k, v] of Object.entries(attrs || {})) s.setAttribute(k, v);
    try {
      const out = await fn(s);
      s.setStatus({ code: SpanStatusCode.OK });
      s.setAttribute("outcome", "ok");
      return out;
    } catch (e) {
      s.setStatus({ code: SpanStatusCode.ERROR, message: String(e) });
      s.setAttribute("outcome", "error");
      s.recordException(e);
      throw e;
    } finally {
      s.end();
    }
  });
}

// Apply the active fault to a span: extra latency + optional hard failure.
async function timedSpan(service, name, segment, baseMin, baseMax, s) {
  const f = faultFor(service, name, segment);
  const latency = baseMin + Math.random() * (baseMax - baseMin) + f.extraMs;
  await sleep(latency);
  s.setAttribute("latency.ms", Math.round(latency));
  if (f.fail) {
    s.addEvent("UpstreamError");
    throw new Error(`${service}/${name} failed`);
  }
}

app.get("/api/catalog", async (_req, res) => {
  try {
    await span("catalog-svc", "catalog.query", {},
      (s) => timedSpan("catalog-svc", "catalog.query", null, 15, 30, s));
    res.json({ items: ["turbo-kit", "arena-pass", "crash-coin"] });
  } catch {
    res.status(500).json({ ok: false });
  }
});

app.post("/api/cart", async (req, res) => {
  const segment = req.body?.segment;
  const attrs = { "cart.id": req.body?.cartId || "c0", ...(segment ? { segment } : {}) };
  try {
    await span("cart-svc", "cart.add", attrs,
      (s) => timedSpan("cart-svc", "cart.add", segment, 10, 20, s));
    res.json({ ok: true });
  } catch {
    res.status(502).json({ ok: false });
  }
});

app.post("/api/checkout", async (req, res) => {
  const { segment = "Web / US", userId = "u0", cartId = "c0", cartValueUsd = 34 } = req.body || {};
  await checkoutStarted({ segment, userId, cartId, cartValueUsd });
  try {
    await span("payment-svc", "razorpay.charge", { segment }, async (s) => {
      // The charge calls an external gateway (its own child span) then settles.
      await span("payment-svc", "razorpay.gateway", { segment },
        (g) => timedSpan("payment-svc", "razorpay.gateway", segment, 20, 40, g));
      await timedSpan("payment-svc", "razorpay.charge", segment, 30, 50, s);
    });
    await checkoutCompleted({ segment, userId, cartId, cartValueUsd });
    res.json({ ok: true });
  } catch {
    res.status(502).json({ ok: false });
  }
});

// Simulated page view with experience signals (apdex, rage clicks). The targeted
// journey for the active scenario degrades for the affected segment.
app.post("/api/pageview", async (req, res) => {
  const chaos = getChaos();
  const { segment = "Web / US", journey = "browse" } = req.body || {};
  const degraded = chaos.active && segment === chaos.segment && journey === chaos.journey;
  await pageView({
    segment, journey,
    apdex: degraded ? 0.5 + Math.random() * 0.12 : 0.9 + Math.random() * 0.08,
    rageClicks: degraded ? Math.round(8 + Math.random() * 8) : Math.round(Math.random() * 2),
    conversion: degraded ? 0.58 : 0.72,
  });
  res.json({ ok: true });
});

// Chaos Panel API.
app.get("/api/chaos", (_req, res) => res.json(getChaos()));
app.post("/api/chaos", (req, res) => res.json(setChaos(req.body || {})));

// Continuous self-traffic so Dynatrace always has live data (set SELF_TRAFFIC=true).
function startSelfTraffic(port) {
  const SEG = ["Web / US", "iOS / US", "Android / US"];
  const J = ["browse", "browse", "checkout"];
  const base = `http://localhost:${port}`;
  const post = (p, b) => fetch(base + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).catch(() => {});
  const get = (p) => fetch(base + p).catch(() => {});
  async function session(i) {
    const segment = SEG[Math.floor(Math.random() * SEG.length)];
    const journey = J[Math.floor(Math.random() * J.length)];
    const cartId = "c" + Math.floor(Math.random() * 1e6);
    await get("/api/catalog");
    await post("/api/pageview", { segment, journey });
    if (journey === "checkout") {
      await post("/api/cart", { cartId, segment });
      await post("/api/checkout", { segment, userId: `u${i}-${Math.floor(Math.random() * 1e5)}`, cartId, cartValueUsd: Math.round(15 + Math.random() * 40) });
    }
  }
  setInterval(() => { for (let k = 0; k < 5; k++) session(Date.now() + k); }, 1200);
  console.log("[shopwave] self-traffic generator running");
}

const PORT = process.env.PORT || 8080;
const server = app.listen(PORT, () => {
  console.log(`[shopwave] listening on http://localhost:${PORT}`);
  if (process.env.SELF_TRAFFIC === "true") startSelfTraffic(PORT);
});

for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, async () => {
    await shutdownTelemetry();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 2000);
  });
}
