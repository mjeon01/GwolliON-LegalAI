import { useEffect, useRef, useState } from "react";
import { language, t, useLanguage } from "../i18n/index.js";
import { api, downloadPdf, href } from "../lib/index.js";
import { streamChat } from "../lib/streamChat.js";
import useSession from "../hooks/useSession.js";
import { ErrorNotice, Evidence, Field, Icon } from "./UI.jsx";

const phases = {
  preparing: "질문을 살펴보고 있습니다.",
  thinking: "필요한 자료를 판단하고 있습니다.",
  verifying: "인용과 근거를 원문과 대조하고 있습니다.",
  revising: "검증 결과에 맞게 답변을 고치고 있습니다.",
};
const factLabels = {
  hourly_wage: "시급",
  monthly_wage: "월급",
  weekly_hours: "주당 근무시간",
  daily_hours: "하루 근무시간",
  start_date: "근무 시작일",
  event_date: "기준 날짜",
  workplace_size: "상시 근로자 수",
  workplace: "근무 장소",
  job: "담당 업무",
  employer_name: "사업주",
  worker_name: "성명",
  contract_received: "계약서 수령 여부",
  days_off: "휴일",
};
const kindLabels = {
  law: "법령",
  precedent_reference: "판결문 (AI Hub)",
  interpretation_reference: "해석례 (AI Hub)",
  decision_reference: "결정례 (AI Hub)",
  qa_example: "법률 질의응답 (AI Hub)",
  summary_example: "판결 요약 (AI Hub)",
  contract: "실제 계약서 문구 (AI Hub)",
};

const reducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Reveal a verified answer as if typed: about 3 seconds per answer, faster for long ones. */
function useTypewriter(text, enabled, onTick) {
  const [count, setCount] = useState(
    enabled && !reducedMotion() ? 0 : text.length,
  );
  useEffect(() => {
    if (count >= text.length) return;
    const step = Math.max(1, Math.ceil(text.length / 180));
    const timer = setTimeout(() => {
      setCount((n) => Math.min(text.length, n + step));
      onTick?.();
    }, 16);
    return () => clearTimeout(timer);
  }, [count, text]);
  return [
    text.slice(0, count),
    count < text.length,
    () => setCount(text.length),
  ];
}

function inline(text) {
  // Only **bold** is rendered; everything else stays plain text (React escapes it).
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, i) =>
      /^\*\*[^*]+\*\*$/.test(part) ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        part.replace(/\*\*/g, "")
      ),
    );
}

/** The answer's light layout: a bold lead, "- " bullets, "1. " steps; works on partially typed text. */
export function AnswerBody({ text }) {
  const blocks = [];
  for (const line of text.split("\n")) {
    const bullet = line.match(/^\s*[-•·]\s+(.*)/);
    const step = line.match(/^\s*\d+[.)]\s+(.*)/);
    const kind = bullet ? "ul" : step ? "ol" : line.trim() ? "p" : null;
    const body = bullet?.[1] ?? step?.[1] ?? line.trim();
    const last = blocks[blocks.length - 1];
    if (!kind) blocks.push({ kind: "gap" });
    else if (last?.kind === kind && kind !== "p") last.items.push(body);
    else blocks.push({ kind, items: [body] });
  }
  return blocks.map((block, i) =>
    block.kind === "gap" ? null : block.kind === "p" ? (
      <p key={i}>{inline(block.items[0])}</p>
    ) : (
      <block.kind key={i}>
        {block.items.map((item, j) => (
          <li key={j}>{inline(item)}</li>
        ))}
      </block.kind>
    ),
  );
}

