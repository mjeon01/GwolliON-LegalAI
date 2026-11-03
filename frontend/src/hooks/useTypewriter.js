import { useEffect, useMemo, useState } from "react";

const segmenter =
  typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;
export default function useTypewriter(text, scope) {
  const [frame, setFrame] = useState({ scope: null, count: 0 });
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const characters = useMemo(
    () =>
      segmenter
        ? Array.from(segmenter.segment(text), (part) => part.segment)
        : Array.from(text),
    [text],
  );
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReducedMotion(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (reducedMotion || !text) return;
    let count = frame.scope === scope ? frame.count : 0;
    let last = performance.now();
    let handle;
    const tick = (now) => {
      // Smooth glyphs, bounded catch-up after a tab has been in the background.
      const step = Math.min(12, Math.floor((now - last) / 12));
      if (step > 0) {
        count = Math.min(characters.length, count + step);
        last = now;
        setFrame({ scope, count });
      }
      if (count < characters.length) handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, [text, scope, reducedMotion]);
  return reducedMotion
    ? text
    : characters.slice(0, frame.scope === scope ? frame.count : 0).join("");
}
