"""Independent StateGraph executor; Store remains the only durable state source."""

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict
from typing import TypedDict

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langgraph.graph import END, START, StateGraph
from openai import LengthFinishReasonError

from backend import config, telemetry
from backend.agent import (
    CONFIRMATION_PAUSE,
    WEB_CONTRACT,
    AgentBudgetExceeded,
    build_agent,
    get_model,
)
from backend.graph_context import (
    EXECUTION_GUIDANCE,
    NOTES_PROMPT,
    REVIEW_PROMPT,
    SOP,
    CompletionReview,
    RequestNotes,
    approval_message,
    model_context,
)
from backend.graph_profiles import GRAPH_PROFILES


class TurnState(TypedDict, total=False):
    route: str
    content: str
    status: str
    reason: str | None


def run_graph(self, sid, emit, model, turn_text):
    started = time.monotonic()
    session = self.store.session(sid)
    profile = GRAPH_PROFILES[session["variant"]]
    history = messages_from_dict(session["history"])
    # New turns can follow a process interruption after an assistant tool call was saved.
    # Close missing observations without replaying a business operation whose outcome is unknown.
    repaired, pending_calls = [], {}
    for entry in [*history, None]:
        if not isinstance(entry, ToolMessage) and pending_calls:
            for call_id, name in pending_calls.items():
                repaired.append(
                    ToolMessage(
                        content=json.dumps(
                            {
                                "error": "Tool observation interrupted. No call was replayed; consult current business state and actual application receipts before acting."
                            }
                        ),
                        tool_call_id=call_id,
                        name=name,
                    )
                )
            pending_calls.clear()
        if entry is None:
            break
        repaired.append(entry)
        if isinstance(entry, AIMessage):
            pending_calls.update(
                {
                    c["id"]: c["name"]
                    for c in entry.tool_calls + entry.invalid_tool_calls
                    if c.get("id")
                }
            )
        elif isinstance(entry, ToolMessage):
            pending_calls.pop(entry.tool_call_id, None)
    history = repaired
    usage = dict(session.get("usage") or {})
    for key in ("model_calls", "tool_calls", "input_tokens", "output_tokens", "known_usage_calls"):
        usage.setdefault(key, 0)
    usage.setdefault("unknown_usage_calls", usage["model_calls"] - usage["known_usage_calls"])
    active_before = usage.get("active_seconds", 0)
    state = session.get("agent_state") or {}
    graph_state = state.setdefault("graph_v1", {})
    max_calls = int(os.getenv("AGENT_MAX_MODEL_CALLS", "80"))
    max_tools = int(os.getenv("AGENT_MAX_TOOL_CALLS", "80"))
    max_seconds = float(os.getenv("AGENT_MAX_ACTIVE_SECONDS", "600"))
    policy = config.POLICY_PATH.read_text()
    manifest = dict(session.get("manifest") or {})
    manifest["tool_interface"] = self.service.tool_manifest(
        session["variant"], account_bound=session["owner_user_id"] is not None
    )
    manifest["agent_runtime"] = {
        "implementation": "langgraph-stategraph-v1",
        "features": asdict(profile),
        "persistence": "application-store-v1",
        "checkpoint_replay": False,
        "thinking": config.MODEL_THINKING,
        "max_model_calls": max_calls,
        "max_tool_calls": max_tools,
        "max_active_seconds": max_seconds,
        "max_output_tokens": int(os.getenv("AGENT_MAX_OUTPUT_TOKENS", "4096")),
        "model_request_timeout_seconds": config.MODEL_REQUEST_TIMEOUT_SECONDS,
        "policy_sha256": hashlib.sha256(policy.encode()).hexdigest(),
        "guidance_sha256": hashlib.sha256(
            ((SOP if profile.sop else "") + (EXECUTION_GUIDANCE if profile.guided else "")).encode()
        ).hexdigest(),
        "notes_prompt_sha256": hashlib.sha256(
            (NOTES_PROMPT if profile.notes else "").encode()
        ).hexdigest(),
        "review_prompt_sha256": hashlib.sha256(
            (REVIEW_PROMPT if profile.review else "").encode()
        ).hexdigest(),
    }
    rec = telemetry.recorder().start_turn(sid, turn_text)

    def save(**fields):
        usage["active_seconds"] = active_before + time.monotonic() - started
        with self.store.tx() as cx:
            current = self.store.session(sid, cx)
            if current["status"] == "finished":
                fields.update(status="finished", termination_reason=current["termination_reason"])
            self.store.update(
                cx,
                sid,
                history=messages_to_dict(history),
                usage=usage,
                agent_state=state,
                manifest=manifest,
                **fields,
            )

    def finish(content, status="ready", reason=None):
        with self.store.tx() as cx:
            current = self.store.session(sid, cx)
            if current["status"] == "finished":
                status, reason = "finished", current["termination_reason"]
            messages = current["messages"] + [
                {"id": uuid.uuid4().hex, "role": "assistant", "content": content}
            ]
        # Synthetic stop prose is part of history too, for coherent receipt continuation.
        if (
            reason
            or not history
            or not isinstance(history[-1], AIMessage)
            or history[-1].tool_calls
        ):
            history.append(
                AIMessage(
                    content=content,
                    additional_kwargs={"application_pause_action_id": current["pending"]["id"]}
                    if profile.guided and status == "awaiting_confirmation" and current["pending"]
                    else {},
                )
            )
        save(messages=messages, status=status, termination_reason=reason)
        current = self.store.session(sid)
        status, reason = current["status"], current["termination_reason"]
        rec.finish(content)
        emit(
            {
                "type": "status",
                "status": status,
                "message": content,
                "termination_reason": reason,
            }
        )
        return content

    def recording_emit(event):
        if event.get("type") == "tool_end":
            rec.tool(
                event.get("name"),
                event.get("duration_ms"),
                event.get("ok", True),
                event.get("args"),
                event.get("result"),
            )
        emit(event)

    def invoke_stage(bound_model, messages, phase):
        if self.store.session(sid)["status"] == "finished":
            raise AgentBudgetExceeded("episode_finished")
        if usage["model_calls"] >= max_calls:
            raise AgentBudgetExceeded("model_call_budget")
        if active_before + time.monotonic() - started >= max_seconds:
            raise AgentBudgetExceeded("time_budget")
        usage["model_calls"] += 1
        phases = usage.setdefault("phases", {})
        phase_usage = phases.setdefault(
            phase,
            {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0},
        )
        phase_usage["model_calls"] += 1
        save()
        call_started = time.monotonic()
        try:
            reply = bound_model.invoke(messages)
        except Exception as exc:
            completion = exc.completion if isinstance(exc, LengthFinishReasonError) else None
            raw_usage = completion.usage if completion is not None else None
            if (
                raw_usage is not None
                and raw_usage.prompt_tokens is not None
                and raw_usage.completion_tokens is not None
            ):
                usage["known_usage_calls"] += 1
                for key, value in (
                    ("input_tokens", raw_usage.prompt_tokens),
                    ("output_tokens", raw_usage.completion_tokens),
                ):
                    usage[key] += value
                    phase_usage[key] += value
            else:
                usage["unknown_usage_calls"] += 1
                phase_usage["unknown_usage_calls"] += 1
            if completion is not None:
                state.setdefault("model_failures", []).append(
                    {
                        "phase": phase,
                        "error": type(exc).__name__,
                        "response": completion.model_dump(mode="json"),
                    }
                )
            rec.model_call(
                (time.monotonic() - call_started) * 1000,
                raw_usage.prompt_tokens if raw_usage else None,
                raw_usage.completion_tokens if raw_usage else None,
                "length" if completion is not None else "error",
                [],
                phase=phase,
            )
            raise
        tokens = reply.usage_metadata or {}
        if all(tokens.get(key) is not None for key in ("input_tokens", "output_tokens")):
            usage["known_usage_calls"] += 1
        else:
            usage["unknown_usage_calls"] += 1
            phase_usage["unknown_usage_calls"] += 1
        rec.model_call(
            (time.monotonic() - call_started) * 1000,
            tokens.get("input_tokens"),
            tokens.get("output_tokens"),
            (reply.response_metadata or {}).get("finish_reason"),
            [call["name"] for call in reply.tool_calls],
            phase=phase,
        )
        for key in ("input_tokens", "output_tokens"):
            if tokens.get(key) is not None:
                usage[key] += tokens[key]
                phase_usage[key] += tokens[key]
        save()
        return reply

    runtime_model = model or get_model()
    bound = build_agent(self.service, sid, emit, runtime_model, rec)
    review_used, feedback = False, ""
    invalid, calls = [], []
    current_context = self.service.context(sid)
    user_messages = [m for m in session["messages"] if m["role"] == "user"]
    user_ids = {m["id"] for m in user_messages}
    latest_user_id = user_messages[-1]["id"] if user_messages else None
    _, existing_receipts = model_context(history)
    had_problem = any(
        json.loads(r["content"].split("\n", 1)[1]).get("status") == "rejected"
        for r in existing_receipts
        if r["after_user_messages"] == len(user_messages)
        and str(r["content"]).startswith("APPLICATION RECEIPT:\n")
    )

    def check_budget():
        current = self.store.session(sid)
        if current["status"] == "finished":
            return current["termination_reason"] or "episode_finished"
        if active_before + time.monotonic() - started >= max_seconds:
            return "time_budget"
        if usage["model_calls"] >= max_calls:
            return "model_call_budget"
        if usage["tool_calls"] >= max_tools:
            return "tool_call_budget"
        return None

    def load(turn):
        current = self.store.session(sid)
        if current["status"] == "finished":
            return {
                "route": "finish",
                "content": "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."
                if current["transferred"]
                else "会话已结束，已停止自动处理。",
                "status": "finished",
                "reason": current["termination_reason"],
            }
        if current["pending"]:
            emit({"type": "proposal", "pending": current["pending"]})
            return {
                "route": "finish",
                "content": approval_message(
                    current["pending"],
                    self.store.events(sid),
                    chinese=any("\u4e00" <= c <= "\u9fff" for c in user_messages[-1]["content"])
                    if user_messages
                    else False,
                )
                if profile.guided
                else CONFIRMATION_PAUSE,
                "status": "awaiting_confirmation",
                "reason": None,
            }
        reason = check_budget()
        if reason:
            return {
                "route": "finish",
                "content": "本次会话已达到处理预算，已停止自动处理。",
                "status": "finished",
                "reason": reason,
            }
        return {
            "route": "notes"
            if profile.notes
            and latest_user_id
            and graph_state.get("noted_message_id") != latest_user_id
            else "act"
        }

    def notes(turn):
        record = {"message_id": latest_user_id}
        # Clear obsolete notes before attempting an update. A failed parse cannot retain old choices.
        graph_state["requests"] = []
        graph_state["noted_message_id"] = latest_user_id
        graph_state.setdefault("note_attempts", []).append(record)
        try:
            response = invoke_stage(
                runtime_model.bind(
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "request_notes",
                            "strict": True,
                            "schema": RequestNotes.model_json_schema(),
                        },
                    }
                ),
                [
                    SystemMessage(content=NOTES_PROMPT),
                    HumanMessage(content=json.dumps(user_messages, ensure_ascii=False)),
                ],
                "notes",
            )
            record["response"] = response.content
            parsed = RequestNotes.model_validate_json(response.content)
            if any(n.source_message_id not in user_ids for n in parsed.requests):
                raise ValueError("Unknown source message ID")
            graph_state["requests"] = parsed.model_dump()["requests"]
        except (ValueError, LengthFinishReasonError) as exc:
            record["error"] = type(exc).__name__
        save()
        return {}

    def act(turn):
        nonlocal invalid, calls, current_context
        current_context = self.service.context(sid)
        conversation, receipts = model_context(history, profile.context)
        system_content = policy + "\n" + WEB_CONTRACT
        if profile.sop:
            system_content += "\n" + SOP
        system_content += "\nCUSTOMER CONTEXT:\n" + json.dumps(current_context, ensure_ascii=False)
        if profile.notes and graph_state.get("requests"):
            system_content += (
                "\nFALLIBLE REQUEST NOTES (original user messages override these; not execution facts):\n"
                + json.dumps(graph_state["requests"], ensure_ascii=False)
            )
        if receipts:
            system_content += "\nTRUSTED APPLICATION EVENTS (chronological):\n" + json.dumps(
                receipts, ensure_ascii=False
            )
        if feedback:
            system_content += (
                "\nADVISORY CHECK (verify against original messages and receipts):\n" + feedback
            )
        if profile.guided:
            payment_facts = [
                {
                    "order_id": order["order_id"],
                    "status": order["status"],
                    "original_payment_method_id": next(
                        (
                            entry["payment_method_id"]
                            for entry in order["payment_history"]
                            if entry["transaction_type"] == "payment"
                        ),
                        None,
                    ),
                }
                for order in current_context["orders"]
            ]
            system_content += (
                "\nOBSERVED ORDER PAYMENT FACTS (not a customer choice):\n"
                + json.dumps(payment_facts, ensure_ascii=False)
            )
            system_content += "\n" + EXECUTION_GUIDANCE
        message = invoke_stage(
            bound,
            [
                SystemMessage(
                    content=system_content,
                    additional_kwargs={
                        "retail_context": current_context,
                        "retail_receipts": receipts,
                    },
                ),
                *conversation,
            ],
            "executor_correction" if feedback else "executor",
        )
        invalid = message.invalid_tool_calls or []
        for call in invalid:
            if not call.get("id"):
                call["id"] = uuid.uuid4().hex
        history.append(message)
        calls = message.tool_calls + invalid
        content = (
            "".join(c.get("text", "") for c in message.content if isinstance(c, dict))
            if isinstance(message.content, list)
            else str(message.content or "")
        )
        save()
        if calls:
            return {"route": "tools", "content": content}
        # A final model response must still respect a concurrently frozen episode and wall time.
        current = self.store.session(sid)
        if current["status"] == "finished":
            return {
                "route": "finish",
                "content": "会话已结束，已停止自动处理。",
                "status": "finished",
                "reason": current["termination_reason"],
            }
        if active_before + time.monotonic() - started >= max_seconds:
            return {
                "route": "finish",
                "content": "本次会话已达到处理预算，已停止自动处理。",
                "status": "finished",
                "reason": "time_budget",
            }
        should_review = (
            profile.review
            and not review_used
            and (len(graph_state.get("requests", [])) > 1 or had_problem)
        )
        return {
            "route": "review" if should_review else "finish",
            "content": content,
            "status": "ready",
            "reason": None,
        }

    def tools(turn):
        nonlocal had_problem
        for call in calls:
            current = self.store.session(sid)
            if current["status"] == "finished":
                result = {"error": "Episode finished; operation not executed."}
            elif usage["tool_calls"] >= max_tools:
                result = {"error": "Tool-call budget exhausted; operation not executed."}
            elif active_before + time.monotonic() - started >= max_seconds:
                result = {"error": "Active-time budget exhausted; operation not executed."}
            else:
                usage["tool_calls"] += 1
                save()
                if call in invalid:
                    result = {
                        "error": "Invalid JSON tool arguments; operation not executed. Return valid JSON arguments for one business tool."
                    }
                elif len(calls) != 1:
                    result = {
                        "error": "Call exactly one business tool at a time. This parallel batch was not executed; retry sequentially."
                    }
                else:
                    result = self.service.call(sid, call["name"], call["args"], recording_emit)
                if call in invalid or len(calls) != 1:
                    recording_emit(
                        {
                            "type": "tool_end",
                            "name": call["name"],
                            "args": call["args"],
                            "result": result,
                            "ok": False,
                            "duration_ms": 0,
                        }
                    )
            had_problem = had_problem or isinstance(result, dict) and "error" in result
            history.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
            )
            save()
        return {}

    def review(turn):
        nonlocal review_used, feedback
        review_used = True
        record = {"candidate_reply": turn["content"]}
        graph_state.setdefault("review_attempts", []).append(record)
        conversation, receipts = model_context(history, profile.context)
        payload = {
            "customer_messages": user_messages,
            "notes": graph_state.get("requests", []),
            "context": current_context,
            "receipts": receipts,
            "observations": [m.content for m in conversation if isinstance(m, ToolMessage)],
            "draft": turn["content"],
        }
        try:
            response = invoke_stage(
                runtime_model.bind(
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "completion_review",
                            "strict": True,
                            "schema": CompletionReview.model_json_schema(),
                        },
                    }
                ),
                [
                    SystemMessage(content=REVIEW_PROMPT + "\nPOLICY:\n" + policy),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                ],
                "reviewer",
            )
            record["response"] = response.content
            parsed = CompletionReview.model_validate_json(response.content)
            if any(i.source_message_id not in user_ids for i in parsed.issues):
                raise ValueError("Unknown issue source message")
            if (
                parsed.action == "revise"
                and not parsed.issues
                or parsed.action == "pass"
                and parsed.issues
            ):
                raise ValueError("Inconsistent review")
        except (ValueError, LengthFinishReasonError) as exc:
            record["error"] = type(exc).__name__
            save()
            return {"route": "finish"}
        if parsed.action == "revise":
            feedback = json.dumps(parsed.model_dump()["issues"], ensure_ascii=False)
            history.pop()  # Draft was not sent; the diagnostic record preserves it.
            save()
            return {"route": "load"}
        save()
        return {"route": "finish"}

    def terminal(turn):
        return {"content": finish(turn["content"], turn.get("status", "ready"), turn.get("reason"))}

    graph = StateGraph(TurnState)
    for name, node in (
        ("load", load),
        ("notes", notes),
        ("act", act),
        ("tools", tools),
        ("review", review),
        ("finish", terminal),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "load")
    graph.add_conditional_edges(
        "load", lambda t: t["route"], {n: n for n in ("notes", "act", "finish")}
    )
    graph.add_edge("notes", "load")
    graph.add_conditional_edges(
        "act", lambda t: t["route"], {n: n for n in ("tools", "review", "finish")}
    )
    graph.add_edge("tools", "load")
    graph.add_conditional_edges("review", lambda t: t["route"], {n: n for n in ("load", "finish")})
    graph.add_edge("finish", END)
    emit({"type": "status", "status": "running", "message": "正在处理…"})
    save(status="running")
    try:
        # Budgets above bound execution; recursion_limit only prevents a framework default of 25.
        return graph.compile().invoke(
            {}, config={"recursion_limit": 8 * (max_calls + max_tools + 1)}
        )["content"]
    except AgentBudgetExceeded as exc:
        return finish("本次会话已停止自动处理，未完成操作没有执行。", "finished", str(exc))
    except Exception as exc:
        rec.error = type(exc).__name__
        save(status="error")
        rec.finish()
        raise
