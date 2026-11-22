"""Official Retail tools with server-side identity, approval and transaction boundaries."""

import ast
import hashlib
import json
import operator
import os
import time
import uuid

from pydantic import BaseModel
from tau2.domains.retail.data_model import RetailDB
from backend.retail_tools import FixedRetailTools as RetailTools
from tau2.environment.toolkit import ToolType

from backend.observations import normalize_variant_changes, variant_change_error
from backend.reviewer import ITEM_CHANGE_TOOLS, check_write_result
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


def staff_enabled():
    """The staff queue exists only when STAFF_TOKEN is configured (see backend/main.py)."""
    return bool(os.getenv("STAFF_TOKEN"))


def review_threshold():
    """Customer-approved actions at or above this amount also need a staff decision."""
    return float(os.getenv("REVIEW_AMOUNT_THRESHOLD", "1000"))


def action_amount(name, args, before, item_details):
    """Money moved by an action: refund value, or absolute price difference."""
    items = list((before.get("order") or {}).get("items", []))

    def take(item_id):
        item = next((i for i in items if i["item_id"] == item_id), None)
        if item is None:
            return 0.0
        items.remove(item)
        return float(item["price"])

    if name == "cancel_pending_order":
        return round(sum(float(i["price"]) for i in items), 2)
    if name == "return_delivered_order_items":
        return round(sum(take(i) for i in args["item_ids"]), 2)
    if name in ITEM_CHANGE_TOOLS:
        old = sum(take(i) for i in args["item_ids"])
        new = sum(float(item_details.get(i, {}).get("price", 0)) for i in args["new_item_ids"])
        return round(abs(new - old), 2)
    return 0.0


def review_requirement(name, args, before, item_details, preview):
    """Reasons a staff member must also approve this exact action (None: not needed).

    Without a staff queue, a preview that does not match the request is refused outright
    and amounts are not gated (nobody could ever release them).
    """
    mismatch = check_write_result(name, args, preview, item_details)
    if mismatch and not staff_enabled():
        raise ValueError("预览结果与请求不一致，已拒绝生成该操作：" + mismatch[0].message)
    if not staff_enabled():
        return None
    reasons = []
    amount = action_amount(name, args, before, item_details)
    if amount >= review_threshold():
        reasons.append(f"金额 ${amount:.2f} 达到人工复核阈值 ${review_threshold():.2f}")
    reasons += ["预览结果与请求不一致：" + f.message for f in mismatch]
    if not reasons:
        return None
    return {"required": True, "reasons": reasons, "amount": amount, "case_id": None}


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
            if session.get("owner_user_id"):
                raise PermissionError("当前账号已登录，不能查询或切换其他客户身份。")
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
                        "review": review_requirement(name, args, before, item_details, result),
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
                    if pending["review"]:
                        result["instruction"] += "该操作在用户确认后还需要人工复核才会执行，请如实告知用户。"
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
                        self.store.create_review(
                            cx, sid, "handoff", "agent_transfer", {"summary": args["summary"]}
                        )
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
            review = pending.get("review")
            if not approve:
                self.store.update(cx, sid, pending=None)
                if review and review.get("case_id"):
                    self.store.resolve_review(
                        cx, review["case_id"], "withdrawn", {"by": "customer"}
                    )
                self.store.event(cx, sid, "decision", {"id": action_id, "approved": False})
                return {"status": "rejected", "message": "已取消本次操作，数据未变更。"}
            if review:
                # Customer approval is necessary but not sufficient: queue for staff.
                if not review.get("case_id"):
                    self.check_fresh(cx, session, pending)
                    review["case_id"] = self.store.create_review(
                        cx, sid, "approval", "; ".join(review["reasons"]),
                        {"action_id": action_id, "tool": pending["tool"],
                         "args": pending["args"], "amount": review["amount"]},
                    )
                    review["customer_approved_at"] = now()
                    self.store.update(cx, sid, pending=pending)
                    self.store.event(cx, sid, "review", {
                        "id": review["case_id"], "action_id": action_id,
                        "status": "open", "reasons": review["reasons"],
                    })
                return {
                    "status": "awaiting_review",
                    "tool": pending["tool"],
                    "message": "您已确认。该操作需要人工复核，复核通过后才会执行；在此之前数据不会改变。",
                    "action_id": action_id,
                    "case_id": review["case_id"],
                }
            return self.execute(cx, sid, session, pending)

    def check_fresh(self, cx, session, pending):
        db = RetailDB.model_validate(self.store.dataset(cx))
        self.authorize(session, db, pending["tool"], pending["args"])
        if fingerprint(subject(db, session["user_id"], pending["args"])) != pending["fingerprint"]:
            # Keep the stale proposal available to reject; never execute a different snapshot.
            raise ValueError("订单或客户资料已变更，本次确认已失效。请取消后重新提出请求。")
        return db

    def execute(self, cx, sid, session, pending, reviewer=None):
        """Apply exactly the previewed action. Caller holds the transaction."""
        action_id, name, args = pending["id"], pending["tool"], pending["args"]
        db = self.check_fresh(cx, session, pending)
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
        if reviewer:
            event["reviewed_by"] = reviewer
        self.store.event(cx, sid, "decision", event)
        return {
            "status": "executed",
            "tool": name,
            "result": result,
            "message": "操作已完成，变更已持久化。",
            "action_id": action_id,
        }

    def escalate(self, sid, reason, details=None):
        """Human fallback: stop the agent for this session and open a handoff case."""
        with self.store.tx() as cx:
            session = self.store.session(sid, cx)
            open_cases = [
                r for r in self.store.reviews(cx, status="open", sid=sid) if r["kind"] == "handoff"
            ]
            if open_cases:
                return open_cases[0]["id"]
            rid = self.store.create_review(cx, sid, "handoff", reason, details or {})
            self.store.update(cx, sid, transferred=1)
            self.store.event(cx, sid, "escalation", {
                "id": rid, "reason": reason, "details": details or {},
                "had_pending": bool(session["pending"]),
            })
            return rid

    def staff_decide(self, rid, approve, staff="staff", note=""):
        """Resolve a review case. approval: execute or reject; handoff: release or close."""
        with self.store.tx() as cx:
            case = self.store.review(rid, cx)
            if case["status"] != "open":
                raise ValueError("复核单已处理。")
            sid = case["session_id"]
            session = self.store.session(sid, cx)
            resolution = {"by": staff, "note": note[:500], "approved": approve}
            if case["kind"] == "approval":
                pending = session["pending"]
                if not pending or pending["id"] != case["details"]["action_id"]:
                    raise ValueError("待执行操作已不存在。")
                if approve:
                    receipt = self.execute(cx, sid, session, pending, reviewer=staff)
                else:
                    self.store.update(cx, sid, pending=None)
                    self.store.event(cx, sid, "decision", {
                        "id": pending["id"], "approved": False, "reviewed_by": staff,
                    })
                    receipt = {"status": "rejected",
                               "message": "人工复核未通过，本次操作已取消，数据未变更。",
                               "action_id": pending["id"]}
            else:
                # Releasing hands the session back to the agent; closing keeps it with staff.
                if approve:
                    self.store.update(cx, sid, transferred=0)
                receipt = {"status": "released" if approve else "closed",
                           "message": "人工客服已处理，可以继续对话。" if approve
                           else "人工客服已处理本次转接。"}
            self.store.resolve_review(
                cx, rid, "approved" if approve else "rejected", resolution | {"receipt": receipt["status"]}
            )
            self.store.event(cx, sid, "review", {"id": rid, "status": receipt["status"], "by": staff})
            return {"case": rid, "session_id": sid, "receipt": receipt}

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
