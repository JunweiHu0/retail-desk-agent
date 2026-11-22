"""Unit tests for the external LLM-as-judge; no API calls are made."""

import json

import httpx

from benchmarks.reference.judge import (
    SECONDARY_PROMPT,
    DeepSeekJudge,
    JudgeError,
    build_judge_input,
    parse_secondary,
    parse_verdict,
    summarize,
    summarize_secondary,
)

VERDICT = {
    "verdict": "pass",
    "score": 9,
    "dimensions": {
        "task_completion": 2,
        "policy_compliance": 2,
        "tool_use": 2,
        "communication": 2,
        "safety": 1,
    },
    "proposal_rubric": {
        "intent_recognition": 5,
        "empathy": 4,
        "policy_compliance": 5,
        "missing_information": 4,
        "overall": 4,
    },
    "hallucination": False,
    "false_success_claim": False,
    "false_claim": False,
    "reason": "The agent completed the requested exchange and asked for confirmation.",
    "violations": [],
    "evidence": ["tool exchange_delivered_order_items", "receipt shown"],
}


def response_with(content: str, status=200):
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        },
    )


def test_parse_verdict_accepts_valid_shape():
    assert parse_verdict(json.dumps(VERDICT))["verdict"] == "pass"


def test_parse_verdict_rejects_missing_dimension():
    bad = dict(VERDICT)
    bad["dimensions"] = {"task_completion": 2}
    try:
        parse_verdict(json.dumps(bad))
    except JudgeError as exc:
        assert "dimensions" in str(exc)
    else:
        raise AssertionError("malformed dimension set must be rejected")


def test_build_judge_input_contains_scenario_and_tools():
    payload = build_judge_input(
        task_id="7",
        seed=1,
        user_scenario={"instructions": {"reason_for_call": "exchange a lamp"}},
        result={"termination": "simulator_finish", "success": True},
        session={
            "messages": [
                {"role": "user", "content": "I want to exchange the lamp."},
                {"role": "assistant", "content": "Confirmed."},
            ],
            "context": {"orders": []},
        },
        trace=[
            {
                "events": [
                    {
                        "data": {
                            "type": "tool_end",
                            "name": "exchange_delivered_order_items",
                            "args": {"item_ids": ["1"]},
                            "ok": True,
                            "result": {"status": "ok"},
                        }
                    }
                ]
            }
        ],
        score={"success": True},
        mismatches=[],
    )
    assert payload["task_id"] == "7"
    assert payload["seed"] == 1
    assert payload["user_scenario"]["instructions"]["reason_for_call"] == "exchange a lamp"
    assert payload["tool_calls"][0]["name"] == "exchange_delivered_order_items"
    assert payload["conversation"][0]["role"] == "user"


def test_judge_aggregates_streaming_chunks_and_usage():
    def handler(request):
        return response_with(json.dumps(VERDICT))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge = DeepSeekJudge(api_key="test", client=client)
    result = judge.judge({"task_id": "1", "seed": 0})
    assert result["verdict"]["score"] == 9
    assert judge.usage.calls == 1
    assert judge.usage.prompt_tokens == 100
    assert judge.usage.completion_tokens == 50


def test_judge_falls_back_when_json_mode_is_rejected():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if "response_format" in calls[-1]:
            return httpx.Response(400, json={"error": "unsupported response_format"})
        return response_with(json.dumps(VERDICT))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge = DeepSeekJudge(api_key="test", client=client, sleeps=lambda _: None)
    result = judge.judge({"task_id": "1", "seed": 0})
    assert result["verdict"]["verdict"] == "pass"
    assert len(calls) == 2


def test_summarize_reports_pass_rate_and_dimension_means():
    summary = summarize(
        [
            VERDICT,
            {
                **VERDICT,
                "verdict": "fail",
                "score": 4,
                "false_claim": True,
                "false_success_claim": True,
                "hallucination": True,
            },
        ]
    )
    assert summary["episodes"] == 2
    assert summary["pass"] == 1
    assert summary["fail"] == 1
    assert summary["mean_score"] == 6.5
    assert summary["mean_dimensions"]["safety"] == 1.0
    assert summary["false_claim_rate"] == 0.5
    assert summary["false_claim_judged"] == 2
    assert summary["false_success_claim_rate"] == 0.5
    assert summary["hallucination_rate"] == 0.5
    assert summary["mean_proposal_rubric"]["overall"] == 4.0
    assert summary["proposal_rubric_judged"] == 2


def test_parse_verdict_accepts_missing_proposal_rubric_for_old_raw():
    old = {
        key: value
        for key, value in VERDICT.items()
        if key not in {"proposal_rubric", "hallucination", "false_success_claim"}
    }
    parsed = parse_verdict(old)
    assert "proposal_rubric" not in parsed


def test_parse_verdict_rejects_out_of_range_proposal_rubric():
    bad = json.loads(json.dumps(VERDICT))
    bad["proposal_rubric"]["empathy"] = 6
    try:
        parse_verdict(bad)
    except JudgeError as exc:
        assert "proposal_rubric" in str(exc)
    else:
        raise AssertionError("out-of-range proposal_rubric must be rejected")


def test_parse_verdict_accepts_missing_false_claim_for_old_raw():
    old = {key: value for key, value in VERDICT.items() if key != "false_claim"}
    parsed = parse_verdict(old)
    assert "false_claim" not in parsed


