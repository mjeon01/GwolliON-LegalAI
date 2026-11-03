import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { t, useLanguage } from "../i18n/index.js";
import { href } from "../lib/index.js";
import useLoad from "../hooks/useLoad.js";
import { ButtonLink, Evidence, Icon } from "./UI.jsx";
const tones = {
  risk: "불리할 수 있는 조항",
  mismatch: "서로 다른 내용",
  check: "확인이 필요한 부분",
  document: "문서 전체 확인",
};
const evidenceKey = (e) => `${e.block_id}:${e.start}:${e.end}`;
const firstBlock = (item) => item.evidence[0]?.block_id ?? "~";
/** Findings and issues as one reading-order list; issues repeating a finding are merged. */
export function reviewItems(r) {
  const findingTypes = new Set(r.review.findings.map((f) => f.issue_type));
  const located = [
    ...r.review.findings.map((f) => ({
      key: f.finding_id,
      tone: "risk",
      title: f.title,
      evidence: f.evidence,
      finding: f,
    })),
    ...r.issues
      .filter((i) => i.evidence.length && !findingTypes.has(i.issue_type))
      .map((i) => ({
        key: i.issue_id,
        tone: i.status === "conflict" ? "mismatch" : "check",
        title: i.title,
        evidence: i.evidence,
        issue: i,
      })),
  ].sort((a, b) => firstBlock(a).localeCompare(firstBlock(b)));
  const whole = r.issues
    .filter((i) => !i.evidence.length)
    .map((i) => ({
      key: i.issue_id,
      tone: "document",
      title: i.title,
      evidence: [],
      issue: i,
    }));
  return [...located, ...whole].map((item, index) => ({
    ...item,
    number: index + 1,
  }));
}
function reveal(scroller, element) {
  if (!scroller || !element) return;
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const behavior = smooth ? "smooth" : "auto";
  if (scroller.scrollHeight <= scroller.clientHeight + 1) {
    element.scrollIntoView({ block: "nearest", behavior });
    return;
  }
  const outer = scroller.getBoundingClientRect();
  const inner = element.getBoundingClientRect();
  scroller.scrollBy({
    top: inner.top - outer.top - (outer.height - inner.height) / 2,
    left: inner.left - outer.left - (outer.width - inner.width) / 2,
    behavior,
  });
}
function Mark({ item, active, select, children, ...props }) {
  return (
    <button
      type="button"
      className={`doc-mark tone-${item.tone}${active ? " active" : ""}${item.number % 2 ? "" : " pin-shift"}`}
      data-item={item.key}
      aria-pressed={active}
      aria-label={t("{0}번 표시: {1}", item.number, t(item.title))}
      onClick={() => select(item.key, "mark")}
      {...props}
    >
      {children}
    </button>
  );
}
function PageImages({ id, pages, located, items, activeKey, select, zoom }) {
  return pages.map((page) => (
    <div
      className="doc-page"
      key={page.page}
      style={{
        aspectRatio: `${page.width} / ${page.height}`,
        width: `${zoom}%`,
        fontSize: `${(13 * zoom) / 100}px`,
      }}
    >
      <img
        src={`/api/analyses/${encodeURIComponent(id)}/pages/${page.page}`}
        alt={t("{0}페이지 원본", page.page)}
      />
      {items.flatMap((item) =>
        item.evidence.flatMap((e) => {
          const spot = located[evidenceKey(e)];
          if (spot?.page !== page.page) return [];
          return spot.rects.map(([x0, y0, x1, y1], n) => (
            <Mark
              key={`${item.key}-${evidenceKey(e)}-${n}`}
              item={item}
              active={activeKey === item.key}
              select={select}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
              }}
            >
              {n === 0 && <span className="doc-pin">{item.number}</span>}
            </Mark>
          ));
        }),
      )}
    </div>
  ));
}
function segments(block, marks) {
  const parts = [];
  let cursor = 0;
  for (const [e, item] of marks) {
    if (e.start < cursor) continue;
    if (e.start > cursor) parts.push([block.text.slice(cursor, e.start)]);
    parts.push([block.text.slice(e.start, e.end), item]);
    cursor = e.end;
  }
  if (cursor < block.text.length) parts.push([block.text.slice(cursor)]);
  return parts;
}
function PageText({ blocks, items, activeKey, select, zoom, translations }) {
  const marks = new Map();
  for (const item of items)
    for (const e of item.evidence)
      marks.set(e.block_id, [...(marks.get(e.block_id) || []), [e, item]]);
  return (
    <article
      className={`paper doc-text${translations ? " doc-translated" : ""}`}
      lang="ko"
      style={{ fontSize: `${(16 * zoom) / 100}px`, width: `${zoom}%` }}
    >
      {blocks.map((b, i) => (
        <div key={b.block_id}>
          {b.page !== blocks[i - 1]?.page && (
            <span className="paper-label">{t("{0}페이지", b.page)}</span>
          )}
          {translations ? (
            <TranslatedLine
              text={translations[b.block_id]}
              original={b.text}
              items={(marks.get(b.block_id) || []).map(([, item]) => item)}
              activeKey={activeKey}
              select={select}
            />
          ) : (
            <p>
              {segments(
                b,
                (marks.get(b.block_id) || []).sort(
                  (x, y) => x[0].start - y[0].start,
                ),
              ).map(([text, item], n) =>
                item ? (
                  <Mark
                    key={n}
                    item={item}
                    active={activeKey === item.key}
                    select={select}
                  >
                    <span className="doc-pin">{item.number}</span>
                    {text}
                  </Mark>
                ) : (
                  <span key={n}>{text}</span>
                ),
              )}
            </p>
          )}
        </div>
      ))}
    </article>
  );
}
/** The original stays under every line: a reference translation must be checkable in place. */
function TranslatedLine({ text, original, items, activeKey, select }) {
  const item = items[0];
  const line = text || original;
  return (
    <div className={`doc-line${text ? "" : " doc-line-original"}`}>
      <p lang={text ? undefined : "ko"}>
        {item ? (
          <Mark item={item} active={activeKey === item.key} select={select}>
            <span className="doc-pin">{item.number}</span>
            {line}
          </Mark>
        ) : (
          line
        )}
      </p>
      {text && (
        <small className="doc-original" lang="ko">
          {original}
        </small>
      )}
    </div>
  );
}
function FindingBody({ item, result: r, original, translated }) {
  const f = item.finding;
  if (!f)
    return (
      <>
        <Evidence evidence={item.evidence} id={r.analysis_id} />
        <p>{t(item.issue.explanation_ko)}</p>
        {item.issue.actions.length > 0 && (
          <ul>
            {item.issue.actions.map((action, n) => (
              <li key={n}>{t(action)}</li>
            ))}
          </ul>
        )}
      </>
    );
  return (
    <>
      <Evidence evidence={f.evidence} id={r.analysis_id} />
      <h3>{t("어떤 부담이 있나요?")}</h3>
      <p>{t(f.why_unfavorable)}</p>
      <details open>
        <summary>{t("상황 예시와 수정 제안")}</summary>
        <h3>{t("예상할 수 있는 상황")}</h3>
        <p>{t(f.scenario)}</p>
        <h3>{t("협의할 수정 문구")}</h3>
        <p className="suggestion">{t(f.revision_suggestion)}</p>
        {translated && (
          <details>
            <summary>{t("한국어 수정 문구")}</summary>
            <p lang="ko">
              {
                original.review.findings.find(
                  (v) => v.finding_id === f.finding_id,
                )?.revision_suggestion
              }
            </p>
          </details>
        )}
        {f.applicability_questions?.length > 0 && (
          <ul>
            {f.applicability_questions.map((q, n) => (
              <li key={n}>{t(q)}</li>
            ))}
          </ul>
        )}
        <p className="small muted">{t(f.legal_note)}</p>
      </details>
      <div className="finding-actions">
        <ButtonLink
          to={href("chat", r.analysis_id, { finding: f.finding_id })}
          icon="chat"
        >
          {t("이 조항 질문하기")}
        </ButtonLink>
        <a
          className="text-link"
          href={href("sources", r.analysis_id, { finding: f.finding_id })}
        >
          {t("근거 자료")}
          <Icon />
        </a>
      </div>
    </>
  );
}
const ZOOM_MIN = 60;
const ZOOM_MAX = 300;
const ZOOM_STEP = 20;
export default function DocumentReview({
  result: r,
  original,
  translated,
  translatedBlocks = {},
  children,
}) {
  const lang = useLanguage();
  const [zoom, setZoom] = useState(100);
  const changeZoom = (next) =>
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)));
  const { data: document_, loading } = useLoad(
    `/api/analyses/${encodeURIComponent(r.analysis_id)}/document`,
  );
  const items = useMemo(() => reviewItems(r), [r]);
  const marked = items.filter((item) => item.evidence.length);
  const [activeKey, setActiveKey] = useState(
    () => (items.find((i) => i.tone === "risk") || items[0])?.key,
  );
  const [view, setView] = useState(null);
  const documentPane = useRef();
  const notes = useRef();
  const located = document_?.highlights || {};
  const pages = document_?.pages || [];
  // A page with no locatable evidence would look falsely clean, so show the marked text instead.
  const preferred =
    pages.length &&
    (!marked.length ||
      marked.some((i) => i.evidence.some((e) => located[evidenceKey(e)])))
      ? "page"
      : "text";
  const translatedAvailable = lang !== "ko";
  const shown =
    view === "translated" && !translatedAvailable
      ? preferred
      : view || (translatedAvailable ? "translated" : preferred);
  // Trackpad pinch arrives as ctrl+wheel; without this the whole browser page zooms.
  useEffect(() => {
    const pane = documentPane.current;
    const wheel = (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      setZoom((old) =>
        Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, old - event.deltaY * 0.5)),
      );
    };
    pane.addEventListener("wheel", wheel, { passive: false });
    return () => pane.removeEventListener("wheel", wheel);
  }, []);
  // Keep the point being read at the centre of the pane while the document scales.
  const previousZoom = useRef(zoom);
  useLayoutEffect(() => {
    const pane = documentPane.current;
    const ratio = zoom / previousZoom.current;
    previousZoom.current = zoom;
    if (ratio === 1 || !pane) return;
    pane.scrollLeft =
      (pane.scrollLeft + pane.clientWidth / 2) * ratio - pane.clientWidth / 2;
    pane.scrollTop =
      (pane.scrollTop + pane.clientHeight / 2) * ratio - pane.clientHeight / 2;
  }, [zoom]);
  const pending = useRef(null);
  function select(key, from) {
    setActiveKey(key);
    pending.current = from;
  }
  useEffect(() => {
    const from = pending.current;
    pending.current = null;
    if (!from) return;
    if (from !== "mark")
      reveal(
        documentPane.current,
        documentPane.current?.querySelector(`[data-item="${activeKey}"]`),
      );
    if (from !== "card")
      reveal(notes.current, document.getElementById("note-" + activeKey));
  }, [activeKey]);
  const position = items.findIndex((i) => i.key === activeKey);
  const count = (tone) => items.filter((i) => i.tone === tone).length;
  return (
    <section className="doc-review" aria-label={t("계약서 표시와 설명")}>
      <div className="doc-toolbar">
        <ul className="doc-legend">
          {Object.entries(tones).map(
            ([tone, label]) =>
              count(tone) > 0 && (
                <li key={tone} className={`tone-${tone}`}>
                  <i aria-hidden="true" />
                  {t(label)} <strong>{count(tone)}</strong>
                </li>
              ),
          )}
        </ul>
        <div className="doc-controls">
          <div className="doc-zoom" role="group" aria-label={t("문서 확대")}>
            <button
              type="button"
              aria-label={t("축소")}
              disabled={zoom <= ZOOM_MIN}
              onClick={() => changeZoom(zoom - ZOOM_STEP)}
            >
              −
            </button>
            <button
              type="button"
              className="doc-zoom-value"
              aria-label={t("원래 크기로")}
              onClick={() => setZoom(100)}
            >
              {Math.round(zoom)}%
            </button>
            <button
              type="button"
              aria-label={t("확대")}
              disabled={zoom >= ZOOM_MAX}
              onClick={() => changeZoom(zoom + ZOOM_STEP)}
            >
              +
            </button>
          </div>
          {(pages.length > 0 || translatedAvailable) && (
            <div
              className="doc-switch"
              role="group"
              aria-label={t("문서 보기")}
            >
              {[
                ...(translatedAvailable ? [["translated", "번역본"]] : []),
                ...(pages.length ? [["page", "원본 문서"]] : []),
                ["text", "읽은 텍스트"],
              ].map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  aria-pressed={shown === value}
                  onClick={() => setView(value)}
                >
                  {t(label)}
                </button>
              ))}
            </div>
          )}
          {items.length > 1 && (
            <div className="doc-stepper">
              <button
                type="button"
                aria-label={t("이전 항목")}
                onClick={() =>
                  select(
                    items[(position - 1 + items.length) % items.length].key,
                    "step",
                  )
                }
              >
                <Icon name="back" />
              </button>
              <span>
                {position + 1} / {items.length}
              </span>
              <button
                type="button"
                aria-label={t("다음 항목")}
                onClick={() =>
                  select(items[(position + 1) % items.length].key, "step")
                }
              >
                <Icon />
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="doc-columns">
        <div className="doc-pane" ref={documentPane} tabIndex={0}>
          {shown === "page" && !loading ? (
            <PageImages
              id={r.analysis_id}
              pages={pages}
              located={located}
              items={marked}
              activeKey={activeKey}
              select={select}
              zoom={zoom}
            />
          ) : (
            <PageText
              blocks={r.blocks}
              items={marked}
              activeKey={activeKey}
              select={select}
              zoom={zoom}
              translations={shown === "translated" ? translatedBlocks : null}
            />
          )}
        </div>
        <div className="doc-notes" ref={notes}>
          {items.length === 0 && (
            <div className="panel">
              <h3>{t("표시된 주의 조항은 없습니다.")}</h3>
              <p className="muted">
                {t(
                  "계약 전체의 안전성을 보증하는 결과는 아닙니다. 함께 확인할 내용과 검토 범위도 확인하세요.",
                )}
              </p>
            </div>
          )}
          {items.map((item) => {
            const open = item.key === activeKey;
            const spots = item.evidence.map((e) => located[evidenceKey(e)]);
            return (
              <article
                id={"note-" + item.key}
                key={item.key}
                className={`doc-note tone-${item.tone}${open ? " active" : ""}${item.finding ? " finding-card" : ""}`}
              >
                <button
                  type="button"
                  className="doc-note-head"
                  aria-expanded={open}
                  onClick={() => select(item.key, "card")}
                >
                  <span className="doc-pin">{item.number}</span>
                  <span>
                    <small>{t(tones[item.tone])}</small>
                    <strong>{t(item.title)}</strong>
                  </span>
                </button>
                {open && (
                  <div className="doc-note-body">
                    {shown === "page" &&
                      item.evidence.length > 0 &&
                      spots.some((s) => !s) && (
                        <p className="doc-location-note">
                          {t(
                            "원본 이미지에서 위치를 찾지 못했습니다. 읽은 텍스트 보기에서 확인하세요.",
                          )}
                        </p>
                      )}
                    {shown === "page" &&
                      spots.some((s) => s?.match === "approximate") && (
                        <p className="doc-location-note">
                          {t(
                            "판독 결과로 찾은 근사 위치입니다. 원본과 대조하세요.",
                          )}
                        </p>
                      )}
                    <FindingBody
                      item={item}
                      result={r}
                      original={original}
                      translated={translated}
                    />
                  </div>
                )}
              </article>
            );
          })}
          <div className="doc-notes-extra">{children}</div>
        </div>
      </div>
    </section>
  );
}
