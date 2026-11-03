import { useEffect, useId, useRef, useState } from "react";
import { setLanguage, t, useLanguage } from "../i18n/index.js";

const languages = [
  { code: "ko", label: "한국어", htmlLang: "ko", short: "KO" },
  { code: "zh", label: "中文", htmlLang: "zh-Hans", short: "ZH" },
  { code: "es", label: "Español", htmlLang: "es", short: "ES" },
];

export default function LanguagePicker({ onOpen }) {
  const lang = useLanguage();
  const [open, setOpen] = useState(false);
  const root = useRef();
  const trigger = useRef();
  const options = useRef([]);
  const id = useId();
  const current = languages.find((item) => item.code === lang);

  useEffect(() => {
    if (!open) return;
    options.current[languages.findIndex((item) => item.code === lang)]?.focus();
    const outside = (event) => {
      if (!root.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, lang]);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  return (
    <div
      ref={root}
      className="language-picker"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}
    >
      <button
        type="button"
        ref={trigger}
        className="language-trigger"
        aria-label={`${t("화면 언어")}: ${current.label}`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => {
          if (!open) onOpen?.();
          setOpen(!open);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            onOpen?.();
            setOpen(true);
          }
        }}
      >
        <svg className="language-globe" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <ellipse cx="12" cy="12" rx="4" ry="9" />
          <path d="M3 12h18" />
        </svg>
        <span lang={current.htmlLang}>{current.label}</span>
        <svg
          className="language-chevron"
          viewBox="0 0 16 16"
          aria-hidden="true"
        >
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {open && (
        <div
          className="language-popover"
          id={id}
          role="group"
          aria-label={t("화면 언어")}
        >
          <p className="language-caption">{t("화면 언어")}</p>
          {languages.map((item, index) => (
            <button
              type="button"
              key={item.code}
              ref={(element) => {
                options.current[index] = element;
              }}
              className="language-option"
              data-language={item.code}
              lang={item.htmlLang}
              aria-pressed={lang === item.code}
              onClick={() => {
                setLanguage(item.code);
                close();
              }}
              onKeyDown={(event) => {
                const next = {
                  ArrowDown: (index + 1) % languages.length,
                  ArrowUp: (index + languages.length - 1) % languages.length,
                  Home: 0,
                  End: languages.length - 1,
                }[event.key];
                if (next !== undefined) {
                  event.preventDefault();
                  options.current[next]?.focus();
                }
              }}
            >
              <span className="language-code" aria-hidden="true">
                {item.short}
              </span>
              <span>{item.label}</span>
              {lang === item.code && (
                <svg
                  className="language-check"
                  viewBox="0 0 20 20"
                  aria-hidden="true"
                >
                  <path d="m4 10 4 4 8-8" />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
