import { useEffect, useState } from "react";
import { api } from "../lib/index.js";

export default function useAnalysis(id) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const data = await api("/api/analyses/" + encodeURIComponent(id), {
          signal: controller.signal,
        });
        if (data.status === "failed") {
          setState({
            data,
            error:
              data.error || "검토를 완료하지 못했습니다. 다시 등록해주세요.",
            loading: false,
          });
          return;
        }
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
