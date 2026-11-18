"""Exact JSON comparison over a scope frozen from the initial database."""

from copy import deepcopy
from numbers import Real

from benchmarks.reference import COMPARATOR_VERSION


def freeze_scope(initial_db: dict, customer_id: str) -> dict:
    if customer_id not in initial_db["users"]:
        raise ValueError(f"Customer absent from initial DB: {customer_id}")
    order_ids = sorted(
        oid for oid, order in initial_db["orders"].items() if order["user_id"] == customer_id
    )
    if set(initial_db["users"][customer_id]["orders"]) != set(order_ids):
        raise ValueError("Initial user order index and order ownership disagree")
    return {"customer_id": customer_id, "order_ids": order_ids}


def project(db: dict, scope: dict) -> dict:
    """Copy entire scoped objects, retaining every optional or financial field."""
    uid = scope["customer_id"]
    return deepcopy(
        {
            "users": {uid: db["users"][uid]} if uid in db["users"] else {},
            "orders": {oid: db["orders"][oid] for oid in scope["order_ids"] if oid in db["orders"]},
        }
    )


def compare_db(target_db: dict, actual_db: dict, scope: dict) -> dict:
    expected, actual = project(target_db, scope), project(actual_db, scope)
    mismatches = []

    def visit(want, got, path):
        if isinstance(want, dict) and isinstance(got, dict):
            for key in sorted(set(want) | set(got)):
                child = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key not in want:
                    mismatches.append({"path": child, "kind": "extra", "actual": got[key]})
                elif key not in got:
                    mismatches.append({"path": child, "kind": "missing", "expected": want[key]})
                else:
                    visit(want[key], got[key], child)
        elif isinstance(want, list) and isinstance(got, list):
            for index in range(max(len(want), len(got))):
                child = path + "/" + str(index)
                if index >= len(want):
                    mismatches.append({"path": child, "kind": "extra", "actual": got[index]})
                elif index >= len(got):
                    mismatches.append({"path": child, "kind": "missing", "expected": want[index]})
                else:
                    visit(want[index], got[index], child)
        else:
            numeric = (
                isinstance(want, Real)
                and not isinstance(want, bool)
                and isinstance(got, Real)
                and not isinstance(got, bool)
            )
            if not ((numeric or type(want) is type(got)) and want == got):
                mismatches.append({"path": path, "kind": "value", "expected": want, "actual": got})

    visit(expected, actual, "")
    return {
        "comparator_version": COMPARATOR_VERSION,
        "success": not mismatches,
        "scope": scope,
        "mismatches": mismatches,
    }