def test_parse_verdict_rejects_non_boolean_false_claim():
    bad = {**VERDICT, "false_claim": "yes"}
    try:
        parse_verdict(bad)
    except JudgeError as exc:
        assert "false_claim" in str(exc)
    else:
        raise AssertionError("non-boolean false_claim must be rejected")


def test_judge_sends_thinking_and_returns_attempt_records():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(VERDICT),
                            "reasoning_content": "step by step",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "completion_tokens_details": {"reasoning_tokens": 5},
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge = DeepSeekJudge(
        api_key="test",
        client=client,
        model="deepseek-flash",
        thinking=True,
        reasoning_effort="high",
        max_tokens=32768,
    )
    result = judge.judge({"task_id": "1", "seed": 0})
    assert seen["thinking"] == {"type": "enabled"}
    assert seen["reasoning_effort"] == "high"
    assert seen["max_tokens"] == 32768
    assert result["reasoning_content"] == "step by step"
    assert result["records"][0]["finish_reason"] == "stop"
    assert judge.usage.reasoning_tokens == 5


def test_judge_keeps_raw_content_when_parsing_fails():
    bad = '{"verdict": "pass", "score": 5}'

    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: response_with(bad))
    )
    judge = DeepSeekJudge(
        api_key="test", client=client, max_retries=1, sleeps=lambda _: None
    )
    try:
        judge.judge({"task_id": "1", "seed": 0})
    except JudgeError as exc:
        assert exc.records[0]["content"] == bad
        assert "missing keys" in str(exc)
    else:
        raise AssertionError("malformed verdict must raise")


def test_parse_verdict_ignores_extra_keys():
    verdict = json.loads(json.dumps(VERDICT))
    verdict["confidence"] = 0.9
    verdict["dimensions"]["extra"] = 2
    parsed = parse_verdict(verdict)
    assert set(parsed["dimensions"]) == {
        "task_completion",
        "policy_compliance",
        "tool_use",
        "communication",
        "safety",
    }


def test_reparse_raw_rebuilds_verdicts_without_api(tmp_path):
    from benchmarks.run_judge import reparse_raw, write_raw

    write_raw(
        tmp_path / "raw" / "task-7-seed-1.json",
        task_id="7",
        seed=1,
        model="deepseek-flash",
        thinking=True,
        reasoning_effort="high",
        max_tokens=2048,
        mode="diagnostic",
        records=[{"attempt": 1, "content": json.dumps(VERDICT), "parse_error": None}],
    )
    verdicts = reparse_raw(tmp_path, "fallback")
    assert verdicts[("7", 1)]["verdict"] == "pass"
    assert verdicts[("7", 1)]["judge_model"] == "deepseek-flash"


SECONDARY = {
    "proposal_rubric": {
        "intent_recognition": 5,
        "empathy": 4,
        "policy_compliance": 5,
        "missing_information": 4,
        "overall": 4,
    },
    "hallucination": False,
    "false_success_claim": False,
    "reason": "The agent understood the request and asked for the missing ZIP code.",
    "evidence": ["user: please change the address", "assistant: which ZIP?"],
}


def test_judge_secondary_mode_uses_secondary_prompt():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return response_with(json.dumps(SECONDARY))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge = DeepSeekJudge(api_key="test", client=client, mode="secondary")
    result = judge.judge({"task_id": "1", "seed": 0})
    assert seen["messages"][0]["content"] == SECONDARY_PROMPT
    assert result["verdict"]["proposal_rubric"]["overall"] == 4
    assert "verdict" not in result["verdict"]


def test_parse_secondary_rejects_out_of_range_aspect():
    bad = json.loads(json.dumps(SECONDARY))
    bad["proposal_rubric"]["empathy"] = 6
    try:
        parse_secondary(bad)
    except JudgeError as exc:
        assert "empathy" in str(exc)
    else:
        raise AssertionError("out-of-range empathy must be rejected")


def test_summarize_secondary_reports_rates():
    summary = summarize_secondary(
        [
            SECONDARY,
            {**SECONDARY, "hallucination": True, "false_success_claim": True},
        ]
    )
    assert summary["judge_mode"] == "secondary"
    assert summary["episodes"] == 2
    assert summary["mean_proposal_rubric"]["overall"] == 4.0
    assert summary["hallucination_rate"] == 0.5
    assert summary["false_success_claim_rate"] == 0.5


def test_reparse_raw_secondary_mode(tmp_path):
    from benchmarks.run_judge import reparse_raw, write_raw

    write_raw(
        tmp_path / "raw" / "task-7-seed-1.json",
        task_id="7",
        seed=1,
        model="deepseek-flash",
        thinking=True,
        reasoning_effort="high",
        max_tokens=2048,
        mode="secondary",
        records=[{"attempt": 1, "content": json.dumps(SECONDARY), "parse_error": None}],
    )
    verdicts = reparse_raw(tmp_path, "fallback")
    assert verdicts[("7", 1)]["judge_mode"] == "secondary"
    assert verdicts[("7", 1)]["proposal_rubric"]["overall"] == 4


def test_load_payload_rows_accepts_gzip(tmp_path):
    import gzip

    from benchmarks.run_judge import load_payload_rows

    path = tmp_path / "payloads.jsonl.gz"
    row = {
        "task_id": "7",
        "seed": 1,
        "split": "test",
        "source": "unit",
        "payload": {"task_id": "7", "seed": 1, "user_scenario": {}},
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    rows = load_payload_rows(path)
    assert rows[0]["task_id"] == "7"
    assert rows[0]["seed"] == 1
    assert rows[0]["payload"]["user_scenario"] == {}
