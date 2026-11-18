"""Build frozen, private targets by replaying official actions in clean RetailTools."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from benchmarks.reference import (
    COMPARATOR_VERSION,
    PROTOCOL_VERSION,
    SMOKE8,
    TAU2_SHA,
    VALIDATION20,
    WRITE_TOOLS,
)
from benchmarks.reference.comparator import compare_db, freeze_scope
from benchmarks.reference.known_failures import (
    AUDIT_REPORT_PATH,
    AUDIT_REPORT_SHA256,
    AUDIT_TAU2_SHA,
    EXPECTED_WRITE_FAILURES,
)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path: Path, value):
    """Exclusive creation: existing inputs, targets and run artifacts are never overwritten."""
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def verify_source_archive(tau_root: Path) -> dict:
    """Verify every archived pinned source/asset against the clean-checkout inventory."""
    manifest = json.loads((tau_root.parent / "source-manifest.json").read_text())
    if manifest.get("tau2_sha") != TAU2_SHA:
        raise ValueError("Archived tau2 revision differs from frozen pin")
    required = {str(path.relative_to(tau_root)) for path in (tau_root / "src").rglob("*.py")}
    if not required:
        raise ValueError("Archived tau2 source inventory is empty")
    required |= {
        "pyproject.toml",
        *(
            "data/tau2/domains/retail/" + name
            for name in ("db.json", "tasks.json", "split_tasks.json", "policy.md")
        ),
    }
    inventory = manifest.get("tau2_file_sha256", {})
    if set(inventory) != required:
        raise ValueError("Archived tau2 source/asset inventory differs from clean pin")
    for relative, expected in inventory.items():
        actual = hashlib.sha256((tau_root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Archived tau2 file hash mismatch: {relative}")
    return manifest


def load_sources(tau_root: Path) -> dict:
    """Pin both repository revision and exact data bytes before any replay."""
    if (tau_root / ".git").exists():
        actual = subprocess.check_output(
            ["git", "-C", str(tau_root), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != TAU2_SHA:
            raise ValueError(f"tau2 HEAD must equal {TAU2_SHA}; got {actual}")
        dirty = subprocess.check_output(
            [
                "git",
                "-C",
                str(tau_root),
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "src",
                "data/tau2/domains/retail",
                "pyproject.toml",
            ],
            text=True,
        )
        if dirty:
            raise ValueError("Pinned tau2 source/data worktree is modified")
    else:
        verify_source_archive(tau_root)
    base = tau_root / "data/tau2/domains/retail"
    paths = {
        "db": base / "db.json",
        "tasks": base / "tasks.json",
        "splits": base / "split_tasks.json",
        "policy": base / "policy.md",
    }
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    values = {
        name: json.loads(path.read_text()) for name, path in paths.items() if name != "policy"
    }
    train = set(values["splits"]["train"])
    if len(train) != 74 or len(values["splits"]["test"]) != 40:
        raise ValueError("Unexpected pinned split sizes")
    if not set(VALIDATION20) <= train or train & set(values["splits"]["test"]):
        raise ValueError("Invalid split membership")
    values["splits"] = {
        "development": sorted(train - set(VALIDATION20), key=int),
        "validation": list(VALIDATION20),
        "test": values["splits"]["test"],
        "smoke": list(SMOKE8),
    }
    return {**values, "hashes": hashes, "tau2_sha": TAU2_SHA, "tau_root": str(tau_root.resolve())}


def resolve_customer(task: dict, db: dict, lookup_results: list[str]) -> str:
    """Resolve privately from reference lookups, explicit identity and seed order ownership."""
    candidates = set(lookup_results)
    for action in task["evaluation_criteria"]["actions"]:
        args = action["arguments"]
        if args.get("user_id") in db["users"]:
            candidates.add(args["user_id"])
        if args.get("order_id") in db["orders"]:
            candidates.add(db["orders"][args["order_id"]]["user_id"])
    known = json.dumps(task["user_scenario"], ensure_ascii=False).casefold()
    # A valid reference/order identity is authoritative. Text fallback is only needed on no-action tasks.
    if not candidates:
        order_ids = re.findall(r"#W\d+", known, flags=re.IGNORECASE)
        for oid in order_ids:
            if oid.upper() in db["orders"]:
                candidates.add(db["orders"][oid.upper()]["user_id"])
        if not candidates:
            for uid, user in db["users"].items():
                full_name = " ".join([user["name"]["first_name"], user["name"]["last_name"]])
                if (
                    uid.casefold() in known
                    or user["email"].casefold() in known
                    or (full_name.casefold() in known and user["address"]["zip"] in known)
                ):
                    candidates.add(uid)
    if len(candidates) != 1:
        raise ValueError(
            f"Task {task['id']} has ambiguous/unresolved customer: {sorted(candidates)}"
        )
    return candidates.pop()


def replay_reference(task: dict, sources: dict, audit: bool = False) -> dict:
    import tau2.domains.retail.data_model as retail_data_model
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.tools import RetailTools
    from tau2.environment.toolkit import ToolType

    imported_source = Path(retail_data_model.__file__).resolve()
    if not imported_source.is_relative_to(Path(sources["tau_root"]) / "src"):
        raise ValueError("Imported tau2 does not come from the pinned source checkout")
    # Pinned retail tasks have no initial-state overrides. Refuse silent protocol drift.
    if task.get("initial_state") is not None:
        raise ValueError("Initial-state overrides require an explicitly versioned protocol")
    db = RetailDB.model_validate(sources["db"])
    initial = db.model_dump(mode="json")
    toolkit = RetailTools(db)
    tools = toolkit.get_tools()
    writes = {name for name in tools if getattr(RetailTools, name).__tool_type__ == ToolType.WRITE}
    if len(tools) != 16 or writes != WRITE_TOOLS:
        raise ValueError("Official Retail tool catalog differs from frozen 16 tools/seven writes")
    trace, identities = replay_actions(task, db, tools, writes, audit)
    return {
        "initial_db": initial,
        "target_db": db.model_dump(mode="json"),
        "trace": trace,
        "identities": identities,
    }


def replay_actions(
    task: dict, db, tools: dict, writes: set, audit: bool = False
) -> tuple[list, list]:
    """Replay one ordered reference trajectory, keeping explicit failure-state evidence."""
    trace, identities = [], []
    for action in task["evaluation_criteria"]["actions"]:
        name, args = action["name"], action["arguments"]
        if name not in tools:
            raise ValueError(f"Unknown reference tool {name}")
        before_hash = digest(db.model_dump(mode="json"))
        record = {
            "action_id": action["action_id"],
            "name": name,
            "arguments": args,
            "write": name in writes,
            "before_db_hash": before_hash,
        }
        try:
            result = tools[name](**args)
            result = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            record.update(ok=True, result=result)
            if name.startswith("find_user_id_"):
                identities.append(result)
        except Exception as exc:
            if not audit and not isinstance(exc, (ValueError, KeyError, ArithmeticError)):
                raise
            record.update(ok=False, error=str(exc), error_type=type(exc).__name__)
            record["after_db_hash"] = digest(db.model_dump(mode="json"))
            if name in writes and not audit:
                expected = EXPECTED_WRITE_FAILURES.get((str(task["id"]), action["action_id"]))
                matches = (
                    TAU2_SHA == AUDIT_TAU2_SHA
                    and expected is not None
                    and all(
                        record[key] == expected[key]
                        for key in ("name", "arguments", "error_type", "error")
                    )
                    and record["before_db_hash"] == record["after_db_hash"]
                )
                if not matches:
                    raise ValueError(
                        f"Reference WRITE failed for task {task['id']}: {record}"
                    ) from exc
                record.update(
                    expected_failure=True,
                    reference_issue=True,
                    rationale=expected["rationale"],
                    audit_report_sha256=AUDIT_REPORT_SHA256,
                )
        record["after_db_hash"] = digest(db.model_dump(mode="json"))
        trace.append(record)
    return trace, identities


def build_fixture(task: dict, sources: dict) -> dict:
    replay = replay_reference(task, sources)
    initial, target = replay["initial_db"], replay["target_db"]
    trace, identities = replay["trace"], replay["identities"]
    uid = resolve_customer(task, initial, identities)
    scope = freeze_scope(initial, uid)
    fixture = {
        "protocol_version": PROTOCOL_VERSION,
        "comparator_version": COMPARATOR_VERSION,
        "tau2_sha": TAU2_SHA,
        "task_id": task["id"],
        "customer_id": uid,
        "source_hashes": sources["hashes"],
        "initial_db": initial,
        "target_db": target,
        "scope": scope,
        "user_scenario": task["user_scenario"],
        "reference_trace": trace,
        "reference_issue": any(record.get("reference_issue") for record in trace),
        "reference_issues": [
            {
                key: record[key]
                for key in (
                    "action_id",
                    "name",
                    "error_type",
                    "error",
                    "before_db_hash",
                    "after_db_hash",
                    "rationale",
                    "audit_report_sha256",
                )
            }
            for record in trace
            if record.get("reference_issue")
        ],
        "reference_audit": {"path": AUDIT_REPORT_PATH, "sha256": AUDIT_REPORT_SHA256},
        "task_hash": digest(task),
        "initial_db_hash": digest(initial),
        "target_db_hash": digest(target),
    }
    if not compare_db(target, target, scope)["success"]:
        raise AssertionError("Reference self-target check failed")
    fixture["fixture_hash"] = digest(fixture)
    return fixture


def public_episode_input(fixture: dict, variant: str, trial_id: int, seed: int) -> dict:
    """The only fixture-derived fields permitted to cross into the agent backend."""
    return {
        "initial_db": fixture["initial_db"],
        "customer_id": fixture["customer_id"],
        "variant": variant,
        "task_id": fixture["task_id"],
        "trial_id": str(trial_id),
        "seed": seed,
        "metadata": {"protocol_version": PROTOCOL_VERSION, "tau2_sha": TAU2_SHA},
    }


def load_fixture(path: Path) -> dict:
    fixture = json.loads(path.read_text())
    expected = fixture.pop("fixture_hash")
    if digest(fixture) != expected:
        raise ValueError(f"Fixture hash mismatch: {path}")
    fixture["fixture_hash"] = expected
    if fixture["tau2_sha"] != TAU2_SHA or fixture["comparator_version"] != COMPARATOR_VERSION:
        raise ValueError("Unsupported fixture source/comparator version")
    if digest(fixture["initial_db"]) != fixture["initial_db_hash"]:
        raise ValueError("Initial database hash mismatch")
    if digest(fixture["target_db"]) != fixture["target_db_hash"]:
        raise ValueError("Target database hash mismatch")
    if freeze_scope(fixture["initial_db"], fixture["customer_id"]) != fixture["scope"]:
        raise ValueError("Fixture scope differs from initial customer/order ownership")
    return fixture
