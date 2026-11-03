import { useEffect, useState } from "react";
import { go, href, params, post } from "../lib.js";
import {
  Back,
  ButtonLink,
  ErrorNotice,
  Evidence,
  Field,
  Icon,
  PageHead,
  Workflow,
} from "../components/UI.jsx";

export default function Review({ result: r }) {
  const review = r.review;
  return (
    <>
      <PageHead
        eyebrow="01 / Review results"
        title={r.title}
        description={`${review.role_label}의 입장에서 살펴본 계약서 · 검토 버전 ${r.analysis_revision}`}
        action={
          <ButtonLink to={href("original", r.analysis_id)} icon="file">
            계약서 원문
          </ButtonLink>
        }
      />
      <Workflow result={r} />
      <section className="verdict-panel">
        <div className="verdict-copy">
          <span className="badge">
            {
              {
                warning: "주의할 조항 발견",
                needs_information: "추가 정보 확인 필요",
                clear: "검토 범위 내 주의 조항 없음",
              }[review.verdict]
            }
          </span>
          <h2>{review.headline}</h2>
          <p>{review.scope_note}</p>
        </div>
        <div className="result-count">
          <strong>{String(review.findings.length).padStart(2, "0")}</strong>
          <span>확인할 주의 조항</span>
        </div>
      </section>
      <div className="review-layout">
        <div>
          {r.questions.length > 0 && (
            <a
              className="notice notice-link"
              href={href("confirm", r.analysis_id)}
            >
              <Icon name="alert" />
              <div>
                <strong>
                  검토를 보완할 질문 {r.questions.length}개가 있습니다.
                </strong>
                <p>실제 상황을 알려주시면 결과를 다시 확인합니다.</p>
              </div>
              <Icon />
            </a>
          )}
          <div className="section-heading">
            <h2>주의해서 읽을 조항</h2>
            <span className="small muted">
              계약서의 표현을 근거로 정리했습니다.
            </span>
          </div>
          {review.findings.length ? (
            review.findings.map((f, i) => (
              <article className="panel finding-card" key={f.finding_id}>
                <div className="finding-top">
                  <span className="index">0{i + 1}</span>
                  <span className="badge">내 입장에서 주의</span>
                </div>
                <h2>{f.title}</h2>
                <Evidence evidence={f.evidence} id={r.analysis_id} />
                <h3>어떤 부담이 있나요?</h3>
                <p>{f.why_unfavorable}</p>
                <details>
                  <summary>상황 예시와 수정 제안</summary>
                  <h3>예상할 수 있는 상황</h3>
                  <p>{f.scenario}</p>
                  <h3>협의할 수정 문구</h3>
                  <p className="suggestion">{f.revision_suggestion}</p>
                  {f.applicability_questions?.length > 0 && (
                    <ul>
                      {f.applicability_questions.map((q, n) => (
                        <li key={n}>{q}</li>
                      ))}
                    </ul>
                  )}
                  <p className="small muted">{f.legal_note}</p>
                </details>
                <div className="finding-actions">
                  <ButtonLink
                    to={href("chat", r.analysis_id, { finding: f.finding_id })}
                    icon="chat"
                  >
                    이 조항 질문하기
                  </ButtonLink>
                  <a
                    className="text-link"
                    href={href("sources", r.analysis_id, {
                      finding: f.finding_id,
                    })}
                  >
                    근거 자료 <Icon />
                  </a>
                </div>
              </article>
            ))
          ) : (
            <div className="panel">
              <h3>표시된 주의 조항은 없습니다.</h3>
              <p className="muted">
                계약 전체의 안전성을 보증하는 결과는 아닙니다. 함께 확인할
                내용과 검토 범위도 확인하세요.
              </p>
            </div>
          )}
          <h2 className="subheading">함께 확인할 내용</h2>
          <div className="panel">
            {r.issues.map((issue) => (
              <div className="issue" key={issue.issue_id}>
                <h3>{issue.title}</h3>
                <p>{issue.explanation_ko}</p>
              </div>
            ))}
          </div>
          <details className="scope-details">
            <summary>이번 검토의 범위와 한계</summary>
            <ul>
              {[
                ...new Set([
                  ...(review.pending_reasons || []),
                  ...(r.coverage?.limitations || []),
                ]),
              ].map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
            <p>등록된 주요 위험 유형을 저장된 법령과 비교한 결과입니다.</p>
          </details>
        </div>
        <aside className="result-sidebar">
          <div className="panel next-step">
            <p className="eyebrow">Your next step</p>
            <h2>
              이해한 만큼,
              <br />
              다음 단계를 준비하세요.
            </h2>
            <p>
              궁금한 조항을 질문하거나 검토 내용을 상담용 문서로 정리하세요.
            </p>
            <ButtonLink primary to={href("chat", r.analysis_id)} icon="chat">
              조항 질문하기
            </ButtonLink>
            <ButtonLink to={href("draft", r.analysis_id)} icon="pen">
              상담 문서 작성
            </ButtonLink>
          </div>
          <div className="panel key-facts">
            <h3>계약서에서 찾은 조건</h3>
            {r.terms.slice(0, 6).map((term) => (
              <div key={term.key}>
                <span>{term.label}</span>
                <strong>
                  {term.status === "not_found"
                    ? "원문에서 찾지 못함"
                    : term.status === "conflict"
                      ? "서로 다른 내용 · 확인 필요"
                      : term.candidates[0]?.value_text}
                </strong>
              </div>
            ))}
            <a className="text-link" href={href("original", r.analysis_id)}>
              원문에서 확인 <Icon />
            </a>
          </div>
          <a className="text-link" href={href("sources", r.analysis_id)}>
            <Icon name="book" /> 검토에 사용한 근거 자료
          </a>
        </aside>
      </div>
    </>
  );
}
export function Original({ result: r }) {
  const block = params.get("block");
  useEffect(() => {
    if (block)
      document
        .getElementById("block-" + block)
        ?.scrollIntoView({ block: "center" });
  }, [block]);
  return (
    <>
      <Back result={r} />
      <PageHead
        eyebrow="Original document"
        title="판단의 출발점, 계약서 원문."
        description={r.title}
      />
      <div className="notice">
        <Icon name="file" />
        <p>
          파일에서 읽어 검토에 사용한 텍스트입니다. 업로드한 원본 파일과
          금액·날짜를 대조하세요.
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
              {b.page}페이지 · {b.block_id}
            </span>
            <p>{b.text}</p>
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
        title="검토의 근거를 확인하세요."
        description={
          finding?.title ||
          "검토에 제공된 자료입니다. 적용 시점과 사실관계를 함께 확인하세요."
        }
      />
      <div className="notice">
        <Icon name="book" />
        <p>
          저장된 법령 자료를 사용했습니다. 실제 적용 전에는 해당 시점의 법령과
          사실관계를 확인하세요.
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
            <h2>{s.title}</h2>
            <p className="small muted">
              {s.effective_date && `시행 ${s.effective_date} · `}
              {s.checked_at
                ? `조회 ${s.checked_at.slice(0, 10)}`
                : "저장된 자료"}
            </p>
            {finding?.citations
              ?.filter((c) => c.source_id === s.source_id)
              .map((c, i) => (
                <blockquote className="evidence" key={i}>
                  {c.quote}
                </blockquote>
              ))}
            <pre>{s.text}</pre>
            <p className="small muted">{s.version_note}</p>
            {/^https:\/\/(?:www\.)?law\.go\.kr\//.test(s.official_url) && (
              <a
                href={s.official_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-link"
              >
                국가법령정보센터에서 확인 ↗
              </a>
            )}
          </article>
        ))}
        {!sources.length && (
          <div className="panel">
            이 조항에 직접 연결된 법령 자료가 없습니다. 원문과 검토 범위를
            확인해주세요.
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
        title="몇 가지만 더 확인할게요."
        description="모르는 내용은 그대로 두세요. 답변한 정보로 검토 결과를 갱신합니다."
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
                      {l}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          ))}
        </fieldset>
        <ErrorNotice message={error} />
        <button className="btn btn-primary" disabled={busy}>
          {busy ? "다시 검토하는 중…" : "답변으로 다시 검토하기"} <Icon />
        </button>
      </form>
    </>
  );
}
