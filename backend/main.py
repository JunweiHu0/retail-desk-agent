"""FastAPI transport. Localhost by default; session capabilities protect customer data."""

import asyncio
import hmac
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config
from backend.agent import AgentRunner
from backend.retail import RetailService
from backend.store import Store

log = logging.getLogger(__name__)


def create_app(store=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or Store()
        app.state.retail = RetailService(app.state.store)
        app.state.runner = AgentRunner(app.state.retail)
        app.state.busy = set()
        app.state.guard = threading.Lock()
        app.state.tasks = set()
        yield

    app = FastAPI(title="Retail Agent API", version="0.1.0", lifespan=lifespan)

    def authorized(sid: str, authorization: str = Header(default="")):
        try:
            session = app.state.store.session(sid)
        except LookupError:
            raise HTTPException(404, "会话不存在") from None
        if not hmac.compare_digest(authorization, f"Bearer {session['token']}"):
            raise HTTPException(403, "无权访问此会话")
        return session

    @contextmanager
    def exclusive(sid):
        with app.state.guard:
            if sid in app.state.busy:
                raise HTTPException(409, "会话正在处理请求，请稍后再试")
            app.state.busy.add(sid)
        try:
            yield
        finally:
            with app.state.guard:
                app.state.busy.discard(sid)

    def snapshot(sid):
        session = app.state.store.session(sid)
        return {
            k: session[k]
            for k in ("id", "title", "created_at", "updated_at", "messages", "transferred")
        } | {"context": app.state.retail.context(sid), "events": app.state.store.events(sid)}

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "mode": config.MODE,
            "model": "offline-demo" if config.MODE == "demo" else config.MODEL,
            "model_ready": config.MODE == "demo" or bool(config.API_KEY),
            "tools": len(app.state.retail.catalog),
            "domain": "retail",
        }

    @app.get("/api/samples")
    def samples():
        return {"samples": app.state.retail.samples()}

    @app.post("/api/sessions", status_code=201)
    def create_session():
        return app.state.store.create_session()

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str, session=Depends(authorized)):
        return snapshot(sid)

    class ChatInput(BaseModel):
        message: str = Field(min_length=1, max_length=8000)

    @app.post("/api/sessions/{sid}/messages")
    async def chat(sid: str, body: ChatInput, request: Request, session=Depends(authorized)):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "消息不能为空")
        if session["pending"] or session["transferred"]:
            raise HTTPException(409, "请先处理待确认操作，或新建会话")
        if config.MODE == "live" and not config.API_KEY:
            raise HTTPException(503, "请在后端 .env 配置模型 API Key 后重启")
        with app.state.guard:
            if sid in app.state.busy:
                raise HTTPException(409, "会话正在处理请求")
            app.state.busy.add(sid)
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(event):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def process():
            try:
                await asyncio.to_thread(app.state.runner.run, sid, text, emit)
                emit({"type": "done", "session": snapshot(sid)})
            except Exception as exc:
                log.error("Agent turn failed: %s", type(exc).__name__)
                message = "模型请求未完成，请检查后端日志、API 配置或网络后重试。工具和已确认操作的结果仍保存在会话中。"
                with app.state.store.tx() as cx:
                    current = app.state.store.session(sid, cx)
                    app.state.store.update(
                        cx,
                        sid,
                        messages=current["messages"]
                        + [{"id": uuid.uuid4().hex, "role": "assistant", "content": message}],
                    )
                    app.state.store.event(cx, sid, "error", {"error_type": type(exc).__name__})
                emit({"type": "error", "message": message, "session": snapshot(sid)})
            finally:
                with app.state.guard:
                    app.state.busy.discard(sid)
                emit(None)

        task = asyncio.create_task(process())
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)

        async def events():
            yield 'data: {"type":"status","message":"正在理解请求并查询业务工具"}\n\n'
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    class Decision(BaseModel):
        action_id: str = Field(min_length=1, max_length=64)
        approve: bool

    @app.post("/api/sessions/{sid}/decisions")
    def decide(sid: str, body: Decision, session=Depends(authorized)):
        with exclusive(sid):
            try:
                receipt = app.state.runner.decide(sid, body.action_id, body.approve)
            except (ValueError, PermissionError) as exc:
                raise HTTPException(409, str(exc)) from None
        return {"receipt": receipt, "session": snapshot(sid)}

    dist = config.ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
