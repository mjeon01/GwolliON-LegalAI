from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mvp.analysis import extract, evaluate
from mvp.documents import draft, translate
from mvp.extraction import ollama_settings
from mvp.knowledge import Knowledge, ROOT
from mvp.schemas import AnalyzeRequest, AnswersRequest, DraftRequest, StandaloneDraftRequest, ChatRequest, TranslationRequest
from mvp.chat import answer_question
from mvp.store import Store, StaleRevision
from mvp.reading import read_document, ReadingError, ocr_available
from starlette.concurrency import run_in_threadpool


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(db_path or os.environ.get("GWOLLION_DB"))
        app.state.executor = ThreadPoolExecutor(max_workers=1)
        yield
        app.state.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="권리ON 1차 MVP", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "같은 로컬 페이지에서만 요청할 수 있습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    def row(id):
        value = app.state.store.get(id)
        if not value:
            raise HTTPException(404, "분석을 찾을 수 없습니다. 삭제되었을 수 있습니다.")
        return value

    def ready(id, revision):
        value = row(id)
        if value["revision"] != revision:
            raise HTTPException(409, "결과가 갱신됐습니다. 최신 분석을 불러와 다시 진행해주세요.")
        if value["status"] not in {"completed", "awaiting_input"} or not value["result"]:
            raise HTTPException(409, "분석 완료 후 진행해주세요.")
        return value

    def public(value):
        return value["result"] or {"analysis_id": value["id"], "analysis_revision": value["revision"], "title": value["request"]["title"], "status": value["status"], "error": value["error"]}

    def worker(id, request):
        if not app.state.store.start(id):
            return
        try:
            blocks, terms, extraction = extract(request)
            result = evaluate(request, blocks, terms, extraction, id, 1)
            app.state.store.finish(id, result=result)
        except ValueError as exc:
            app.state.store.finish(id, error=str(exc) if "자까지" in str(exc) else "모델 출력이나 추출값을 검증하지 못했습니다. 규칙 추출로 확인하거나 다시 시도해주세요.")
        except Exception:
            app.state.store.finish(id, error="분석을 완료하지 못했습니다. 로컬 Ollama 실행 여부와 모델을 확인하고 다시 시도해주세요.")

    @app.get("/")
    def home():
        return FileResponse(ROOT / "mvp/static/index.html")

    @app.get("/api/health")
    def health():
        _, model = ollama_settings()
        articles = Knowledge().articles
        return {"status": "ok", "articles": len(articles), "laws": sorted({a["law_title"] for a in articles}), "ollama_model": model, "supported_uploads": ["txt", "pdf", "jpg", "jpeg", "png", "webp"], "ocr_available": ocr_available(), "mode": "local-mvp"}

    @app.get("/api/samples")
    def samples():
        return json.loads((ROOT / "samples/manifest.json").read_text())

    @app.get("/api/samples/{id}")
    def sample(id: str):
        items = samples()
        item = next((i for i in items if i["id"] == id), None)
        if item is None:
            raise HTTPException(404, "샘플을 찾을 수 없습니다.")
        return {**item, "text": (ROOT / "samples" / f"{id}.txt").read_text()}

    @app.get("/api/samples/{id}/pdf")
    def sample_pdf(id: str):
        sample(id)
        return FileResponse(ROOT / "output/pdf" / f"{id}.pdf", media_type="application/pdf", filename=f"{id}.pdf")

    @app.post("/api/uploads")
    async def upload(file: UploadFile):
        raw = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(413, "파일은 5MB까지 업로드할 수 있습니다.")
        suffix = Path(file.filename or "").suffix.lower()
        try:
            result = await run_in_threadpool(read_document, raw, suffix)
        except ReadingError as exc:
            raise HTTPException(exc.status, str(exc))
        return {**result, "filename": Path(file.filename or "문서").name}

    @app.post("/api/analyses", status_code=202)
    def analyze(request: AnalyzeRequest):
        id = str(uuid4())
        app.state.store.create(id, request.model_dump(mode="json"))
        app.state.executor.submit(worker, id, request)
        return {"analysis_id": id, "analysis_revision": 1, "status": "queued"}

    @app.get("/api/analyses")
    def history():
        return app.state.store.list()

    @app.get("/api/analyses/{id}")
    def get_analysis(id: str):
        return public(row(id))

    @app.post("/api/analyses/{id}/answers")
    def answers(id: str, body: AnswersRequest):
        value = ready(id, body.analysis_revision)
        context = {**value["request"]["context"], **body.context.model_dump(mode="json", exclude_unset=True)}
        request = AnalyzeRequest(**{**value["request"], "context": context})
        previous = value["result"]
        result = evaluate(request, previous["blocks"], previous["terms"], previous["extraction"], id, body.analysis_revision + 1)
        try:
            app.state.store.revise(id, body.analysis_revision, request.model_dump(mode="json"), result)
        except StaleRevision:
            raise HTTPException(409, "분석이 갱신되거나 삭제됐습니다. 최신 결과를 확인해주세요.")
        return result

    @app.post("/api/analyses/{id}/drafts")
    def drafts(id: str, body: DraftRequest):
        return draft(ready(id, body.analysis_revision)["result"], body.kind, body.incident)

    @app.post("/api/drafts")
    def standalone_draft(body: StandaloneDraftRequest):
        return draft(None, body.kind, body.incident)

    @app.get("/api/analyses/{id}/chat")
    def chat_history(id: str, analysis_revision: int):
        ready(id, analysis_revision)
        return {"analysis_revision": analysis_revision, "turns": app.state.store.chat(id, analysis_revision)}

    @app.post("/api/analyses/{id}/chat")
    async def chat(id: str, body: ChatRequest):
        value = ready(id, body.analysis_revision)
        history = app.state.store.chat(id, body.analysis_revision)
        try:
            answer = await run_in_threadpool(answer_question, value["result"], body, history)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            raise HTTPException(503, "로컬 AI 답변을 완료하지 못했습니다. Ollama 실행 여부를 확인하고 다시 시도해주세요.")
        turn = {"question": body.question, "finding_id": body.finding_id, "answer": answer}
        try:
            app.state.store.append_chat(id, body.analysis_revision, len(history), turn)
        except StaleRevision:
            raise HTTPException(409, "분석이나 대화가 갱신되거나 삭제됐습니다. 최신 결과를 확인해주세요.")
        return {"analysis_revision": body.analysis_revision, "turn": turn}

    @app.post("/api/analyses/{id}/translations")
    def translations(id: str, body: TranslationRequest):
        return translate(ready(id, body.analysis_revision)["result"], body.language)

    @app.get("/api/sources")
    def search_sources(q: str = "근로시간"):
        return Knowledge().search(q[:200])

    @app.get("/api/evidence/status")
    def evidence_status():
        from mvp.corpus import Corpus
        from mvp.legal_api import LegalAPI
        try:
            configured = bool(LegalAPI().oc)
        except ValueError:
            configured = False
        return {"corpus": Corpus().status(), "official_api_configured": configured,
                "targets": ["eflaw", "prec", "expc", "decc"],
                "privacy": "계약서와 사용자 설명은 로컬에서 처리합니다. 공식 API에는 일반 법률 쟁점만 전송합니다."}

    @app.delete("/api/analyses/{id}", status_code=204)
    def delete(id: str):
        if not app.state.store.delete(id):
            raise HTTPException(404, "분석을 찾을 수 없습니다.")

    app.mount("/static", StaticFiles(directory=ROOT / "mvp/static"), name="static")
    return app


app = create_app()
