"""SSE transport: live generation status, then validated answer chunks and commit."""
import asyncio
import json
import time
from threading import Event

from fastapi import HTTPException
from backend.openai_client import OpenAIError


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_events(complete):
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancelled = Event()
    last_phase, last_time = "", 0

    def progress(phase):
        nonlocal last_phase, last_time
        now = time.monotonic()
        if cancelled.is_set() or (phase == last_phase and now - last_time < 0.5):
            return
        last_phase, last_time = phase, now
        loop.call_soon_threadsafe(queue.put_nowait, ("status", {"phase": phase}))

    async def run():
        try:
            result = await complete(progress, cancelled)
            await queue.put(("result", result))
        except OpenAIError as exc:
            await queue.put(("error", {"detail": str(exc), "code": exc.code, "status": exc.status}))
        except HTTPException as exc:
            await queue.put(("error", {"detail": exc.detail, "status": exc.status_code}))
        except Exception:
            await queue.put(("error", {"detail": "답변 수신이 중단되었습니다. 다시 시도해주세요.", "status": 503}))

    task = asyncio.create_task(run())
    try:
        yield event("status", {"phase": "preparing"})
        while True:
            try:
                name, data = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if name == "result":
                # Never display speculative JSON tokens. Existing citation and role
                # validation must succeed and the conversation must be saved first.
                text = data["turn"]["answer"]["text"]
                for offset in range(0, len(text), 24):
                    yield event("delta", {"text": text[offset:offset + 24]})
                yield event("done", data)
                break
            yield event(name, data)
            if name == "error":
                break
    finally:
        cancelled.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
