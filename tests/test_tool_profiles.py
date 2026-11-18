"""Tool interfaces may change, but reads stay pure and official writes stay identical."""

import copy
import json
from argparse import Namespace

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.tools import RetailTools

from backend.agent import AgentRunner
from backend.main import create_app
from backend.tool_profiles import DESCRIPTIONS, EXTRA_READ_TOOLS, TOOL_PROFILES
from tests.conftest import dataset
from tests.test_agent_runtime import ScriptedModel, tool


@pytest.fixture
def tool_episode(service, c1_episode):
    initial = copy.deepcopy(dataset(service, c1_episode["id"]))
    uid = service.context(c1_episode["id"])["user"]["user_id"]
    variants = {
        "small": {
            "item_id": "small",
            "options": {"size": "S", "color": "blue", "style": "v-neck"},
            "available": True,
            "price": 10.0,
        },
        "large": {
            "item_id": "large",
            "options": {"size": "L", "color": "blue", "style": "v-neck"},
            "available": True,
            "price": 12.0,
        },
        "purple": {
            "item_id": "purple",
            "options": {"size": "S", "color": "purple", "style": "v-neck"},
            "available": True,
            "price": 11.0,
        },
        "sold-out": {
            "item_id": "sold-out",
            "options": {"size": "S", "color": "purple", "style": "v-neck"},
            "available": False,
            "price": 8.0,
        },
    }
    initial["products"] = {
        "shirt": {"product_id": "shirt", "name": "T-Shirt", "variants": variants}
    }
    items = [
        {
            "item_id": key,
            "product_id": "shirt",
            "name": "T-Shirt",
            "options": variants[key]["options"],
            "price": variants[key]["price"],
        }
        for key in ["small", "small", "large"]
    ]
    initial["orders"]["#W9000001"]["items"] = copy.deepcopy(items)
    initial["orders"]["#W9000002"]["items"] = copy.deepcopy(items[:1])
    initial["orders"]["#W9000002"]["status"] = "delivered"
    foreign = copy.deepcopy(initial["orders"]["#W9000001"])
    foreign.update(order_id="#W9999999", user_id="other")
    initial["orders"]["#W9999999"] = foreign
    initial["users"]["other"] = copy.deepcopy(initial["users"][uid])
    initial["users"]["other"].update(user_id="other", orders=["#W9999999"])
    ref = service.store.create_session(user_id=uid, variant="tools_extended", initial_db=initial)
    return ref, initial, uid


def test_filter_orders_respects_owner_status_attributes_and_duplicate_quantities(
    service, tool_episode
):
    ref, before, _ = tool_episode
    result = service.call(
        ref["id"],
        "find_customer_order_items",
        {"statuses": ["pending"], "product_name": "t-shirt", "options": {"SIZE": " s "}},
    )
    data = result["data"]
    assert data["match_count"] == 2
    assert [(x["order_id"], x["item_index"], x["item_id"]) for x in data["matches"]] == [
        ("#W9000001", 0, "small"),
        ("#W9000001", 1, "small"),
    ]
    assert dataset(service, ref["id"]) == before
    assert service.store.session(ref["id"])["pending"] is None
    assert result["read_only"] is True and result["status"] == "observed"


def test_variants_do_not_relax_filters_or_hide_unavailable_counts(service, tool_episode):
    ref, before, _ = tool_episode
    args = {"product_id": "shirt", "options": {"color": "PURPLE", "size": "S"}}
    data = service.call(ref["id"], "find_product_variants", args)["data"]
    assert [v["item_id"] for v in data["matches"]] == ["purple"]
    assert data["total_variant_count"] == 4 and data["available_variant_count"] == 3
    all_matches = service.call(
        ref["id"], "find_product_variants", {**args, "available_only": False}
    )["data"]
    assert [v["item_id"] for v in all_matches["matches"]] == ["purple", "sold-out"]
    empty = service.call(
        ref["id"], "find_product_variants", {"product_id": "shirt", "options": {"size": "small"}}
    )["data"]
    assert empty["match_count"] == 0
    assert empty["option_values"]["size"] == ["L", "S"]
    assert dataset(service, ref["id"]) == before


def test_new_tools_are_explicitly_scoped_and_require_authentication(service, tool_episode):
    ref, _, _ = tool_episode
    assert "error" in service.call(ref["id"], "find_customer_order_items", {"user_id": "other"})
    unauth = service.store.create_session(variant="tools_extended")
    assert "error" in service.call(unauth["id"], "find_product_variants", {"product_id": "shirt"})
    for variant in ["b1", "lean", "tools_described", "tools_structured"]:
        with service.store.tx() as cx:
            service.store.update(cx, ref["id"], variant=variant)
        assert "error" in service.call(ref["id"], "find_product_variants", {"product_id": "shirt"})
        assert len(service.tool_definitions(variant)) == 16


