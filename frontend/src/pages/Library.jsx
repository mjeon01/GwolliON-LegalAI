import { useLanguage, t } from "../i18n/index.js";
import { useRef, useState } from "react";
import { api, dateLabel, href, statusLabel } from "../lib/index.js";
import useLoad from "../hooks/useLoad.js";
import {
  ButtonLink,
  Empty,
  ErrorNotice,
  Icon,
  Loading,
  PageHead,
} from "../components/UI.jsx";
export function Samples() {
  const lang = useLanguage();
  const { data, error, loading } = useLoad("/api/samples");
  return (
    <>
      <PageHead
        eyebrow="Explore your rights"
        title={t("계약서 없이 먼저 경험해보세요.")}
        description={t(
          "가상의 계약서로 검토부터 상담 문서 준비까지 둘러볼 수 있습니다.",
        )}
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : (
        <div className="sample-grid">
          {t(
            data?.map((item, i) => (
              <article className="sample-card panel" key={item.id}>
                <div className="sample-top">
                  <span className="index">0{t(i + 1)}</span>
                  <span className="badge">
                    {item.translations?.[lang]?.tag || item.tag}
                  </span>
                </div>
                <Icon name="file" />
                <h2>{item.translations?.[lang]?.title || item.title}</h2>
                <p>
                  {item.translations?.[lang]?.description || item.description}
                </p>
                <a
                  className="text-link"
                  href={href("upload", null, {
                    sample: item.id,
                  })}
                >
                  {t("이 계약서로 시작하기")}
                  <Icon />
                </a>
                <a
                  className="text-link"
                  href={`/api/samples/${item.id}/pdf`}
                  download
                >
                  {t("PDF 저장")}
                  <Icon name="download" />
                </a>
                <a
                  className="text-link"
                  href={`/api/samples/${item.id}/png`}
                  download
                >
                  {t("PNG 저장")}
                  <Icon name="download" />
                </a>
              </article>
            )),
          )}
        </div>
      )}
    </>
  );
}
export function Library({ target = "review", selector = false }) {
  const { data, error, loading } = useLoad("/api/analyses");
  const [query, setQuery] = useState("");
  const [removed, setRemoved] = useState([]);
  const [selected, setSelected] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef();
  const label =
    target === "chat"
      ? "질문하기"
      : target === "draft"
        ? "문서 작성"
        : "검토 결과";
  const items = (data || []).filter(
    (item) => !removed.includes(item.analysis_id),
  );
  const filtered = items.filter((item) =>
    item.title.toLowerCase().includes(query.trim().toLowerCase()),
  );
  function confirm(item) {
    setSelected(item);
    setDeleteError("");
    dialog.current.showModal();
  }
  async function remove() {
    setBusy(true);
    setDeleteError("");
    try {
      await api("/api/analyses/" + encodeURIComponent(selected.analysis_id), {
        method: "DELETE",
      });
      setRemoved((old) => [...old, selected.analysis_id]);
      try {
        Object.keys(sessionStorage)
          .filter(
            (key) =>
              key.startsWith("veritas:") && key.includes(selected.analysis_id),
          )
          .forEach((key) => sessionStorage.removeItem(key));
      } catch {
        /* disabled storage */
      }
      dialog.current.close();
    } catch (e) {
      setDeleteError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead
        eyebrow={
          selector
            ? `Workspace / ${target === "chat" ? "Questions" : "Documents"}`
            : "Your archive"
        }
        title={t(
          selector
            ? t("{0}에 사용할 계약서를 선택하세요.", label)
            : "다시 꺼내보는 나의 계약서.",
        )}
        description={t(
          selector
            ? "검토한 계약서를 선택하면 해당 작업 페이지로 이동합니다."
            : "이 컴퓨터에 저장된 검토 결과와 대화를 이어서 확인하세요.",
        )}
        action={
          <ButtonLink to="/upload/" primary>
            {t("새 계약서 검토")}
          </ButtonLink>
        }
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : !items.length ? (
        <Empty
          title={t("아직 검토한 계약서가 없습니다.")}
          action={
            <ButtonLink to="/samples/">{t("샘플로 시작하기")}</ButtonLink>
          }
        >
          {t("계약서를 등록하면 이곳에서 이어서 작업할 수 있습니다.")}
        </Empty>
      ) : (
        <>
          <div className="archive-toolbar">
            <span>
              {t("전체")}
              <strong>{items.length}</strong>
              {t("건")}
              {t(" ")}
              <span className="muted small">{t("· 최근 50건")}</span>
            </span>
            <label className="search-box">
              <span className="visually-hidden">{t("계약서 이름 검색")}</span>
              <input
                type="search"
                placeholder={t("계약서 이름으로 검색")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          </div>
          <div className="archive-list">
            {filtered.map((item) => (
              <article className="archive-row" key={item.analysis_id}>
                <div className="document-icon">
                  <Icon name="file" />
                </div>
                <a
                  className="archive-title"
                  href={href(target, item.analysis_id)}
                >
                  <h2>{t(item.title)}</h2>
                  <span>
                    {t(dateLabel(item.created_at))}
                    {t("· 버전 {0}", item.analysis_revision)}
                  </span>
                </a>
                <span
                  className={`badge ${item.status === "failed" ? "danger" : ""}`}
                >
                  {t(statusLabel(item.status))}
                </span>
                <a className="text-link" href={href(target, item.analysis_id)}>
                  {t(label)} <Icon />
                </a>
                {!selector && (
                  <button
                    className="icon-button"
                    aria-label={t("{0} 기록 삭제", item.title)}
                    onClick={() => confirm(item)}
                  >
                    <Icon name="trash" />
                  </button>
                )}
              </article>
            ))}
          </div>
          {!filtered.length && (
            <Empty title={t("검색 결과가 없습니다.")}>
              {t("다른 계약서 이름으로 검색해보세요.")}
            </Empty>
          )}
        </>
      )}
      <dialog
        ref={dialog}
        className="delete-dialog"
        onCancel={(e) => {
          if (busy) e.preventDefault();
        }}
      >
        <p className="eyebrow">Delete record</p>
        <h2>{t("이 기록을 삭제할까요?")}</h2>
        <p>
          <strong>{t(selected?.title)}</strong>
        </p>
        <p>
          {t(
            "계약서 원문, 페이지 이미지, 검토 결과, 대화가 함께 삭제됩니다. 삭제한 내용은 복구할 수 없습니다.",
          )}
        </p>
        <ErrorNotice message={deleteError} />
        <div className="action-row">
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => dialog.current.close()}
          >
            {t("유지하기")}
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={remove}>
            {t(busy ? "삭제 중…" : "기록 삭제")}
          </button>
        </div>
      </dialog>
    </>
  );
}
