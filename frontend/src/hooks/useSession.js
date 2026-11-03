import { useEffect, useState } from "react";
import { readSession, saveSession } from "../lib/index.js";

export default function useSession(key, initial) {
  const [state, setState] = useState(() => ({
    key,
    value: readSession(key, initial),
  }));
  if (state.key !== key) setState({ key, value: readSession(key, initial) });
  useEffect(() => saveSession(state.key, state.value), [state]);
  return [
    state.value,
    (update) =>
      setState((old) => ({
        key,
        value: typeof update === "function" ? update(old.value) : update,
      })),
  ];
}
