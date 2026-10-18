"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const statusLabels = {attention:"확인 필요",needs_context:"추가 정보 필요",conflict:"후보 충돌",insufficient_evidence:"적용 근거 확인 필요",information:"참고 안내",queued:"대기 중",running:"분석 중",completed:"분석 완료",awaiting_input:"답변 대기",failed:"분석 실패"};
const contextLabels = {document_complete:"모든 페이지·별첨을 입력했나요?",event_date:"계약·사건 날짜",workplace_size:"상시 근로자 수",weekly_work_hours:"실제 주당 근로시간",move_in:"입주·주택 인도 완료",resident_registration:"전입신고 완료",deposit_returned:"계약 종료 후 보증금 전액 반환"};
const motion = () => matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth";
let current = null, selectedSample = null, initialContext = {}, uploadedReading = null, pollToken = 0, toastTimer;
let chatTurns = [], selectedFinding = null, chatScope = "", chatBusy = false, chatRequestToken = 0;
const roleChoices = {employment:[["worker","근로자 · 일하는 사람"],["employer","사업주 · 고용하는 사람"]],lease:[["tenant","임차인 · 집을 빌리는 사람"],["landlord","임대인 · 집을 빌려주는 사람"]],sale:[["buyer","매수인 · 사는 사람"],["seller","매도인 · 파는 사람"]]};
function renderRoles(role) {$("user-role").innerHTML=roleChoices[$("contract-type").value].map(([v,l])=>`<option value="${v}" ${v===role?"selected":""}>${l}</option>`).join("");}

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{...(options.body instanceof FormData ? {} : {"Content-Type":"application/json"}), ...options.headers}});
  if (response.status === 204) return null;
  const payload = await response.json();
  if (!response.ok) {
    const message = Array.isArray(payload.detail) ? payload.detail.map(d => d.msg).join(" · ") : payload.detail;
    throw new Error(message || "요청을 처리하지 못했습니다.");
  }
  return payload;
}
function errorBox(id, message) {$(id).textContent = message || ""; $(id).hidden = !message;}
function toast(message) {$("toast").textContent = message; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {$("toast").hidden = true;}, 3500);}
function view(name) {
  for (const n of ["entry","loading","result","draft-entry"]) $(n + "-view").hidden = n !== name;
  const preparing = name === "draft-entry";
  $("current-page").textContent = preparing ? "상담·고소 문서 준비" : "계약서 살펴보기";
  for (const [id, active] of [["new-document", !preparing], ["prepare-document", preparing]]) {
    $(id).classList.toggle("active", active);
    if (active) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
}
function settingsSummary() {
  $("settings-summary").textContent = `${$("engine").value === "ollama" ? "AI 검토" : "빠른 검토"} · ${$("live-evidence").checked ? "공식 근거 조회" : "저장된 근거"}`;
}
$("engine").addEventListener("change", settingsSummary);
$("live-evidence").addEventListener("change", settingsSummary);
function count() {$("character-count").textContent = `${$("document-text").value.length.toLocaleString()}자`;}
function selectedReset(preserveReading = false) {selectedSample = null; initialContext = {}; if (!preserveReading) uploadedReading = null; $("sample-download").hidden = true; document.querySelectorAll(".sample-card").forEach(b => b.classList.remove("selected"));}

async function loadHistory() {
  const items = await api("/api/analyses");
  $("history-count").textContent = items.length;
  $("history").innerHTML = items.length ? items.map(a => `<button class="history-item ${a.analysis_id === current?.analysis_id ? "current" : ""}" data-history="${esc(a.analysis_id)}">${esc(a.title)}<small>${esc(statusLabels[a.status])} · 수정 ${a.analysis_revision}</small></button>`).join("") : '<p class="muted">분석한 계약서가 여기에 모입니다.</p>';
}

async function loadSample(id) {
  const sample = await api(`/api/samples/${encodeURIComponent(id)}`);
  pollToken++;
  selectedSample = sample; initialContext = {...sample.context}; current = null;
  uploadedReading = null;
  $("document-title").value = sample.title;
  $("contract-type").value = sample.contract_type;
  renderRoles();
  $("document-text").value = sample.text;
  $("document-complete").checked = sample.context.document_complete === true;
  $("file-input").value = "";
  $("file-status").textContent = "";
  $("sample-download").innerHTML = `가상 시연 문서가 입력됐어요. <a href="/api/samples/${esc(id)}/pdf" target="_blank" rel="noopener">샘플 PDF 내려받기 ↗</a>`;
  $("sample-download").hidden = false;
  document.querySelectorAll(".sample-card").forEach(b => b.classList.toggle("selected", b.dataset.sample === id));
  history.replaceState(null,"",location.pathname);
  view("entry"); count(); errorBox("form-error", "");
  $("input-heading").scrollIntoView({behavior:motion(),block:"start"});
  $("document-text").focus({preventScroll:true});
  toast("샘플을 가져왔어요. ‘계약서 분석하기’를 눌러보세요.");
}

async function poll(id) {
  const token = ++pollToken;
  view("loading"); errorBox("form-error", "");
  const started = Date.now();
  while (token === pollToken) {
    const result = await api(`/api/analyses/${encodeURIComponent(id)}`);
    if (token !== pollToken) return;
    if (result.status === "failed") {
      view("entry"); errorBox("form-error", result.error); await loadHistory(); return;
    }
    if (["completed","awaiting_input"].includes(result.status)) {
      current = result; render(); await loadHistory(); return;
    }
    $("loading-text").textContent = result.status === "queued" ? "이전 분석이 끝나면 순서대로 진행합니다." : "원문 근거와 계약조건을 확인하고 있어요.";
    if (Date.now() - started > 240000) {view("entry"); errorBox("form-error","분석이 계속 진행 중입니다. 잠시 후 최근 분석에서 결과를 확인해주세요."); await loadHistory(); return;}
    await new Promise(resolve => setTimeout(resolve, 600));
  }
}

function sourceDetails(ids, citations = []) {
  return ids.map(id => {
    const s = current.sources.find(s => s.source_id === id);
    if (!s) return "";
    const url = /^https:\/\/(?:www\.)?law\.go\.kr\//.test(s.official_url) ? s.official_url : "";
    const kind = s.kind || "law", label = {law:"법령 기준",precedent:"관련 판례",interpretation:"법령해석 사례",decision:"행정심판 사례",dataset:"데이터 참고자료"}[kind] || "참고자료";
    const quoted = citations.filter(c=>c.source_id===id);
    const datasetLabel={contract:"계약서",contract_label:"계약서 항목 자료",precedent_reference:"판결문",interpretation_reference:"유권해석",decision_reference:"심결례",law_reference:"법령 참고자료",qa_example:"질의응답 예시",summary_example:"요약 예시"}[s.dataset_kind]||"참고자료";
    const meta = kind==="law" ? `시행 ${esc(s.effective_date)} · 조회 ${esc((s.checked_at||"").slice(0,10))}` : kind==="dataset" ? `제공된 자료의 원문 발췌 · ${esc(datasetLabel)}<br>${esc(s.archive)} / ${esc(s.member)}` : `${esc(s.court)} · ${esc(s.case_number)} · ${esc(s.decision_date)}<br>조회 ${esc((s.checked_at||"").slice(0,10))}`;
    return `<details class="source-details" data-source-kind="${esc(kind)}"><summary>${esc(label)} · ${esc(s.title)}</summary>${url?`<a class="source-title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">국가법령정보센터에서 보기 ↗</a>`:""}<div class="source-meta">${meta}<br>출처 ${esc(s.source_id)}</div>${quoted.length?`<h4>이 설명에서 인용한 문구</h4>${quoted.map(c=>`<blockquote>${esc(c.quote)}</blockquote>`).join("")}`:""}<div class="source-body">${esc(s.text)}</div><div class="source-warning">${esc(s.version_note)}</div></details>`;
  }).join("");
}
function evidenceButton(e) {return `<button class="evidence-link" data-evidence="${esc(e.block_id)}">${e.page}페이지 · 원문 보기 ↗</button>`;}
function formatValue(value) {
  const n = value.normalized_value;
  if (n?.currency === "KRW") {const period = {month:"월",hour:"시간",day:"일",year:"연",once:"보증금",unknown:"단위 확인"}[n.period]; return `${esc(n.amount.toLocaleString("ko-KR"))}원 <span class="subtle">/ ${esc(period)}</span>`;}
  if (n?.hours != null) return `주 ${esc(n.hours)}시간`;
  if (n?.minutes != null) return `${esc(n.minutes)}분`;
  if (n?.text) return esc(n.text);
  return esc(value.value_text);
}

function render() {
  view("result");
  history.replaceState(null,"",`#analysis=${current.analysis_id}`);
  $("result-title").textContent = current.title;
  $("result-revision").textContent = "수정 " + current.analysis_revision;
  $("result-meta").textContent = `${{employment:"근로계약서",lease:"주택 임대차계약서",sale:"부동산 매매계약서"}[current.contract_type]} · ${current.review?.role_label || "계약 당사자"} 입장 · ${current.engine === "ollama" ? "AI 검토 · " + current.extraction.model : "주요 위험 유형 빠른 검토"}`;
  const review=current.review;
  $("review-verdict").className="review-verdict "+(review?.verdict || "needs_information");
  $("review-verdict").innerHTML=`<span class="verdict-label">${{warning:"주의할 조항 발견",needs_information:"추가 확인 필요",clear:"검토 범위에서 이상 없음"}[review?.verdict] || "이전 분석 결과"}</span><h2>${esc(review?.headline || "최신 검토 기능을 사용하려면 내용을 수정해 다시 분석하세요.")}</h2>${review?.pending_reasons.length ? `<ul>${review.pending_reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>` : ""}<p>${esc(review?.scope_note || "")}</p>`;
  $("risk-findings").innerHTML=(review?.findings || []).map(f=>`<article class="risk-card" data-finding="${esc(f.finding_id)}"><div class="issue-top"><span class="badge attention">내 입장에서 주의</span><h3>${esc(f.title)}</h3></div><blockquote>${f.evidence.map(e=>esc(e.quote)).join("<br>")}</blockquote><h4>왜 나에게 불리한가요?</h4><p>${esc(f.why_unfavorable)}</p><h4>이런 상황이 생길 수 있어요</h4><p>${esc(f.scenario)}</p><details><summary>협의할 수정 문구 보기</summary><p>${esc(f.revision_suggestion)}</p></details><p class="field-help">${esc(f.legal_note)}</p>${f.applicability_questions?.length?`<h4>적용 전에 확인할 내용</h4><ul>${f.applicability_questions.map(q=>`<li>${esc(q)}</li>`).join("")}</ul>`:""}<div class="evidence-list">${f.evidence.map(evidenceButton).join("")}</div>${sourceDetails(f.source_ids,f.citations)}<button class="primary" data-explain="${esc(f.finding_id)}">이 조항 쉽게 설명해줘</button></article>`).join("");
  const grounding=current.grounding;
  $("grounding-panel").hidden=!grounding;
  if(grounding){
    const totals={law:0,case:0,dataset:0};current.sources.forEach(s=>totals[s.kind==="dataset"?"dataset":["precedent","interpretation","decision"].includes(s.kind)?"case":"law"]++);
    $("grounding-count").textContent=`법령 ${totals.law} · 사례 ${totals.case} · 참고 ${totals.dataset}`;
    $("grounding-status").textContent=`${grounding.mode==="live"?"국가법령정보센터에서 조회한 근거로 비교":"저장된 법령으로 비교"} · 기준 날짜 ${grounding.target_date}. 아래는 검토에 제공한 자료이며, 각 설명에 실제로 인용한 문구는 해당 조항에서 확인하세요.`;
    $("grounding-warning").hidden=!grounding.failures?.length;
    $("grounding-warning").textContent=grounding.failures?.length?`공식 조회를 완료하지 못한 자료: ${grounding.failures.map(f=>f.query||"API 설정").join(", ")}. 저장된 자료가 있으면 참고하며 최신성·적용 시점은 추가 확인이 필요합니다.`:"";
    $("grounding-sources").innerHTML=sourceDetails(current.sources.map(s=>s.source_id));
  }
  $("page-count").textContent = current.coverage.pages_read.length + "페이지";
  $("original-heading").textContent = current.reading?.ocr_used ? "읽은 계약서 텍스트 · OCR" : "계약서 원문";
  $("reading-notice").hidden = !current.reading?.ocr_used;
  $("reading-notice").textContent = current.reading?.ocr_used ? "OCR로 읽은 문서입니다. 날짜·금액·시간·체크 표시를 원본과 대조하세요. 잘못 읽힌 값은 ‘내용 수정’에서 바로잡을 수 있습니다." : "";
  $("summary-strip").innerHTML = [[review?.findings.length || 0,"주의 조항"],[current.terms.filter(t=>t.status==="found").length,"찾은 계약조건"],[current.questions.length,"남은 질문"]].map(([n,l]) => `<div class="summary-item"><strong>${n}</strong><span>${l}</span></div>`).join("");
  let page = 0;
  $("original-blocks").innerHTML = current.blocks.map(b => {const label = page !== b.page ? `<div class="page-label">PAGE ${b.page}</div>` : ""; page = b.page; return label + `<p class="block" id="block-${esc(b.block_id)}" tabindex="-1">${esc(b.text)}</p>`;}).join("");
  $("terms").innerHTML = current.terms.map(t => `<div class="term-row"><div class="term-label">${esc(t.label)}</div><div class="term-value">${t.status === "not_found" ? '<span class="term-status missing">현재 문서에서 찾지 못했어요</span>' : `${t.status === "conflict" ? '<p class="term-status">여러 후보 · 원문 확인 필요</p>' : ""}${t.candidates.map(c=>`<p>${formatValue(c)}</p>${evidenceButton(c.evidence)}`).join("")}`}</div></div>`).join("");
  $("issue-count").textContent = current.issues.length + "개 항목";
  $("issues").innerHTML = current.issues.map(i => `<article class="issue-card" data-issue="${esc(i.issue_type)}"><div class="issue-top"><span class="badge ${esc(i.status)}">${esc(statusLabels[i.status])}</span><h3>${esc(i.title)}</h3></div><p>${esc(i.explanation_ko)}</p>${i.issue_type === "missing_terms" ? `<ul>${(current.validation_checks || []).filter(c=>c.status === "not_found" && c.term_key !== "break_time").map(c=>`<li data-field="${esc(c.field)}">${esc(c.message)}</li>`).join("")}</ul>` : ""}<div class="evidence-list">${i.evidence.map(evidenceButton).join("")}</div>${sourceDetails(i.source_ids)}</article>`).join("");
  $("structured-details").hidden = !current.structured_contract;
  $("additional-details").open=review?.verdict === "needs_information";
  $("additional-details").hidden=current.issues.every(i=>i.status==="information");
  $("terms-details").open=false;
  $("structured-json").textContent = current.structured_contract ? JSON.stringify(current.structured_contract, null, 2) : "";
  renderQuestions();
  $("questions-panel").open=current.questions.length>0;
  $("actions").innerHTML = current.actions.map(a => `<li>${esc(a)}</li>`).join("");
  $("coverage").innerHTML = `<details><summary>이번 분석의 범위와 한계</summary><ul>${current.coverage.limitations.map(l=>`<li>${esc(l)}</li>`).join("")}<li>확인 항목: ${esc(current.coverage.checked_issue_types.join(", "))}</li><li>원문 대조에서 제외한 모델 후보: ${current.extraction.rejected_candidates}개</li><li>모든 페이지 입력 여부: ${current.context.document_complete === true ? "사용자 확인" : current.context.document_complete === false ? "미완료" : "미확인"}</li></ul></details>`;
  if (current.reading?.ocr_used) $("coverage").insertAdjacentHTML("afterbegin", '<p class="field-help">이 문서는 OCR로 읽었습니다. 날짜·금액·시간·체크 표시를 원본과 대조해주세요.</p>');
  if(current.review?.checked_items)$("coverage").querySelector("ul").insertAdjacentHTML("afterbegin",`<li>이번 입장에서 확인한 위험 유형: ${esc(current.review.checked_items.join(", "))}</li><li>${current.review.method==="rules_and_semantic"?"AI가 추가로 입력 문구의 의미를 검토했습니다.":"빠른 검토는 위에 표시한 위험 유형을 확인합니다. AI 검토를 선택하면 추가 특약의 의미도 검토합니다."}</li>`);
  $("draft-text").value = ""; $("draft-missing").textContent = ""; $("translation").innerHTML = "";
  $("copy-draft").disabled = true; $("download-draft").disabled = true;
  updateDraftIntake();
  loadChat().catch(e=>errorBox("chat-error",e.message));
  errorBox("result-error", ""); errorBox("answers-error", ""); errorBox("draft-error", ""); setTab("review");
  $("result-title").focus({preventScroll:true}); window.scrollTo({top:0,behavior:motion()});
}

function renderQuestions() {
  const keys = ["document_complete","event_date",...(current.contract_type === "employment" ? ["workplace_size","weekly_work_hours"] : current.contract_type === "lease" ? ["move_in","resident_registration","deposit_returned"] : [])];
  $("questions").innerHTML = keys.map(key => {
    const value = current.context[key];
    let input;
    if (key === "event_date") input = `<input id="context-${key}" name="${key}" type="date" value="${esc(value || "")}">`;
    else if (key === "weekly_work_hours") input = `<input id="context-${key}" name="${key}" type="number" min="0" max="168" step="0.5" placeholder="모르면 비워두세요" value="${esc(value ?? "")}">`;
    else {const choices = key === "workplace_size" ? [["unknown","모름"],["under5","5명 미만"],["5plus","5명 이상"]] : [["","모름"],["true","예"],["false","아니오"]]; input = `<select id="context-${key}" name="${key}">${choices.map(([v,l])=>`<option value="${v}" ${String(value ?? "") === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;}
    const needed = current.questions.some(q=>q.context_key===key);
    return `<div class="field"><label for="context-${key}">${esc(contextLabels[key])}${needed ? ' <span class="badge needs_context">추가 확인</span>' : ""}</label>${input}</div>`;
  }).join("");
}

function setTab(name) {
  for (const tab of document.querySelectorAll("[data-tab]")) {const selected = tab.dataset.tab === name; tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1; $(tab.dataset.tab + "-panel").hidden = !selected;}
}

function resetEntry(clear = false) {
  pollToken++;
  history.replaceState(null,"",location.pathname);
  view("entry"); errorBox("form-error", "");
  if (clear) {current=null; selectedReset(); $("analyze-form").reset(); renderRoles(); $("document-text").value=""; $("file-status").textContent=""; count();}
  settingsSummary();
  window.scrollTo({top:0,behavior:motion()}); $("document-title").focus({preventScroll:true});
}

$("document-text").addEventListener("input", () => {count(); selectedReset(true);});
$("contract-type").addEventListener("change", ()=>{selectedReset();renderRoles();});
$("new-document").addEventListener("click", () => resetEntry(true));
$("history-toggle").addEventListener("click", () => {const expanded=$("history-toggle").getAttribute("aria-expanded")!=="true";$("history-toggle").setAttribute("aria-expanded",String(expanded));document.querySelector(".sidebar").classList.toggle("history-open",expanded);});
$("loading-back").addEventListener("click", () => {resetEntry(); loadHistory().catch(()=>{});});
$("edit-document").addEventListener("click", () => {selectedReset(); uploadedReading = current.reading || null; $("document-text").value = current.blocks.reduce((text,b,index)=>text+(index&&b.page!==current.blocks[index-1].page?"\f":index?"\n":"")+b.text,""); $("document-title").value=current.title; $("contract-type").value=current.contract_type; renderRoles(current.user_role); $("engine").value=current.engine; $("live-evidence").checked=current.evidence_mode==="live"; $("document-complete").checked=current.context.document_complete===true; initialContext={...current.context}; count(); resetEntry();});

$("samples").addEventListener("click", event => {const button=event.target.closest("[data-sample]"); if(button) loadSample(button.dataset.sample).catch(e=>errorBox("form-error",e.message));});
$("history").addEventListener("click", event => {const button=event.target.closest("[data-history]"); if(button) poll(button.dataset.history).catch(e=>{view("entry");errorBox("form-error",e.message);});});
document.addEventListener("click", event => {
  const evidence = event.target.closest("[data-evidence]");
  if (evidence) {document.querySelectorAll(".block.selected").forEach(b=>b.classList.remove("selected")); const block=$("block-"+evidence.dataset.evidence); block?.classList.add("selected"); block?.scrollIntoView({behavior:motion(),block:"center"}); block?.focus({preventScroll:true});}
  const tab=event.target.closest("[data-tab]"); if(tab) setTab(tab.dataset.tab);
  const explain=event.target.closest("[data-explain]"); if(explain){selectedFinding=explain.dataset.explain;setTab("chat");renderChat();sendChat("쉽게 설명해줘", "explain");}
  const quick=event.target.closest("[data-intent]"); if(quick)sendChat(quick.textContent,quick.dataset.intent);
  if(event.target.closest("[data-chat-all]")){selectedFinding=null;renderChat();}
});
document.querySelector(".result-tabs").addEventListener("keydown", event => {if(!["ArrowRight","ArrowLeft","Home","End"].includes(event.key))return; const tabs=[...document.querySelectorAll("[data-tab]")]; let index=tabs.indexOf(document.activeElement); if(index<0)return; event.preventDefault(); index=event.key==="Home"?0:event.key==="End"?tabs.length-1:(index+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length; setTab(tabs[index].dataset.tab);tabs[index].focus();});

$("file-input").addEventListener("change", async () => {
  const file=$("file-input").files[0]; if(!file)return;
  $("analyze-button").disabled=true; $("file-status").textContent="문서 내용을 읽고 있어요…"; errorBox("form-error", "");
  try {const body=new FormData();body.append("file",file);const data=await api("/api/uploads",{method:"POST",body}); selectedReset();uploadedReading = data.reading;$("document-text").value=data.text;$("document-title").value=data.filename.slice(0,120);$("file-status").textContent=`${data.filename} · ${data.pages}페이지 읽음${data.reading?.ocr_used ? " · OCR 사용" : ""} ${(data.reading?.warnings || []).join(" ")}`; count();}
  catch(e){$("file-status").textContent="파일을 읽지 못했습니다.";errorBox("form-error",e.message);}
  finally{$("analyze-button").disabled=false;}
});

$("download-json").addEventListener("click", () => {
  if (!current?.structured_contract) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(current.structured_contract, null, 2)], {type:"application/json;charset=utf-8"}));
  const link = document.createElement("a"); link.href = url; link.download = "contract.json"; link.click(); URL.revokeObjectURL(url);
});

$("analyze-form").addEventListener("submit", async event => {
  event.preventDefault(); errorBox("form-error", "");
  if($("document-text").value.trim().length<20){errorBox("form-error","계약서 내용을 20자 이상 입력해주세요.");return;}
  const context={...initialContext,document_complete:$("document-complete").checked?true:null};
  $("analyze-button").disabled=true;
  try {const result=await api("/api/analyses",{method:"POST",body:JSON.stringify({title:$("document-title").value,text:$("document-text").value,contract_type:$("contract-type").value,user_role:$("user-role").value,engine:$("engine").value,evidence_mode:$("live-evidence").checked?"live":"local",context,reading:uploadedReading})}); await loadHistory();await poll(result.analysis_id);}
  catch(e){view("entry");errorBox("form-error",e.message);}
  finally{$("analyze-button").disabled=false;}
});

$("answers-form").addEventListener("submit",async event=>{
  event.preventDefault(); const context={};
  for(const [key,value] of new FormData(event.target)){context[key]=value===""?null:["document_complete","move_in","resident_registration","deposit_returned"].includes(key)?value==="true":key==="weekly_work_hours"?Number(value):value;}
  $("answers-button").disabled=true;
  try {current=await api(`/api/analyses/${current.analysis_id}/answers`,{method:"POST",body:JSON.stringify({analysis_revision:current.analysis_revision,context})});render();await loadHistory();toast("답변을 반영했어요. 확인할 사항이 갱신됐습니다.");}
  catch(e){errorBox("answers-error",e.message);}
  finally{$("answers-button").disabled=false;}
});

$("delete-analysis").addEventListener("click",async()=>{
  if(!current)return;const id=current.analysis_id;
  $("delete-analysis").disabled=true;
  try{await api(`/api/analyses/${id}`,{method:"DELETE"});resetEntry(true);await loadHistory();toast("계약서 원문과 분석 기록을 삭제했어요.");}
  catch(e){errorBox("result-error",e.message);}
  finally{$("delete-analysis").disabled=false;}
});

$("generate-draft").addEventListener("click",async()=>{
  $("generate-draft").disabled=true;errorBox("draft-error", "");const id=current.analysis_id, revision=current.analysis_revision;
  try{const data=await api(`/api/analyses/${id}/drafts`,{method:"POST",body:JSON.stringify({analysis_revision:revision,kind:$("draft-kind").value,incident:readIncident("draft")})});if(current?.analysis_id!==id||current.analysis_revision!==revision)return;$("draft-text").value=data.draft_text;$("draft-missing").textContent="직접 확인할 항목: "+data.missing_fields.join(", ");$("copy-draft").disabled=false;$("download-draft").disabled=false;}
  catch(e){errorBox("draft-error",e.message);}
  finally{$("generate-draft").disabled=false;}
});
$("copy-draft").addEventListener("click",async()=>{try{await navigator.clipboard.writeText($("draft-text").value);toast("초안 내용을 복사했어요.");}catch{$("draft-text").select();toast("초안을 선택했어요. 복사 단축키를 눌러주세요.");}});
$("download-draft").addEventListener("click",()=>{const blob=new Blob([$("draft-text").value],{type:"text/plain;charset=utf-8"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="권리ON_검토용_초안.txt";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});

$("generate-translation").addEventListener("click",async()=>{
  $("generate-translation").disabled=true;errorBox("result-error", "");const id=current.analysis_id,revision=current.analysis_revision;
  try{const data=await api(`/api/analyses/${id}/translations`,{method:"POST",body:JSON.stringify({analysis_revision:revision,language:$("language").value})});if(current?.analysis_id!==id||current.analysis_revision!==revision)return;
    $("translation").innerHTML=`<div class="translation-block" lang="${data.language === "zh" ? "zh-Hans" : "es"}"><h3>${esc(data.heading)}</h3><p>${esc(data.notice)}</p><h3>${esc(data.facts_heading)}</h3>${data.terms.map(t=>`<div class="term-row"><div class="term-label">${esc(t.label)}</div><div class="term-value">${t.candidates.map(c=>`<p lang="ko">${esc(c.value_text)}</p>${evidenceButton(c.evidence)}`).join("")}<div class="subtle">${esc(t.status_text)}</div></div></div>`).join("")}${data.issues.map(i=>`<div class="translation-issue"><span class="badge ${esc(i.status)}" lang="ko">${esc(statusLabels[i.status])}</span><p>${esc(i.text)}</p>${i.evidence.map(e=>`<blockquote lang="ko">${esc(e.quote)}</blockquote>`).join("")}<div lang="ko">${sourceDetails(i.source_ids)}</div></div>`).join("")}<ul>${data.questions.map(q=>`<li>${esc(q.text)}</li>`).join("")}</ul><ul>${data.actions.map(a=>`<li>${esc(a)}</li>`).join("")}</ul></div>`;
    if (data.context_facts?.length) {
      const root=$("translation").firstElementChild;
      const heading=document.createElement("h3");heading.textContent=data.context_heading;root.append(heading);
      for (const fact of data.context_facts) {
        const row=document.createElement("div");row.className="term-row";
        const label=document.createElement("div");label.className="term-label";label.textContent=fact.label;
        const value=document.createElement("div");value.className="term-value";value.textContent=fact.text;
        row.append(label,value);root.append(row);
      }
    }
  }catch(e){errorBox("result-error",e.message);}finally{$("generate-translation").disabled=false;}
});

window.addEventListener("hashchange",()=>{const id=location.hash.match(/^#analysis=([a-f0-9-]{36})$/)?.[1];if(id)poll(id).catch(e=>{view("entry");errorBox("form-error",e.message);});else resetEntry();});

function renderChat() {
  const finding=current?.review?.findings.find(f=>f.finding_id===selectedFinding);
  $("chat-focus").innerHTML=finding ? `<strong>지금 질문할 조항: ${esc(finding.title)}</strong><blockquote>${esc(finding.evidence[0].quote)}</blockquote><button class="secondary" data-chat-all>계약 전체에 관해 질문하기</button>` : '<p>계약 전체에 관해 질문하고 있어요. 특정 조항을 설명받으려면 검토 결과에서 ‘쉽게 설명해줘’를 누르세요.</p>';
  $("chat-messages").innerHTML=chatTurns.length ? chatTurns.map(t=>`<article class="chat-message user"><strong>내 질문</strong><p>${esc(t.question)}</p></article><article class="chat-message assistant"><strong>권리ON <span class="subtle">${t.answer.method==="ollama"?"로컬 AI 답변":"검토 내용에 따른 설명"}</span></strong><p>${esc(t.answer.text)}</p>${t.answer.evidence.map(evidenceButton).join("")}${sourceDetails(t.answer.source_ids,t.answer.citations)}</article>`).join("") : '<p class="muted">아직 대화가 없습니다. 조항의 뜻, 불리한 상황, 수정 문구를 물어보세요.</p>';
  document.querySelectorAll("[data-intent]").forEach(b=>b.disabled=chatBusy||!finding);
  $("send-chat").disabled=chatBusy;
}

async function loadChat() {
  const scope=`${current.analysis_id}:${current.analysis_revision}`, id=current.analysis_id, revision=current.analysis_revision;
  if(chatScope!==scope){
    if(!chatScope.startsWith(id+":"))document.querySelectorAll("#draft-intake input,#draft-intake textarea").forEach(e=>e.value="");
    chatScope=scope;chatTurns=[];selectedFinding=null;chatBusy=false;chatRequestToken++;$("chat-status").textContent="";errorBox("chat-error","");
  }
  renderChat();
  const token=chatRequestToken;
  const data=await api(`/api/analyses/${id}/chat?analysis_revision=${revision}`);
  if(chatScope!==scope||token!==chatRequestToken)return;
  chatTurns=data.turns;renderChat();
}

async function sendChat(question,intent="custom") {
  if(chatBusy||!current)return;
  const id=current.analysis_id, revision=current.analysis_revision, token=++chatRequestToken;
  chatBusy=true;renderChat();errorBox("chat-error","");$("chat-status").textContent=intent==="custom"?"원문을 참고해 답변을 작성하고 있습니다…":"이 조항을 쉬운 말로 정리하고 있습니다…";
  try {
    const data=await api(`/api/analyses/${id}/chat`,{method:"POST",body:JSON.stringify({analysis_revision:revision,question,finding_id:selectedFinding,intent})});
    if(token!==chatRequestToken||current?.analysis_id!==id||current.analysis_revision!==revision)return;
    chatTurns.push(data.turn);$("chat-question").value="";$("chat-status").textContent="답변이 도착했습니다.";renderChat();$("chat-messages").lastElementChild?.scrollIntoView({behavior:motion(),block:"nearest"});
  } catch(e) {if(token===chatRequestToken)errorBox("chat-error",e.message);}
  finally {if(token===chatRequestToken){chatBusy=false;renderChat();}}
}
$("chat-form").addEventListener("submit",event=>{event.preventDefault();sendChat($("chat-question").value);});

const incidentSpecs=[
  ["writer","작성자 이름","input",200,"가려도 됩니다. 최종 사용 전에 직접 입력하세요."],
  ["counterparty","상대방 이름·명칭","input",200,"알고 있는 정보만 입력하세요."],
  ["date","언제 있었던 일인가요?","input",100,"예: 2026년 10월 초 / 정확히 모르면 모름"],
  ["place","어디에서 있었나요?","input",300,"장소나 거래·연락 경로"],
  ["summary","실제로 있었던 일","textarea",8000,"상대방이 한 말·행동, 내가 한 일, 현재 상황을 시간 순서로 적어주세요. 모르는 사실은 만들지 마세요."],
  ["loss","실제 피해와 우려되는 부담","textarea",500,"실제로 지급한 돈·받지 못한 돈·그 밖의 피해와 근거를 구분해 적어주세요."],
  ["evidence","가지고 있는 자료","textarea",2000,"예: 계약서, 입금 내역, 날짜가 보이는 메시지. 보유한 자료만 적어주세요."],
  ["desired_outcome","어떤 도움을 원하나요?","textarea",1000,"예: 조항 수정 상담, 반환 요청 방법, 사건 조사 요청"]
];
function incidentFields(prefix) {
  const field=([key,label,type,max,help])=>`<div class="field ${type==="textarea"?"wide-field":""}"><label for="${prefix}-${key}">${label}</label>${type==="textarea"?`<textarea id="${prefix}-${key}" rows="${key==="summary"?5:2}" maxlength="${max}" ${prefix==="standalone"&&key==="summary"?'required minlength="20"':""}></textarea>`:`<input id="${prefix}-${key}" maxlength="${max}">`}<p class="field-help">${help}</p></div>`;
  return '<p class="field-help intake-notice"></p><div class="question-grid">'+incidentSpecs.filter(s=>s[2]==="textarea").map(field).join("")+'</div><details class="incident-people"><summary>이름·사건 시점·장소 추가하기 (모르면 비워두세요)</summary><div class="question-grid">'+incidentSpecs.filter(s=>s[2]==="input").map(field).join("")+"</div></details>";
}
function readIncident(prefix) {return Object.fromEntries(incidentSpecs.map(([key])=>[key,$(`${prefix}-${key}`).value]));}
function updateDraftIntake() {
  const kind=$("draft-kind").value;
  $("draft-intake").hidden=["summary","request"].includes(kind);
  $("draft-intake").querySelector(".intake-notice").textContent=kind==="complaint"?"고소 초안은 실제 사건 경위를 20자 이상 입력해야 만들 수 있습니다. 죄명과 범죄 성립은 미확정으로 남깁니다.":"사건 경위를 추가하면 상담 요청문에 함께 들어갑니다. 계약서에 없는 사실은 직접 설명한 내용으로 표시합니다.";
}
$("draft-intake").innerHTML=incidentFields("draft");
$("standalone-intake").innerHTML=incidentFields("standalone");
$("standalone-intake").querySelector(".intake-notice").textContent="실제로 있었던 일을 20자 이상 적어주세요. 고소 초안의 죄명과 범죄 성립은 검토할 항목으로 남깁니다.";
$("draft-kind").addEventListener("change",()=>{updateDraftIntake();errorBox("draft-error","");$("draft-text").value="";$("copy-draft").disabled=true;$("download-draft").disabled=true;$("draft-missing").textContent="";});
$("consultation-draft").addEventListener("click",()=>{$("draft-kind").value="lawyer_request";updateDraftIntake();setTab("draft");$("draft-summary").focus();});
$("prepare-document").addEventListener("click",()=>{pollToken++;history.replaceState(null,"",location.pathname);view("draft-entry");window.scrollTo({top:0,behavior:motion()});$("standalone-summary").focus({preventScroll:true});});
$("standalone-form").addEventListener("submit",async event=>{
  event.preventDefault();$("standalone-generate").disabled=true;errorBox("standalone-error","");$("standalone-status").textContent="입력한 사실로 초안을 정리하고 있습니다…";
  try {const data=await api("/api/drafts",{method:"POST",body:JSON.stringify({kind:$("standalone-kind").value,incident:readIncident("standalone")})});$("standalone-text").value=data.draft_text;$("standalone-missing").textContent="직접 확인할 항목: "+data.missing_fields.join(", ");$("standalone-download").disabled=false;$("standalone-status").textContent="초안을 만들었습니다. 사실과 빈칸을 확인하고 수정하세요.";}
  catch(e){errorBox("standalone-error",e.message);$("standalone-status").textContent="";}
  finally{$("standalone-generate").disabled=false;}
});
$("standalone-download").addEventListener("click",()=>{const url=URL.createObjectURL(new Blob([$("standalone-text").value],{type:"text/plain;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="권리ON_사건문서_초안.txt";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$("standalone-kind").addEventListener("change",()=>{$("standalone-text").value="";$("standalone-download").disabled=true;$("standalone-missing").textContent="";});
updateDraftIntake();
async function init(){
  const samples=await api("/api/samples");
  $("samples").innerHTML=samples.map((s,index)=>`<button class="sample-card" data-sample="${esc(s.id)}"><span class="sample-tag">${esc(s.tag)}<span>${String(index+1).padStart(2,"0")}</span></span><strong>${esc(s.title)}</strong><p>${esc(s.description)}</p><span class="arrow" aria-hidden="true">↗</span></button>`).join("");
  await loadHistory();
  view("entry"); settingsSummary();
  const id=location.hash.match(/^#analysis=([a-f0-9-]{36})$/)?.[1];if(id)await poll(id);
}
init().catch(e=>{view("entry");errorBox("form-error",e.message);});
