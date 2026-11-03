import { useEffect, useRef, useState } from "react";
import { href, params, post, useLoad, useSession } from "../lib.js";
import {
  ButtonLink,
  ErrorNotice,
  Evidence,
  Field,
  Icon,
  PageHead,
  Workflow,
} from "../components/UI.jsx";

const prompts = [
  ["explain", "쉽게 설명해줘"],
  ["scenario", "어떤 상황에서 불리해?"],
  ["rewrite", "어떻게 수정하면 좋을까?"],
  ["prepare", "상담 때 무엇을 준비할까?"],
];
export default function Chat({ result: r }) {
  const findings = r.review.findings;
  const initial = findings.some((f) => f.finding_id === params.get("finding"))
    ? params.get("finding")
    : findings[0]?.finding_id || "";
  const [findingId, setFindingId] = useState(initial);
  const [question, setQuestion] = useSession(
    `question:${r.analysis_id}:${r.analysis_revision}`,
    "",
  );
  const [added, setAdded] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const {
    data,
    error: loadError,
    loading,
  } = useLoad(
    `/api/analyses/${r.analysis_id}/chat?analysis_revision=${r.analysis_revision}`,
  );
  const end = useRef();
  const turns = [...(data?.turns || []), ...added];
  const finding = findings.find((f) => f.finding_id === findingId);
  useEffect(() => {
    if (added.length)
      end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [added.length]);
  async function ask(intent, text) {
    if (busy || loading) return;
    setBusy(true);
    setError("");
    try {
      const result = await post(`/api/analyses/${r.analysis_id}/chat`, {
        analysis_revision: r.analysis_revision,
        finding_id: findingId || null,
        question: text,
        intent,
      });
      setAdded((old) => [...old, result.turn]);
      if (intent === "custom") setQuestion("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead
        eyebrow="02 / Understand your contract"
        title="어떤 조항이 궁금한가요?"
        description={r.title}
        action={
          <ButtonLink to={href("draft", r.analysis_id)} icon="pen">
            문서 작성으로
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      <div className="chat-layout">
        <aside className="panel clause-sidebar">
          <p className="eyebrow">Focus on a clause</p>
          <Field label="질문할 범위">
            <select
              value={findingId}
              onChange={(e) => setFindingId(e.target.value)}
              disabled={busy}
            >
              <option value="">계약서 전체</option>
              {findings.map((f) => (
                <option key={f.finding_id} value={f.finding_id}>
                  {f.title}
                </option>
              ))}
            </select>
          </Field>
          {finding ? (
            <>
              <span className="badge">선택한 주의 조항</span>
              <h2>{finding.title}</h2>
              <Evidence id={r.analysis_id} evidence={finding.evidence} />
              <a
                className="text-link"
                href={href("sources", r.analysis_id, { finding: findingId })}
              >
                관련 근거 보기 <Icon />
              </a>
            </>
          ) : (
            <>
              <h2>계약서 전체에 대해 질문합니다.</h2>
              <p className="muted">
                긴 계약서는 주의 조항을 선택하면 해당 범위에 집중해 질문할 수
                있습니다.
              </p>
              <a className="text-link" href={href("original", r.analysis_id)}>
                계약서 원문 <Icon />
              </a>
            </>
          )}
        </aside>
        <section
          className="panel conversation-panel"
          aria-label="계약서 질문과 답변"
        >
          <div className="conversation-heading">
            <div className="document-icon">
              <Icon name="chat" />
            </div>
            <div>
              <h2>계약서 이해하기</h2>
              <p>원문과 검토 결과를 바탕으로 답합니다.</p>
            </div>
            <span className="badge">버전 {r.analysis_revision}</span>
          </div>
          <ErrorNotice message={loadError} />
          <div
            className="conversation-log"
            aria-live="polite"
            aria-relevant="additions"
            role="log"
          >
            {!turns.length && (
              <div className="chat-welcome">
                <span className="mini-brand">ON</span>
                <h3>어려운 문구, 하나씩 짚어볼까요?</h3>
                <p>
                  {finding
                    ? "아래 질문을 선택해 조항의 의미와 수정 방향을 확인하세요."
                    : "궁금한 내용을 입력하거나 왼쪽에서 주의 조항을 선택하세요."}
                </p>
              </div>
            )}
            {turns.map((turn, i) => (
              <div className="chat-turn" key={i}>
                <div className="user-message">
                  <span>나의 질문</span>
                  <p>{turn.question}</p>
                </div>
                <div className="assistant-message">
                  <span className="answer-label">
                    권리ON{" "}
                    <span>
                      {turn.answer.method === "ollama"
                        ? "로컬 AI 답변"
                        : "조항 해설"}
                    </span>
                  </span>
                  <p>{turn.answer.text}</p>
                  {turn.answer.evidence?.length > 0 && (
                    <details>
                      <summary>답변에 사용한 계약서 원문</summary>
                      <Evidence
                        id={r.analysis_id}
                        evidence={turn.answer.evidence}
                      />
                    </details>
                  )}
                  {turn.answer.source_ids?.length > 0 && (
                    <a
                      className="text-link"
                      href={href(
                        "sources",
                        r.analysis_id,
                        turn.finding_id ? { finding: turn.finding_id } : {},
                      )}
                    >
                      참고 근거 확인 <Icon />
                    </a>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <p className="inline-status" role="status">
                <span className="spinner" />
                답변을 준비하고 있습니다.
              </p>
            )}
            <div ref={end} />
          </div>
          <div className="composer">
            <div className="quick-prompts">
              {prompts.map(([intent, text]) => (
                <button
                  key={intent}
                  disabled={!finding || busy || loading || !!loadError}
                  onClick={() => ask(intent, text)}
                >
                  {text}
                </button>
              ))}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask("custom", question.trim());
              }}
            >
              <Field label="직접 질문하기">
                <textarea
                  rows={3}
                  minLength={2}
                  maxLength={1500}
                  required
                  value={question}
                  disabled={busy}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="이 계약서에서 궁금한 내용을 적어주세요."
                />
              </Field>
              <div className="composer-bottom">
                <span className="small muted">
                  자유 질문은 이 컴퓨터의 Ollama 모델을 사용합니다.
                </span>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={
                    busy || loading || !!loadError || question.trim().length < 2
                  }
                >
                  질문 보내기 <Icon />
                </button>
              </div>
            </form>
            <ErrorNotice message={error} />
          </div>
        </section>
      </div>
    </>
  );
}
