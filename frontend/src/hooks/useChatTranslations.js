import { useEffect, useState } from "react";
import { api } from "../lib/index.js";

export default function useChatTranslations(result, turns, language) {
  const [cache, setCache] = useState({});
  const [retry, setRetry] = useState(0);
  const scope = `${result.analysis_id}:${result.analysis_revision}:${language}`;
  const keyFor = (turn, index) =>
    `${scope}:${index}:${turn.answer.text_ko || turn.answer.text}`;
  const signature = JSON.stringify(
    turns.map((turn, index) => keyFor(turn, index)),
  );
  useEffect(() => {
    if (language === "ko") return;
    const controller = new AbortController();
    async function translate() {
      // Translate the latest answer first, then the older conversation.
      for (let i = turns.length - 1; i >= 0; i--) {
        const turn = turns[i];
        const key = keyFor(turn, i);
        if (turn.language === language || cache[key]?.data) continue;
        setCache((old) => ({ ...old, [key]: { pending: true } }));
        try {
          const data = await api(
            `/api/analyses/${result.analysis_id}/chat/${i + 1}/translation`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                analysis_revision: result.analysis_revision,
                language,
              }),
              signal: controller.signal,
            },
          );
          if (controller.signal.aborted) return;
          setCache((old) => ({ ...old, [key]: { data } }));
        } catch (error) {
          if (controller.signal.aborted) return;
          setCache((old) => ({ ...old, [key]: { error: error.message } }));
        }
      }
    }
    translate();
    return () => controller.abort();
  }, [scope, signature, retry]);

  return {
    turns: turns.map((turn, index) => {
      const original = turn.answer.text_ko || turn.answer.text;
      if (language === (turn.language || "ko"))
        return { ...turn, displayLanguage: language };
      if (language === "ko")
        return {
          ...turn,
          answer: { ...turn.answer, text: original },
          displayLanguage: "ko",
        };
      const translated = cache[keyFor(turn, index)];
      return {
        ...turn,
        answer: {
          ...turn.answer,
          text: translated?.data?.text || "",
          text_ko: original,
        },
        displayLanguage: language,
        translationPending: !translated?.data && !translated?.error,
        translationError: translated?.error,
      };
    }),
    retry: () => setRetry((value) => value + 1),
  };
}
