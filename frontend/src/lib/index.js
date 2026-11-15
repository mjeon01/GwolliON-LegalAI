import { t, language } from "../i18n/index.js";

export const params = new URLSearchParams(window.location.search);
export const analysisId = params.get("id");
export const page =
  window.location.pathname.split("/").filter(Boolean)[0] || "home";
export const href = (name, id, extra = {}) => {
  const query = new URLSearchParams({ ...(id ? { id } : {}), ...extra });
  return `/${name === "home" ? "" : name + "/"}${query.size ? "?" + query : ""}`;
};
export const go = (name, id, extra) =>
  window.location.assign(href(name, id, extra));
// Owner tokens: the server only shows an analysis or agent session to the browser that created it.
const ACCESS_KEY = "gwollion:access";
const OWNED = /\/api\/(?:analyses|agent\/sessions)\/([0-9a-f-]{36})/;
function readAccess() {
  try {
    return JSON.parse(localStorage.getItem(ACCESS_KEY)) || {};
  } catch {
    return {};
  }
}
export function rememberAccess(id, token) {
  if (!id || !token) return;
  try {
    localStorage.setItem(ACCESS_KEY, JSON.stringify({ ...readAccess(), [id]: token }));
  } catch {
    /* Storage can be disabled; the page keeps working until it is closed. */
  }
}
export function forgetAccess(id) {
  const all = readAccess();
  delete all[id];
  try {
    localStorage.setItem(ACCESS_KEY, JSON.stringify(all));
  } catch {
    /* disabled storage */
  }
}
export const accessToken = (id) => readAccess()[id];
export function accessHeaders(path) {
  if (/^\/api\/analyses\/?(?:\?|$)/.test(path))
    return {
      "X-Gwollion-Tokens": Object.entries(readAccess())
        .map(([id, token]) => `${id}:${token}`)
        .join(","),
    };
  const token = accessToken(path.match(OWNED)?.[1]);
  return token ? { "X-Gwollion-Token": token } : {};
}
// For <img src> and download links, which cannot carry headers.
export const withAccess = (path) => {
  const token = accessToken(path.match(OWNED)?.[1]);
  return token
    ? `${path}${path.includes("?") ? "&" : "?"}access=${encodeURIComponent(token)}`
    : path;
};
export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...accessHeaders(path), ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (data && data.access_token)
    rememberAccess(data.session_id || data.analysis_id, data.access_token);
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((item) => item.msg.replace(/^Value error, /, ""))
              .join(" / ")
          : "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.",
    );
    error.status = response.status;
    error.code = data.code;
    throw error;
  }
  return data;
}
export const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });


export function readSession(key, fallback) {
  try {
    return JSON.parse(sessionStorage.getItem("veritas:" + key)) ?? fallback;
  } catch {
    return fallback;
  }
}
export function saveSession(key, value) {
  try {
    sessionStorage.setItem("veritas:" + key, JSON.stringify(value));
  } catch {
    /* Storage can be disabled. */
  }
}

export async function downloadPdf(text, name) {
  const response = await fetch("/api/documents/pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: name.slice(0, 200), text }),
  });
  if (!response.ok)
    throw new Error("PDF를 만들지 못했습니다. 다시 시도해주세요.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name.replace(/[\\/:*?"<>|]/g, "_") + ".pdf";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const dateLabel = (value) =>
  new Date(value).toLocaleDateString(
    { ko: "ko-KR", zh: "zh-CN", es: "es-ES" }[language()],
    {
      year: "numeric",
      month: "long",
      day: "numeric",
    },
  );
export const statusLabel = (status) =>
  ({
    completed: "검토 완료",
    awaiting_input: "추가 확인 필요",
    queued: "대기 중",
    running: "검토 중",
    failed: "검토 실패",
  })[status] || status;
export const roles = {
  employment: [
    ["worker", "근로자"],
    ["employer", "사용자"],
  ],
  lease: [
    ["tenant", "임차인"],
    ["landlord", "임대인"],
  ],
  sale: [
    ["buyer", "매수인"],
    ["seller", "매도인"],
  ],
};
