"""C1's tool-free planning boundary. Only customer-visible information enters it."""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

PLANNER_VERSION = "explicit-task-plan-v3"
WRITE_NAMES = (
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
)


class Argument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    value: str | list[str]


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    operation: Literal[
        "answer",
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    ]
    request: str = Field(min_length=1)
    source_message_id: str
    scope: Literal["single", "all_orders", "all_pending_orders", "all_delivered_orders"]
    object_id: str
    arguments: list[Argument]
    missing: list[str]
    depends_on: list[str]


class AccountTask(TaskDraft):
    operation: Literal["modify_user_address"]
    scope: Literal["single"]


class AnswerTask(TaskDraft):
    operation: Literal["answer"]
    scope: Literal["single"]
    arguments: list[Argument] = Field(max_length=0)


class OrderTask(TaskDraft):
    operation: Literal[
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "return_delivered_order_items",
    ]


class SingleOrderTask(OrderTask):
    scope: Literal["single"]


class ScopedArgument(Argument):
    name: Literal[
        "reason",
        "address1",
        "address2",
        "city",
        "state",
        "country",
        "zip",
        "item_ids",
        "new_item_ids",
        "payment_method_id",
    ]


class OrderScopeTask(OrderTask):
    scope: Literal["all_orders", "all_pending_orders", "all_delivered_orders"]
    object_id: Literal[""]
    arguments: list[ScopedArgument]


class Supersession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    source_message_id: str


class PlanDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[AccountTask | AnswerTask | SingleOrderTask | OrderScopeTask] = Field(max_length=24)
    supersede: list[Supersession] = Field(max_length=24)


PLANNER_PROMPT = """Extract/update the customer's retail tasks. This is planning only, not execution.
Return the required JSON object. Never claim execution or approval. No business tools are available.
Preserve every unfinished request. Use the exact customer message ID as intent evidence.
The application attaches the original text by that ID; do not copy or rewrite source quotations.
Facts and identifiers may come from public context or observed tools.
Use existing task IDs as keys when updating a task; new tasks need distinct descriptive keys.
Omit unchanged tasks: omission never deletes them. Supersede only when a customer explicitly cancels
or replaces a request. Do not supersede or change an executed task; a new request needs a new task.
One task per operation/object. Group all requested item changes within the same order into one task.
For 'all orders' use ONE all_* scope with object_id empty and no order_id argument; the application
expands the observed order set. For a specific order use scope=single and its exact object_id. A user-default
address update is a separate modify_user_address task. Record informational requests with answer.
Unknown object IDs are empty strings. Unknown arguments stay absent and are described in missing.
arguments are KNOWN constraints, not suggestions: use name/value pairs with direct strings or
arrays of strings. Missing information belongs only in the missing list, never in arguments.
An order operation's object_id is an ORDER ID (#W...), never a product or item ID. For an
informational answer you may identify an observed product. Do not guess replacement IDs or choices.
Never choose a refund/payment method unless the customer selected it or explicitly requested the
original method. Keep natural-language requirements in request until a query resolves exact IDs.
Use missing only for unresolved information. The executor can obtain missing facts via read tools.
For dependencies use WRITE task keys/IDs, not informational answer tasks (the executor can read
necessary facts before writing). Address/payment changes should precede one-time item changes
when the same order needs both, according to policy. Avoid circular dependencies.
A rejection is not permission to repeat: reactivate a rejected task only after a new user instruction.
Do not convert assistant assertions into customer intent. No target/reference/score is available.
"""

C1_CONTRACT = """
TASK-LEDGER EXECUTION:
The application extracted TASKS from customer requests. Handle all of them, including separate
account and order changes. executed/rejected states come from real application receipts only.
Choose one unfinished task at a time, respecting dependencies and user constraints. Read tools may
resolve missing facts; when user preference is unknown ask the user rather than inventing it.
Known arguments in the ledger are binding. A write must match an active task and its object.
Once arguments are known, stage the preview directly: the application's card provides confirmation,
so no additional chat 'yes' is needed before staging. Stop when a card is pending. After its actual
executed receipt, continue other tasks without asking for the same approval again. Do not restage a
rejected task without a new customer request. Answer informational questions needed for decisions.
Do not say all tasks are complete while an operation remains unexecuted. Describe unresolved work
or ask a focused question. If the user insists on an unsupported request, use the handoff tool.
Do not output task JSON: task updates are owned by the separate planning stage.
"""


