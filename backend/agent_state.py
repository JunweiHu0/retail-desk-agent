"""Optional intent ledger: model requests are distinct from observed application facts."""

import json


def observe(state, source, value):
    """Keep concise facts copied from actual observations, never model assertions."""
    state.setdefault("facts", {})[source] = value


def update_intents(state, content):
    """Accept a structured response envelope, but never accept model-written DONE."""
    if not content.lstrip().startswith("{"):
        return content
    try:
        envelope = json.loads(content)
    except ValueError:
        return content
    if not isinstance(envelope, dict) or not isinstance(envelope.get("reply"), str):
        return content
    entries = envelope.get("intents", [])
    if not isinstance(entries, list):
        return envelope["reply"]
    ledger = state.setdefault("intents", [])
    by_id = {entry["id"]: entry for entry in ledger}
    for entry in entries[:20]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        if not isinstance(entry.get("request"), str):
            continue
        old = by_id.get(entry["id"])
        # Receipt-settled entries remain immutable; changed requests need a new id.
        if old and old["status"] == "done":
            continue
        item = {
            "id": entry["id"],
            "request": entry["request"][:500],
            "status": "superseded" if entry.get("status") == "superseded" else "open",
        }
        if isinstance(entry.get("tool"), str) and isinstance(entry.get("args"), dict):
            item.update(tool=entry["tool"], args=entry["args"])
        if old:
            ledger[ledger.index(old)] = item
        else:
            ledger.append(item)
        by_id[item["id"]] = item
    return envelope["reply"]


def reconcile_receipt(state, receipt, pending):
    """Only an executed receipt for the exact proposed operation settles an intent."""
    observe(
        state,
        "last_receipt",
        {
            "status": receipt["status"],
            "action_id": pending["id"],
            "tool": pending["tool"],
            "args": pending["args"],
        },
    )
    for entry in state.get("intents", []):
        if (
            entry.get("status") == "open"
            and entry.get("tool") == pending["tool"]
            and entry.get("args") == pending["args"]
        ):
            entry["status"] = "done" if receipt["status"] == "executed" else "open"
            if receipt["status"] == "executed":
                entry["receipt_id"] = pending["id"]


def apply_task_plan(state, delta, parsed, context, latest_message_id):
    """Apply a validated plan atomically; application owns task IDs and execution states."""
    from copy import deepcopy

    tasks = deepcopy(state.get("tasks", []))
    by_id = {t["id"]: t for t in tasks}
    aliases = {t["id"]: [t["id"]] for t in tasks}
    dependency_updates = []
    for draft, constraints, source_quote in parsed:
        if draft.scope == "single":
            objects = [draft.object_id]
        else:
            objects = [
                o["order_id"]
                for o in context["orders"]
                if (
                    draft.scope == "all_orders"
                    or (draft.scope == "all_pending_orders" and o["status"].startswith("pending"))
                    or (draft.scope == "all_delivered_orders" and o["status"] == "delivered")
                )
            ]
            if not objects:
                objects = [""]  # Unresolved/empty scope must not disappear as if completed.
        expanded = []
        for oid in objects:
            old = by_id.get(draft.key) if draft.scope == "single" else None
            if old and (old["operation"] != draft.operation or old["object_id"] not in {"", oid}):
                raise ValueError(
                    "Changed operation/object needs a new task and explicit supersession"
                )
            if old is None:
                old = next(
                    (
                        t
                        for t in tasks
                        if oid
                        and draft.operation != "answer"
                        and t["operation"] == draft.operation
                        and t["object_id"] == oid
                        and (
                            t["status"] not in {"executed", "answered", "superseded"}
                            or t["source_message_id"] == draft.source_message_id
                        )
                    ),
                    None,
                )
            if old and old["status"] in {
                "executed",
                "answered",
                "superseded",
                "awaiting_confirmation",
            }:
                expanded.append(old["id"])
                continue
            if (
                old
                and old["status"] == "rejected"
                and (
                    draft.source_message_id != latest_message_id
                    or latest_message_id == old.get("rejected_after_message_id")
                )
            ):
                expanded.append(old["id"])
                continue
            args = {**(old.get("known_args", {}) if old else {}), **constraints}
            if oid and draft.operation != "answer":
                args["user_id" if draft.operation == "modify_user_address" else "order_id"] = oid
            identifier = old["id"] if old else f"task-{len(tasks) + 1:04d}"
            item = {
                "id": identifier,
                "operation": draft.operation,
                "object_id": oid,
                "request": draft.request,
                "scope": draft.scope,
                "source_message_id": draft.source_message_id,
                "source_quote": source_quote,
                "known_args": args,
                "missing": draft.missing,
                "status": "needs_info"
                if draft.missing or (not oid and draft.operation != "answer")
                else "ready",
                "depends_on": old.get("depends_on", []) if old else [],
            }
            if old:
                tasks[tasks.index(old)] = item
            else:
                tasks.append(item)
            by_id[identifier] = item
            expanded.append(identifier)
            dependency_updates.append((item, draft.depends_on))
        aliases[draft.key] = expanded
    for drop in delta.supersede:
        item = by_id[drop.task_id]
        if item["status"] not in {"executed", "awaiting_confirmation"}:
            item["status"] = "superseded"
            item["superseded_by_message_id"] = drop.source_message_id
    for item, keys in dependency_updates:
        item["depends_on"] = list(dict.fromkeys(i for key in keys for i in aliases[key]))
    # Cycles make execution impossible, so reject the external plan before persisting.
    for item in tasks:
        visiting = set()
        stack = [(item["id"], False)]
        while stack:
            identifier, leaving = stack.pop()
            if leaving:
                visiting.remove(identifier)
                continue
            if identifier in visiting:
                raise ValueError("Circular task dependency")
            visiting.add(identifier)
            stack.append((identifier, True))
            stack.extend((dep, False) for dep in by_id[identifier]["depends_on"])
    state["tasks"] = tasks
    state["task_schema_version"] = "explicit-task-ledger-v1"
    state["planned_message_id"] = latest_message_id


def matching_write_task(state, name, args):
    """Return a matching active task; mismatches are observations, never argument rewrites."""
    tasks = state.get("tasks", [])
    oid = args.get("user_id") if name == "modify_user_address" else args.get("order_id")
    candidates = [
        t
        for t in tasks
        if t["operation"] == name
        and t["object_id"] == oid
        and t["status"] in {"ready", "needs_info"}
    ]
    by_id = {t["id"]: t for t in tasks}
    for task in candidates:
        if any(
            by_id[d]["status"] not in {"executed", "answered", "superseded"}
            for d in task["depends_on"]
        ):
            continue
        if all(args.get(k) == v for k, v in task["known_args"].items()):
            return task
    return None


def settle_task_receipt(state, receipt, latest_message_id):
    for task in state.get("tasks", []):
        if (
            task["status"] == "awaiting_confirmation"
            and task.get("action_id") == receipt["action_id"]
            and task["operation"] == receipt["tool"]
            and task.get("proposed_args") == receipt["args"]
        ):
            task["status"] = receipt["status"]
            task["receipt_id"] = receipt["action_id"]
            if receipt["status"] == "rejected":
                task["rejected_after_message_id"] = latest_message_id
