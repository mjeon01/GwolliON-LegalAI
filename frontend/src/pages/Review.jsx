import { t } from "../i18n/index.js";
import useTranslatedReview from "../hooks/useTranslatedReview.js";
import { useEffect, useState } from "react";
import { go, href, params, post } from "../lib/index.js";
import DocumentReview from "../components/DocumentReview.jsx";
import {
  Back,
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
  Workflow,
} from "../components/UI.jsx";
export default function Review({ result: original }) {
  const {
    result: r,
    translated,
    blocks,
    done,
    total,
    untranslated,
    bundled,
    busy,
    error,
    retry,
    lang,
  } = useTranslatedReview(original);
  const review = r.review;
  return (
    <>
      <PageHead
        eyebrow="01 / Review results"
        title={t(r.title)}
        description={t(
          "{0}의 입장에서 살펴본 계약서 · 검토 버전 {1}",
          review.role_label,
          r.analysis_revision,
        )}
        action={
          <ButtonLink to={href("original", r.analysis_id)} icon="file">
            {t("계약서 원문")}
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      {lang !== "ko" && (
        <div className="notice translation-status" role="status">
          <p>
            {busy
              ? total
                ? t("계약서와 설명을 번역하고 있습니다. ({0}/{1})", done, total)
                : t("번역을 준비하고 있습니다.")
              : translated
                ? t(
                    bundled
                      ? "샘플 계약서용으로 AI가 미리 만든 참고 번역입니다. 계약의 효력은 한국어 원문을 기준으로 확인하세요."
                      : "AI가 만든 참고 번역입니다. 계약의 효력은 한국어 원문을 기준으로 확인하세요.",
                  )
                : t("한국어 원문을 표시합니다. 번역을 다시 시도해주세요.")}
            {translated &&
              untranslated > 0 &&
              " " +
                t(
                  "검증을 통과하지 못한 {0}줄은 한국어로 표시합니다.",
                  untranslated,
                )}
          </p>
          {!busy && !translated && (
            <button className="text-link" onClick={retry}>
              {t("번역 다시 시도")}
            </button>
          )}
        </div>
      )}
      <ErrorNotice message={error} />
      <section className="verdict-panel">
        <div className="verdict-copy">
          <span className="badge">
            {t(
              {
                warning: "주의할 조항 발견",
                needs_information: "추가 정보 확인 필요",
                clear: "검토 범위 내 주의 조항 없음",
              }[review.verdict],
            )}
          </span>
          <h2>{t(review.headline)}</h2>
          <p>{t(review.scope_note)}</p>
        </div>
        <div className="result-count">
          <strong>{t(String(review.findings.length).padStart(2, "0"))}</strong>
          <span>{t("확인할 주의 조항")}</span>
        </div>
      </section>
      <DocumentReview
        result={r}
        original={original}
        translated={translated}
        translatedBlocks={blocks}
      >
        <section className="next-band panel">
          <div>
            <p className="eyebrow">Your next step</p>
            <h2>{t("이해한 만큼, 다음 단계를 준비하세요.")}</h2>
            <p>
              {t(
                "궁금한 조항을 질문하거나 검토 내용을 상담용 문서로 정리하세요.",
              )}
            </p>
          </div>
          <div className="next-band-actions">
            <ButtonLink primary to={href("chat", r.analysis_id)} icon="chat">
              {t("조항 질문하기")}
            </ButtonLink>
            <ButtonLink to={href("draft", r.analysis_id)} icon="pen">
              {t("상담 문서 작성")}
            </ButtonLink>
          </div>
        </section>
        <div className="panel key-facts">
          <h3>{t("계약서에서 찾은 조건")}</h3>
          {r.terms.slice(0, 6).map((term) => (
            <div key={term.key}>
              <span>{t(term.label)}</span>
              <strong>
                {t(
                  term.status === "not_found"
                    ? "원문에서 찾지 못함"
                    : term.status === "conflict"
                      ? "서로 다른 내용 · 확인 필요"
                      : term.candidates[0]?.value_text,
                )}
              </strong>
            </div>
          ))}
          <a className="text-link" href={href("original", r.analysis_id)}>
            {t("원문에서 확인")}
            <Icon />
          </a>
        </div>
      </DocumentReview>
      {r.questions.length > 0 && (
        <a className="notice notice-link" href={href("confirm", r.analysis_id)}>
          <Icon name="alert" />
          <div>
            <strong>
              {t("검토를 보완할 질문 {0}개가 있습니다.", r.questions.length)}
            </strong>
            <p>{t("실제 상황을 알려주시면 결과를 다시 확인합니다.")}</p>
          </div>
          <Icon />
        </a>
      )}
      <details className="scope-details">
        <summary>{t("이번 검토의 범위와 한계")}</summary>
        <ul>
          {[
            ...new Set([
              ...(review.pending_reasons || []),
              ...(r.coverage?.limitations || []),
            ]),
          ].map((item, i) => (
            <li key={i}>{t(item)}</li>
          ))}
        </ul>
        <p>{t("등록된 주요 위험 유형을 저장된 법령과 비교한 결과입니다.")}</p>
      </details>
      <a className="text-link" href={href("sources", r.analysis_id)}>
        <Icon name="book" />
        {t("검토에 사용한 근거 자료")}
      </a>
    </>
  );
}
export function Original({ result: r }) {
  const block = params.get("block");
  useEffect(() => {
    if (block)
      document.getElementById("block-" + block)?.scrollIntoView({
        block: "center",
      });
  }, [block]);
  return (
    <>
      <Back result={r} />
      <PageHead
        eyebrow="Original document"
        title={t("판단의 출발점, 계약서 원문.")}
        description={t(r.title)}
      />
      <div className="notice">
        <Icon name="file" />
        <p>
          {t(
            "파일에서 읽어 검토에 사용한 텍스트입니다. 업로드한 원본 파일과 금액·날짜를 대조하세요.",
          )}
        </p>
      </div>
      <article className="paper original-paper">
        {r.blocks.map((b) => (
          <section
            key={b.block_id}
            id={"block-" + b.block_id}
            className={block === b.block_id ? "highlighted-block" : ""}
          >
            <span className="paper-label">
              {t("{0}페이지 · {1}", b.page, b.block_id)}
            </span>
            <p lang="ko">{b.text}</p>
          </section>
        ))}
      </article>
    </>
  );
}
export function Sources({ result: r }) {
  const finding = r.review.findings.find(
    (f) => f.finding_id === params.get("finding"),
  );
  const sources = finding
    ? r.sources.filter((s) => finding.source_ids.includes(s.source_id))
    : r.sources;
  return (
    <>
      <Back result={r} />
      <PageHead
        eyebrow="Evidence & sources"
        title={t("검토의 근거를 확인하세요.")}
        description={
          finding?.title ||
          "검토에 제공된 자료입니다. 적용 시점과 사실관계를 함께 확인하세요."
        }
      />
      <div className="notice">
        <Icon name="book" />
        <p>
          {t(
            "저장된 법령 자료를 사용했습니다. 실제 적용 전에는 해당 시점의 법령과 사실관계를 확인하세요.",
          )}
        </p>
      </div>
      <div className="source-list">
        {sources.map((s) => (
          <article key={s.source_id} className="panel source-card">
            <span className="badge">
              {{
                law: "법령",
                precedent: "판례",
                interpretation: "법령해석",
                decision: "행정심판",
                dataset: "참고자료",
              }[s.kind || "law"] || "근거 자료"}
            </span>
            <h2>{t(s.title)}</h2>
            <p className="small muted">
              {s.effective_date && t("시행 {0} · ", s.effective_date)}
              {t(
                s.checked_at
                  ? t("조회 {0}", s.checked_at.slice(0, 10))
                  : "저장된 자료",
              )}
            </p>
            {t(
              finding?.citations
                ?.filter((c) => c.source_id === s.source_id)
                .map((c, i) => (
                  <blockquote className="evidence" key={i}>
                    {c.quote}
                  </blockquote>
                )),
            )}
            <pre lang="ko">{s.text}</pre>
            <p className="small muted">{t(s.version_note)}</p>
            {/^https:\/\/(?:www\.)?law\.go\.kr\//.test(s.official_url) && (
              <a
                href={s.official_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-link"
              >
                {t("국가법령정보센터에서 확인 ↗")}
              </a>
            )}
          </article>
        ))}
        {!sources.length && (
          <div className="panel">
            {t(
              "이 조항에 직접 연결된 법령 자료가 없습니다. 원문과 검토 범위를 확인해주세요.",
            )}
          </div>
        )}
      </div>
    </>
  );
}
const labels = {
  document_complete: "모든 페이지와 별첨이 포함되어 있나요?",
  event_date: "계약 또는 사건 날짜",
  workplace_size: "상시 근로자 수",
  weekly_work_hours: "실제 주당 근로시간",
  move_in: "입주를 완료했나요?",
  resident_registration: "전입신고를 마쳤나요?",
  deposit_returned: "계약 종료 후 보증금을 모두 받았나요?",
};
export function Confirm({ result: r }) {
  const [context, setContext] = useState(r.context);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const keys = [
    ...new Set([
      ...r.questions.map((q) => q.context_key),
      "document_complete",
      "event_date",
    ]),
  ];
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/api/analyses/${r.analysis_id}/answers`, {
        analysis_revision: r.analysis_revision,
        context: Object.fromEntries(
          keys.map((k) => [
            k,
            context[k] ?? (k === "workplace_size" ? "unknown" : null),
          ]),
        ),
      });
      go("review", r.analysis_id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  return (
    <>
      <Back result={r} />
      <PageHead
        eyebrow="A little more context"
        title={t("몇 가지만 더 확인할게요.")}
        description={t(
          "모르는 내용은 그대로 두세요. 답변한 정보로 검토 결과를 갱신합니다.",
        )}
      />
      <form className="panel narrow-form" onSubmit={submit}>
        <fieldset disabled={busy}>
          {keys.map((k) => (
            <Field key={k} label={labels[k] || k}>
              {["event_date", "weekly_work_hours"].includes(k) ? (
                <input
                  type={k === "event_date" ? "date" : "number"}
                  min={k === "weekly_work_hours" ? 0 : undefined}
                  max={k === "weekly_work_hours" ? 168 : undefined}
                  step={k === "weekly_work_hours" ? 0.5 : undefined}
                  value={context[k] ?? ""}
                  onChange={(e) =>
                    setContext((old) => ({
                      ...old,
                      [k]:
                        e.target.value === ""
                          ? null
                          : k === "weekly_work_hours"
                            ? Number(e.target.value)
                            : e.target.value,
                    }))
                  }
                />
              ) : (
                <select
                  value={context[k] == null ? "" : String(context[k])}
                  onChange={(e) =>
                    setContext((old) => ({
                      ...old,
                      [k]:
                        e.target.value === ""
                          ? null
                          : e.target.value === "true"
                            ? true
                            : e.target.value === "false"
                              ? false
                              : e.target.value,
                    }))
                  }
                >
                  {(k === "workplace_size"
                    ? [
                        ["unknown", "모름"],
                        ["under5", "5명 미만"],
                        ["5plus", "5명 이상"],
                      ]
                    : [
                        ["", "모름"],
                        ["true", "예"],
                        ["false", "아니오"],
                      ]
                  ).map(([v, l]) => (
                    <option value={v} key={v}>
                      {t(l)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          ))}
        </fieldset>
        <ErrorNotice message={error} />
        <button className="btn btn-primary" disabled={busy}>
          {t(busy ? "다시 검토하는 중…" : "답변으로 다시 검토하기")} <Icon />
        </button>
      </form>
    </>
  );
}
