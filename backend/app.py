from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.analysis import extract, evaluate
from backend.documents import draft, translate
from backend.extraction import ollama_settings, GenerationCancelled
from backend.streaming import chat_events
from backend.knowledge import Knowledge, ROOT
from backend.schemas import AnalyzeRequest, AnswersRequest, DraftRequest, DocumentPdfRequest, AutoTranslationRequest, StandaloneDraftRequest, ChatRequest, TranslationRequest, DocumentTranslationRequest, IncidentTranslationRequest
from backend.chat import answer_question, multilingual_answer
from backend.store import Store, StaleRevision
from backend.reading import read_document, read_documents, ReadingError, ocr_available
from backend.auto_translation import TranslationUnavailable, translate_analysis
from backend.pdf_export import render_pdf
from backend.pages import highlights, ocr_words, snapshot
from starlette.concurrency import run_in_threadpool
from backend.sample_translations import sample_translation
from backend.openai_client import OpenAIError, settings as openai_settings, require_key
from backend.translation import content_hash, translate_review, translate_document, translate_incident

FRONTEND_DIR = ROOT / "frontend/dist"
SAMPLES_DIR = ROOT / "samples"


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(db_path or os.environ.get("GWOLLION_DB"))
        app.state.executor = ThreadPoolExecutor(max_workers=1)
        app.state.translator = ThreadPoolExecutor(max_workers=1)
        app.state.translation_jobs = {}
        yield
        app.state.executor.shutdown(wait=True, cancel_futures=True)
        app.state.translator.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="권리ON API", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver", *filter(None, os.environ.get("GWOLLION_ALLOWED_HOSTS", "").split(","))])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "같은 로컬 페이지에서만 요청할 수 있습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-transform" if response.headers.get("content-type", "").startswith("text/event-stream") else "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(OpenAIError)
    async def openai_error(request, exc):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)

    @app.exception_handler(StaleRevision)
    async def stale_error(request, exc):
        return JSONResponse({"detail": "분석이 갱신되거나 삭제됐습니다. 최신 결과를 확인해주세요.", "code": "stale_revision"}, status_code=409)

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
        return value["result"] or {"analysis_id": value["id"], "analysis_revision": value["revision"], "title": value["request"]["title"], "status": value["status"], "error": value["error"], "request": value["request"] if value["status"] == "failed" else None}

    def add_ocr_layout(document_id):
        store = app.state.store
        for page in store.document_pages(document_id) if document_id else []:
            if page["words"] is None:
                words = ocr_words(store.document_image(document_id, page["page"]), page["width"], page["height"])
                store.set_document_words(document_id, page["page"], words)

    def worker(id, request):
        if not app.state.store.start(id):
            return
        try:
            add_ocr_layout(request.document_id)
            blocks, terms, extraction = extract(request)
            result = evaluate(request, blocks, terms, extraction, id, 1)
            app.state.store.finish(id, result=result)
        except OpenAIError as exc:
            app.state.store.finish(id, error=str(exc))
        except ValueError as exc:
            app.state.store.finish(id, error=str(exc) if "자까지" in str(exc) else "모델 출력이나 추출값을 검증하지 못했습니다. 규칙 추출로 확인하거나 다시 시도해주세요.")
        except Exception:
            app.state.store.finish(id, error="분석을 완료하지 못했습니다. 로컬 Ollama 실행 여부와 모델을 확인하고 다시 시도해주세요.")

    @app.get("/")
    def home():
        index = FRONTEND_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(503, "화면 빌드가 없습니다. 프로젝트 루트에서 ./run_app.sh를 실행해주세요.")
        return FileResponse(index)

    # Each task has a document URL; refresh and browser back keep the current task.
    for page in ("upload", "samples", "review", "chat", "draft", "documents", "history",
                 "original", "sources", "confirm"):
        app.add_api_route(f"/{page}/", home, methods=["GET"], include_in_schema=False)

    @app.get("/api/health")
    def health():
        _, model = ollama_settings()
        key, openai_model = openai_settings()
        articles = Knowledge().articles
        return {"status": "ok", "articles": len(articles), "laws": sorted({a["law_title"] for a in articles}), "ollama_model": model, "supported_uploads": ["txt", "pdf", "jpg", "jpeg", "png", "webp"], "ocr_available": ocr_available(), "mode": "local-workspace", "openai_configured": bool(key), "openai_model": openai_model}

    @app.get("/api/samples")
    def samples():
        return json.loads((SAMPLES_DIR / "manifest.json").read_text())

    @app.get("/api/samples/{id}")
    def sample(id: str):
        items = samples()
        item = next((i for i in items if i["id"] == id), None)
        if item is None:
            raise HTTPException(404, "샘플을 찾을 수 없습니다.")
        return {**item, "text": (SAMPLES_DIR / f"{id}.txt").read_text()}

    @app.get("/api/samples/{id}/txt")
    def sample_txt(id: str):
        sample(id)
        return FileResponse(SAMPLES_DIR / f"{id}.txt", media_type="text/plain", filename=f"{id}.txt")

    @app.get("/api/samples/{id}/pdf")
    def sample_pdf(id: str):
        sample(id)
        return FileResponse(SAMPLES_DIR / "pdf" / f"{id}.pdf", media_type="application/pdf", filename=f"{id}.pdf")

    @app.get("/api/samples/{id}/png")
    def sample_png(id: str):
        sample(id)
        return FileResponse(SAMPLES_DIR / "images" / f"{id}.png", media_type="image/png", filename=f"{id}.png")

    @app.post("/api/samples/{id}/document")
    def sample_document(id: str):
        sample(id)
        pages = snapshot([((SAMPLES_DIR / "pdf" / f"{id}.pdf").read_bytes(), ".pdf")])
        return {"document_id": app.state.store.save_document(pages) if pages else None}

    @app.post("/api/uploads")
    async def upload(file: UploadFile | None = File(default=None), files: list[UploadFile] | None = File(default=None),
                     reading_mode: str = Form(default="local"), rotations: str = Form(default="[]")):
        selected = ([file] if file else []) + (files or [])
        try:
            if not 1 <= len(selected) <= 5:
                raise HTTPException(413, "사진은 최대 5장까지 등록할 수 있습니다.")
            raw_files = []
            for item in selected:
                raw = await item.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise HTTPException(413, "파일은 장당 5MB까지 업로드할 수 있습니다.")
                raw_files.append((raw, Path(item.filename or "").suffix.lower()))
            try:
                angles = json.loads(rotations)
                if not isinstance(angles, list):
                    raise ValueError()
            except ValueError:
                raise HTTPException(422, "사진 회전 정보를 확인해주세요.") from None
            # Keep the legacy single-file local API's error behavior.
            if file and not files and reading_mode == "local" and not angles:
                result = await run_in_threadpool(read_document, *raw_files[0])
            else:
                result = await run_in_threadpool(read_documents, raw_files, reading_mode, angles or None)
            pages = await run_in_threadpool(snapshot, raw_files, angles or None)
            return {**result, "filename": Path(selected[0].filename or "문서").name,
                    "document_id": app.state.store.save_document(pages) if pages else None}
        except ReadingError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        finally:
            for item in selected:
                await item.close()

    @app.post("/api/analyses", status_code=202)
    def analyze(request: AnalyzeRequest):
        if request.engine == "openai":
            require_key()
        id = str(uuid4())
        app.state.store.create(id, request.model_dump(mode="json"))
        # Serverless hosts may freeze threads once the response is sent.
        if os.environ.get("GWOLLION_INLINE_ANALYSIS"):
            worker(id, request)
        else:
            app.state.executor.submit(worker, id, request)
        return {"analysis_id": id, "analysis_revision": 1, "status": "queued"}

    @app.get("/api/analyses")
    def history():
        return app.state.store.list()

    @app.get("/api/analyses/{id}")
    def get_analysis(id: str):
        return public(row(id))

    @app.get("/api/analyses/{id}/document")
    def get_document(id: str):
        value = row(id)
        pages = app.state.store.document_pages(value["request"].get("document_id")) if value["result"] else []
        return {"pages": [{k: p[k] for k in ("page", "width", "height")} for p in pages],
                "highlights": highlights(value["result"], pages) if pages else {}}

    @app.get("/api/analyses/{id}/pages/{page}")
    def get_document_page(id: str, page: int):
        image = app.state.store.document_image(row(id)["request"].get("document_id"), page)
        if image is None:
            raise HTTPException(404, "저장된 페이지가 없습니다.")
        return Response(image, media_type="image/jpeg")

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
        result = draft(ready(id, body.analysis_revision)["result"], body.kind, body.incident, body.finding_ids, body.written_on, body.reply_by)
        result.update({"language": body.language, "incident_original": body.incident_original.model_dump() if body.incident_original else None,
                       "incident_ko": body.incident.model_dump(), "incident_confirmed": body.incident_confirmed})
        return result

    @app.post("/api/documents/pdf")
    def document_pdf(body: DocumentPdfRequest):
        return Response(render_pdf(body.text, body.title), media_type="application/pdf")

    @app.post("/api/drafts")
    def standalone_draft(body: StandaloneDraftRequest):
        return draft(None, body.kind, body.incident)

    @app.get("/api/analyses/{id}/chat")
    def chat_history(id: str, analysis_revision: int):
        ready(id, analysis_revision)
        return {"analysis_revision": analysis_revision, "turns": app.state.store.chat(id, analysis_revision)}

    async def complete_chat(id, body, value, history, progress=None, cancelled=None):
        try:
            options = {"on_progress": progress, "cancelled": cancelled} if progress else {}
            if body.engine == "openai" or body.language != "ko" or not re.search(r"[가-힣]", body.question):
                answer, question_ko = await run_in_threadpool(multilingual_answer, value["result"], body, history, **options)
            else:
                answer = await run_in_threadpool(answer_question, value["result"], body, history, **options)
                question_ko = body.question
        except GenerationCancelled:
            raise asyncio.CancelledError()
        except OpenAIError:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except Exception:
            raise HTTPException(503, "로컬 AI 답변을 완료하지 못했습니다. Ollama 실행 여부를 확인하고 다시 시도해주세요.")
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError()
        turn = {"question": body.question, "question_ko": question_ko, "language": body.language, "engine": body.engine, "finding_id": body.finding_id, "answer": answer}
        try:
            app.state.store.append_chat(id, body.analysis_revision, len(history), turn)
        except StaleRevision:
            raise HTTPException(409, "분석이나 대화가 갱신되거나 삭제됐습니다. 최신 결과를 확인해주세요.")
        return {"analysis_revision": body.analysis_revision, "turn": turn}

    @app.post("/api/analyses/{id}/chat")
    async def chat(id: str, body: ChatRequest):
        value = ready(id, body.analysis_revision)
        history = app.state.store.chat(id, body.analysis_revision)
        return await complete_chat(id, body, value, history)

    @app.post("/api/analyses/{id}/chat/stream")
    async def chat_stream(id: str, body: ChatRequest):
        value = ready(id, body.analysis_revision)
        history = app.state.store.chat(id, body.analysis_revision)
        return StreamingResponse(
            chat_events(lambda progress, cancelled: complete_chat(id, body, value, history, progress, cancelled)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    def run_translation(key, source, digest):
        id, revision, language = key
        job = app.state.translation_jobs[key]

        def progress(done, total, text, translated):
            job.update(done=done, total=total)
            if translated:
                job["blocks"].update({b["block_id"]: translated for b in source["blocks"] if b["text"] == text})

        try:
            payload = translate_analysis(source, language, progress)
            app.state.store.save_translation(id, revision, language, "auto_review", digest, payload)
            job.update(status="complete", payload=payload)
        except TranslationUnavailable:
            job.update(status="failed", error="로컬 번역 모델에 연결하지 못했습니다. Ollama 실행 여부를 확인하고 다시 시도해주세요.")
        except Exception:
            job.update(status="failed", error="번역을 완료하지 못했습니다. 다시 시도해주세요.")

    @app.post("/api/analyses/{id}/auto-translation")
    def auto_translation(id: str, body: AutoTranslationRequest):
        """Start or poll the local translation; repeat the call until status is complete."""
        source = ready(id, body.analysis_revision)["result"]
        digest = content_hash({"blocks": source["blocks"], "review": source["review"], "issues": source["issues"]})
        cached = app.state.store.translation(id, body.analysis_revision, body.language, "auto_review", digest)
        if cached:
            return {"status": "complete", **cached}
        bundled = sample_translation(source, body.language)
        if bundled:
            return {"status": "complete", **bundled}
        key, jobs = (id, body.analysis_revision, body.language), app.state.translation_jobs
        job = jobs.get(key)
        if job is None:
            job = jobs[key] = {"status": "running", "done": 0, "total": 0, "blocks": {}}
            app.state.translator.submit(run_translation, key, source, digest)
        if job["status"] == "running":
            return {k: job[k] for k in ("status", "done", "total")} | {"blocks": dict(job["blocks"])}
        del jobs[key]
        return {"status": "complete", **job["payload"]} if job["status"] == "complete" else {"status": "failed", "error": job["error"]}

    def cached_translation(id, revision, language, purpose, source, make):
        ready(id, revision)
        digest = content_hash(source)
        cached = app.state.store.translation(id, revision, language, purpose, digest)
        if cached:
            return cached
        result = make()
        app.state.store.save_translation(id, revision, language, purpose, digest, result)
        return result

    @app.post("/api/analyses/{id}/chat/{turn}/translation")
    def chat_translation(id: str, turn: int, body: AutoTranslationRequest):
        from backend.chat_translation import local_fields
        ready(id, body.analysis_revision)
        turns = app.state.store.chat(id, body.analysis_revision)
        if turn < 1 or turn > len(turns):
            raise HTTPException(404, "대화를 찾을 수 없습니다.")
        item = turns[turn - 1]
        source = item['answer'].get('text_ko') or item['answer']['text']
        if item.get('language', 'ko') == body.language:
            return {'text': item['answer']['text'], 'text_ko': source, 'language': body.language}
        try:
            return cached_translation(id, body.analysis_revision, body.language, f'chat:{turn}', source,
                lambda: {'text': local_fields({'answer': source}, body.language)['answer'], 'text_ko': source, 'language': body.language})
        except StaleRevision:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(503, "답변 번역을 완료하지 못했습니다. 잠시 후 다시 시도해주세요.") from None

    @app.post("/api/analyses/{id}/document-translations")
    def document_translations(id: str, body: DocumentTranslationRequest):
        return cached_translation(id, body.analysis_revision, body.language, "document", body.text,
                                  lambda: {**translate_document(body.text, body.language), "analysis_id": id, "analysis_revision": body.analysis_revision})

    @app.post("/api/analyses/{id}/incident-translations")
    def incident_translations(id: str, body: IncidentTranslationRequest):
        return cached_translation(id, body.analysis_revision, body.language, "incident", body.incident.model_dump(),
                                  lambda: translate_incident(body.incident))

    @app.post("/api/analyses/{id}/translations")
    def translations(id: str, body: TranslationRequest):
        result = ready(id, body.analysis_revision)["result"]
        if body.engine == "openai":
            return cached_translation(id, body.analysis_revision, body.language, "review", result,
                                      lambda: translate_review(result, body.language))
        return translate(result, body.language)

    @app.get("/api/sources")
    def search_sources(q: str = "근로시간"):
        return Knowledge().search(q[:200])

    @app.get("/api/evidence/status")
    def evidence_status():
        from backend.corpus import Corpus
        from backend.legal_api import LegalAPI
        try:
            configured = bool(LegalAPI().oc)
        except ValueError:
            configured = False
        return {"corpus": Corpus().status(), "official_api_configured": configured,
                "targets": ["eflaw", "prec", "expc", "decc"],
                "privacy": "원문·검토·대화는 로컬 DB에 저장됩니다. OpenAI 선택 시 이미지·텍스트가 OpenAI API로 전달됩니다. store:false는 완전한 무보관을 뜻하지 않습니다. 공식 법령 API에는 일반 법률 쟁점만 전송합니다."}

    @app.delete("/api/analyses/{id}", status_code=204)
    def delete(id: str):
        if not app.state.store.delete(id):
            raise HTTPException(404, "분석을 찾을 수 없습니다.")

    if (FRONTEND_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")
    return app


app = create_app()
