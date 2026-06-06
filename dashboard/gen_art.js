// One-off: generate Quell console art via OpenAI gpt-image-1.
// Saves PNGs to static/img/. Run once: OPENAI_API_KEY=... node gen_art.js
const fs = require("fs");
const path = require("path");

const KEY = process.env.OPENAI_API_KEY;
const OUT = path.join(__dirname, "static", "img");
fs.mkdirSync(OUT, { recursive: true });

const EMBLEM =
  "A minimalist editorial emblem icon, flat two-color design in deep terracotta and muted sage green " +
  "on a solid warm cream circular background, vintage letterpress woodcut style, thick clean confident " +
  "lines, centered, balanced, refined, no text, no lettering. The emblem depicts: ";

const ITEMS = [
  { id: "watcher",   prompt: "a single calm watchful eye inside a radar monitoring ring with subtle signal arcs" },
  { id: "tracer",    prompt: "a magnifying glass held over a branching network trace path with nodes" },
  { id: "judge",     prompt: "a balanced set of weighing scales holding coins, symbolising business impact" },
  { id: "actuator",  prompt: "a firm hand pulling a control lever beside a rollback arrow" },
  { id: "scribe",    prompt: "a quill pen writing a line on an open ledger scroll" },
  { id: "evaluator", prompt: "a clipboard checklist with a five-point star rating, symbolising grading and review" },
  { id: "hero",      prompt:
      "EDITORIAL SCENE (not an emblem): a calm operations command center at night, a lone guardian figure " +
      "watching flowing data streams and a single steady heartbeat line across screens, warm terracotta and " +
      "sage green on a cream background, vintage magazine illustration style, refined, no text" },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function gen(it, attempt = 1) {
  const dest = path.join(OUT, `${it.id}.png`);
  if (fs.existsSync(dest)) { console.log(`  ${it.id}: exists, skip`); return true; }
  const prompt = it.id === "hero" ? it.prompt : EMBLEM + it.prompt + ".";
  const size = it.id === "hero" ? "1536x1024" : "1024x1024";
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 120000);
    const res = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-image-1", prompt, size, quality: "medium", n: 1 }),
      signal: ctrl.signal,
    });
    clearTimeout(t);
    const text = await res.text();
    let j; try { j = JSON.parse(text); } catch { j = null; }
    if (!j || !j.data || !j.data[0] || !j.data[0].b64_json) throw new Error((text || "no body").slice(0, 120));
    fs.writeFileSync(dest, Buffer.from(j.data[0].b64_json, "base64"));
    console.log(`  ${it.id}: saved`);
    return true;
  } catch (e) {
    if (attempt < 4) { console.log(`  ${it.id}: retry ${attempt} (${String(e.message).slice(0,50)})`); await sleep(3000*attempt); return gen(it, attempt+1); }
    console.error(`  ${it.id}: FAILED -> ${e.message}`); return false;
  }
}

(async () => {
  console.log(`generating ${ITEMS.length} console images...`);
  let ok = 0;
  for (const it of ITEMS) { if (await gen(it)) ok++; }
  console.log(`done: ${ok}/${ITEMS.length}`);
})();
