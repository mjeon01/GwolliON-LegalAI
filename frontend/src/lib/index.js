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
export async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
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
