"""FastAPI transport. Localhost by default; session capabilities protect customer data."""

import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config
from backend.agent import AgentRunner
from backend.auth import SESSION_TTL, AuthService
from backend.retail import RetailService
from backend.store import Store

log = logging.getLogger(__name__)


def create_app(store=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or Store()
        app.state.retail = RetailService(app.state.store)
        app.state.runner = AgentRunner(app.state.retail)
        app.state.auth = AuthService(app.state.store, os.getenv("DEMO_ACCOUNTS", "1") == "1")
        app.state.busy = set()
        app.state.guard = threading.Lock()
        app.state.tasks = set()
        yield

    app = FastAPI(title="Retail Agent API", version="0.1.0", lifespan=lifespan)

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
        return await call_next(request)

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
        )
        return customer(uid)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        app.state.auth.logout(request.cookies.get("retail_auth"))
        response.delete_cookie("retail_auth")
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
        sid = app.state.store.create_session(uid)["id"]
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
        value = app.state.store.create_session(uid)
        return {k: v for k, v in value.items() if k != "token"}

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