def plan_response_schema(messages, context, catalog):
    schema = PlanDelta.model_json_schema()
    definitions = schema["$defs"]
    user_ids = [m["id"] for m in messages if m["role"] == "user"]
    for definition in definitions.values():
        prop = definition.get("properties", {}).get("source_message_id")
        if prop is not None:
            prop["enum"] = user_ids
    orders = [o["order_id"] for o in context["orders"]]
    uid = (context.get("user") or {}).get("user_id", "")
    products = sorted({i["product_id"] for o in context["orders"] for i in o["items"]})
    definitions["AccountTask"]["properties"]["object_id"]["enum"] = list(dict.fromkeys(["", uid]))
    definitions["SingleOrderTask"]["properties"]["object_id"]["enum"] = ["", *orders]
    definitions["AnswerTask"]["properties"]["object_id"]["enum"] = list(
        dict.fromkeys(["", uid, *orders, *products])
    )
    definitions["Argument"]["properties"]["name"]["enum"] = sorted(
        {field for name in WRITE_NAMES for field in catalog[name].params.model_fields}
    )
    return schema


def planner_messages(policy, context, messages, state, observations, catalog):
    return [
        SystemMessage(content=policy + "\n" + PLANNER_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "customer_messages": [m for m in messages if m["role"] == "user"],
                    "visible_conversation": messages,
                    "customer_context": context,
                    "tasks": [
                        {k: v for k, v in t.items() if k != "source_quote"}
                        for t in state.get("tasks", [])
                    ],
                    "observed_tool_results": observations,
                    "business_parameters": {
                        name: catalog[name].params.model_json_schema() for name in WRITE_NAMES
                    },
                },
                ensure_ascii=False,
            )
        ),
    ]


def parse_plan(content, messages, context, state, catalog):
    """Validate the entire external delta before applying any part of it."""
    delta = PlanDelta.model_validate_json(content)
    users = {m["id"]: m["content"] for m in messages if m["role"] == "user"}
    existing = {t["id"]: t for t in state.get("tasks", [])}
    keys = [t.key for t in delta.tasks]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate task keys")
    known_ids = {o["order_id"] for o in context["orders"]}
    if context.get("user"):
        known_ids.add(context["user"]["user_id"])
    parsed = []
    for task in delta.tasks:
        if task.source_message_id not in users:
            raise ValueError(f"Task {task.key}: evidence must reference a real customer message ID")
        allowed_ids = known_ids | (
            {i["product_id"] for o in context["orders"] for i in o["items"]}
            if task.operation == "answer"
            else set()
        )
        if task.object_id and task.object_id not in allowed_ids:
            raise ValueError("Task object is not in the observed customer context")
        if (
            task.operation == "modify_user_address"
            and task.object_id
            and task.object_id != (context.get("user") or {}).get("user_id")
        ):
            raise ValueError("Account task must target the authenticated customer")
        if (
            task.operation not in {"answer", "modify_user_address"}
            and task.object_id
            and task.object_id not in {o["order_id"] for o in context["orders"]}
        ):
            raise ValueError("Order task must target an observed customer order")
        if task.operation in {"answer", "modify_user_address"} and task.scope != "single":
            raise ValueError("Account/answer tasks cannot use an order scope")
        if any(key not in existing and key not in keys for key in task.depends_on):
            raise ValueError("Unknown dependency")
        if task.key in task.depends_on:
            raise ValueError("Task cannot depend on itself")
        args = {}
        for item in task.arguments:
            if item.name in args:
                raise ValueError("Duplicate argument")
            if (
                task.operation == "answer"
                or item.name not in catalog[task.operation].params.model_fields
            ):
                raise ValueError("Unknown business argument")
            args[item.name] = item.value
        if task.scope != "single" and "order_id" in args:
            raise ValueError("Order scopes bind each order_id during expansion")
        object_key = "user_id" if task.operation == "modify_user_address" else "order_id"
        if object_key in args and args[object_key] != task.object_id:
            raise ValueError("Argument object differs from task object")
        parsed.append((task, args, users[task.source_message_id]))
    for drop in delta.supersede:
        if drop.task_id not in existing or drop.source_message_id not in users:
            raise ValueError("Supersession needs a known task and customer evidence")
    return delta, parsed
