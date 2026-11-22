"""retail_ours: our course-project variant of the tau2 Retail benchmark.

NOT the official tau2 Retail benchmark. Scores on this domain must be reported as
"retail_ours" and never compared to, or presented as, official tau2 scores.

Differences from upstream tau2 Retail (commit 0c69df4), all listed in README.md:
  * the environment uses ``FixedRetailTools`` (per-item variant lookup in
    ``modify_pending_order_items``);
  * tasks listed in ``task_patches.json`` have their ambiguous or infeasible
    scenario text / gold actions / NL assertions replaced.
Everything else (DB, policy, other 108 tasks, splits, evaluator) is upstream.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Optional

DOMAIN = "retail_ours"
PATCH_FILE = Path(__file__).with_name("task_patches.json")


def load_patches() -> dict[str, dict[str, Any]]:
    data = json.loads(PATCH_FILE.read_text(encoding="utf-8"))
    return data["tasks"]


def _set_path(obj: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    for key in keys[:-1]:
        if obj.get(key) is None:
            obj[key] = {}
        obj = obj[key]
    obj[keys[-1]] = value


def apply_patches(raw_tasks: list[dict], patches: dict[str, dict]) -> list[dict]:
    """Return a patched deep copy of the upstream task dicts."""
    tasks = copy.deepcopy(raw_tasks)
    by_id = {t["id"]: t for t in tasks}
    missing = sorted(set(patches) - set(by_id))
    if missing:
        raise ValueError(f"retail_ours patches reference unknown tasks: {missing}")
    for task_id, patch in patches.items():
        task = by_id[task_id]
        drop = set(patch.get("remove_action_ids", []))
        if drop:
            actions = task["evaluation_criteria"]["actions"]
            ids = {a["action_id"] for a in actions}
            if not drop <= ids:
                raise ValueError(f"task {task_id}: unknown action ids {sorted(drop - ids)}")
            task["evaluation_criteria"]["actions"] = [
                a for a in actions if a["action_id"] not in drop
            ]
        for path, value in patch.get("set", {}).items():
            _set_path(task, path, copy.deepcopy(value))
        _set_path(task, "description.notes", f"[retail_ours patch] {patch['reason']}")
    return tasks


def get_environment(db=None, solo_mode: bool = False, policy: Optional[str] = None,
                    regional_settings=None):
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.utils import RETAIL_DB_PATH, RETAIL_POLICY_PATH
    from tau2.environment.environment import Environment

    from backend.retail_tools import FixedRetailTools

    if solo_mode:
        raise ValueError("Retail domain does not support solo mode")
    db = RetailDB.load(RETAIL_DB_PATH) if db is None else db.model_copy(deep=True)
    if policy is None:
        policy = Path(RETAIL_POLICY_PATH).read_text()
    return Environment(
        domain_name=DOMAIN,
        policy=policy,
        tools=FixedRetailTools(db, regional_settings=regional_settings),
    )


def get_tasks_split() -> dict[str, list[str]]:
    from tau2.domains.retail.environment import get_tasks_split as upstream_split

    return upstream_split()


def get_tasks(task_split_name: Optional[str] = "base"):
    from tau2.data_model.tasks import Task
    from tau2.domains.retail.utils import RETAIL_TASK_SET_PATH
    from tau2.utils import load_file

    raw = apply_patches(load_file(RETAIL_TASK_SET_PATH), load_patches())
    tasks = [Task.model_validate(t) for t in raw]
    if task_split_name is None:
        return tasks
    splits = get_tasks_split()
    if task_split_name not in splits:
        raise ValueError(f"Invalid task split name: {task_split_name}. Valid: {list(splits)}")
    keep = set(splits[task_split_name])
    return [t for t in tasks if t.id in keep]


def register() -> None:
    """Register the retail_ours domain and tasks with the tau2 registry (idempotent)."""
    from tau2.registry import registry

    if DOMAIN in registry.get_domains():
        return
    registry.register_domain(get_environment, DOMAIN)
    registry.register_tasks(get_tasks, DOMAIN, get_task_splits=get_tasks_split)
