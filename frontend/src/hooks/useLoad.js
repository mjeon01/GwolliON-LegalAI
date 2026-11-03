import { useEffect, useState } from "react";
import { api } from "../lib/index.js";

export default function useLoad(path) {
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
