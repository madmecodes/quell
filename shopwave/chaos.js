// Shared chaos state + the scenario library.
// The Operations panel (or /api/chaos) picks a scenario; each one targets a
// different service/span/journey and emits distinct telemetry, so Quell's agents
// genuinely diagnose a different root cause each time (not a replayed script).

const SEGMENTS = ["iOS / US", "Web / US", "Android / US"];
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const randDeploy = () => "#" + (800 + Math.floor(Math.random() * 99));

// Each scenario: which service/span breaks, how, and on which journey.
//  addedLatencyMs — extra latency on the targeted span (felt by users)
//  errorRate      — fraction of targeted requests that hard-fail (5xx)
//  journey        — the user journey whose experience degrades (browse|checkout)
const SCENARIOS = {
  payment_latency: {
    label: "Slow payments", service: "payment-svc", span: "razorpay.charge",
    journey: "checkout", addedLatencyMs: 2200, errorRate: 0,
    blurb: "A bad deploy made the payment charge call ~2s slower.",
  },
  checkout_errors: {
    label: "Checkout failing", service: "payment-svc", span: "razorpay.charge",
    journey: "checkout", addedLatencyMs: 300, errorRate: 0.55,
    blurb: "The payment service started returning 5xx errors on checkout.",
  },
  catalog_slowdown: {
    label: "Catalog slow", service: "catalog-svc", span: "catalog.query",
    journey: "browse", addedLatencyMs: 1500, errorRate: 0,
    blurb: "The catalog service slowed down, hurting the browse experience.",
  },
  cart_failures: {
    label: "Cart failures", service: "cart-svc", span: "cart.add",
    journey: "checkout", addedLatencyMs: 200, errorRate: 0.5,
    blurb: "Adding items to cart fails intermittently before checkout.",
  },
  third_party_outage: {
    label: "Razorpay outage", service: "payment-svc", span: "razorpay.gateway",
    journey: "checkout", addedLatencyMs: 900, errorRate: 0.6,
    blurb: "The external Razorpay gateway is erroring — payments fail downstream.",
  },
};

const state = {
  active: false,
  scenario: "",
  fault: "",            // kept for back-compat with existing payloads
  service: "",
  span: "",
  segment: "",
  deploy: "",
  addedLatencyMs: 0,
  errorRate: 0,
  journey: "checkout",
};

function setChaos(patch) {
  // Accept either {active, scenario} (preferred) or a full legacy payload.
  if (patch.active === false) {
    Object.assign(state, { active: false, scenario: "", fault: "", service: "",
      span: "", segment: "", deploy: "", addedLatencyMs: 0, errorRate: 0 });
    return getChaos();
  }
  const sid = patch.scenario || patch.fault || "payment_latency";
  const sc = SCENARIOS[sid] || SCENARIOS.payment_latency;
  Object.assign(state, {
    active: true,
    scenario: sid,
    fault: sid,                                   // legacy alias
    service: sc.service,
    span: sc.span,
    journey: sc.journey,
    addedLatencyMs: patch.addedLatencyMs != null ? patch.addedLatencyMs : sc.addedLatencyMs,
    errorRate: patch.errorRate != null ? patch.errorRate : sc.errorRate,
    segment: patch.segment || pick(SEGMENTS),     // vary the affected segment
    deploy: patch.deploy || randDeploy(),         // vary the deploy id
  });
  return getChaos();
}

function getChaos() {
  const sc = SCENARIOS[state.scenario];
  return { ...state, label: sc ? sc.label : "", blurb: sc ? sc.blurb : "" };
}

// Decide whether a given span on a given service (for an optional segment) is
// faulted right now, and by how much / whether it should hard-fail.
function faultFor(service, span, segment) {
  if (!state.active || state.service !== service || state.span !== span)
    return { extraMs: 0, fail: false };
  // Segment-scoped scenarios only hit the affected segment; if the caller does
  // not know the segment (e.g. catalog browse), the fault applies broadly.
  if (segment && state.segment && segment !== state.segment)
    return { extraMs: 0, fail: false };
  const fail = Math.random() < (state.errorRate || 0);
  return { extraMs: state.addedLatencyMs || 0, fail };
}

module.exports = { setChaos, getChaos, faultFor, SCENARIOS, SEGMENTS };
