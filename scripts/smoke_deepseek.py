"""Opt-in live integration check. Uses only an isolated temporary Retail database."""

import argparse
import json
import tempfile
from pathlib import Path

from backend import config
from backend.agent import AgentRunner
from backend.retail import RetailService
from backend.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-live", action="store_true", help="Explicitly allow paid model requests"
    )
    args = parser.parse_args()
    if not args.run_live:
        parser.error("This makes real API calls. Pass --run-live to opt in.")
    if config.MODE != "live" or not config.IS_DEEPSEEK or not config.API_KEY:
        parser.error("Configure the local DeepSeek live profile first.")
    with tempfile.TemporaryDirectory(prefix="retail-deepseek-") as temporary:
        store = Store(Path(temporary) / "smoke.sqlite3")
        service = RetailService(store)
        runner = AgentRunner(service)
        sid = store.create_session()["id"]
        sample = next(s for s in service.samples() if s["status"] == "pending")
        events = []
        query = runner.run(
            sid,
            f"我的邮箱是 {sample['email']}，请查询订单 {sample['order_id']} 的状态、商品和总金额。",
            events.append,
        )
        assert store.session(sid)["user_id"], "Customer was not verified"
        assert any(e.get("name") == "get_order_details" and e.get("ok") for e in events), (
            "Order query tool was not used"
        )
        with store.tx() as cx:
            before = store.dataset(cx)
        runner.run(
            sid,
            f"请取消订单 {sample['order_id']}，原因是不再需要（no longer needed）。"
            "请先通过工具生成待确认预览，我会在网页卡片确认后才允许真正提交。",
            events.append,
        )
        if not store.session(sid)["pending"]:
            runner.run(
                sid,
                f"是的，确认我要取消 {sample['order_id']}，原因是 no longer needed。"
                "请继续生成操作预览卡片，后端会在我点击卡片确认后才提交。",
                events.append,
            )
        pending = store.session(sid)["pending"]
        assert pending and pending["tool"] == "cancel_pending_order", (
            "No cancellation preview was staged"
        )
        assert pending["args"]["order_id"] == sample["order_id"]
        with store.tx() as cx:
            assert store.dataset(cx) == before, "Data changed before explicit approval"
        receipt = runner.decide(sid, pending["id"], True)
        assert receipt["result"]["status"] == "cancelled"
        followup = runner.run(
            sid, f"请重新查询订单 {sample['order_id']}，确认现在的状态。", events.append
        )
        assert any(
            e.get("name") == "get_order_details"
            and isinstance(e.get("result"), dict)
            and e["result"].get("status") == "cancelled"
            for e in events
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "model": config.MODEL,
                    "database": "temporary, removed after test",
                    "order_id": sample["order_id"],
                    "query_reply": query,
                    "followup_reply": followup,
                    "tools": [e["name"] for e in events if e.get("type") == "tool_end"],
                    "approval_boundary": "verified",
                    "final_order_status": "cancelled",
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
