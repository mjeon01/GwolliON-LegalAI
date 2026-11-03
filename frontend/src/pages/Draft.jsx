import { useLanguage, t } from "../i18n/index.js";
import { CLOUD_AI_ENABLED } from "../config/features.js";
import { useRef, useState } from "react";
import { downloadPdf, href, post } from "../lib/index.js";
import useSession from "../hooks/useSession.js";
import {
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
  PrivacyNote,
  Workflow,
} from "../components/UI.jsx";
const kinds = [
  [
    "lawyer_request",
    "상담 요청문",
    "주의 조항과 내 상황을 정리해 상담을 준비합니다.",
  ],
  [
    "revision_request",
    "계약 수정 요청서",
    "불리한 조항의 현재 문구와 제안 문구를 상대방에게 전달합니다.",
  ],
  ["summary", "검토 요약", "계약 조건과 확인할 쟁점을 한 문서로 모읍니다."],
  ["request", "사실확인 요청문", "모호한 계약조건을 상대방에게 확인합니다."],
];
const fields = [
  ["date", "일이 있었던 날짜", 100],
  ["place", "관련 장소", 300],
  ["summary", "실제로 있었던 일", 8000],
  ["loss", "발생한 손해 또는 미지급 금액", 500],
  ["evidence", "가지고 있는 증거·자료", 2000],
  ["desired_outcome", "원하는 해결 방향", 1000],
];
const today = () => {
  const now = new Date();
  return new Date(now - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
};
/** Blanks are written as [직접 입력]-style markers in the draft. */
function findBlanks(text) {
  return [...text.matchAll(/\[[^\]\n]+\]/g)].map((match) => {
    const start = text.lastIndexOf("\n", match.index) + 1;
    const name = match[0].slice(1, -1).replace(/\s*직접 입력$/, "");
    const label = text
      .slice(start, match.index)
      .trim()
      .replace(/[:：]$/, "");
    return {
      start: match.index,
      end: match.index + match[0].length,
      label: name || label,
    };
  });
}
function lineKind(line) {
  if (/^\d+\.\s/.test(line)) return "heading";
  if (/^조항 \d+\.\s/.test(line)) return "clause";
  if (line.startsWith("- ")) return "bullet";
  return line.startsWith(" ") ? "indent" : "body";
}
function DocumentView({ text, onBlank }) {
  let offset = 0;
  let titled = false;
  return (
    <article className="paper document-view" lang="ko">
      {text.split("\n").map((line, n) => {
        const lineStart = offset;
        offset += line.length + 1;
        if (!line.trim()) return <div className="document-gap" key={n} />;
        const parts = [];
        let cursor = 0;
        for (const match of line.matchAll(/\[[^\]]+\]/g)) {
          parts.push(line.slice(cursor, match.index));
          const start = lineStart + match.index;
          parts.push(
            <button
              type="button"
              className="document-blank"
              key={match.index}
              onClick={() => onBlank(start, start + match[0].length)}
            >
              {match[0].slice(1, -1)}
            </button>,
          );
          cursor = match.index + match[0].length;
        }
        parts.push(line.slice(cursor));
        const kind = titled ? lineKind(line) : "title";
        titled = true;
        return (
          <p className={`document-${kind}`} key={n}>
            {parts}
          </p>
        );
      })}
    </article>
  );
}
export default function Draft({ result: r }) {
  const lang = useLanguage();
  const key = `draft:${r.analysis_id}:${r.analysis_revision}`;
  const [state, setState] = useSession(key, {
    kind: "lawyer_request",
    incident: {},
    text: "",
    generated: false,
    missing: [],
    translations: {},
    incidentKo: null,
    incidentSource: "",
    incidentConfirmed: false,
    writtenOn: today(),
    replyBy: "",
    clauses: null,
    view: "preview",
    note: "",
  });
  const editor = useRef();
  const findings = r.review.findings;
  const chosen = state.clauses ?? findings.map((f) => f.finding_id);
  const blanks = findBlanks(state.text);
  const toCounterparty = ["revision_request", "request"].includes(state.kind);
  const setIncident = (name, value) =>
    setState((old) => ({
      ...old,
      incident: { ...old.incident, [name]: value },
    }));
  function openBlank(start, end) {
    setState((old) => ({ ...old, view: "edit" }));
    requestAnimationFrame(() => {
      editor.current?.focus();
      editor.current?.setSelectionRange(start, end);
    });
  }
  async function savePdf(text, name) {
    if (
      findBlanks(text).length &&
      !window.confirm(
        t(
          "빈칸 {0}개가 남아 있습니다. 그대로 저장할까요?",
          findBlanks(text).length,
        ),
      )
    )
      return;
    setError("");
    try {
      await downloadPdf(text, name);
      setNotice("PDF를 저장했습니다.");
    } catch (e) {
      setError(e.message);
    }
  }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const foreignIncident = Object.entries(state.incident).some(
    ([key, value]) =>
      ["summary", "loss", "evidence", "desired_outcome"].includes(key) &&
      /[A-Za-z一-鿿]/.test(value) &&
      !/[가-힣]/.test(value),
  );
  const needsInterpretation =
    CLOUD_AI_ENABLED && (lang !== "ko" || foreignIncident);
  const incidentCurrent =
    state.incidentSource === JSON.stringify(state.incident);
  const localizedDraft = state.translations?.[lang];
  const translationCurrent = localizedDraft?.original_text === state.text;
  async function interpret() {
    setBusy(true);
    setError("");
    try {
      const data = await post(
        `/api/analyses/${r.analysis_id}/incident-translations`,
        {
          analysis_revision: r.analysis_revision,
          language: lang,
          incident: state.incident,
        },
      );
      setState((old) => ({
        ...old,
        incidentKo: data.incident,
        incidentSource: JSON.stringify(state.incident),
        incidentConfirmed: false,
      }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function updateTranslation() {
    const snapshot = state.text;
    setBusy(true);
    setError("");
    try {
      const data = await post(
        `/api/analyses/${r.analysis_id}/document-translations`,
        {
          analysis_revision: r.analysis_revision,
          language: lang,
          text: snapshot,
        },
      );
      setState((old) => ({
        ...old,
        translations: {
          ...old.translations,
          [lang]: data,
        },
      }));
      setNotice("번역을 갱신했습니다. 한국어 원문과 대조해주세요.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const exportText = (both) =>
    both
      ? t(
          "한국어\n{0}\n\n{1}\n{2}",
          state.text,
          lang === "zh" ? "中文" : "Español",
          localizedDraft.text,
        )
      : state.text;
  async function generate(event) {
    event.preventDefault();
    if (
      !CLOUD_AI_ENABLED &&
      state.kind === "lawyer_request" &&
      foreignIncident
    ) {
      setError("사건 경위는 한국어로 입력해주세요.");
      return;
    }
    if (
      needsInterpretation &&
      state.kind === "lawyer_request" &&
      Object.values(state.incident).some(Boolean) &&
      (!incidentCurrent || !state.incidentConfirmed)
    ) {
      setError("사건 경위의 한국어 해석을 확인한 뒤 문서에 반영해주세요.");
      return;
    }
    if (state.kind === "revision_request" && !chosen.length) {
      setError("수정을 요청할 조항을 하나 이상 선택해주세요.");
      return;
    }
    if (
      state.generated &&
      !window.confirm(
        t("새 초안을 만들면 현재 편집한 문서가 바뀝니다. 다시 만들까요?"),
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await post(`/api/analyses/${r.analysis_id}/drafts`, {
        analysis_revision: r.analysis_revision,
        kind: state.kind,
        incident:
          state.kind === "lawyer_request"
            ? !needsInterpretation
              ? state.incident
              : state.incidentKo || {}
            : {
                writer: state.incident.writer || "",
                counterparty: state.incident.counterparty || "",
              },
        finding_ids: chosen,
        written_on: state.writtenOn || "",
        reply_by: toCounterparty ? state.replyBy || "" : "",
        language: CLOUD_AI_ENABLED ? lang : "ko",
        incident_original:
          needsInterpretation && state.kind === "lawyer_request"
            ? state.incident
            : null,
        incident_confirmed:
          state.kind !== "lawyer_request" ||
          !needsInterpretation ||
          (incidentCurrent && !!state.incidentConfirmed),
      });
      setState((old) => ({
        ...old,
        text: data.draft_text,
        generated: true,
        generatedKind: state.kind,
        note: data.review_note || "",
        view: "preview",
      }));
      setNotice(
        "초안을 만들었습니다. 내용을 확인하고 직접 수정할 수 있습니다.",
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function copy(both = false) {
    try {
      await navigator.clipboard.writeText(exportText(both));
      setNotice("문서를 복사했습니다.");
    } catch {
      setNotice(
        "복사하지 못했습니다. 문서 내용을 선택해 복사하거나 PDF로 저장해주세요.",
      );
    }
  }
  return (
    <>
      <PageHead
        eyebrow="03 / Prepare your next step"
        title={t("전할 내용을 명확하게.")}
        description={t(r.title)}
        action={
          <ButtonLink to={href("review", r.analysis_id)} icon="back">
            {t("검토 결과")}
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      <div className="draft-layout">
        <form className="panel draft-form" onSubmit={generate}>
          <fieldset disabled={busy}>
            <div className="section-heading">
              <h2>{t("어떤 문서가 필요한가요?")}</h2>
            </div>
            <div className="document-types">
              {kinds.map(([value, title, description]) => (
                <label
                  key={value}
                  className={`document-type ${state.kind === value ? "selected" : ""}${value === "revision_request" && !findings.length ? " unavailable" : ""}`}
                >
                  <input
                    type="radio"
                    name="kind"
                    value={value}
                    checked={state.kind === value}
                    disabled={value === "revision_request" && !findings.length}
                    onChange={() =>
                      setState((old) => ({
                        ...old,
                        kind: value,
                      }))
                    }
                  />
                  <span>
                    <strong>{t(title)}</strong>
                    <small>{t(description)}</small>
                  </span>
                </label>
              ))}
            </div>
            <h3 className="subheading">{t("문서 기본 정보")}</h3>
            <div className="form-grid">
              <Field label={t("내 이름")}>
                <input
                  maxLength={200}
                  value={state.incident.writer || ""}
                  onChange={(e) => setIncident("writer", e.target.value)}
                />
              </Field>
              <Field
                label={t(
                  state.kind === "lawyer_request" ? "상대방" : "받는 사람",
                )}
              >
                <input
                  maxLength={200}
                  value={state.incident.counterparty || ""}
                  onChange={(e) => setIncident("counterparty", e.target.value)}
                />
              </Field>
              <Field label={t("작성일")}>
                <input
                  type="date"
                  value={state.writtenOn || ""}
                  onChange={(e) =>
                    setState((old) => ({ ...old, writtenOn: e.target.value }))
                  }
                />
              </Field>
              {toCounterparty && (
                <Field label={t("회신 희망일")}>
                  <input
                    type="date"
                    value={state.replyBy || ""}
                    onChange={(e) =>
                      setState((old) => ({ ...old, replyBy: e.target.value }))
                    }
                  />
                </Field>
              )}
            </div>
            {findings.length > 0 && (
              <fieldset className="clause-picker">
                <legend>{t("문서에 넣을 조항")}</legend>
                {findings.map((f) => (
                  <label className="check-label" key={f.finding_id}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(f.finding_id)}
                      onChange={(e) =>
                        setState((old) => ({
                          ...old,
                          clauses: e.target.checked
                            ? [...chosen, f.finding_id]
                            : chosen.filter((id) => id !== f.finding_id),
                        }))
                      }
                    />
                    {t(f.title)}
                  </label>
                ))}
              </fieldset>
            )}
            {state.kind === "lawyer_request" && (
              <>
                <h3 className="subheading">{t("내 상황을 더해주세요")}</h3>
                <p className="small muted">
                  {t(
                    "아는 내용만 적어주세요. 비워둔 내용은 초안에서 확인할 수 있습니다.",
                  )}
                  {!CLOUD_AI_ENABLED && (
                    <> {t("사건 경위는 한국어로 입력해주세요.")}</>
                  )}
                </p>
                {fields.map(([name, label, max]) => (
                  <Field key={name} label={t(label)}>
                    {["summary", "evidence", "desired_outcome"].includes(
                      name,
                    ) ? (
                      <textarea
                        rows={name === "summary" ? 5 : 3}
                        maxLength={max}
                        value={state.incident[name] || ""}
                        onChange={(e) => setIncident(name, e.target.value)}
                      />
                    ) : (
                      <input
                        maxLength={max}
                        value={state.incident[name] || ""}
                        onChange={(e) => setIncident(name, e.target.value)}
                      />
                    )}
                  </Field>
                ))}
                {needsInterpretation && (
                  <div className="incident-translation">
                    <PrivacyNote />
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={interpret}
                    >
                      {t("한국어로 해석하기")}
                    </button>
                    {state.incidentKo && (
                      <>
                        <p className="notice">
                          {t("한국어 해석을 확인·수정한 뒤 문서에 반영하세요.")}
                        </p>
                        {fields.map(([name, label, max]) => (
                          <Field key={name} label={t(label)}>
                            <textarea
                              rows={name === "summary" ? 4 : 2}
                              lang="ko"
                              maxLength={max}
                              value={state.incidentKo[name] || ""}
                              onChange={(e) =>
                                setState((old) => ({
                                  ...old,
                                  incidentKo: {
                                    ...old.incidentKo,
                                    [name]: e.target.value,
                                  },
                                  incidentConfirmed: false,
                                }))
                              }
                            />
                          </Field>
                        ))}
                        <label className="check-label">
                          <input
                            type="checkbox"
                            checked={
                              !!state.incidentConfirmed && incidentCurrent
                            }
                            disabled={!incidentCurrent}
                            onChange={(e) =>
                              setState((old) => ({
                                ...old,
                                incidentConfirmed: e.target.checked,
                              }))
                            }
                          />
                          {t("한국어 해석이 실제 설명과 일치합니다.")}
                        </label>
                        {!incidentCurrent && (
                          <p className="notice">
                            {t(
                              "사건 설명이 바뀌었습니다. 한국어 해석을 다시 확인해주세요.",
                            )}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </fieldset>
          <ErrorNotice message={error} />
          <button className="btn btn-primary full-width" disabled={busy}>
            {t(
              busy
                ? "초안을 만드는 중…"
                : state.generated
                  ? "입력 내용으로 다시 만들기"
                  : "문서 초안 만들기",
            )}
            {t(" ")}
            <Icon name="pen" />
          </button>
        </form>
        <section className="draft-preview" aria-label={t("문서 초안 편집")}>
          <div className="preview-toolbar">
            <span className="eyebrow">Your document</span>
            <span className="small muted">
              {t("검토 버전 {0} 기준", r.analysis_revision)}
            </span>
          </div>
          {state.generated &&
            state.generatedKind &&
            state.generatedKind !== state.kind && (
              <div className="notice">
                {t(
                  "아래는 이전에 생성한 초안입니다. 선택한 문서로 바꾸려면 다시 만들기를 눌러주세요.",
                )}
              </div>
            )}
          {state.generated ? (
            <>
              <div className="document-status">
                {blanks.length ? (
                  <>
                    <strong>{t("채워야 할 빈칸 {0}개", blanks.length)}</strong>
                    <div className="blank-chips">
                      {blanks.map((blank) => (
                        <button
                          type="button"
                          key={blank.start}
                          onClick={() => openBlank(blank.start, blank.end)}
                        >
                          {t(blank.label)}
                        </button>
                      ))}
                    </div>
                  </>
                ) : (
                  <strong className="blanks-done">
                    <Icon name="check" />
                    {t("빈칸을 모두 채웠습니다.")}
                  </strong>
                )}
                {state.note && <p>{t(state.note)}</p>}
              </div>
              <div className="doc-switch document-switch">
                {[
                  ["preview", "미리보기"],
                  ["edit", "직접 수정"],
                ].map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={(state.view || "preview") === value}
                    onClick={() => setState((old) => ({ ...old, view: value }))}
                  >
                    {t(label)}
                  </button>
                ))}
              </div>
              {state.view === "edit" ? (
                <>
                  <label className="visually-hidden" htmlFor="draft-editor">
                    {t("문서 초안 편집")}
                  </label>
                  <textarea
                    id="draft-editor"
                    ref={editor}
                    className="paper draft-paper"
                    value={state.text}
                    lang="ko"
                    maxLength={50000}
                    onChange={(e) =>
                      setState((old) => ({
                        ...old,
                        text: e.target.value,
                      }))
                    }
                  />
                </>
              ) : (
                <DocumentView text={state.text} onBlank={openBlank} />
              )}
              {CLOUD_AI_ENABLED && lang !== "ko" && (
                <section className="document-translation">
                  <h2>{t("번역본")}</h2>
                  <PrivacyNote />
                  <p className="notice" role="status">
                    {t(
                      translationCurrent
                        ? "현재 한국어 편집본과 연결된 번역입니다."
                        : "한국어 편집본이 변경되었거나 번역이 없습니다. 번역을 갱신해주세요.",
                    )}
                  </p>
                  <button
                    className="btn btn-ghost"
                    disabled={busy || !state.text.trim()}
                    onClick={updateTranslation}
                  >
                    {t(busy ? "번역 중…" : "편집본 번역 갱신")}
                  </button>
                  {localizedDraft && (
                    <textarea
                      className="paper translation-paper"
                      aria-label={t("번역 문서")}
                      readOnly
                      lang={lang}
                      value={localizedDraft.text}
                    />
                  )}
                </section>
              )}
              <div className="action-row">
                <button
                  className="btn btn-ghost"
                  disabled={!state.text.trim()}
                  onClick={() => copy(false)}
                >
                  {t("한국어 복사")}
                </button>
                <button
                  className="btn btn-primary"
                  disabled={!state.text.trim()}
                  onClick={() => savePdf(state.text, r.title + "_문서")}
                >
                  <Icon name="download" />
                  {t("PDF 저장")}
                </button>
                {CLOUD_AI_ENABLED && lang !== "ko" && (
                  <>
                    <button
                      className="btn btn-ghost"
                      disabled={!translationCurrent || busy}
                      onClick={() => copy(true)}
                    >
                      {t("두 언어 복사")}
                    </button>
                    <button
                      className="btn btn-primary"
                      disabled={!translationCurrent || busy}
                      onClick={() =>
                        savePdf(exportText(true), r.title + "_" + lang)
                      }
                    >
                      {t("두 언어 PDF 저장")}
                    </button>
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="paper draft-placeholder">
              <Icon name="pen" />
              <h2>
                {t("당신의 상황을 담은")}
                <br />
                {t("한 장의 준비.")}
              </h2>
              <p>
                {t("문서 종류를 고르고 상황을 입력하면")}
                <br />
                {t("검토 결과를 바탕으로 초안을 만듭니다.")}
              </p>
              <div className="placeholder-lines">
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <p className="save-note">
            {t(
              "입력과 편집 내용은 현재 브라우저 탭에 임시 저장됩니다. 보관할 문서는 PDF로 저장하세요.",
            )}
          </p>
          <p className="inline-status" role="status">
            {t(notice)}
          </p>
        </section>
      </div>
    </>
  );
}
