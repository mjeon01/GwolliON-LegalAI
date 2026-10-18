import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.GWOLLION_URL || "http://127.0.0.1:8021";
const output = "docs/images";
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  reducedMotion: "reduce",
  deviceScaleFactor: 1,
});
const page = await context.newPage();
const errors = [];
const created = [];
page.on("pageerror", error => errors.push(error.message));
mkdirSync(output, { recursive: true });

async function capture(name) {
  await page.locator("#toast").waitFor({ state: "hidden" });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: `${output}/${name}.png` });
}

async function checkWidths() {
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1100 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}px`);
  }
}

try {
  const history = await (await context.request.get(`${base}/api/analyses`)).json();
  assert.equal(history.length, 0, "Use a dedicated, empty GWOLLION_DB to keep personal history out of screenshots.");
  await page.goto(base);
  await page.locator(".sample-card").last().waitFor();
  assert.equal(await page.locator(".sample-card").count(), 6);
  await checkWidths();
  await page.setViewportSize({ width: 1440, height: 1360 });
  await capture("mvp-home");
  await page.setViewportSize({ width: 375, height: 1050 });
  await capture("mvp-mobile");
  await page.setViewportSize({ width: 1440, height: 1100 });

  await page.locator('[data-sample="lease-return"]').click();
  await page.locator("#review-settings > summary").click();
  await page.locator("#engine").selectOption("rules");
  await page.locator("#live-evidence").uncheck();
  assert.equal(await page.locator("#settings-summary").textContent(), "빠른 검토 · 저장된 근거");
  await page.locator("#analyze-button").click();
  await page.locator("#result-view").waitFor({ state: "visible" });
  const id = new URL(page.url()).hash.split("=")[1];
  created.push(id);
  const analysis = await (await context.request.get(`${base}/api/analyses/${id}`)).json();
  assert.equal(analysis.review.verdict, "warning");
  await checkWidths();
  await page.locator(".risk-card .evidence-link").first().click();
  assert.equal(await page.locator(".block.selected").count(), 1);
  await capture("mvp-review");

  await page.locator("[data-explain]").first().click();
  await page.locator(".chat-message.assistant").waitFor();
  assert((await page.locator("#chat-messages").textContent()).includes("새 임차인"));
  await page.setViewportSize({ width: 1440, height: 1600 });
  await capture("mvp-chat");
  await page.locator("#tab-chat").focus();
  await page.keyboard.press("ArrowRight");
  assert.equal(await page.locator("#tab-draft").getAttribute("aria-selected"), "true");
  await page.locator("#draft-kind").selectOption("summary");
  await page.locator("#generate-draft").click();
  await page.waitForFunction(() => document.querySelector("#draft-text").value.length > 100);
  await page.setViewportSize({ width: 1440, height: 1500 });
  await capture("mvp-draft");

  await page.locator("#prepare-document").click();
  assert.equal(await page.locator("#prepare-document").getAttribute("aria-current"), "page");
  assert.equal(await page.locator("#current-page").textContent(), "상담·고소 문서 준비");
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ screenshots: 5, widths: [375, 768, 1024, 1440], checks: ["sample analysis", "original evidence", "quick explanation", "draft", "keyboard tabs", "navigation state"], browser_errors: errors }, null, 2));
} finally {
  for (const id of created) await context.request.delete(`${base}/api/analyses/${id}`);
  await context.close();
  await browser.close();
}
