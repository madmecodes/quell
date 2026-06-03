// Shared chaos state. The Chaos Panel toggles a fault that ShopWave's services
// react to (added latency, errors), which is what Quell later detects.

const state = {
  active: false,
  fault: "",            // "payment_latency"
  service: "payment-svc",
  span: "razorpay.charge",
  segment: "Android / IN",
  deploy: "#847",
  addedLatencyMs: 0,
};

function setChaos(patch) {
  Object.assign(state, patch);
  if (patch.active === false) {
    state.fault = "";
    state.addedLatencyMs = 0;
  }
  return getChaos();
}

function getChaos() {
  return { ...state };
}

module.exports = { setChaos, getChaos };
