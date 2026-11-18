"""Shared browser/evaluator HTTP boundary for isolated Retail episodes."""

import asyncio
import hmac
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from tau2.domains.retail.data_model import RetailDB

from backend import config, infra
from backend.agent import AgentRunner
from backend.provenance import runtime_manifest
from backend.retail import RetailService
from backend.store import Store

log = logging.getLogger(__name__)
Variant = Literal["b1", "state", "errors", "guide", "enhanced", "c1"]


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = None
    variant: Variant = "b1"


class EvalEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_db: RetailDB
    customer_id: str
    variant: Variant = "b1"
    task_id: str
    trial_id: str | int = 0
    seed: int = 0
    metadata: dict = Field(default_factory=dict)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8000)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1, max_length=64)
    approve: bool


class FinishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="user_stop", min_length=1, max_length=80)


def create_app(store=None, runner=None, artifact_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or Store()
        app.state.retail = RetailService(app.state.store)
        app.state.runner = runner or AgentRunner(app.state.retail)
        app.state.manifest = runtime_manifest()
        app.state.artifact_dir = artifact_dir or (
            store.path.parent / "episodes" if store else config.ARTIFACT_DIR
        )
        app.state.busy = set()
        app.state.guard = threading.Lock()
        app.state.tasks = set()
        yield
        if app.state.tasks:
            await asyncio.gather(*app.state.tasks, return_exceptions=True)

    app = FastAPI(title="Retail Agent API", version="0.2.0", lifespan=lifespan)

    def get_session(sid):
        try:
            return app.state.store.session(sid)
        except LookupError:
            raise HTTPException(404, "会话不存在") from None

    def authorized(sid: str, authorization: str = Header(default="")):
        session = get_session(sid)
        if not hmac.compare_digest(authorization, f"Bearer {session['token']}"):
            raise HTTPException(403, "无权访问此会话")
        return session

    def eval_authorized(authorization: str = Header(default="")):
        if not config.EVAL_API_TOKEN:
            raise HTTPException(503, "评测接口尚未配置")
        if not hmac.compare_digest(authorization, f"Bearer {config.EVAL_API_TOKEN}"):
            raise HTTPException(403, "无权访问评测接口")

    @contextmanager
    def exclusive(sid):
        with app.state.guard:
            if sid in app.state.busy:
                raise HTTPException(409, "会话正在处理请求")
            app.state.busy.add(sid)
        try:
            yield
        finally:
            with app.state.guard:
                app.state.busy.discard(sid)

    def snapshot(sid):
        session = get_session(sid)
        manifest = app.state.manifest | {
            key: value for key, value in session["manifest"].items() if key != "metadata"
        }
        return {
            key: session[key]
            for key in (
                "id",
                "title",
                "created_at",
                "updated_at",
                "messages",
                "transferred",
                "variant",
                "status",
                "termination_reason",
                "usage",
            )
        } | {
            "manifest": manifest,
            "context": app.state.retail.context(sid),
            "events": app.state.store.events(sid),
        }

    def export(sid, label):
        with app.state.store.tx() as cx:
            db = app.state.store.dataset(cx, sid)
        state = snapshot(sid)
        result = {
            "db": db,
            "session": state,
            "manifest": state["manifest"],
            "agent_state": get_session(sid)["agent_state"],
        }
        directory = app.state.artifact_dir / sid
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{label}-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "mode": config.MODE,
            "model": app.state.manifest["model"],
            "thinking": config.MODEL_THINKING,
            "model_ready": config.MODE == "demo" or bool(config.API_KEY),
            "tools": len(app.state.retail.catalog),
            "domain": "retail",
            "variants": list(config.VARIANTS),
            "protocol_version": "retail-http-v1",
        }

    @app.get("/api/samples")
    def samples():
        return {"samples": app.state.retail.samples()}

    @app.post("/api/sessions", status_code=201)
    def create_session(body: CreateSession | None = None):
        body = body or CreateSession()
        try:
            ref = app.state.store.create_session(user_id=body.scenario_id, variant=body.variant)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return ref

    @app.get("/api/sessions/{sid}")
    def session_snapshot(sid: str, session=Depends(authorized)):
        return snapshot(sid)

    def stream_turn(sid, operation, args):
        if config.MODE == "live" and not config.API_KEY:
            raise HTTPException(503, "真实模型服务尚未配置")
        with app.state.guard:
            if sid in app.state.busy:
                raise HTTPException(409, "会话正在处理请求")
            current = get_session(sid)
            if current["status"] == "finished":
                raise HTTPException(409, "任务已结束，请新建会话")
            if operation == "message" and (current["pending"] or current["transferred"]):
                raise HTTPException(409, "请先处理待确认操作，或新建会话")
            if operation == "decision":
                if not current["pending"] or current["pending"]["id"] != args[0]:
                    raise HTTPException(409, "操作已处理或不存在，请刷新会话")
            app.state.busy.add(sid)
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(event):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def process():
            try:
                with app.state.store.tx() as cx:
                    current = app.state.store.session(sid, cx)
                    if current["status"] != "finished":
                        app.state.store.update(cx, sid, status="running")
                if current["status"] == "finished":
                    emit({"type": "done", "session": snapshot(sid)})
                    return
                if operation == "message":
                    await asyncio.to_thread(app.state.runner.run, sid, args[0], emit)
                else:
                    await asyncio.to_thread(app.state.runner.decide, sid, *args, emit=emit)
                current = get_session(sid)
                if current["status"] == "running":
                    with app.state.store.tx() as cx:
                        app.state.store.update(
                            cx,
                            sid,
                            status="awaiting_confirmation" if current["pending"] else "ready",
                        )
                export(sid, "turn")
                emit({"type": "done", "session": snapshot(sid)})
            except Exception as exc:
                log.error("Episode turn failed: %s", type(exc).__name__)
                message = "本轮未能完成；已提交的操作仍然有效。请查看执行回执和当前订单。"
                with app.state.store.tx() as cx:
                    current = app.state.store.session(sid, cx)
                    app.state.store.update(
                        cx,
                        sid,
                        status=(
                            "finished"
                            if current["status"] == "finished"
                            else "awaiting_confirmation"
                            if current["pending"]
                            else "error"
                        ),
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
            yield 'data: {"type":"status","message":"正在处理本轮请求"}\n\n'
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

    @app.post("/api/sessions/{sid}/messages")
    async def chat(sid: str, body: ChatInput, session=Depends(authorized)):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "消息不能为空")
        return stream_turn(sid, "message", (text,))

    @app.post("/api/sessions/{sid}/decisions")
    async def decide(sid: str, body: Decision, session=Depends(authorized)):
        return stream_turn(sid, "decision", (body.action_id, body.approve))

    @app.post("/internal/eval/episodes", dependencies=[Depends(eval_authorized)], status_code=201)
    def create_episode(body: EvalEpisode):
        try:
            ref = app.state.store.create_session(
                user_id=body.customer_id,
                variant=body.variant,
                initial_db=body.initial_db,
                task_id=body.task_id,
                trial_id=body.trial_id,
                seed=body.seed,
                metadata=body.metadata,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        state = snapshot(ref["id"])
        return {"session": ref, "manifest": state["manifest"]}

    @app.get("/internal/eval/episodes/{sid}/snapshot", dependencies=[Depends(eval_authorized)])
    def eval_snapshot(sid: str):
        get_session(sid)
        with exclusive(sid):
            return export(sid, "snapshot")

    @app.post("/internal/eval/episodes/{sid}/finish", dependencies=[Depends(eval_authorized)])
    async def finish_episode(sid: str, body: FinishInput):
        get_session(sid)
        # Seal business state immediately. A pending model response may drain, but
        # the service and runner cannot execute tools or reopen this episode.
        app.state.store.finish(sid, body.reason)
        deadline = asyncio.get_running_loop().time() + config.MODEL_REQUEST_TIMEOUT_SECONDS + 10
        while sid in app.state.busy:
            if asyncio.get_running_loop().time() >= deadline:
                raise HTTPException(409, "任务已冻结，正在等待模型调用结束")
            await asyncio.sleep(0.05)
        return export(sid, "final")

    app.include_router(infra.router)
    web = config.ROOT / "web"
    if (web / "infra/index.html").is_file():
        app.mount("/infra", StaticFiles(directory=web / "infra", html=True), name="infra")
    dist = config.ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
