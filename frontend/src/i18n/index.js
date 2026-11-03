import { useSyncExternalStore } from "react";
import messages from "./messages.json";
let current = "ko";
try {
  const saved = localStorage.getItem("gwollion:language");
  if (["ko", "zh", "es"].includes(saved)) current = saved;
} catch {
  /* private browsing */
}
const listeners = new Set();
export const language = () => current;
export function setLanguage(value) {
  if (!["ko", "zh", "es"].includes(value)) return;
  current = value;
  try {
    localStorage.setItem("gwollion:language", value);
  } catch {
    /* optional */
  }
  document.documentElement.lang = value === "zh" ? "zh-Hans" : value;
  listeners.forEach((fn) => fn());
}
export function useLanguage() {
  return useSyncExternalStore((fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, language);
}
export function t(key, ...values) {
  if (typeof key !== "string") return key;
  const value = current === "ko" ? key : (messages[key]?.[current] ?? key);
  return value.replace(/\{(\d+)\}/g, (_, i) => String(values[i] ?? `{${i}}`));
}
document.documentElement.lang = current === "zh" ? "zh-Hans" : current;
