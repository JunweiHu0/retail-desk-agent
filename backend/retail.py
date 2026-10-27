"""Official Retail tools with server-side identity, approval and transaction boundaries."""

import ast
import hashlib
import json
import operator
import time
import uuid

from pydantic import BaseModel
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools
from tau2.environment.toolkit import ToolType

from backend.observations import normalize_variant_changes, variant_change_error
from backend.store import encode, now

AUTH_TOOLS = {"find_user_id_by_email", "find_user_id_by_name_zip"}


def plain(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def calculator(expression):
    """Bounded arithmetic evaluator; does not execute Python eval from upstream."""
    if len(expression) > 200:
        raise ValueError("Expression too long")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node, depth=0):
        if depth > 20:
            raise ValueError("Expression too complex")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand, depth + 1)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            value = operations[type(node.op)](
                visit(node.left, depth + 1), visit(node.right, depth + 1)
            )
            if abs(value) > 1e15:
                raise ValueError("Result too large")
            return value
        raise ValueError("Only +, -, *, / and parentheses are allowed")

    return str(round(float(visit(ast.parse(expression, mode="eval").body)), 2))


def subject(db, user_id, args):
    result = {"user": db.users[user_id].model_dump(mode="json")}
    if "order_id" in args:
        result["order"] = db.orders[args["order_id"]].model_dump(mode="json")
    return result


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class RetailService:
    def __init__(self, store):
        self.store = store
        with store.tx() as cx:
            self.catalog = RetailTools(RetailDB.model_validate(store.dataset(cx))).get_tools()
        self.writes = {
            name
            for name in self.catalog
            if getattr(RetailTools, name).__tool_type__ == ToolType.WRITE
        }

    def authorize(self, session, db, name, args):
        uid = session["user_id"]
        if name in AUTH_TOOLS:
            return
        if not uid:
            raise PermissionError("请先通过邮箱或姓名和邮编核验身份。")
        if args.get("user_id", uid) != uid:
            raise PermissionError("一个会话只能服务同一位客户，不能访问其他客户资料。")
        if "order_id" in args:
            order = db.orders.get(args["order_id"])
            if order is None or order.user_id != uid:
                raise PermissionError("订单不存在或不属于当前客户。")
        if name in {"get_product_details", "get_item_details"}:
            # Products are catalog data, available to any verified retail customer.
            return

    def validate_write(self, name, args):
        error = variant_change_error(name, args)
        if error:
            raise ValueError(error)
        if "item_ids" in args and not args["item_ids"]:
            raise ValueError("必须选择至少一件商品。")
        if "new_item_ids" in args and len(args["new_item_ids"]) != len(args["item_ids"]):
            raise ValueError("原商品和新商品数量必须一致。")

    def call(self, sid, name, args, emit=lambda event: None):
        """Read tools execute; write tools validate on a copy and create a pending action."""
        start = time.monotonic()
        emit({"type": "tool_start", "name": name, "args": args})
        try:
            with self.store.tx() as cx:
                session = self.store.session(sid, cx)
                if session["transferred"]:
                    raise ValueError("会话已转人工，请新建会话继续。")
                db = RetailDB.model_validate(self.store.dataset(cx))
                if name not in self.catalog:
                    raise ValueError("Unknown retail tool")
                args = self.catalog[name].params.model_validate(args).model_dump()
                args = normalize_variant_changes(name, args)
                self.authorize(session, db, name, args)
                tools = RetailTools(db).get_tools()
                if name in self.writes:
                    if session["pending"]:
                        raise ValueError("已有待确认操作，请先确认或取消。")
                    self.validate_write(name, args)
                    before = subject(db, session["user_id"], args)
                    result = plain(tools[name](**args))
                    after = subject(db, session["user_id"], args)
                    selected_ids = set(args.get("item_ids", []) + args.get("new_item_ids", []))
                    item_details = {
                        v.item_id: {
                            "item_id": v.item_id,
                            "product_id": p.product_id,
                            "name": p.name,
                            "price": v.price,
                            "options": v.options,
                        }
                        for p in db.products.values()
                        for v in p.variants.values()
                        if v.item_id in selected_ids
                    }
                    pending = {
                        "id": uuid.uuid4().hex,
                        "tool": name,
                        "args": args,
                        "item_details": item_details,
                        "before": before,
                        "after": after,
                        "fingerprint": fingerprint(before),
                        "created_at": now(),
                    }
                    self.store.update(cx, sid, pending=pending)
                    result = {
                        "status": "awaiting_confirmation",
                        "action_id": pending["id"],
                        "tool": name,
                        "args": args,
                        "preview": result,
                        "instruction": "尚未执行。请用户检查界面中的变更明细并点击确认。立即停止工具调用。",
                    }
                elif name == "calculate":
                    result = calculator(args["expression"])
                else:
                    result = plain(tools[name](**args))
                    if name in AUTH_TOOLS:
                        if session["user_id"] and session["user_id"] != result:
                            raise PermissionError("不能在同一会话切换客户。请新建会话。")
                        self.store.update(cx, sid, user_id=result)
                    if name == "transfer_to_human_agents":
                        self.store.update(cx, sid, transferred=1)
                event = {
                    "type": "tool_end",
                    "name": name,
                    "args": args,
                    "result": result,
                    "ok": True,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                }
                self.store.event(cx, sid, "tool", event)
        except (ValueError, PermissionError, KeyError, ArithmeticError, SyntaxError) as exc:
            event = {
                "type": "tool_end",
                "name": name,
                "args": args,
                "result": {"error": str(exc)},
                "ok": False,
                "duration_ms": round((time.monotonic() - start) * 1000),
            }
            with self.store.tx() as cx:
                self.store.event(cx, sid, "tool", event)
        emit(event)
        return event["result"]

    def decide(self, sid, action_id, approve):
        """Atomically consume a one-time approval and apply the exact previewed operation."""
        with self.store.tx() as cx:
            session = self.store.session(sid, cx)
            pending = session["pending"]
            if not pending or pending["id"] != action_id:
                raise ValueError("操作已处理或不存在，请刷新会话。")
            if not approve:
                self.store.update(cx, sid, pending=None)
                self.store.event(cx, sid, "decision", {"id": action_id, "approved": False})
                return {"status": "rejected", "message": "已取消本次操作，数据未变更。"}
            db = RetailDB.model_validate(self.store.dataset(cx))
            name, args = pending["tool"], pending["args"]
            self.authorize(session, db, name, args)
            if fingerprint(subject(db, session["user_id"], args)) != pending["fingerprint"]:
                # Keep the stale proposal available to reject; never execute a different snapshot.
                raise ValueError("订单或客户资料已变更，本次确认已失效。请取消后重新提出请求。")
            self.validate_write(name, args)
            result = plain(RetailTools(db).get_tools()[name](**args))
            after = subject(db, session["user_id"], args)
            self.store.save_dataset(cx, db.model_dump(mode="json"))
            cx.execute(
                "INSERT INTO actions VALUES(?,?,?,?,?,?,?)",
                (
                    action_id,
                    sid,
                    name,
                    encode(args),
                    encode(pending["before"]),
                    encode(after),
                    now(),
                ),
            )
            self.store.update(cx, sid, pending=None)
            event = {
                "id": action_id,
                "tool": name,
                "args": args,
                "approved": True,
                "before": pending["before"],
                "after": after,
            }
            self.store.event(cx, sid, "decision", event)
            return {
                "status": "executed",
                "tool": name,
                "result": result,
                "message": "操作已完成，变更已持久化。",
                "action_id": action_id,
            }

    def context(self, sid):
        with self.store.tx() as cx:
            session = self.store.session(sid, cx)
            if not session["user_id"]:
                return {"user": None, "orders": [], "pending": None}
            db = self.store.dataset(cx)
            user = db["users"][session["user_id"]]
            return {
                "user": user,
                "orders": [db["orders"][oid] for oid in user["orders"]],
                "pending": session["pending"],
            }

    def samples(self):
        """Public synthetic identities from the benchmark, never real customer credentials."""
        with self.store.tx() as cx:
            data = self.store.dataset(cx)
            samples = []
            candidates = sorted(
                data["orders"].values(),
                key=lambda order: (not order["user_id"].startswith("demo_"), order["order_id"]),
            )
            for status in ("pending", "delivered", "processed"):
                order = next((o for o in candidates if o["status"] == status), None)
                if order:
                    user = data["users"][order["user_id"]]
                    samples.append(
                        {
                            "email": user["email"],
                            "name": " ".join(user["name"].values()),
                            "order_id": order["order_id"],
                            "status": status,
                            "items": len(order["items"]),
                        }
                    )
            return samples
