import { useEffect, useRef, useState } from "react";
import { analysisId, href, page } from "../lib.js";

export function Icon({ name = "arrow", ...props }) {
  const paths = {
    arrow: "M4 12h16m-6-6 6 6-6 6",
    back: "M20 12H4m6-6-6 6 6 6",
    file: "M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8m-8 4h6",
    upload: "M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5",
    chat: "M4 4h16v12H9l-5 5V4Zm4 5h8m-8 3h5",
    pen: "m5 15 10-10 4 4L9 19l-5 1 1-5Zm8-8 4 4",
    clock: "M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
    check: "m5 12 4 4L19 6",
    book: "M12 5v16M3 3l9 2 9-2v16l-9 2-9-2V3Z",
    trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    download: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
    alert: "M12 3 2 21h20L12 3Zm0 6v5m0 3v1",
  };
  return (
    <svg viewBox="0 0 24 24" className="icon" aria-hidden="true" {...props}>
      <path d={paths[name] || paths.arrow} />
    </svg>
  );
}
export function Header({ home = false }) {
  const [open, setOpen] = useState(false);
  const burger = useRef();
  useEffect(() => {
    const close = (event) => {
      if (event.key === "Escape" && open) {
        setOpen(false);
        burger.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  const nav = [
    ["review", "계약서 검토"],
    ["chat", "질문하기"],
    ["draft", "문서 작성"],
    ["history", "검토 기록"],
  ];
  const selected = [
    "upload",
    "samples",
    "original",
    "sources",
    "confirm",
  ].includes(page)
    ? "review"
    : page;
  return (
    <header className={`nav ${home ? "" : "workspace-nav"}`}>
      <a className="skip-link" href="#main">
        본문으로 건너뛰기
      </a>
      <a href="/" className="brand" aria-label="권리ON 홈">
        <svg viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
          <path d="M16 4v22M9 26h14M6 9h20M16 5.5l-10 3.5M16 5.5l10 3.5M6 9l-3.5 8h7zM26 9l-3.5 8h7zM2.5 17a3.5 2 0 0 0 7 0M22.5 17a3.5 2 0 0 0 7 0" />
        </svg>
        <span className="brand-wordmark">
          권리
          <span className="brand-on" lang="en">
            ON
          </span>
        </span>
      </a>
      <nav
        id="primary-nav"
        aria-label="주 메뉴"
        className={`links ${open ? "open" : ""}`}
      >
        {nav.map(([key, label]) => (
          <a
            key={key}
            href={href(
              key === "review" && !analysisId ? "upload" : key,
              key === "history" ? null : analysisId,
            )}
            className={selected === key ? "active" : ""}
            aria-current={selected === key ? "page" : undefined}
          >
            {label}
          </a>
        ))}
        <a href="/upload/" className="btn btn-sm btn-primary nav-cta">
          새 계약서 검토 <Icon />
        </a>
      </nav>
      <button
        ref={burger}
        className={`burger ${open ? "x" : ""}`}
        aria-label={open ? "메뉴 닫기" : "메뉴 열기"}
        aria-controls="primary-nav"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span />
        <span />
      </button>
    </header>
  );
}
export function PageHead({ eyebrow, title, description, action }) {
  return (
    <div className="page-head">
      <div>
        <p className="eyebrow" lang="en">
          <span className="rule" />
          {eyebrow}
        </p>
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function ButtonLink({
  children,
  to,
  primary = false,
  icon = "arrow",
  ...props
}) {
  return (
    <a
      className={`btn ${primary ? "btn-primary" : "btn-ghost"}`}
      href={to}
      {...props}
    >
      {children}
      {icon && <Icon name={icon} />}
    </a>
  );
}
export function ErrorNotice({ message }) {
  if (!message) return null;
  return (
    <div className="notice error-notice" role="alert">
      <Icon name="alert" />
      <div>
        {message}
        <div className="error-action">
          <button
            type="button"
            className="text-link"
            onClick={() => window.location.reload()}
          >
            최신 화면 다시 불러오기
          </button>
        </div>
      </div>
    </div>
  );
}
export function Loading({ text = "내용을 불러오는 중입니다." }) {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" />
      <h2>{text}</h2>
      <p>잠시만 기다려주세요.</p>
    </div>
  );
}
export function Empty({ title, children, action, icon = "file" }) {
  return (
    <div className="empty-state panel">
      <Icon name={icon} />
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Workflow({ result }) {
  return (
    <div className="workflow" aria-label="계약서 작업 단계">
      {[
        ["review", "검토 결과"],
        ["chat", "조항 질문"],
        ["draft", "문서 작성"],
      ].map(([name, title], i) => (
        <a
          key={name}
          className={page === name ? "current" : ""}
          aria-current={page === name ? "step" : undefined}
          href={href(name, result.analysis_id)}
        >
          <span>0{i + 1}</span>
          {title}
          <Icon />
        </a>
      ))}
    </div>
  );
}
export function Back({ result }) {
  return (
    <a
      className="text-link back-link"
      href={href("review", result.analysis_id)}
    >
      <Icon name="back" /> 검토 결과로
    </a>
  );
}
export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}
export function Evidence({ evidence = [], id }) {
  return evidence.map((e, i) => (
    <blockquote className="evidence" key={i}>
      <p>{e.quote}</p>
      <a
        className="text-link"
        href={href("original", id, { block: e.block_id })}
      >
        {e.page}페이지 원문 보기 <Icon />
      </a>
    </blockquote>
  ));
}
