// One-off: generate professional product photos via OpenAI gpt-image-1.
// Saves PNGs to public/products/. Run once: OPENAI_API_KEY=... node gen_products.js
const fs = require("fs");
const path = require("path");

const KEY = process.env.OPENAI_API_KEY;
const OUT = path.join(__dirname, "public", "products");
fs.mkdirSync(OUT, { recursive: true });

const STYLE =
  "Professional e-commerce product photo, centered on a clean soft warm-beige studio background, " +
  "soft even lighting, subtle shadow, high detail, crisp, catalog quality, no text, no watermark.";

const PRODUCTS = [
  { id: "hoodie",     prompt: "a premium charcoal pullover hoodie with a small embroidered race-car emblem on the chest" },
  { id: "rc-car",     prompt: "a sleek remote-control turbo race car toy, glossy red and black with large rugged tires" },
  { id: "controller", prompt: "a modern wireless game controller in matte black with terracotta-orange accents" },
  { id: "mug",        prompt: "a ceramic coffee mug in cream color with a minimalist orange race-flag icon" },
  { id: "cap",        prompt: "a structured baseball cap in olive green with a small embroidered crash-arena logo patch" },
  { id: "headset",    prompt: "an over-ear gaming headset in black with bronze metallic earcups, studio product shot" },
  { id: "decals",     prompt: "a flat-lay set of colorful vinyl racing decal stickers arranged neatly" },
  { id: "toolbox",    prompt: "a compact metal hobby toolbox kit, open, with small modeling tools neatly arranged inside" },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function gen(p, attempt = 1) {
  const dest = path.join(OUT, `${p.id}.png`);
  if (fs.existsSync(dest)) { console.log(`  ${p.id}: exists, skip`); return true; }
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 120000);
    const res = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-image-1",
        prompt: `${STYLE} The product is ${p.prompt}.`,
        size: "1024x1024", quality: "medium", n: 1,
      }),
      signal: ctrl.signal,
    });
    clearTimeout(t);
    const text = await res.text();
    let j; try { j = JSON.parse(text); } catch { j = null; }
    if (!j || !j.data || !j.data[0] || !j.data[0].b64_json) {
      throw new Error((text || "no body").slice(0, 120));
    }
    fs.writeFileSync(dest, Buffer.from(j.data[0].b64_json, "base64"));
    console.log(`  ${p.id}: saved`);
    return true;
  } catch (e) {
    if (attempt < 4) {
      console.log(`  ${p.id}: retry ${attempt} (${String(e.message).slice(0,60)})`);
      await sleep(3000 * attempt);
      return gen(p, attempt + 1);
    }
    console.error(`  ${p.id}: FAILED -> ${e.message}`);
    return false;
  }
}

(async () => {
  console.log(`generating ${PRODUCTS.length} product images (sequential + retry)...`);
  let ok = 0;
  for (const p of PRODUCTS) { if (await gen(p)) ok++; }
  console.log(`done: ${ok}/${PRODUCTS.length}`);
})();
