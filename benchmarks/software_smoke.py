"""Two deterministic demo HTTP contract checks; these are not live benchmark grades."""

import argparse
import copy
import json
import os
from pathlib import Path

import httpx

from benchmarks.reference import PROTOCOL_VERSION, TAU2_SHA
from benchmarks.reference.comparator import compare_db, freeze_scope
from benchmarks.reference.fixtures import digest, load_sources, write_json
from benchmarks.reference.http import EpisodeHTTP, StreamProtocolError, without_credentials
from benchmarks.run_http import validate_url, version_manifest

VALIDATION_KIND = "deterministic_http_contract"


def contract_cases(initial_db: dict) -> list[dict]:
    """Select script inputs solely from public initial status, ownership and item data."""
    pending = next(
        order for _, order in sorted(initial_db["orders"].items()) if order["status"] == "pending"
    )
    delivered = next(
        order
        for _, order in sorted(initial_db["orders"].items())
        if order["status"] == "delivered" and order["items"] and order["payment_history"]
    )
    return [
        {
            "name": "cancel_approve",
            "customer_id": pending["user_id"],
            "order_id": pending["order_id"],
            "message": f"Please cancel order {pending['order_id']}; no longer needed.",
            "tool": "cancel_pending_order",
            "approve": True,
            "expected_args": {"order_id": pending["order_id"], "reason": "no longer needed"},
        },
        {
            "name": "return_reject",
            "customer_id": delivered["user_id"],
            "order_id": delivered["order_id"],
            "message": f"Please return all items in order {delivered['order_id']} to the original payment method.",
            "tool": "return_delivered_order_items",
            "approve": False,
            "expected_args": {
                "order_id": delivered["order_id"],
                "item_ids": [item["item_id"] for item in delivered["items"]],
                "payment_method_id": delivered["payment_history"][0]["payment_method_id"],
            },
        },
    ]


def build_contract_targets(initial_db: dict, cases: list[dict], tau_root: Path) -> dict:
    import tau2.domains.retail.data_model as retail_data_model
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.tools import RetailTools

    if not Path(retail_data_model.__file__).resolve().is_relative_to(tau_root / "src"):
        raise ValueError("Imported tau2 does not come from the pinned source checkout")
    targets = {}
    for case in cases:
        db = RetailDB.model_validate(initial_db)
        if case["approve"]:
            # The reference invocation is used only offline to compute an expected DB.
            RetailTools(db).get_tools()[case["tool"]](**case["expected_args"])
        targets[case["name"]] = db.model_dump(mode="json")
    return targets


