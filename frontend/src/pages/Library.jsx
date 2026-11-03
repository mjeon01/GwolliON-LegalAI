import { useRef, useState } from "react";
import { api, dateLabel, href, statusLabel, useLoad } from "../lib.js";
import {
  ButtonLink,
  Empty,
  ErrorNotice,
  Icon,
  Loading,
  PageHead,
} from "../components/UI.jsx";

export function Samples() {
  const { data, error, loading } = useLoad("/api/samples");
  return (
    <>
      <PageHead
        eyebrow="Explore your rights"
        title="계약서 없이 먼저 경험해보세요."
        description="가상의 계약서로 검토부터 상담 문서 준비까지 둘러볼 수 있습니다."
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : (
        <div className="sample-grid">
          {data?.map((item, i) => (
            <a
              className="sample-card panel"
              href={href("upload", null, { sample: item.id })}
              key={item.id}
            >
              <div className="sample-top">
                <span className="index">0{i + 1}</span>
                <span className="badge">{item.tag}</span>
              </div>
              <Icon name="file" />
              <h2>{item.title}</h2>
              <p>{item.description}</p>
              <span className="text-link">
                이 계약서로 시작하기 <Icon />
              </span>
            </a>
          ))}
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
        title={
          selector
            ? `${label}에 사용할 계약서를 선택하세요.`
            : "다시 꺼내보는 나의 계약서."
        }
        description={
          selector
            ? "검토한 계약서를 선택하면 해당 작업 페이지로 이동합니다."
            : "이 컴퓨터에 저장된 검토 결과와 대화를 이어서 확인하세요."
        }
        action={
          <ButtonLink to="/upload/" primary>
            새 계약서 검토
          </ButtonLink>
        }
      />
      <ErrorNotice message={error} />
      {loading ? (
        <Loading />
      ) : !items.length ? (
        <Empty
          title="아직 검토한 계약서가 없습니다."
          action={<ButtonLink to="/samples/">샘플로 시작하기</ButtonLink>}
        >
          계약서를 등록하면 이곳에서 이어서 작업할 수 있습니다.
        </Empty>
      ) : (
        <>
          <div className="archive-toolbar">
            <span>
              전체 <strong>{items.length}</strong>건{" "}
              <span className="muted small">· 최근 50건</span>
            </span>
            <label className="search-box">
              <span className="visually-hidden">계약서 이름 검색</span>
              <input
                type="search"
                placeholder="계약서 이름으로 검색"
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
                  <h2>{item.title}</h2>
                  <span>
                    {dateLabel(item.created_at)} · 버전 {item.analysis_revision}
                  </span>
                </a>
                <span
                  className={`badge ${item.status === "failed" ? "danger" : ""}`}
                >
                  {statusLabel(item.status)}
                </span>
                <a className="text-link" href={href(target, item.analysis_id)}>
                  {label} <Icon />
                </a>
                {!selector && (
                  <button
                    className="icon-button"
                    aria-label={`${item.title} 기록 삭제`}
                    onClick={() => confirm(item)}
                  >
                    <Icon name="trash" />
                  </button>
                )}
              </article>
            ))}
          </div>
          {!filtered.length && (
            <Empty title="검색 결과가 없습니다.">
              다른 계약서 이름으로 검색해보세요.
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
        <h2>이 기록을 삭제할까요?</h2>
        <p>
          <strong>{selected?.title}</strong>
        </p>
        <p>
          계약서 원문, 검토 결과, 대화가 함께 삭제됩니다. 삭제한 내용은 복구할
          수 없습니다.
        </p>
        <ErrorNotice message={deleteError} />
        <div className="action-row">
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => dialog.current.close()}
          >
            유지하기
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={remove}>
            {busy ? "삭제 중…" : "기록 삭제"}
          </button>
        </div>
      </dialog>
    </>
  );
}
