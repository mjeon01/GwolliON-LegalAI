import { useState } from "react";
import { t } from "../i18n/index.js";
import { href, params } from "../lib/index.js";
import AgentConversation from "../components/AgentConversation.jsx";
import LegacyChat from "./LegacyChat.jsx";
import { useAgentAvailable, useContractSession } from "../hooks/useAgent.js";
import useTranslatedReview from "../hooks/useTranslatedReview.js";
import {
  ButtonLink,
  ErrorNotice,
  Evidence,
  Field,
  Loading,
  PageHead,
  Workflow,
} from "../components/UI.jsx";

const suggestions = [
  "이 계약서에서 가장 먼저 확인할 조항은?",
  "보통 근로계약서와 비교해 빠진 내용이 있어?",
  "이 임금이 최저임금보다 적은지 계산해줘",
];

export default function Chat({ result: original }) {
  const available = useAgentAvailable();
  const session = useContractSession(original.analysis_id, available === true);
  const translated = useTranslatedReview(original);
  const findings = translated.result.review.findings;
  const [findingId, setFindingId] = useState(
    findings.some((f) => f.finding_id === params.get("finding")) ? params.get("finding") : "",
  );
  if (available === null) return <Loading />;
  if (!available) return <LegacyChat result={original} />;
  const finding = findings.find((f) => f.finding_id === findingId);
  return (
    <>
      <PageHead
        eyebrow="02 / Ask the assistant"
        title={t("어떤 조항이 궁금한가요?")}
        description={t(original.title)}
        action={
          <ButtonLink to={href("draft", original.analysis_id)} icon="pen">
            {t("문서 작성으로")}
          </ButtonLink>
        }
      />
      <Workflow result={original} />
      <ErrorNotice message={translated.error || session.error} />
      <div className="chat-layout">
        <aside className="panel clause-sidebar">
          <p className="eyebrow">Focus on a clause</p>
          <Field label={t("질문할 범위")}>
            <select value={findingId} onChange={(e) => setFindingId(e.target.value)}>
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
              <Evidence id={original.analysis_id} evidence={finding.evidence} />
            </>
          ) : (
            <p className="muted">
              {t("권리ON이 계약서를 읽고, 필요한 법령·판례·실제 계약서 사례를 직접 찾아 답합니다. 모르는 사실은 되묻습니다.")}
            </p>
          )}
        </aside>
        {session.id ? (
          <AgentConversation
            sessionId={session.id}
            analysisId={original.analysis_id}
            findingId={findingId}
            suggestions={suggestions}
            emptyTitle={t("어려운 문구, 하나씩 짚어볼까요?")}
            emptyText={t("궁금한 내용을 입력하거나 왼쪽에서 주의 조항을 선택하세요.")}
          />
        ) : (
          !session.error && <Loading />
        )}
      </div>
    </>
  );
}
