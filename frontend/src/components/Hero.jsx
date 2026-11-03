import { t } from "../i18n/index.js";
import { useRef, useState } from "react";
import JusticeStatue from "./JusticeStatue.jsx";
import { Header, Icon } from "./UI.jsx";
export default function Hero() {
  const sectionRef = useRef(null);
  const [paused, setPaused] = useState(false);
  return (
    <section
      className={`hero ${paused ? "motion-paused" : ""}`}
      ref={sectionRef}
    >
      <div className="hero-scene" aria-hidden="true">
        <div className="scene-light" />
        <div className="scene-haze" />
        <JusticeStatue trackRef={sectionRef} paused={paused} />
        <div className="scene-shade" />
        <div className="scene-grain" />
      </div>
      <Header home />
      <main className="hero-main" id="main">
        <div className="hero-copy">
          <p className="eyebrow reveal" lang="en">
            <span className="rule" /> KNOW YOUR RIGHTS
          </p>
          <h1 className="reveal">
            {t("어려운 계약서,")}
            <br />
            {t("내 권리부터")}
            <br />
            <span>{t("명확하게.")}</span>
          </h1>
          <p className="hero-description reveal">
            {t("불리한 조항을 찾고, 궁금한 내용을 묻고.")}
            <br />
            {t("상담에 필요한 문서까지 준비하세요.")}
          </p>
          <div className="ctas reveal">
            <a href="/upload/" className="btn btn-primary">
              {t("계약서 검토 시작")}
              <Icon />
            </a>
            <a href="/samples/" className="btn btn-ghost">
              {t("샘플로 먼저 살펴보기")}
              <Icon />
            </a>
          </div>
          <p className="hero-scope reveal">
            {t("근로 · 주택 임대차 · 매매계약")}
          </p>
        </div>
      </main>
      <div className="hero-bottom">
        <p>
          <span className="status-dot" />
          {t("나의 권리를 켜다.")}
          {t(" ")}
          <strong>
            {t("권리")}
            <span lang="en">ON</span>
          </strong>
        </p>
        <button
          className="motion-control"
          onClick={() => setPaused(!paused)}
          aria-pressed={paused}
          aria-label={t(paused ? "배경 움직임 재생" : "배경 움직임 멈춤")}
        >
          <span
            className={paused ? "play-symbol" : "pause-symbol"}
            aria-hidden="true"
          />
        </button>
      </div>
    </section>
  );
}
