import { useState } from "react";
import { t } from "../i18n/index.js";
import { api, go, params, roles } from "../lib/index.js";
import AgentConversation from "../components/AgentConversation.jsx";
import { useAgentAvailable } from "../hooks/useAgent.js";
import { ButtonLink, Empty, ErrorNotice, Field, Icon, Loading, PageHead } from "../components/UI.jsx";

const suggestions = {
  employment: [
    "최저시급을 못 받았는데 괜찮은 건가요?",
    "주휴수당은 언제 받을 수 있나요?",
    "월급이 제날짜에 안 들어와요. 어떻게 해야 하나요?",
    "회사가 여권을 맡기라고 해요",
    "갑자기 그만두라고 하는데 어떻게 하나요?",
    "근로계약서를 아직 못 받았어요",
  ],
  lease: ["계약 전에 무엇을 확인해야 하나요?", "보증금을 돌려받지 못하고 있어요"],
  sale: ["계약 전에 무엇을 확인해야 하나요?"],
};
const types = [
  ["employment", "근로계약"],
  ["lease", "주택 임대차"],
  ["sale", "부동산 매매"],
];

// For people who cannot photograph the contract on the spot, or never received one.
export default function Interview() {
  const available = useAgentAvailable();
  const sessionId = params.get("session");
  const [type, setType] = useState(params.get("type") || "employment");
  const [role, setRole] = useState(roles[params.get("type") || "employment"][0][0]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (available === null) return <Loading />;
  if (!available)
    return (
      <Empty title={t("계약서 없이 상담하기는 AI 연결이 필요합니다.")} action={<ButtonLink to="/upload/">{t("계약서 등록")}</ButtonLink>}>
        {t("서버에 OpenAI 설정이 되어 있지 않습니다. 계약서 사진이나 파일을 등록하면 로컬 검토를 이용할 수 있습니다.")}
      </Empty>
    );
  async function start(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await api("/api/agent/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contract_type: type, user_role: role }),
      });
      go("interview", null, { session: data.session_id, type });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }
  if (sessionId)
    return (
      <>
        <PageHead
          eyebrow="No contract yet"
          title={t("계약서 없이 상담하기")}
          description={t("궁금한 점이나 말로 안내받은 조건을 적어주시면 정리하고, 확인할 점과 요청할 문서를 함께 준비합니다.")}
          action={<ButtonLink to="/upload/">{t("계약서가 생기면 등록하기")}</ButtonLink>}
        />
        <AgentConversation
          sessionId={sessionId}
          suggestions={suggestions[params.get("type")] || suggestions.employment}
          emptyTitle={t("어떤 상황인지 알려주세요.")}
          emptyText={t("궁금한 점을 묻거나, 사장님께 말로 들은 시급·근무시간·시작일을 그대로 적어주세요.")}
        />
      </>
    );
  return (
    <>
      <PageHead
        eyebrow="No contract yet"
        title={t("계약서가 없거나 지금 찍기 어려운가요?")}
        description={t("근로계약서는 받기 어렵거나 현장에서 촬영하기 곤란한 경우가 많습니다. 아래 방법 중 편한 것을 선택하세요.")}
      />
      <div className="option-grid">
        <div className="panel">
          <h2>{t("나중에 사진·파일로 올리기")}</h2>
          <p className="muted">
            {t("받은 사본, 메신저로 받은 사진이나 PDF, 갤러리 사진도 등록할 수 있습니다. 집에서 천천히 올려도 됩니다.")}
          </p>
          <ButtonLink to="/upload/">{t("사진·파일 올리기")}</ButtonLink>
        </div>
        <form className="panel" onSubmit={start}>
          <h2>{t("말로 안내받은 조건으로 상담하기")}</h2>
          <p className="muted">
            {t("계약서를 받지 못했다면 그 자체가 확인할 문제일 수 있습니다. 말로 안내받은 조건을 정리하고 교부 요청서를 준비합니다.")}
          </p>
          <Field label={t("계약 종류")}>
            <select
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setRole(roles[e.target.value][0][0]);
              }}
            >
              {types.map(([value, label]) => (
                <option key={value} value={value}>
                  {t(label)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("나의 입장")}>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {roles[type].map(([value, label]) => (
                <option key={value} value={value}>
                  {t(label)}
                </option>
              ))}
            </select>
          </Field>
          <ErrorNotice message={error} />
          <button className="btn btn-primary" disabled={busy}>
            {t("상담 시작")}
            <Icon />
          </button>
        </form>
      </div>
    </>
  );
}
