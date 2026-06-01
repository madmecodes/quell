// Sends business events (page views, checkouts) to Dynatrace.
// These populate Grail bizevents, which the Judge and Watcher query via DQL.
// Requires DT_INGEST_TOKEN with bizevents.ingest scope; no-ops without it.

// Bizevents ingest is on the classic .live host (not the .apps platform host).
const DT_ENV = (process.env.DT_INGEST_BASE
  || (process.env.DT_ENVIRONMENT || "").replace(".apps.dynatrace.com", ".live.dynatrace.com")
  ).replace(/\/$/, "");
const DT_TOKEN = process.env.DT_INGEST_TOKEN || "";

async function sendBizEvent(type, payload) {
  if (!DT_ENV || !DT_TOKEN) return { skipped: true };
  try {
    const res = await fetch(`${DT_ENV}/api/v2/bizevents/ingest`, {
      method: "POST",
      headers: {
        Authorization: `Api-Token ${DT_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ "event.type": type, ...payload }),
    });
    return { ok: res.ok, status: res.status };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// A simulated page view with experience signals.
function pageView({ segment, journey, apdex, rageClicks, conversion }) {
  return sendBizEvent("page.view", {
    segment, journey, apdex, rage_clicks: rageClicks, conversion,
  });
}

// A checkout attempt with its cart value.
function checkoutStarted({ segment, userId, cartId, cartValueInr }) {
  return sendBizEvent("checkout.started", {
    segment, user_id: userId, cart_id: cartId, cart_value_inr: cartValueInr,
  });
}

function checkoutCompleted({ segment, userId, cartId, cartValueInr }) {
  return sendBizEvent("checkout.completed", {
    segment, user_id: userId, cart_id: cartId, cart_value_inr: cartValueInr,
  });
}

module.exports = { sendBizEvent, pageView, checkoutStarted, checkoutCompleted };
