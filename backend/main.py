"""Shared browser/evaluator HTTP boundary for isolated Retail episodes."""

import asyncio
import hmac
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from tau2.domains.retail.data_model import RetailDB

from backend import config, infra
from backend.agent import AgentRunner
from backend.auth import SESSION_TTL, AuthService
from backend.provenance import runtime_manifest
from backend.retail import RetailService
from backend.store import Store

log = logging.getLogger(__name__)
Variant = Literal[
    "b1",
    "tools_described",
    "tools_structured",
    "tools_extended",
    "lg_b1",
    "lg_described",
    "lg_structured",
    "lg_extended",
    "lg_guided",
    "lg_context",
    "lg_sop",
    "lg_notes",
    "lg_review",
]


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
        app.state.auth = AuthService(app.state.store, os.getenv("DEMO_ACCOUNTS", "1") == "1")
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

    prefix = os.getenv("APP_BASE_PATH", "").rstrip("/")
    cookie_path = prefix + "/"
    app = FastAPI(title="Retail Agent API", version="0.3.0", lifespan=lifespan, root_path=prefix)

    @app.middleware("http")
    async def same_origin(request, call_next):
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and urlparse(origin).netloc != request.headers.get("host")
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(prefix + "/api/") or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def identity(request: Request):
        uid = app.state.auth.current(request.cookies.get("retail_auth"))
        if not uid:
            raise HTTPException(401, "请先登录")
        return uid

    def customer(uid):
        with app.state.store.tx() as cx:
            return app.state.store.dataset(cx)["users"][uid]

    class Login(BaseModel):
        email: str = Field(min_length=3, max_length=254)
        password: str = Field(min_length=1, max_length=128)

    class Registration(Login):
        password: str = Field(min_length=10, max_length=128)
        first_name: str = Field(min_length=1, max_length=60)
        last_name: str = Field(min_length=1, max_length=60)

    @app.post("/api/auth/register", status_code=201)
    def register(body: Registration):
        if "@" not in body.email or not body.first_name.strip() or not body.last_name.strip():
            raise HTTPException(422, "请填写有效邮箱和姓名")
        try:
            app.state.auth.register(
                body.email, body.password, body.first_name.strip(), body.last_name.strip()
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"message": "注册成功，请登录"}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        try:
            token, uid = app.state.auth.login(body.email, body.password, request.client.host)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from None
        except TimeoutError as exc:
            raise HTTPException(429, str(exc)) from None
        app.state.auth.logout(request.cookies.get("retail_auth"))
        response.set_cookie(
            "retail_auth",
            token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=SESSION_TTL,
            path=cookie_path,
        )
        return customer(uid)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        app.state.auth.logout(request.cookies.get("retail_auth"))
        response.delete_cookie("retail_auth", path=cookie_path)
        return {"message": "已退出"}

    @app.get("/api/me")
    def me(uid=Depends(identity)):
        return customer(uid)

    @app.get("/api/orders")
    def orders(uid=Depends(identity)):
        with app.state.store.tx() as cx:
            return {
                "orders": [
                    o for o in app.state.store.dataset(cx)["orders"].values() if o["user_id"] == uid
                ]
            }

    @app.get("/api/orders/{oid}")
    def order(oid: str, uid=Depends(identity)):
        with app.state.store.tx() as cx:
            value = app.state.store.dataset(cx)["orders"].get(oid)
        if not value or value["user_id"] != uid:
            raise HTTPException(404, "订单不存在")
        return value

    class Action(BaseModel):
        tool: str
        args: dict = Field(default_factory=dict)

    def stage(uid, tool, args):
        sid = app.state.store.create_session(
            owner_user_id=uid, variant=config.BROWSER_AGENT_VARIANT
        )["id"]
        result = app.state.retail.call(sid, tool, args)
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(422, result["error"])
        with app.state.store.tx() as cx:
            app.state.store.update(
                cx,
                sid,
                title="订单 / 资料变更确认",
                messages=[
                    {
                        "id": uuid.uuid4().hex,
                        "role": "assistant",
                        "content": "已生成操作预览。请核对变更后确认执行，确认前数据不会改变。",
                    }
                ],
            )
        return snapshot(sid)

    @app.post("/api/orders/{oid}/actions", status_code=201)
    def order_action(oid: str, body: Action, uid=Depends(identity)):
        order(oid, uid)
        if body.tool not in app.state.retail.writes - {"modify_user_address"}:
            raise HTTPException(422, "不支持的订单操作")
        return stage(uid, body.tool, body.args | {"order_id": oid})

    @app.post("/api/me/address", status_code=201)
    def address(body: dict, uid=Depends(identity)):
        return stage(uid, "modify_user_address", body | {"user_id": uid})

    def authorized(sid: str, uid=Depends(identity)):
        try:
            session = app.state.store.session(sid)
        except LookupError:
            raise HTTPException(404, "会话不存在") from None
        if session["owner_user_id"] != uid:
            raise HTTPException(404, "会话不存在")
        return session

    def get_session(sid):
        try:
            return app.state.store.session(sid)
        except LookupError:
            raise HTTPException(404, "会话不存在") from None

    def episode_authorized(sid: str, authorization: str = Header(default="")):
        session = get_session(sid)
        if session["owner_user_id"] is not None:
            raise HTTPException(404, "评测会话不存在")
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
            "tool_interfaces": {v: app.state.retail.tool_manifest(v) for v in config.VARIANTS},
            "domain": "retail",
            "variants": list(config.VARIANTS),
            "protocol_version": "retail-http-v2",
            "browser_auth": "retail_auth_cookie",
            "eval_protocol_version": "retail-eval-http-v2",
        }

    @app.get("/api/samples")
    def samples(uid=Depends(identity)):
        user = customer(uid)
        return {
            "samples": [
                {
                    "email": user["email"],
                    "name": " ".join(user["name"].values()),
                    "order_id": o["order_id"],
                    "status": o["status"],
                    "items": len(o["items"]),
                }
                for o in orders(uid)["orders"]
            ]
        }

    @app.get("/api/sessions")
    def list_sessions(uid=Depends(identity)):
        with app.state.store.tx() as cx:
            return {
                "sessions": [
                    dict(r)
                    for r in cx.execute(
                        "SELECT id,title,updated_at FROM sessions WHERE owner_user_id=? ORDER BY updated_at DESC",
                        (uid,),
                    )
                ]
            }

    @app.post("/api/sessions", status_code=201)
    def create_session(uid=Depends(identity)):
        value = app.state.store.create_session(
            owner_user_id=uid, variant=config.BROWSER_AGENT_VARIANT
        )
        return {k: v for k, v in value.items() if k != "token"}

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
    def decide(sid: str, body: Decision, session=Depends(authorized)):
        with exclusive(sid):
            try:
                receipt = app.state.runner.decide(
                    sid, body.action_id, body.approve, continue_agent=False
                )
            except (ValueError, PermissionError) as exc:
                raise HTTPException(409, str(exc)) from None
        return {"receipt": receipt, "session": snapshot(sid)}

    @app.get("/internal/eval/episodes/{sid}")
    def episode_session(sid: str, session=Depends(episode_authorized)):
        return snapshot(sid)

    @app.post("/internal/eval/episodes/{sid}/messages")
    async def episode_chat(sid: str, body: ChatInput, session=Depends(episode_authorized)):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "消息不能为空")
        return stream_turn(sid, "message", (text,))

    @app.post("/internal/eval/episodes/{sid}/decisions")
    async def episode_decide(sid: str, body: Decision, session=Depends(episode_authorized)):
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
        if get_session(sid)["owner_user_id"] is not None:
            raise HTTPException(404, "评测会话不存在")
        with exclusive(sid):
            return export(sid, "snapshot")

    @app.post("/internal/eval/episodes/{sid}/finish", dependencies=[Depends(eval_authorized)])
    async def finish_episode(sid: str, body: FinishInput):
        if get_session(sid)["owner_user_id"] is not None:
            raise HTTPException(404, "评测会话不存在")
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
