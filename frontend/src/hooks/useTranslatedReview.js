import { useEffect, useState } from "react";
import { useLanguage } from "../i18n/index.js";
import { post } from "../lib/index.js";
const POLL_MS = 1500;
const idle = {
  result: null,
  blocks: {},
  done: 0,
  total: 0,
  busy: false,
  error: "",
};
/** Translates the contract and review automatically when a non-Korean language is selected. */
export default function useTranslatedReview(original) {
  const lang = useLanguage();
  const scope = `${original.analysis_id}:${original.analysis_revision}:${lang}`;
  const [state, setState] = useState({ scope: "", ...idle });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (lang === "ko") return;
    let stopped = false;
    let timer;
    setState({ scope, ...idle, busy: true });
    async function poll() {
      try {
        const data = await post(
          `/api/analyses/${original.analysis_id}/auto-translation`,
          { analysis_revision: original.analysis_revision, language: lang },
        );
        if (stopped) return;
        if (data.status === "running") {
          setState({ scope, ...idle, ...data, busy: true });
          timer = setTimeout(poll, POLL_MS);
        } else if (data.status === "failed") {
          setState({ scope, ...idle, error: data.error });
        } else {
          setState({
            scope,
            ...idle,
            result: data.result,
            blocks: data.blocks,
            untranslated: data.untranslated_lines,
            bundled: !!data.bundled,
          });
        }
      } catch (e) {
        if (!stopped) setState({ scope, ...idle, error: e.message });
      }
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [scope, retry]);
  const active = lang !== "ko" && state.scope === scope;
  return {
    result: (active && state.result) || original,
    translated: !!(active && state.result),
    blocks: active ? state.blocks : {},
    done: active ? state.done : 0,
    total: active ? state.total : 0,
    untranslated: active ? state.untranslated || 0 : 0,
    bundled: active && !!state.bundled,
    busy: active && state.busy,
    error: active ? state.error : "",
    retry: () => setRetry((n) => n + 1),
    lang,
  };
}
