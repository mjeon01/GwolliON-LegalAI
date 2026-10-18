import {createRequire} from "node:module";
import {mkdirSync, writeFileSync} from "node:fs";
import assert from "node:assert/strict";

const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||"playwright");
const base=process.env.GWOLLION_URL||"http://127.0.0.1:8020";
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const context=await browser.newContext({viewport:{width:1440,height:1100}});
const page=await context.newPage(), ids=[], errors=[], report={checks:[],ai:[]};
page.on("pageerror",e=>errors.push(e.message));
mkdirSync("var/mvp-review",{recursive:true});
async function sample(id, engine="rules") {
  await page.locator("#new-document").click();
  await page.locator(`[data-sample="${id}"]`).click();
  await page.waitForFunction(()=>document.querySelector("#document-text").value.includes("가상"));
  if (!(await page.locator("#engine").isVisible())) await page.locator("#review-settings > summary").click();
  await page.locator("#engine").selectOption(engine);
  await page.locator("#live-evidence").uncheck();
  await page.locator("#analyze-button").click();
  await page.locator("#result-view").waitFor({state:"visible",timeout:220000});
  const analysisId=page.url().split("#analysis=")[1];ids.push(analysisId);
  return (await context.request.get(`${base}/api/analyses/${analysisId}`)).json();
}
try {
  await page.goto(base);await page.locator(".sample-card").last().waitFor();
  const basic=await sample("employment-basic",process.argv.includes("--ai")?"ollama":"rules");
  assert.equal(basic.review.verdict,"clear",JSON.stringify({pending_reasons:basic.review.pending_reasons,issues:basic.issues,semantic:basic.extraction.semantic_review}));
  assert((await page.locator("#review-verdict").textContent()).includes("불리한 조항이 발견되지 않았습니다"));
  if(basic.engine==="ollama")report.ai.push({scenario:"normal employment",semantic:basic.extraction.semantic_review,verdict:basic.review.verdict});
  await page.screenshot({path:"var/mvp-review/clear-desktop.png",fullPage:true});
  const lease=await sample("lease-return",process.argv.includes("--ai")?"ollama":"rules");
  assert.equal(lease.review.verdict,"warning");
  for(const finding of lease.review.findings.filter(f=>f.method==="ollama")) {
    assert(!/협의\s*(의무|책임)/.test(finding.why_unfavorable),"AI invented a negotiation burden");
    assert(!/예\s*[:：]/.test(finding.revision_suggestion),"AI rewrite included an example label");
    assert(!/반환\s*시기는\s*임대인이\s*결정/.test(finding.revision_suggestion),"AI rewrite introduced unilateral return timing");
  }
  assert((await page.locator(".risk-card").first().textContent()).includes("본인이 통제하기 어려운"));
  await page.locator("[data-explain]").first().click();
  await page.locator(".chat-message.assistant").waitFor();
  assert((await page.locator("#chat-messages").textContent()).includes("새 임차인"));
  await page.locator('[data-intent="scenario"]').click();
  await page.waitForFunction(()=>document.querySelectorAll(".chat-message.assistant").length===2);
  assert((await page.locator("#chat-messages").textContent()).includes("예시"));
  await page.locator('[data-intent="rewrite"]').click();
  await page.waitForFunction(()=>document.querySelectorAll(".chat-message.assistant").length===3);
  assert((await page.locator("#chat-messages").textContent()).includes("조건으로 삼지 않는다"));
  await page.screenshot({path:"var/mvp-review/chat-desktop.png",fullPage:true});
  await page.reload();await page.locator("#result-view").waitFor({state:"visible"});
  await page.locator("#tab-chat").click();
  await page.waitForFunction(()=>document.querySelectorAll(".chat-message.assistant").length===3);
  report.checks.push("clear verdict, adverse clause reasons, explanation/scenario/rewrite and persisted conversation");
  if(process.argv.includes("--ai")) {
    // Select the source clause again after reload, then ask an actual model follow-up.
    await page.locator("#tab-review").click();await page.locator("[data-explain]").first().click();
    await page.waitForFunction(()=>document.querySelectorAll(".chat-message.assistant").length===4);
    await page.locator("#chat-question").fill("내가 이사할 날짜가 정해져 있는데 이 특약 때문에 어떤 준비를 하면 좋을까?");
    const started=Date.now();await page.locator("#send-chat").click();
    await page.waitForFunction(()=>document.querySelectorAll(".chat-message.assistant").length===5||!document.querySelector("#chat-error").hidden,{},{timeout:130000});
    assert(await page.locator("#chat-error").isHidden(),await page.locator("#chat-error").textContent());
    const history=(await context.request.get(`${base}/api/analyses/${lease.analysis_id}/chat?analysis_revision=1`)).json();
    const turns=await history;
    assert.equal(turns.turns.at(-1).answer.method,"ollama");
    assert(turns.turns.at(-1).answer.text.length>20);
    report.ai.push({scenario:"conditional deposit return",semantic:lease.extraction.semantic_review,chat:turns.turns.at(-1),chat_seconds:(Date.now()-started)/1000});
    assert(!/새\s*세입자\s*모집\s*일정/.test(turns.turns.at(-1).answer.text));
    await page.screenshot({path:"var/mvp-review/chat-ai-desktop.png",fullPage:true});
    const standard=(await context.request.get(`${base}/api/samples/lease-basic`));
    const standardData=await standard.json();
    const customClause="특약: 임대인은 임차인의 동의 없이 보증금 반환 예정일을 변경할 수 있다.";
    const created=(await context.request.post(`${base}/api/analyses`,{data:{title:"동의 없는 반환일 변경 테스트",text:standardData.text+"\n"+customClause,contract_type:"lease",engine:"ollama",context:{document_complete:true,event_date:"2026-10-10"}}}));
    const customId=(await created.json()).analysis_id;ids.push(customId);
    let custom;
    for(let attempt=0;attempt<220;attempt++){
      custom=await (await context.request.get(`${base}/api/analyses/${customId}`)).json();
      if(!["queued","running"].includes(custom.status))break;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    assert.notEqual(custom.status,"failed",custom.error);
    assert(custom.review.findings.some(f=>f.method==="ollama"&&f.evidence.some(e=>customClause.includes(e.quote))));
    for(const finding of custom.review.findings.filter(f=>f.method==="ollama")) {
      const sentences=finding.revision_suggestion.split(/[.!?]/).map(s=>s.trim()).filter(Boolean);
      assert.equal(new Set(sentences).size,sentences.length,"AI rewrite repeated a sentence");
      assert(/[.!?]$/.test(finding.revision_suggestion),"AI rewrite stopped mid-sentence");
    }
    report.ai.push({scenario:"unilateral change expressed beyond predefined rules",review:custom.review});
  }
  await page.locator("#tab-draft").click();
  await page.locator("#draft-summary").fill("계약 종료가 다가와서 반환일을 물었는데 새 임차인을 구할 때까지 기다리라는 답을 받았습니다.");
  await page.locator("#draft-desired_outcome").fill("반환 조건을 수정하는 상담을 받고 싶습니다.");
  for(const kind of ["lawyer_request","help_request","complaint"]) {
    await page.locator("#draft-kind").selectOption(kind);await page.locator("#generate-draft").click();
    await page.waitForFunction(()=>document.querySelector("#draft-text").value.length>100);
    const text=await page.locator("#draft-text").inputValue();
    assert(text.includes("새 임차인"));
    if(kind==="complaint"){assert(text.includes("현재 미확정"));assert(!text.includes("1억원"));}
  }
  report.checks.push("consultation/help/complaint drafts with user facts; contractual deposit not claimed as loss");
  await page.locator("#prepare-document").click();
  await page.locator("#standalone-kind").selectOption("complaint");
  await page.locator("#standalone-summary").fill("온라인 거래 상대방이 물품을 보내겠다고 해서 입금했으나 약속한 날짜가 지나도 물품을 받지 못했습니다.");
  await page.locator("#standalone-loss").fill("실제로 보낸 35만원");
  await page.locator("#standalone-evidence").fill("이체 내역과 대화 캡처");
  await page.locator("#standalone-generate").click();
  await page.waitForFunction(()=>document.querySelector("#standalone-text").value.includes("고소장 초안"));
  assert((await page.locator("#standalone-text").inputValue()).includes("35만원"));
  const downloadEvent=page.waitForEvent("download");await page.locator("#standalone-download").click();
  assert((await downloadEvent).suggestedFilename().endsWith(".txt"));
  await page.screenshot({path:"var/mvp-review/complaint-desktop.png",fullPage:true});
  await page.setViewportSize({width:375,height:900});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:"var/mvp-review/complaint-mobile.png",fullPage:true});
  await page.locator("#new-document").click();await page.locator("#contract-type").selectOption("sale");
  await page.locator("#user-role").selectOption("seller");
  assert.equal(await page.locator("#user-role").inputValue(),"seller");
  report.checks.push("standalone incident complaint, editable TXT download, mobile layout, sale role selection");
  assert.deepEqual(errors,[]);report.browser_errors=errors;
  writeFileSync(`var/mvp-review/review-flow${process.argv.includes("--ai")?"-ai":""}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} finally {for(const id of ids)await context.request.delete(`${base}/api/analyses/${id}`);await context.request.dispose();await context.close();await browser.close();}
