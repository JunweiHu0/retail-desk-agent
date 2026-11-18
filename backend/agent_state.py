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
