import { language, useLanguage, t } from "../i18n/index.js";
import { CLOUD_AI_ENABLED } from "../config/features.js";
import useTranslatedReview from "../hooks/useTranslatedReview.js";
import { useEffect, useRef, useState } from "react";
import { api, href, params } from "../lib/index.js";
import useLoad from "../hooks/useLoad.js";
import useSession from "../hooks/useSession.js";
import { streamChat } from "../lib/streamChat.js";
import useTypewriter from "../hooks/useTypewriter.js";
import useChatTranslations from "../hooks/useChatTranslations.js";
import {
  ButtonLink,
  ErrorNotice,
  Evidence,
  Field,
  Icon,
  PageHead,
  PrivacyNote,
  Workflow,
} from "../components/UI.jsx";
const prompts = [
  ["explain", "쉽게 설명해줘"],
  ["scenario", "어떤 상황에서 불리해?"],
  ["rewrite", "어떻게 수정하면 좋을까?"],
  ["prepare", "상담 때 무엇을 준비할까?"],
];
export default function Chat({ result: r }) {
  const lang = useLanguage();
  const translated = useTranslatedReview(r);
  const findings = translated.result.review.findings;
  const initial = findings.some((f) => f.finding_id === params.get("finding"))
    ? params.get("finding")
    : findings[0]?.finding_id || "";
  const [findingId, setFindingId] = useState(initial);
  const [question, setQuestion] = useSession(
    `question:${r.analysis_id}:${r.analysis_revision}:${lang}`,
    "",
  );
  const [added, setAdded] = useState([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(null);
  const requestRef = useRef(null);
  const committed = useRef(null);
  const log = useRef(null);
  const followOutput = useRef(true);
  const busy = !!live;
  const typedText = useTypewriter(live?.text || "", live?.id);
  const phaseText =
    {
      preparing: "계약서와 질문을 살펴보고 있습니다.",
      generating: "답변을 작성하고 있습니다.",
      verifying: "원문과 근거를 확인하고 있습니다.",
      retrying: "근거에 맞게 답변을 다듬고 있습니다.",
      translating: "선택한 언어로 답변을 번역하고 있습니다.",
      typing: "답변을 표시하고 있습니다.",
    }[live?.phase] || "답변을 준비하고 있습니다.";
  const {
    data,
    error: loadError,
    loading,
  } = useLoad(
    `/api/analyses/${r.analysis_id}/chat?analysis_revision=${r.analysis_revision}`,
  );
  const end = useRef();
  const turns = [...(data?.turns || []), ...added];
  const localizedChat = useChatTranslations(r, turns, lang);
  const finding = findings.find((f) => f.finding_id === findingId);
  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    if (followOutput.current && log.current)
      log.current.scrollTop = log.current.scrollHeight;
  }, [typedText, live?.phase]);
  useEffect(() => {
    if (!live?.turn || typedText !== live.text || committed.current === live.id)
      return;
    committed.current = live.id;
    setAdded((old) => [...old, live.turn]);
    if (live.intent === "custom" && language() === live.language)
      setQuestion("");
    setLive(null);
  }, [live, typedText]);
  useEffect(() => {
    if (added.length)
      end.current?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
  }, [added.length]);
  async function ask(intent, text) {
    if (busy || loading || requestRef.current) return;
    const controller = new AbortController();
    requestRef.current = controller;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 210000);
    const snapshot = {
      id: crypto.randomUUID(),
      question: text,
      text: "",
      phase: "preparing",
      intent,
      language: lang,
      turn: null,
    };
    followOutput.current = true;
    setLive(snapshot);
    setError("");
    try {
      const result = await streamChat(
        `/api/analyses/${r.analysis_id}/chat/stream`,
        {
          analysis_revision: r.analysis_revision,
          finding_id: findingId || null,
          question: text,
          intent,
          language: lang,
          engine: CLOUD_AI_ENABLED ? "openai" : "ollama",
        },
        (event, data) => {
          if (event === "status")
            setLive((old) =>
              old?.id === snapshot.id ? { ...old, phase: data.phase } : old,
            );
          if (event === "delta" && typeof data.text === "string")
            setLive((old) =>
              old?.id === snapshot.id
                ? { ...old, text: old.text + data.text, phase: "typing" }
                : old,
            );
        },
        controller.signal,
      );
      setLive((old) =>
        old?.id === snapshot.id
          ? {
              ...old,
              text: result.turn.answer.text,
              turn: result.turn,
              phase: "typing",
            }
          : old,
      );
    } catch (e) {
      if (controller.signal.aborted && !timedOut) return;
      // A disconnect can occur after the server has saved the answer. Recover it
      // before offering retry so the same question is not accidentally sent twice.
      const history = await api(
        `/api/analyses/${r.analysis_id}/chat?analysis_revision=${r.analysis_revision}`,
      ).catch(() => null);
      const recovered =
        history?.turns.length === turns.length + 1 &&
        history.turns[turns.length];
      if (
        recovered &&
        recovered.question === text &&
        recovered.finding_id === (findingId || null)
      ) {
        setLive({
          ...snapshot,
          text: recovered.answer.text,
          turn: recovered,
          phase: "typing",
        });
      } else {
        setLive(null);
        setError(
          timedOut
            ? "답변 시간이 초과되었습니다. 질문을 유지했으니 다시 시도해주세요."
            : e.message,
        );
      }
    } finally {
      clearTimeout(timeout);
      requestRef.current = null;
    }
  }
  return (
    <>
      <PageHead
        eyebrow="02 / Understand your contract"
        title={t("어떤 조항이 궁금한가요?")}
        description={t(r.title)}
        action={
          <ButtonLink to={href("draft", r.analysis_id)} icon="pen">
            {t("문서 작성으로")}
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      <ErrorNotice message={translated.error} />
      <div className="chat-layout">
        <aside className="panel clause-sidebar">
          <p className="eyebrow">Focus on a clause</p>
          <Field label={t("질문할 범위")}>
            <select
              value={findingId}
              onChange={(e) => setFindingId(e.target.value)}
              disabled={busy}
            >
              <option value="">{t("계약서 전체")}</option>
              {findings.map((f) => (
                <option key={f.finding_id} value={f.finding_id}>
                  {t(f.title)}
                </option>
              ))}
            </select>
          </Field>
          {finding ? (
            <>
              <span className="badge">{t("선택한 주의 조항")}</span>
              <h2>{t(finding.title)}</h2>
              <Evidence id={r.analysis_id} evidence={finding.evidence} />
              <a
                className="text-link"
                href={href("sources", r.analysis_id, {
                  finding: findingId,
                })}
              >
                {t("관련 근거 보기")}
                <Icon />
              </a>
            </>
          ) : (
            <>
              <h2>{t("계약서 전체에 대해 질문합니다.")}</h2>
              <p className="muted">
                {t(
                  "긴 계약서는 주의 조항을 선택하면 해당 범위에 집중해 질문할 수 있습니다.",
                )}
              </p>
              <a className="text-link" href={href("original", r.analysis_id)}>
                {t("계약서 원문")}
                <Icon />
              </a>
            </>
          )}
        </aside>
        <section
          className="panel conversation-panel"
          aria-label={t("계약서 질문과 답변")}
        >
          <div className="conversation-heading">
            <div className="document-icon">
              <Icon name="chat" />
            </div>
            <div>
              <h2>{t("계약서 이해하기")}</h2>
              <p>{t("원문과 검토 결과를 바탕으로 답합니다.")}</p>
            </div>
            <span className="badge">
              {t("버전")}
              {r.analysis_revision}
            </span>
          </div>
          <ErrorNotice message={loadError} />
          <div
            ref={log}
            className="conversation-log"
            aria-live="polite"
            aria-busy={busy}
            aria-relevant="additions"
            role="log"
            onScroll={() => {
              const node = log.current;
              followOutput.current =
                node.scrollHeight - node.scrollTop - node.clientHeight < 80;
            }}
          >
            {!turns.length && !live && (
              <div className="chat-welcome">
                <span className="mini-brand">ON</span>
                <h3>{t("어려운 문구, 하나씩 짚어볼까요?")}</h3>
                <p>
                  {t(
                    finding
                      ? "아래 질문을 선택해 조항의 의미와 수정 방향을 확인하세요."
                      : "궁금한 내용을 입력하거나 왼쪽에서 주의 조항을 선택하세요.",
                  )}
                </p>
              </div>
            )}
            {localizedChat.turns.map((turn, i) => (
              <div className="chat-turn" key={i}>
                <div className="user-message">
                  <span>{t("나의 질문")}</span>
                  <p>{turn.question}</p>
                  {turn.question_ko && turn.language !== "ko" && (
                    <details>
                      <summary>{t("질문의 한국어 해석")}</summary>
                      <p lang="ko">{turn.question_ko}</p>
                    </details>
                  )}
                </div>
                <div className="assistant-message">
                  <span className="answer-label">
                    {t("권리ON")}
                    {t(" ")}
                    <span>
                      {t(
                        turn.answer.method === "ollama" ||
                          turn.answer.method === "openai"
                          ? "AI 답변"
                          : "조항 해설",
                      )}
                    </span>
                  </span>
                  {turn.translationPending && (
                    <p className="inline-status" role="status">
                      <span className="spinner" />
                      {t("선택한 언어로 답변을 번역하고 있습니다.")}
                    </p>
                  )}
                  {turn.translationError && (
                    <div className="notice" role="alert">
                      <p>{t(turn.translationError)}</p>
                      <button
                        className="text-link"
                        onClick={localizedChat.retry}
                      >
                        {t("번역 다시 시도")}
                      </button>
                    </div>
                  )}
                  {turn.answer.text && (
                    <p
                      lang={
                        turn.displayLanguage === "zh"
                          ? "zh-Hans"
                          : turn.displayLanguage || "ko"
                      }
                    >
                      {turn.answer.text}
                    </p>
                  )}
                  {turn.answer.text_ko && turn.displayLanguage !== "ko" && (
                    <details>
                      <summary>{t("한국어 답변")}</summary>
                      <p lang="ko">{turn.answer.text_ko}</p>
                    </details>
                  )}
                  {turn.answer.evidence?.length > 0 && (
                    <details>
                      <summary>{t("답변에 사용한 계약서 원문")}</summary>
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
                        turn.finding_id
                          ? {
                              finding: turn.finding_id,
                            }
                          : {},
                      )}
                    >
                      {t("참고 근거 확인")}
                      <Icon />
                    </a>
                  )}
                </div>
              </div>
            ))}
            {live && (
              <div className="chat-turn streaming-turn" aria-hidden="true">
                <div className="user-message">
                  <span>{t("나의 질문")}</span>
                  <p>{live.question}</p>
                </div>
                <div className="assistant-message">
                  <span className="answer-label">{t("권리ON")}</span>
                  {typedText ? (
                    <p
                      className="streaming-text"
                      lang={live.language === "zh" ? "zh-Hans" : live.language}
                    >
                      {typedText}
                      <span className="typing-caret" />
                    </p>
                  ) : (
                    <div className="typing-status">
                      <span className="typing-dots">
                        <i />
                        <i />
                        <i />
                      </span>
                      <span>{t(phaseText)}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            <div ref={end} />
          </div>
          <p className="visually-hidden" role="status">
            {busy ? t(phaseText) : ""}
          </p>
          <div className="composer">
            <div className="quick-prompts">
              {prompts.map(([intent, text]) => (
                <button
                  key={intent}
                  disabled={!finding || busy || loading || !!loadError}
                  onClick={() => ask(intent, t(text))}
                >
                  {t(text)}
                </button>
              ))}
            </div>
            <PrivacyNote />
            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask("custom", question.trim());
              }}
            >
              <Field label={t("직접 질문하기")}>
                <textarea
                  rows={3}
                  minLength={2}
                  maxLength={1500}
                  required
                  value={question}
                  disabled={busy}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={t("이 계약서에서 궁금한 내용을 적어주세요.")}
                />
              </Field>
              <div className="composer-bottom">
                <span className="small muted">
                  {t("한국어·중국어·스페인어로 질문할 수 있습니다.")}
                </span>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={
                    busy || loading || !!loadError || question.trim().length < 2
                  }
                >
                  {t("질문 보내기")}
                  <Icon />
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