def test_structured_reads_preserve_entire_official_result_and_errors(service, tool_episode):
    ref, initial, _ = tool_episode
    expected = (
        RetailTools(RetailDB.model_validate(initial))
        .get_product_details("shirt")
        .model_dump(mode="json")
    )
    result = service.call(ref["id"], "get_product_details", {"product_id": "shirt"})
    assert result["data"] == expected
    assert result["summary"] == {"total_variant_count": 4, "available_variant_count": 3}
    error = service.call(ref["id"], "get_order_details", {"order_id": "#W9999999"})
    assert error["status"] == "error" and error["error"]
    for variant in ["b1", "tools_described"]:
        with service.store.tx() as cx:
            service.store.update(cx, ref["id"], variant=variant)
        assert service.call(ref["id"], "get_product_details", {"product_id": "shirt"}) == expected


@pytest.mark.parametrize("variant", ["b1", *TOOL_PROFILES])
def test_write_preview_and_commit_use_identical_official_business_logic(
    service, tool_episode, variant
):
    _, initial, uid = tool_episode
    ref = service.store.create_session(user_id=uid, variant=variant, initial_db=initial)
    expected = RetailDB.model_validate(copy.deepcopy(initial))
    args = {"order_id": "#W9000001", "reason": "no longer needed"}
    RetailTools(expected).cancel_pending_order(**args)
    preview = service.call(ref["id"], "cancel_pending_order", args)
    assert preview["status"] == "awaiting_confirmation"
    assert dataset(service, ref["id"]) == initial
    if variant == "tools_extended":
        action = service.store.session(ref["id"])["pending"]
        service.call(ref["id"], "find_customer_order_items", {})
        assert service.store.session(ref["id"])["pending"] == action
    service.decide(ref["id"], preview["action_id"], True)
    assert dataset(service, ref["id"]) == expected.model_dump(mode="json")


def test_binding_and_runtime_record_actual_extended_interface(service, tool_episode):
    ref, _, _ = tool_episode
    model = ScriptedModel(
        tool(
            "find_product_variants",
            {"product_id": "shirt", "options": {"size": "S", "color": "purple"}},
        ),
        AIMessage(content="One available purple small variant."),
    )
    AgentRunner(service).run(ref["id"], "Find the available purple small t-shirt.", model=model)
    assert set(model.tool_names) == set(service.catalog) | set(EXTRA_READ_TOOLS)
    observation = next(m for m in model.requests[-1] if isinstance(m, ToolMessage))
    assert json.loads(observation.content)["data"]["match_count"] == 1
    snapshot = service.store.session(ref["id"])
    assert snapshot["manifest"]["tool_interface"] == service.tool_manifest("tools_extended")
    assert snapshot["usage"]["tool_calls"] == 1 and snapshot["usage"]["model_calls"] == 2
    assert not snapshot["agent_state"].get("planning_attempts")


def test_descriptions_keep_official_schemas_and_explain_preview_contract(service):
    assert set(DESCRIPTIONS) == set(service.catalog)
    official = service.tool_definitions("b1")
    described = service.tool_definitions("tools_described")
    for a, b in zip(official, described):
        assert a.name == b.name and a.params.model_json_schema() == b.params.model_json_schema()
        if b.name in service.writes:
            assert "stages a preview ONLY" in b.description
            assert "extra chat yes" in b.description
            assert "explicit user confirmation (yes/no)" not in b.description
    assert len({service.tool_manifest(v)["spec_sha256"] for v in ["b1", *TOOL_PROFILES]}) == 4


def test_health_advertises_variant_specific_tools_without_changing_base(service):
    with TestClient(create_app(store=service.store)) as client:
        health = client.get("/api/health").json()
        assert health["tools"] == 16
        assert health["tool_interfaces"]["tools_extended"]["count"] == 18
        assert health["tool_interfaces"]["b1"]["count"] == 16
        assert client.post("/api/sessions", json={"variant": "tools_extended"}).status_code == 201


