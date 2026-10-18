import { createRequire } from "node:module";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.GWOLLION_URL || "http://127.0.0.1:8020";
const out = "var/mvp-review";
mkdirSync(out, { recursive: true });
execFileSync(".venv/bin/python",["-c","from pathlib import Path; import fitz; Path('tmp/pdfs').mkdir(parents=True,exist_ok=True); d=fitz.open('output/pdf/employment-basic.pdf'); d[0].get_pixmap(matrix=fitz.Matrix(3,3)).save('tmp/pdfs/ocr-photo.png')"]);
const launch = { headless: true };
if (process.env.CHROME_PATH) launch.executablePath = process.env.CHROME_PATH;
const browser = await chromium.launch(launch);
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await context.newPage();
const errors = [], created = [], report = { cases: [], layouts: [], checks: [], browser_errors: errors };
page.on("pageerror", e => errors.push(e.message));
page.on("console", e => { if (e.type() === "error") errors.push(e.text()); });
try {
  await page.goto(base);
  await page.locator(".sample-card").last().waitFor();
  if (process.argv.includes("--ollama-only")) {
    await page.locator('[data-sample="employment-basic"]').click();
    await page.waitForFunction(()=>document.querySelector("#document-text").value.includes("가상회사 A"));
    if (!(await page.locator("#engine").isVisible())) await page.locator("#review-settings > summary").click();
    await page.locator("#engine").selectOption("ollama");
    await page.locator("#live-evidence").uncheck();
    const started = Date.now();
    await page.locator("#analyze-button").click();
    await page.locator("#result-view").waitFor({state:"visible",timeout:130000});
    const id=page.url().split("#analysis=")[1]; created.push(id);
    const result=await (await context.request.get(`${base}/api/analyses/${id}`)).json();
    assert.equal(result.engine,"ollama");
    assert.equal(result.extraction.model,"qwen2.5:7b");
    const wage=result.terms.find(t=>t.key==="wage");
    assert.equal(wage.candidates[0].normalized_value.amount,2500000);
    assert.equal(wage.candidates[0].normalized_value.period,"month");
    assert.equal(result.terms.find(t=>t.key==="break_time").candidates[0].normalized_value.minutes,60);
    const probe={engine:result.engine,model:result.extraction.model,status:result.status,elapsed_seconds:(Date.now()-started)/1000,rejected_candidates:result.extraction.rejected_candidates,terms:result.terms.map(t=>({key:t.key,status:t.status,candidates:t.candidates})),issues:result.issues};
    writeFileSync(`${out}/ollama-report.json`,JSON.stringify(probe,null,2));
    await page.screenshot({path:`${out}/ollama-desktop.png`,fullPage:true});
    console.log(JSON.stringify({engine:probe.engine,model:probe.model,status:probe.status,elapsed_seconds:probe.elapsed_seconds,rejected_candidates:probe.rejected_candidates,terms:probe.terms.map(t=>({key:t.key,status:t.status}))},null,2));
  } else {
  assert.equal(await page.locator(".sample-card").count(), 6);
  await page.screenshot({ path: `${out}/home-desktop.png`, fullPage: true });
  const fixtures = JSON.parse(readFileSync("samples/manifest.json", "utf-8"));
  for (const fixture of fixtures) {
    await page.locator(`[data-sample="${fixture.id}"]`).click();
    await page.waitForFunction(()=>document.querySelector("#document-text").value.includes("가상"));
    assert((await page.locator("#document-text").inputValue()).includes("가상"));
    if (!(await page.locator("#engine").isVisible())) await page.locator("#review-settings > summary").click();
    await page.locator("#engine").selectOption("rules");
    await page.locator("#live-evidence").uncheck();
    await page.locator("#analyze-button").click();
    await page.locator("#result-view").waitFor({ state: "visible" });
    assert.equal(await page.locator("#result-title").textContent(), fixture.title);
    const id = page.url().split("#analysis=")[1]; created.push(id);
    const response = await context.request.get(`${base}/api/analyses/${id}`);
    const result = await response.json();
    if (fixture.id === "employment-basic") {
      assert.equal(result.structured_contract.wage.amount,2500000);
      assert.equal(result.structured_contract.working_hours.break,"12:00~13:00");
      await page.locator("#terms-details > summary").click();
      await page.locator("#structured-details summary").click();
      const jsonDownload = page.waitForEvent("download");
      await page.locator("#download-json").click();
      const downloaded = await jsonDownload;
      assert.equal(downloaded.suggestedFilename(),"contract.json");
      const structured = JSON.parse(readFileSync(await downloaded.path(),"utf-8"));
      assert.equal(structured.wage.amount,2500000);
      await page.setViewportSize({width:375,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.setViewportSize({width:1440,height:1100});
      await page.locator("#structured-details summary").click();
      report.checks.push("structured JSON download and mobile layout");
    }
    if (fixture.id === "employment-missing") {
      assert.equal(result.structured_contract.contract_period.end,null);
      assert.equal(result.structured_contract.wage.payment_method,null);
      assert.equal(await page.locator('[data-field="wage.payment_method"]').count(),1);
      assert.equal(await page.locator('[data-field="annual_leave"]').count(),1);
    }
    assert.deepEqual([...new Set(result.issues.map(i => i.issue_type))].sort(), [...fixture.expected.issue_types].sort());
    assert.equal(await page.locator(".issue-card").count(), result.issues.length);
    if(!(await page.locator(".evidence-link").first().isVisible()))await page.locator("#terms-details > summary").click();
    await page.locator(".evidence-link").first().click();
    assert.equal(await page.locator(".block.selected").count(), 1);
    report.cases.push({ id: fixture.id, status: result.status, issues: result.issues.map(i=>i.issue_type) });
    if (fixture.id === "employment-attention") {
      await page.locator(".source-details summary").first().click();
      assert(await page.locator(".source-body").first().isVisible());
      await page.locator("#context-event_date").fill("2026-10-10");
      await page.locator("#context-workplace_size").selectOption("5plus");
      await page.locator("#context-weekly_work_hours").fill("45");
      await page.locator("#answers-button").click();
      await page.locator("#result-revision").filter({hasText:"수정 2"}).waitFor();
      assert(!(await page.locator("#issues").textContent()).includes("추가 정보 필요"));
      await page.waitForFunction(()=>window.scrollY===0);
      await page.screenshot({path:`${out}/review-desktop.png`,fullPage:true});
      await page.locator("#tab-draft").click();
      await page.locator("#draft-kind").selectOption("summary");
      await page.locator("#generate-draft").click();
      await page.waitForFunction(()=>document.querySelector("#draft-text").value.includes("상담 준비 요약서"));
      assert((await page.locator("#draft-text").inputValue()).includes("250만원"));
      await page.locator("#draft-kind").selectOption("request");
      await page.locator("#generate-draft").click();
      await page.waitForFunction(()=>document.querySelector("#draft-text").value.includes("사실확인 요청문"));
      const downloadPromise = page.waitForEvent("download");
      await page.locator("#download-draft").click();
      const download = await downloadPromise;
      assert(download.suggestedFilename().endsWith(".txt"));
      await page.locator("#tab-language").click();
      for (const language of ["zh", "es"]) {
        await page.locator("#language").selectOption(language);
        await page.locator("#generate-translation").click();
        await page.locator(`#translation [lang="${language === "zh" ? "zh-Hans" : "es"}"]`).waitFor();
        assert((await page.locator("#translation").textContent()).includes("250만원"));
        assert((await page.locator("#translation").textContent()).includes("law-"));
      }
      await page.screenshot({path:`${out}/language-desktop.png`,fullPage:true});
      await page.locator("#tab-review").focus();
      await page.keyboard.press("ArrowRight");
      assert.equal(await page.locator("#tab-chat").getAttribute("aria-selected"),"true");
      report.checks.push("source links, document highlights, answer revision, two drafts, TXT download, two languages, keyboard tabs");
    }
    if (fixture.id === "lease-return") {
      await page.locator("#context-deposit_returned").selectOption("false");
      await page.locator("#context-event_date").fill("2026-10-10");
      await page.locator("#context-move_in").selectOption("true");
      await page.locator("#context-resident_registration").selectOption("true");
      await page.locator("#answers-button").click();
      await page.locator('[data-issue="deposit_unreturned"]').waitFor({state:"attached"});
      report.checks.push("lease unreturned-deposit branch");
      await page.setViewportSize({width:375,height:900});
      await page.screenshot({path:`${out}/review-mobile.png`,fullPage:true});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.setViewportSize({width:1440,height:1100});
    }
    await page.locator("#new-document").click();
  }
  await page.locator("#file-input").setInputFiles("output/pdf/employment-basic.pdf");
  if (!(await page.locator("#engine").isVisible())) await page.locator("#review-settings > summary").click();
  await page.locator("#engine").selectOption("rules");
  await page.locator("#live-evidence").uncheck();
  await page.locator("#file-status").filter({hasText:"페이지 읽음"}).waitFor();
  assert((await page.locator("#document-text").inputValue()).includes("2,500,000원"));
  await page.locator("#document-complete").check();
  await page.locator("#analyze-button").click();
  await page.locator("#result-view").waitFor({state:"visible"});
  const uploadId=page.url().split("#analysis=")[1];
  assert((await page.locator("#terms").textContent()).includes("2,500,000원"));
  await page.reload();
  await page.locator("#result-view").waitFor({state:"visible"});
  assert.equal(page.url().split("#analysis=")[1],uploadId);
  await page.locator("#delete-analysis").click();
  await page.locator("#entry-view").waitFor({state:"visible"});
  assert.equal((await context.request.get(`${base}/api/analyses/${uploadId}`)).status(),404);
  report.checks.push("PDF upload, persisted analysis reload, record deletion");
  await page.locator("#file-input").setInputFiles("tmp/pdfs/ocr-photo.png");
  if (!(await page.locator("#engine").isVisible())) await page.locator("#review-settings > summary").click();
  await page.locator("#engine").selectOption("rules");
  await page.locator("#live-evidence").uncheck();
  await page.locator("#file-status").filter({hasText:"OCR 사용"}).waitFor();
  assert((await page.locator("#file-status").textContent()).includes("원본"));
  await page.locator("#analyze-button").click();
  await page.locator("#result-view").waitFor({state:"visible"});
  const photoId=page.url().split("#analysis=")[1]; created.push(photoId);
  const photoResult=await (await context.request.get(`${base}/api/analyses/${photoId}`)).json();
  assert.equal(photoResult.reading.ocr_used,true);
  assert((await page.locator("#original-heading").textContent()).includes("OCR"));
  assert(await page.locator("#reading-notice").isVisible());
  assert((await page.locator("#coverage").textContent()).includes("원본과 대조"));
  await page.screenshot({path:`${out}/ocr-review-desktop.png`,fullPage:true});
  await page.locator("#new-document").click();
  report.checks.push("actual photo OCR upload, editable text and retained OCR notice");
  for (const width of [375,768,1024,1440]) {
    await page.setViewportSize({width,height:1000});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    report.layouts.push({width,overflow:false});
    if(width===375) {
      await page.locator("#history-toggle").click();
      assert.equal(await page.locator("#history-toggle").getAttribute("aria-expanded"),"true");
      assert(await page.locator("#history").isVisible());
      await page.locator("#history-toggle").click();
      await page.screenshot({path:`${out}/home-mobile.png`,fullPage:true});
    }
  }
  await page.emulateMedia({reducedMotion:"reduce"});
  assert.equal(await page.locator(".primary").first().evaluate(el=>getComputedStyle(el).transitionDuration),"0s");
  assert.deepEqual(errors,[]);
  writeFileSync(`${out}/e2e-report.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
  }
} finally {
  for (const id of created) await context.request.delete(`${base}/api/analyses/${id}`);
  await browser.close();
}
