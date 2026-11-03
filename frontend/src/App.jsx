import { Component, lazy, Suspense, useEffect } from "react";
import { analysisId, page, useAnalysis } from "./lib.js";
import {
  ButtonLink,
  Empty,
  ErrorNotice,
  Header,
  Loading,
} from "./components/UI.jsx";
import Upload from "./pages/Upload.jsx";
import Review, { Confirm, Original, Sources } from "./pages/Review.jsx";
import Chat from "./pages/Chat.jsx";
import Draft from "./pages/Draft.jsx";
import { Library, Samples } from "./pages/Library.jsx";
const Hero = lazy(() => import("./components/Hero.jsx"));
const titles = {
  home: "어려운 계약서, 내 권리부터 명확하게",
  upload: "계약서 등록",
  review: "검토 결과",
  chat: "질문하기",
  draft: "문서 작성",
  history: "검토 기록",
  samples: "샘플 계약서",
  original: "계약서 원문",
  sources: "근거 자료",
  confirm: "추가 정보 확인",
};
function AnalysisPage() {
  const { data, error, loading } = useAnalysis(analysisId);
  if (!analysisId)
    return (
      <Library
        selector
        target={
          page === "chat"
            ? "chat"
            : page === "draft" || page === "documents"
              ? "draft"
              : "review"
        }
      />
    );
  if (loading) return <Loading text="계약서를 검토하고 있습니다." />;
  if (error)
    return (
      <>
        <ErrorNotice message={error} />
        <Empty
          title="이 계약서를 불러오지 못했습니다."
          action={<ButtonLink to="/history/">검토 기록으로</ButtonLink>}
        >
          기록에서 다른 계약서를 선택하거나 다시 등록해주세요.
        </Empty>
      </>
    );
  const View = {
    review: Review,
    chat: Chat,
    draft: Draft,
    documents: Draft,
    original: Original,
    sources: Sources,
    confirm: Confirm,
  }[page];
  return View && data ? <View result={data} /> : null;
}
class ErrorBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="workspace">
        <ErrorNotice message="화면을 표시하지 못했습니다. 다시 불러오거나 검토 기록으로 이동해주세요." />
        <ButtonLink to="/history/">검토 기록</ButtonLink>
      </div>
    ) : (
      this.props.children
    );
  }
}
export default function App() {
  useEffect(() => {
    document.title = `${titles[page] || "작업 공간"} · 권리ON`;
  }, []);
  return (
    <ErrorBoundary>
      {page === "home" ? (
        <Suspense fallback={<Loading />}>
          <Hero />
        </Suspense>
      ) : (
        <div className="app-shell">
          <Header />
          <main id="main" className="workspace">
            {page === "upload" ? (
              <Upload />
            ) : page === "samples" ? (
              <Samples />
            ) : page === "history" ? (
              <Library />
            ) : [
                "review",
                "chat",
                "draft",
                "documents",
                "original",
                "sources",
                "confirm",
              ].includes(page) ? (
              <AnalysisPage />
            ) : (
              <Empty
                title="이 페이지는 현재 작업 공간에 없습니다."
                action={<ButtonLink to="/">메인화면으로</ButtonLink>}
              >
                상단 메뉴에서 필요한 작업을 선택해주세요.
              </Empty>
            )}
          </main>
          <footer className="workspace-footer">
            <a href="/" className="footer-brand">
              권리
              <span className="brand-on" lang="en">
                ON
              </span>
            </a>
            <p>계약을 이해하고, 다음을 준비하는 공간.</p>
            <span>LOCAL WORKSPACE</span>
          </footer>
        </div>
      )}
    </ErrorBoundary>
  );
}