def test_evaluator_refuses_unadvertised_extended_tools(tmp_path, monkeypatch):
    from benchmarks.run_http import run

    (tmp_path / "manifest.json").write_text(json.dumps({"task_ids": ["0"]}))
    (tmp_path / "complete.json").write_text(json.dumps({"complete": True, "task_ids": ["0"]}))
    monkeypatch.setenv("TEST_EVAL_TOKEN", "not-a-real-token")
    monkeypatch.setenv("TEST_MODEL_KEY", "not-a-real-key")

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "mode": "live",
                    "model": "test",
                    "model_ready": True,
                    "thinking": "off",
                    "tools": 16,
                    "protocol_version": "retail-http-v1",
                },
                request=httpx.Request("GET", "http://test/api/health"),
            )

    monkeypatch.setattr("benchmarks.run_http.httpx.Client", Client)
    args = Namespace(
        eval_token_env="TEST_EVAL_TOKEN",
        api_key_env="TEST_MODEL_KEY",
        base_url="http://test",
        model_base_url="http://model",
        fixtures=tmp_path,
        seeds="0",
        variant="tools_extended",
        model="test",
        thinking="off",
    )
    with pytest.raises(ValueError, match="does not advertise"):
        run(args)


def test_comparison_labels_tool_changes_and_rejects_runtime_catalog_drift(tmp_path):
    from benchmarks.run_http import compare

    common = {
        k: "same"
        for k in [
            "model",
            "simulator_base_url",
            "temperature",
            "source_hashes",
            "fixture_hashes",
            "protocol_version",
            "comparator_version",
            "max_user_actions",
            "max_seconds",
            "max_tokens",
        ]
    }
    common.update(
        task_ids=["0"],
        seeds=[0],
        evaluator_source_hashes={"benchmarks/reference/simulator.py": "same"},
    )
    budgets = {
        "max_model_calls": 80,
        "max_tool_calls": 80,
        "max_active_seconds": 600,
        "max_output_tokens": 4096,
    }
    for side, count in [("left", 16), ("right", 18)]:
        folder = tmp_path / side
        (folder / "attempt").mkdir(parents=True)
        interface = {"profile": side, "count": count, "spec_sha256": side}
        (folder / "manifest.json").write_text(json.dumps({**common, "tool_interface": interface}))
        (folder / "complete.json").write_text(json.dumps({"suite_complete": True}))
        (folder / "results.json").write_text(
            json.dumps(
                [
                    {
                        "path": "attempt",
                        "task_id": "0",
                        "seed": 0,
                        "snapshot_available": True,
                        "success": True,
                        "termination": "simulator_finish",
                        "agent_usage": {"model_calls": 1},
                    }
                ]
            )
        )
        (folder / "attempt/snapshot.json").write_text(
            json.dumps(
                {
                    "manifest": {
                        "mode": "live",
                        "model": "same",
                        "tau2_expected_sha": "same",
                        "policy_sha256": "same",
                        "agent_runtime": budgets,
                        "tool_interface": interface,
                    }
                }
            )
        )
    args = Namespace(
        left=tmp_path / "left",
        right=tmp_path / "right",
        samples=10,
        seed=0,
        output=tmp_path / "comparison.json",
    )
    compare(args)
    result = json.loads(args.output.read_text())
    assert result["comparison_kind"] == "tool_interface" and result["difference"] == 0
    path = tmp_path / "right/attempt/snapshot.json"
    snapshot = json.loads(path.read_text())
    snapshot["manifest"]["tool_interface"]["count"] = 16
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="tool interface differs"):
        compare(args)


def test_extended_catalog_uses_real_sdk_tool_transport(service, tool_episode):
    from langchain_openai import ChatOpenAI

    ref, _, _ = tool_episode
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        names = {t["function"]["name"] for t in body["tools"]}
        assert names == set(service.catalog) | set(EXTRA_READ_TOOLS)
        assert body["parallel_tool_calls"] is False
        if len(requests) == 1:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "filter-1",
                        "type": "function",
                        "function": {
                            "name": "find_customer_order_items",
                            "arguments": json.dumps(
                                {"statuses": ["pending"], "options": {"size": "S"}}
                            ),
                        },
                    }
                ],
            }
            reason = "tool_calls"
        else:
            result = json.loads(body["messages"][-1]["content"])
            assert result["read_only"] is True and result["data"]["match_count"] == 2
            msg = {"role": "assistant", "content": "Two matching small items in the pending order."}
            reason = "stop"
        return httpx.Response(
            200,
            json={
                "id": "test-read-profile",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [{"index": 0, "message": msg, "finish_reason": reason}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    model = ChatOpenAI(
        model="test",
        api_key="test-only",
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    before = dataset(service, ref["id"])
    answer = AgentRunner(service).run(
        ref["id"], "Find my small items in pending orders.", model=model
    )
    assert "Two matching" in answer and len(requests) == 2
    assert dataset(service, ref["id"]) == before
    assert service.store.session(ref["id"])["usage"]["tool_calls"] == 1
