import { useEffect, useState } from "react";

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
export function useLoad(path) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState({ data: null, error: "", loading: true });
    if (!path) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    api(path, { signal: controller.signal })
      .then((data) => setState({ data, error: "", loading: false }))
      .catch((error) => {
        if (error.name !== "AbortError")
          setState({ data: null, error: error.message, loading: false });
      });
    return () => controller.abort();
  }, [path]);
  return state;
}
export function useAnalysis(id) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const data = await api("/api/analyses/" + encodeURIComponent(id), {
          signal: controller.signal,
        });
        if (data.status === "failed")
          throw new Error(
            data.error || "검토를 완료하지 못했습니다. 다시 등록해주세요.",
          );
        const loading = ["queued", "running"].includes(data.status);
        setState({ data, loading, error: "" });
        if (loading) timer = setTimeout(poll, 1400);
      } catch (error) {
        if (error.name !== "AbortError")
          setState({ data: null, error: error.message, loading: false });
      }
    }
    if (id) poll();
    else setState({ data: null, error: "", loading: false });
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id]);
  return state;
}
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
export function useSession(key, initial) {
  const [value, setValue] = useState(() => readSession(key, initial));
  useEffect(() => saveSession(key, value), [key, value]);
  return [value, setValue];
}
export function download(text, name) {
  const url = URL.createObjectURL(
    new Blob(["\uFEFF", text], { type: "text/plain;charset=utf-8" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name.replace(/[\\/:*?"<>|]/g, "_") + ".txt";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const dateLabel = (value) =>
  new Date(value).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
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
