// Traffic generator: drives realistic, continuous load against ShopWave so
// Dynatrace fills with live spans and business events across segments.
//   node traffic.js            (steady traffic)
//   node traffic.js --burst    (one quick burst, then exit)

const BASE = process.env.SHOPWAVE_URL || "http://localhost:8080";

// US-only segments. iOS / US is the segment the Chaos Panel degrades.
const SEGMENTS = ["Web / US", "iOS / US", "iOS / US", "Android / US", "Web / US"];
const JOURNEYS = ["browse", "browse", "checkout"];

const pick = (a) => a[Math.floor(Math.random() * a.length)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function post(path, body) {
  try {
    await fetch(`${BASE}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch { /* ignore transient errors */ }
}
async function get(path) { try { await fetch(`${BASE}${path}`); } catch { /* ignore */ } }

async function session(i) {
  const segment = pick(SEGMENTS);
  const journey = pick(JOURNEYS);
  const userId = `u${i}-${Math.floor(Math.random() * 1e5)}`;
  const cartId = `c${Math.floor(Math.random() * 1e6)}`;

  await get("/api/catalog");
  await post("/api/pageview", { segment, journey });
  if (journey === "checkout") {
    await post("/api/cart", { cartId, segment });
    await post("/api/checkout", {
      segment, userId, cartId, cartValueUsd: Math.round(15 + Math.random() * 40),
    });
  }
}

async function main() {
  const burst = process.argv.includes("--burst");
  let i = 0;
  if (burst) {
    await Promise.all(Array.from({ length: 40 }, (_, k) => session(k)));
    console.log("burst of 40 sessions sent");
    return;
  }
  console.log(`generating steady traffic against ${BASE} (ctrl-c to stop)`);
  while (true) {
    await Promise.all(Array.from({ length: 6 }, () => session(i++)));
    await sleep(1000);
    if (i % 60 === 0) console.log(`${i} sessions sent`);
  }
}

main();