export default function AgentConversation({
  sessionId,
  analysisId = null,
  findingId = null,
  suggestions = [],
  emptyTitle,
  emptyText,
}) {
  const lang = useLanguage();
  const [session, setSession] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [live, setLive] = useState(null);
  const [fresh, setFresh] = useState(-1);
  const [error, setError] = useState("");
  const [draft, setDraft] = useSession(`agent:${sessionId}:${lang}`, "");
  const request = useRef(null);
  const log = useRef(null);
  const busy = !!live;
  const path = `/api/agent/sessions/${sessionId}`;

  useEffect(() => {
    api(path)
      .then(setSession)
      .catch((e) => setLoadError(e.message));
    return () => request.current?.abort();
  }, [path]);
  const follow = () => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  };
  useEffect(follow, [session?.turns.length, live?.steps.length, live?.phase]);

  async function send(text) {
    const message = text.trim();
    if (!message || busy || !session) return;
    const controller = new AbortController();
    request.current = controller;
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 240000);
    const before = session.turns.length;
    setLive({ question: message, steps: [], phase: "preparing" });
    setError("");
    try {
      const data = await streamChat(
        `${path}/messages`,
        { message, language: language(), finding_id: findingId || null },
        (event, payload) =>
          setLive((old) =>
            !old
              ? old
              : event === "step"
                ? { ...old, steps: [...old.steps, payload.label] }
                : event === "status"
                  ? { ...old, phase: payload.phase }
                  : old,
          ),
        controller.signal,
      );
      setFresh(before);
      setSession((old) => ({
        ...old,
        turns: [...old.turns, data.turn],
        facts: data.facts,
      }));
      if (message === draft.trim()) setDraft("");
    } catch (e) {
      if (controller.signal.aborted && !timedOut) return;
      // The server may have saved the answer before the connection dropped.
      const fresh = await api(path).catch(() => null);
      if (fresh && fresh.turns.length === before + 1) {
        setSession(fresh);
        if (message === draft.trim()) setDraft("");
      } else
        setError(
          timedOut
            ? t(
                "답변 시간이 초과되었습니다. 질문을 유지했으니 다시 시도해주세요.",
              )
            : e.message,
        );
    } finally {
      clearTimeout(timer);
      request.current = null;
      setLive(null);
    }
  }

  async function forget(key) {
    try {
      const data = await api(`${path}/facts/${encodeURIComponent(key)}`, {
        method: "DELETE",
      });
      setSession((old) => ({ ...old, facts: data.facts }));
    } catch (e) {
      setError(e.message);
    }
  }

  if (loadError) return <ErrorNotice message={loadError} />;
  if (!session)
    return (
      <p className="inline-status" role="status">
        <span className="spinner" />
        {t("대화를 불러오고 있습니다.")}
      </p>
    );
  const facts = Object.entries(session.facts || {});
  const last = session.turns[session.turns.length - 1];
  return (
    <div className="agent-layout">
      <section
        className="panel conversation-panel"
        aria-label={t("계약서 질문과 답변")}
      >
        <div
          ref={log}
          className="conversation-log"
          role="log"
          aria-live="polite"
          aria-busy={busy}
        >
          {!session.turns.length && !live && (
            <div className="chat-welcome">
              <span className="mini-brand">ON</span>
              <h3>{emptyTitle}</h3>
              <p>{emptyText}</p>
            </div>
          )}
          {session.turns.map((turn, i) => (
            <Turn
              key={i}
              turn={turn}
              analysisId={analysisId}
              latest={turn === last && !busy}
              typing={i === fresh}
              onTick={follow}
              onAnswer={send}
            />
          ))}
          {live && (
            <div className="chat-turn">
              <div className="user-message">
                <span>{t("나의 질문")}</span>
                <p>{live.question}</p>
              </div>
              <div className="assistant-message">
                <span className="answer-label">{t("권리ON")}</span>
                <ol className="agent-steps live">
                  {live.steps.map((label, i) => (
                    <li key={i}>{t(label)}</li>
                  ))}
                </ol>
                <div className="typing-status">
                  <span className="typing-dots">
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>{t(phases[live.phase] || phases.thinking)}</span>
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="composer">
          {!session.turns.length && suggestions.length > 0 && (
            <div className="quick-prompts">
              {suggestions.map((text) => (
                <button
                  key={text}
                  disabled={busy}
                  onClick={() => send(t(text))}
                >
                  {t(text)}
                </button>
              ))}
            </div>
          )}
          <p className="privacy-note">
            {t(
              "이미지·텍스트가 OpenAI로 전송됩니다. 응답 저장은 끄지만 완전한 무보관은 아닙니다.",
            )}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
          >
            <Field label={t("직접 질문하기")}>
              <textarea
                rows={3}
                maxLength={2000}
                value={draft}
                disabled={busy}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={t("궁금한 점이나 상황을 편하게 적어주세요.")}
              />
            </Field>
            <div className="composer-bottom">
              <span className="small muted">
                {t("한국어·중국어·스페인어로 질문할 수 있습니다.")}
              </span>
              <button
                className="btn btn-primary btn-sm"
                disabled={busy || !draft.trim()}
              >
                {t("질문 보내기")}
                <Icon />
              </button>
            </div>
          </form>
          <ErrorNotice message={error} />
        </div>
      </section>
      <aside className="panel facts-panel" aria-label={t("기록한 사실")}>
        <p className="eyebrow">Facts you told us</p>
        <h2>{t("기록한 사실")}</h2>
        <p className="small muted">
          {t(
            "대화에서 직접 말씀하신 내용만 기록합니다. 틀린 내용은 지워주세요.",
          )}
        </p>
        {facts.length ? (
          <ul className="fact-list">
            {facts.map(([key, fact]) => (
              <li key={key}>
                <strong>{t(factLabels[key] || key)}</strong>
                <span>{fact.value}</span>
                <button
                  className="text-link"
                  disabled={busy}
                  onClick={() => forget(key)}
                  aria-label={t("{0} 지우기", t(factLabels[key] || key))}
                >
                  {t("지우기")}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small">{t("아직 기록한 사실이 없습니다.")}</p>
        )}
      </aside>
    </div>
  );
}

function Turn({ turn, analysisId, latest, typing, onTick, onAnswer }) {
  const { answer } = turn;
  const [saving, setSaving] = useState("");
  const [typed, writing, finish] = useTypewriter(answer.text, typing, onTick);
  const shown = turn.language || "ko";
  return (
    <div className="chat-turn">
      <div className="user-message">
        <span>{t("나의 질문")}</span>
        <p>{turn.question}</p>
      </div>
      <div className="assistant-message">
        <span className="answer-label">
          {t("권리ON")} <span>{t("AI 답변")}</span>
        </span>
        {turn.steps?.length > 0 && (
          <details className="agent-steps">
            <summary>{t("확인한 과정 {0}단계", turn.steps.length)}</summary>
            <ol>
              {turn.steps.map((step, i) => (
                <li key={i} className={step.ok ? "" : "muted"}>
                  {t(step.label)}
                </li>
              ))}
            </ol>
          </details>
        )}
        {answer.warnings?.length > 0 && (
          <div className="notice" role="note">
            {answer.warnings.map((w) => (
              <p key={w}>{t(w)}</p>
            ))}
          </div>
        )}
        <div
          className="answer-text answer-body"
          lang={shown === "zh" ? "zh-Hans" : shown}
          onClick={writing ? finish : undefined}
        >
          {writing ? (
            <>
              <div aria-hidden="true" className="answer-typing">
                <AnswerBody text={typed} />
                <span className="typing-caret" />
              </div>
              <div className="visually-hidden">{answer.text}</div>
            </>
          ) : (
            <AnswerBody text={answer.text} />
          )}
        </div>
        {!writing && (
          <>
            {shown !== "ko" && (
              <details>
                <summary>{t("한국어 답변")}</summary>
                <div lang="ko" className="answer-body">
                  <AnswerBody text={answer.text_ko} />
                </div>
              </details>
            )}
            {answer.ask?.question && (
              <div className="agent-ask">
                <p>
                  <strong>{answer.ask.question}</strong>
                </p>
                {latest &&
                  answer.ask.options.map((option) => (
                    <button
                      key={option}
                      className="btn btn-sm"
                      onClick={() => onAnswer(option)}
                    >
                      {option}
                    </button>
                  ))}
              </div>
            )}
            {turn.document && (
              <div className="agent-document">
                <h3>{t(turn.document.title)}</h3>
                {turn.document.blanks.length > 0 && (
                  <p className="small muted">
                    {t(
                      "빈칸을 채운 뒤 사용하세요: {0}",
                      turn.document.blanks.join(", "),
                    )}
                  </p>
                )}
                <pre lang="ko">{turn.document.text}</pre>
                <div className="button-row">
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={!!saving}
                    onClick={async () => {
                      setSaving("pdf");
                      await downloadPdf(
                        turn.document.text,
                        turn.document.title,
                      ).catch(() => {});
                      setSaving("");
                    }}
                  >
                    {t("PDF로 저장")}
                  </button>
                  <button
                    className="btn btn-sm"
                    onClick={() =>
                      navigator.clipboard?.writeText(turn.document.text)
                    }
                  >
                    {t("복사")}
                  </button>
                </div>
              </div>
            )}
            {answer.evidence?.length > 0 && analysisId && (
              <details>
                <summary>{t("답변에 사용한 계약서 원문")}</summary>
                <Evidence id={analysisId} evidence={answer.evidence} />
              </details>
            )}
            {answer.citations?.length > 0 && (
              <details>
                <summary>
                  {t("확인된 인용 {0}건", answer.citations.length)}
                </summary>
                {answer.citations.map((c, i) => (
                  <blockquote className="evidence" key={i} lang="ko">
                    <span className="badge">
                      {t(kindLabels[c.dataset_kind || c.kind] || "참고 자료")}
                    </span>
                    <strong>{c.title}</strong>
                    <p>“{c.quote}”</p>
                    {c.kind === "dataset" && (
                      <p className="small muted">
                        {t(
                          "현재 계약의 사실관계·판단 결과를 뜻하지 않는 참고 자료입니다.",
                        )}
                      </p>
                    )}
                  </blockquote>
                ))}
              </details>
            )}
            {latest && answer.next_action === "upload_contract" && (
              <a className="text-link" href="/upload/">
                {t("계약서 사진·파일 올리기")}
                <Icon />
              </a>
            )}
            {latest &&
              answer.next_action === "draft_revision" &&
              analysisId && (
                <a className="text-link" href={href("draft", analysisId)}>
                  {t("수정 요청서 작성하기")}
                  <Icon />
                </a>
              )}
            {latest && answer.next_action === "consult" && (
              <p className="small muted">
                {t("무료 상담: 고용노동부 1350 · 대한법률구조공단 132")}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
