import { useState } from "react";
import { download, href, post, useSession } from "../lib.js";
import {
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
  Workflow,
} from "../components/UI.jsx";

const kinds = [
  [
    "lawyer_request",
    "상담 요청문",
    "주의 조항과 내 상황을 정리해 상담을 준비합니다.",
  ],
  ["summary", "검토 요약", "계약 조건과 확인할 쟁점을 한 문서로 모읍니다."],
  ["request", "사실확인 요청문", "모호한 계약조건을 상대방에게 확인합니다."],
];
const fields = [
  ["writer", "내 이름", 200],
  ["counterparty", "상대방", 200],
  ["date", "일이 있었던 날짜", 100],
  ["place", "관련 장소", 300],
  ["summary", "실제로 있었던 일", 8000],
  ["loss", "발생한 손해 또는 미지급 금액", 500],
  ["evidence", "가지고 있는 증거·자료", 2000],
  ["desired_outcome", "원하는 해결 방향", 1000],
];
export default function Draft({ result: r }) {
  const key = `draft:${r.analysis_id}:${r.analysis_revision}`;
  const [state, setState] = useSession(key, {
    kind: "lawyer_request",
    incident: {},
    text: "",
    generated: false,
    missing: [],
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function generate(event) {
    event.preventDefault();
    if (
      state.generated &&
      !window.confirm(
        "새 초안을 만들면 현재 편집한 문서가 바뀝니다. 다시 만들까요?",
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
        incident: state.kind === "lawyer_request" ? state.incident : {},
      });
      setState((old) => ({
        ...old,
        text: data.draft_text,
        generated: true,
        generatedKind: state.kind,
        missing: data.missing_fields || [],
      }));
      setNotice(
        "초안을 만들었습니다. 내용을 확인하고 직접 수정할 수 있습니다.",
      );
      requestAnimationFrame(() =>
        document.getElementById("draft-editor")?.focus(),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(state.text);
      setNotice("문서를 복사했습니다.");
    } catch {
      setNotice(
        "복사하지 못했습니다. 문서 내용을 선택해 복사하거나 TXT로 저장해주세요.",
      );
    }
  }
  return (
    <>
      <PageHead
        eyebrow="03 / Prepare your next step"
        title="전할 내용을 명확하게."
        description={r.title}
        action={
          <ButtonLink to={href("review", r.analysis_id)} icon="back">
            검토 결과
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      <div className="draft-layout">
        <form className="panel draft-form" onSubmit={generate}>
          <fieldset disabled={busy}>
            <div className="section-heading">
              <h2>어떤 문서가 필요한가요?</h2>
            </div>
            <div className="document-types">
              {kinds.map(([value, title, description]) => (
                <label
                  key={value}
                  className={`document-type ${state.kind === value ? "selected" : ""}`}
                >
                  <input
                    type="radio"
                    name="kind"
                    value={value}
                    checked={state.kind === value}
                    onChange={() =>
                      setState((old) => ({ ...old, kind: value }))
                    }
                  />
                  <span>
                    <strong>{title}</strong>
                    <small>{description}</small>
                  </span>
                </label>
              ))}
            </div>
            {state.kind === "lawyer_request" ? (
              <>
                <h3 className="subheading">내 상황을 더해주세요</h3>
                <p className="small muted">
                  아는 내용만 적어주세요. 비워둔 내용은 초안에서 확인할 수
                  있습니다.
                </p>
                {fields.map(([name, label, max]) => (
                  <Field key={name} label={label}>
                    {["summary", "evidence", "desired_outcome"].includes(
                      name,
                    ) ? (
                      <textarea
                        rows={name === "summary" ? 5 : 3}
                        maxLength={max}
                        value={state.incident[name] || ""}
                        onChange={(e) =>
                          setState((old) => ({
                            ...old,
                            incident: {
                              ...old.incident,
                              [name]: e.target.value,
                            },
                          }))
                        }
                      />
                    ) : (
                      <input
                        maxLength={max}
                        value={state.incident[name] || ""}
                        onChange={(e) =>
                          setState((old) => ({
                            ...old,
                            incident: {
                              ...old.incident,
                              [name]: e.target.value,
                            },
                          }))
                        }
                      />
                    )}
                  </Field>
                ))}
              </>
            ) : (
              <p className="small muted subheading">
                검토한 계약조건과 확인할 쟁점으로 문서를 만듭니다. 이름·날짜와
                추가 설명은 생성한 초안에서 직접 편집하세요.
              </p>
            )}
          </fieldset>
          <ErrorNotice message={error} />
          <button className="btn btn-primary full-width" disabled={busy}>
            {busy
              ? "초안을 만드는 중…"
              : state.generated
                ? "입력 내용으로 다시 만들기"
                : "문서 초안 만들기"}{" "}
            <Icon name="pen" />
          </button>
        </form>
        <section className="draft-preview" aria-label="문서 초안 편집">
          <div className="preview-toolbar">
            <span className="eyebrow">Your document</span>
            <span className="small muted">
              검토 버전 {r.analysis_revision} 기준
            </span>
          </div>
          {state.generated &&
            state.generatedKind &&
            state.generatedKind !== state.kind && (
              <div className="notice">
                아래는 이전에 생성한 초안입니다. 선택한 문서로 바꾸려면 다시
                만들기를 눌러주세요.
              </div>
            )}
          {state.generated ? (
            <>
              <div className="notice">
                <Icon name="pen" />
                <p>
                  제출 전 이름·날짜·금액과 실제 사실을 확인하세요. 아래 초안을
                  직접 수정할 수 있습니다.
                </p>
              </div>
              {state.missing.length > 0 && (
                <details className="missing-fields">
                  <summary>
                    작성 시 확인할 정보 {state.missing.length}개
                  </summary>
                  <ul>
                    {state.missing.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </details>
              )}
              <label className="visually-hidden" htmlFor="draft-editor">
                문서 초안 편집
              </label>
              <textarea
                id="draft-editor"
                className="paper draft-paper"
                value={state.text}
                onChange={(e) =>
                  setState((old) => ({ ...old, text: e.target.value }))
                }
              />
              <div className="action-row">
                <button
                  className="btn btn-ghost"
                  disabled={!state.text.trim()}
                  onClick={copy}
                >
                  내용 복사
                </button>
                <button
                  className="btn btn-primary"
                  disabled={!state.text.trim()}
                  onClick={() => download(state.text, r.title + "_상담문서")}
                >
                  <Icon name="download" /> TXT로 저장
                </button>
              </div>
            </>
          ) : (
            <div className="paper draft-placeholder">
              <Icon name="pen" />
              <h2>
                당신의 상황을 담은
                <br />한 장의 준비.
              </h2>
              <p>
                문서 종류를 고르고 상황을 입력하면
                <br />
                검토 결과를 바탕으로 초안을 만듭니다.
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
            입력과 편집 내용은 현재 브라우저 탭에 임시 저장됩니다. 보관할 문서는
            TXT로 저장하세요.
          </p>
          <p className="inline-status" role="status">
            {notice}
          </p>
        </section>
      </div>
    </>
  );
}
