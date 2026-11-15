import { useEffect, useState } from "react";
import { accessToken, api, rememberAccess } from "../lib/index.js";

// Whether the server runs the OpenAI agent; local (Ollama) mode keeps the classic chat.
export function useAgentAvailable() {
  const [available, setAvailable] = useState(null);
  useEffect(() => {
    api("/api/health")
      .then((health) => setAvailable(!!health.agent_available))
      .catch(() => setAvailable(false));
  }, []);
  return available;
}

// One conversation per analysis, kept across review revisions.
export function useContractSession(analysisId, enabled) {
  const [state, setState] = useState({ id: null, error: "" });
  useEffect(() => {
    if (!enabled || !analysisId) return;
    api("/api/agent/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gwollion-Token": accessToken(analysisId) || "",
      },
      body: JSON.stringify({ analysis_id: analysisId }),
    })
      .then((data) => {
        rememberAccess(data.session_id, data.access_token);
        setState({ id: data.session_id, error: "" });
      })
      .catch((e) => setState({ id: null, error: e.message }));
  }, [analysisId, enabled]);
  return state;
}
