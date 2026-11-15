import { useState } from "react";
import { language, t } from "../i18n/index.js";
import { downloadPdf, post } from "../lib/index.js";
import useSession from "../hooks/useSession.js";
import {
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
  PrivacyNote,
} from "../components/UI.jsx";
import { DocumentView } from "./Draft.jsx";

// Finished filings without a contract. Each kind asks for everything its document needs (* = required).
const kinds = [
  [
    "labor_petition",
    "노동청 진정서",
    "임금체불·최저임금 미달 등을 고용노동부에 알립니다.",
  ],
  ["complaint", "고소장", "범죄로 의심되는 일을 경찰서에 고소합니다."],
  [
    "lawyer_request",
    "법률 상담 요청서",
    "변호사·법률구조공단에 상황을 정리해 상담을 요청합니다.",
  ],
  [
    "help_request",
    "도움 요청서",
    "기관이나 단체에 상황을 설명하고 도움을 요청합니다.",
  ],
];
const me = [
  ["name", "성명", "text", true],
  ["birth", "생년월일", "date"],
  ["address", "주소", "text", true],
  ["phone", "연락처", "tel", true],
];
const sections = {
  labor_petition: [
    ["진정인 (나)", me],
    [
      "사업주",
      [
        ["company", "사업장명", "text", true, "예: 행복편의점 망원점"],
        ["employer", "대표자(사업주) 성명", "text", true],
        ["company_address", "사업장 소재지", "text", true],
        ["company_phone", "사업장 연락처", "tel"],
        ["workers", "상시 근로자 수", "text", false, "예: 5명"],
      ],
    ],
    [
      "근무 내용",
      [
        ["start_date", "입사일", "date", true],
        ["end_date", "퇴사일 (재직 중이면 비워두세요)", "date"],
        ["job", "담당 업무", "text", true, "예: 계산 및 상품 진열"],
        [
          "wage_terms",
          "임금 조건",
          "text",
          false,
          "예: 시급 9,000원, 매월 10일 지급",
        ],
      ],
    ],
    [
      "받지 못한 돈과 있었던 일",
      [
        [
          "unpaid",
          "받지 못한 금품 (한 줄에 하나)",
          "area",
          true,
          "예: 10월 임금 1,200,000원\n9월 최저임금 차액 300,000원",
        ],
        [
          "facts",
          "있었던 일",
          "story",
          true,
          "예: 9월 1일부터 주 5일 하루 8시간 일했는데 시급 9천원만 받았고, 10월 월급은 달라고 해도 다음 달에 준다며 주지 않았습니다.",
        ],
        [
          "evidence",
          "입증 자료 (한 줄에 하나)",
          "area",
          false,
          "예: 통장 입금내역\n근무표 사진\n사업주와 주고받은 문자",
        ],
        ["request", "요청 사항", "area"],
        [
          "office",
          "제출할 노동청",
          "text",
          false,
          "예: 서울서부지방고용노동청장 (모르면 비워두세요)",
        ],
      ],
    ],
  ],
  complaint: [
    ["고소인 (나)", me],
    [
      "피고소인",
      [
        ["accused", "성명 (모르면 '성명불상')", "text", true],
        ["accused_address", "주소", "text"],
        ["accused_phone", "연락처", "tel"],
        [
          "relation",
          "나와의 관계",
          "text",
          false,
          "예: 고소인이 일한 편의점의 사업주",
        ],
      ],
    ],
    [
      "고소 내용",
      [
        [
          "charge",
          "죄명 (모르면 비워두세요)",
          "text",
          false,
          "예: 사기, 근로기준법 위반",
        ],
        [
          "facts",
          "있었던 일",
          "story",
          true,
          "언제, 어디서, 상대방이 무엇을 했는지 순서대로 적어주세요.",
        ],
        [
          "request",
          "고소 이유",
          "area",
          false,
          "처벌을 원하는 이유를 적어주세요.",
        ],
        [
          "evidence",
          "증거 자료 (한 줄에 하나)",
          "area",
          false,
          "예: 이체 내역\n대화 캡처",
        ],
        [
          "office",
          "제출할 경찰서",
          "text",
          false,
          "예: 서울마포경찰서장 (모르면 비워두세요)",
        ],
      ],
    ],
  ],
  lawyer_request: [
    [
      "보내는 사람 (나)",
      [
        ["name", "성명", "text", true],
        ["phone", "연락처", "tel", true],
        ["email", "이메일", "email"],
      ],
    ],
    [
      "상담 내용",
      [
        [
          "recipient",
          "받는 분",
          "text",
          true,
          "예: 대한법률구조공단 서울중앙지부",
        ],
        ["facts", "있었던 일", "story", true],
        ["unpaid", "피해 내용 (한 줄에 하나)", "area"],
        ["questions", "여쭙고 싶은 점 (한 줄에 하나)", "area"],
        ["evidence", "보유 자료 (한 줄에 하나)", "area"],
      ],
    ],
  ],
  help_request: [
    [
      "보내는 사람 (나)",
      [
        ["name", "성명", "text", true],
        ["phone", "연락처", "tel", true],
        ["email", "이메일", "email"],
      ],
    ],
    [
      "요청 내용",
      [
        ["recipient", "받는 분", "text", true, "예: 외국인력상담센터"],
        ["facts", "있었던 일", "story", true],
        ["unpaid", "피해 내용 (한 줄에 하나)", "area"],
        ["questions", "요청하는 도움 (한 줄에 하나)", "area"],
        ["evidence", "보유 자료 (한 줄에 하나)", "area"],
      ],
    ],
  ],
};
const today = () => {
  const now = new Date();
  return new Date(now - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
};

export default function StandaloneDraft() {
  const [state, setState] = useSession("filing", {
    kind: "labor_petition",
    fields: { written_on: today() },
    text: "",
    title: "",
    note: "",
    view: "preview",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const setField = (key, value) =>
    setState((old) => ({ ...old, fields: { ...old.fields, [key]: value } }));

  async function generate(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const wanted = new Set([
        "written_on",
        ...sections[state.kind].flatMap(([, list]) => list.map(([key]) => key)),
      ]);
      const fields = Object.fromEntries(
        Object.entries(state.fields).filter(
          ([key, value]) => wanted.has(key) && value,
        ),
      );
      const data = await post("/api/filings", {
        kind: state.kind,
        language: language(),
        fields,
      });
      setState((old) => ({
        ...old,
        text: data.text,
        title: data.title,
        note: data.note,
        view: "preview",
      }));
      setNotice(t("문서를 완성했습니다. 내용을 확인한 뒤 PDF로 저장하세요."));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(state.text);
      setNotice(t("문서를 복사했습니다."));
    } catch {
      setNotice(
        t(
          "복사하지 못했습니다. 문서 내용을 선택해 복사하거나 PDF로 저장해주세요.",
        ),
      );
    }
  }

  return (
    <>
      <PageHead
        eyebrow="03 / Prepare your next step"
        title={t("계약서 없이 문서 만들기")}
        description={t(
          "필요한 내용을 채우면 바로 제출할 수 있는 진정서·고소장을 한국어로 완성합니다.",
        )}
        action={
          <ButtonLink to="/upload/" icon="file">
            {t("계약서가 있다면 먼저 검토하기")}
          </ButtonLink>
        }
      />
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
                    <strong>{t(title)}</strong>
                    <small>{t(description)}</small>
                  </span>
                </label>
              ))}
            </div>
            <p className="small muted">
              {t(
                "* 표시는 꼭 필요한 항목입니다. 나머지는 아는 것만 적어주세요.",
              )}
            </p>
            {sections[state.kind].map(([heading, list]) => (
              <section className="filing-section" key={heading}>
                <h3 className="subheading">{t(heading)}</h3>
                <div className="form-grid">
                  {list.map(([key, label, type, required, hint]) => {
                    const props = {
                      value: state.fields[key] || "",
                      required: !!required,
                      maxLength: type === "story" ? 6000 : 1000,
                      placeholder: hint ? t(hint) : undefined,
                      onChange: (e) => setField(key, e.target.value),
                    };
                    return (
                      <Field
                        key={key}
                        label={t(label) + (required ? " *" : "")}
                      >
                        {type === "story" || type === "area" ? (
                          <textarea
                            rows={type === "story" ? 6 : 3}
                            {...props}
                          />
                        ) : (
                          <input type={type} {...props} />
                        )}
                      </Field>
                    );
                  })}
                </div>
              </section>
            ))}
            <Field label={t("작성일")}>
              <input
                type="date"
                value={state.fields.written_on || ""}
                onChange={(e) => setField("written_on", e.target.value)}
              />
            </Field>
            {language() !== "ko" && <PrivacyNote />}
          </fieldset>
          <ErrorNotice message={error} />
          <button className="btn btn-primary full-width" disabled={busy}>
            {t(
              busy
                ? "문서를 작성하고 있습니다…"
                : state.text
                  ? "입력 내용으로 다시 만들기"
                  : "문서 완성하기",
            )}{" "}
            <Icon name="pen" />
          </button>
        </form>
        <section className="draft-preview" aria-label={t("완성 문서")}>
          <div className="preview-toolbar">
            <span className="eyebrow">Your document</span>
          </div>
          {state.text ? (
            <>
              {state.note && <p className="notice">{t(state.note)}</p>}
              <div className="doc-switch document-switch">
                {[
                  ["preview", "미리보기"],
                  ["edit", "직접 수정"],
                ].map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={state.view === value}
                    onClick={() => setState((old) => ({ ...old, view: value }))}
                  >
                    {t(label)}
                  </button>
                ))}
              </div>
              {state.view === "edit" ? (
                <textarea
                  className="paper draft-paper"
                  aria-label={t("완성 문서")}
                  value={state.text}
                  lang="ko"
                  maxLength={50000}
                  onChange={(e) =>
                    setState((old) => ({ ...old, text: e.target.value }))
                  }
                />
              ) : (
                <DocumentView text={state.text} onBlank={() => {}} />
              )}
              <div className="action-row">
                <button className="btn btn-ghost" onClick={copy}>
                  {t("한국어 복사")}
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() =>
                    downloadPdf(state.text, state.title || "문서").catch((e) =>
                      setError(e.message),
                    )
                  }
                >
                  <Icon name="download" />
                  {t("PDF 저장")}
                </button>
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
                {t(
                  "문서 종류를 고르고 내용을 채우면 제출용 문서를 완성합니다.",
                )}
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
            {notice}
          </p>
        </section>
      </div>
    </>
  );
}