def run_case(
    client: httpx.Client,
    base_url: str,
    eval_token: str,
    initial_db: dict,
    source_hashes: dict,
    case: dict,
    target_db: dict,
    output: Path,
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    api = EpisodeHTTP(client, base_url, eval_token)
    scope = freeze_scope(initial_db, case["customer_id"])
    initial = {
        "initial_db": initial_db,
        "customer_id": case["customer_id"],
        "variant": "b1",
        "task_id": "software-" + case["name"],
        "trial_id": "0",
        "seed": 0,
        "metadata": {"validation_kind": VALIDATION_KIND, "tau2_sha": TAU2_SHA},
    }
    write_json(output / "input.json", initial)
    write_json(output / "script.json", case)
    trace, receipts, errors = [], [], []
    final, comparison, preview_comparison = None, None, None
    try:
        created = api.create(initial, timeout=30)
        write_json(output / "initial_response.json", without_credentials(created))
        manifest = created["manifest"]
        if (
            manifest.get("mode") != "demo"
            or manifest.get("tau2_expected_sha") != TAU2_SHA
            or manifest.get("policy_sha256") != source_hashes["policy"]
        ):
            raise ValueError("Demo runtime policy/pin differs from contract inputs")
        session, events = api.turn({"action": "message", "message": case["message"]}, timeout=60)
        trace.append({"stage": "message", "events": events})
        if any(
            event["data"].get("type") == "error" or event["event"] == "error" for event in events
        ):
            raise ValueError("Agent returned an error during proposal generation")
        proposal = session.get("context", {}).get("pending")
        if (
            not proposal
            or proposal["tool"] != case["tool"]
            or proposal["args"] != case["expected_args"]
        ):
            raise ValueError("Visible proposal does not match the explicit script request")
        response = client.get(
            f"{base_url}/internal/eval/episodes/{api.sid}/snapshot",
            headers=api.eval_headers,
            timeout=30,
        )
        response.raise_for_status()
        preview = response.json()
        write_json(output / "preview_snapshot.json", without_credentials(preview))
        preview_comparison = compare_db(initial_db, preview["db"], scope)
        if not preview_comparison["success"]:
            raise ValueError("Proposal changed the DB before the scripted decision")
        # This explicit deterministic fixture rule is not a user simulator or auto-approval policy.
        session, events = api.turn(
            {"action": "decision", "action_id": proposal["id"], "approve": case["approve"]},
            timeout=60,
        )
        trace.append({"stage": "decision", "approve": case["approve"], "events": events})
        receipts = [
            event["data"].get("receipt", event["data"])
            for event in events
            if event["event"] == "receipt" or event["data"].get("type") == "receipt"
        ]
        if not receipts:
            receipts = [
                event["data"]
                for event in session.get("events", [])
                if event.get("kind") == "receipt"
            ]
        if any(
            event["event"] == "error" or event["data"].get("type") == "error" for event in events
        ):
            raise ValueError("Agent continuation failed after the scripted decision")
        expected_status = "executed" if case["approve"] else "rejected"
        if not any(
            receipt.get("status") == expected_status and receipt.get("tool") == case["tool"]
            for receipt in receipts
        ):
            raise ValueError("Missing actual application receipt for the scripted decision")
        if session.get("context", {}).get("pending"):
            raise ValueError("Scripted decision did not consume the pending proposal")
    except (httpx.HTTPError, StreamProtocolError, ValueError, KeyError, TypeError) as exc:
        errors.append({"stage": "conversation", "type": type(exc).__name__})
    if api.sid:
        try:
            api.finish("deterministic_http_contract_complete")
        except (httpx.HTTPError, ValueError) as exc:
            errors.append({"stage": "finish", "type": type(exc).__name__})
        try:
            final = api.snapshot()
            comparison = compare_db(target_db, final["db"], scope)
            write_json(output / "final_snapshot.json", without_credentials(final))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            errors.append({"stage": "snapshot", "type": type(exc).__name__})
    result = {
        "validation_kind": VALIDATION_KIND,
        "name": case["name"],
        "session_id": api.sid,
        "pass": not errors and comparison is not None and comparison["success"],
        "snapshot_available": final is not None,
        "errors": errors,
        "initial_db_hash": digest(initial_db),
        "expected_db_hash": digest(target_db),
        "comparison": comparison,
        "preview_comparison": preview_comparison,
    }
    write_json(output / "sse_trace.json", without_credentials(trace))
    write_json(output / "receipts.json", without_credentials(receipts))
    write_json(output / "expected_db.json", target_db)
    write_json(output / "result.json", result)
    return result


def run(args):
    token = os.environ.get(args.eval_token_env, "")
    if not token:
        raise ValueError("Evaluation token environment variable must be set")
    base_url = validate_url(args.base_url)
    sources = load_sources(args.tau_root.resolve())
    cases = contract_cases(sources["db"])
    targets = build_contract_targets(sources["db"], cases, args.tau_root.resolve())
    initial_db = targets["return_reject"]  # RetailDB-normalized seed, before either script.
    with httpx.Client() as client:
        response = client.get(base_url + "/api/health", timeout=30)
        response.raise_for_status()
        health = response.json()
        if (
            health.get("mode") != "demo"
            or health.get("tools") != 16
            or health.get("protocol_version") != PROTOCOL_VERSION
        ):
            raise ValueError(
                "Software contract checks require demo mode and the 16-tool HTTP protocol"
            )
        args.output.mkdir(parents=True, exist_ok=False)
        write_json(
            args.output / "manifest.json",
            {
                **version_manifest(),
                "validation_kind": VALIDATION_KIND,
                "base_url": base_url,
                "source_hashes": sources["hashes"],
                "health": health,
                "case_count": len(cases),
            },
        )
        results = [
            run_case(
                client,
                base_url,
                token,
                copy.deepcopy(initial_db),
                sources["hashes"],
                case,
                targets[case["name"]],
                args.output / case["name"],
            )
            for case in cases
        ]
    report = {
        "validation_kind": VALIDATION_KIND,
        "complete": len(results) == 2 and all(result["snapshot_available"] for result in results),
        "execution_finished": True,
        "pass": all(result["pass"] for result in results),
        "cases": results,
    }
    write_json(args.output / "summary.json", report)
    write_json(
        args.output / "complete.json",
        {
            "validation_kind": VALIDATION_KIND,
            "complete": report["complete"],
            "pass": report["pass"],
        },
    )
    print(json.dumps({"output": str(args.output), **report}))
    if not report["pass"]:
        raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18881")
    parser.add_argument("--tau-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--eval-token-env", default="EVAL_API_TOKEN")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
