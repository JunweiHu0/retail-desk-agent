"""No conversation context may leak between benchmark adapters or web sessions."""

import threading
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tau2.data_model.message import UserMessage

from backend.agent import AgentRunner, DemoRetailModel
from benchmarks.tau2_agent import DeepRetailAgent
from tests.conftest import authenticate


class EchoModel(DemoRetailModel):
    """Answers with the latest human text and records every prompt it was given."""

    prompts: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        humans = [m.content for m in messages if isinstance(m, HumanMessage)]
        self.prompts.append(humans)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="echo:" + humans[-1]))]
        )


def tokens(n):
    return [f"TOKEN-{i}-{uuid.uuid4().hex[:8]}" for i in range(n)]


def test_interleaved_benchmark_adapters_share_a_model_but_not_context(service):
    model = EchoModel(prompts=[])
    tools = list(service.catalog.values())
    a = DeepRetailAgent(tools, "Retail policy", model=model)
    b = DeepRetailAgent(tools, "Retail policy", model=model)
    sa, sb = a.get_init_state(), b.get_init_state()
    ta, tb = tokens(2)
    for turn in range(3):
        ra, sa = a.generate_next_message(UserMessage(role="user", content=f"{ta} #{turn}"), sa)
        rb, sb = b.generate_next_message(UserMessage(role="user", content=f"{tb} #{turn}"), sb)
        assert ra.content == f"echo:{ta} #{turn}"
        assert rb.content == f"echo:{tb} #{turn}"
    for prompt in model.prompts:
        text = " ".join(prompt)
        assert (ta in text) != (tb in text)
    assert all(tb not in str(m.content) for m in sa.messages)
    assert all(ta not in str(m.content) for m in sb.messages)


def test_concurrent_benchmark_adapters_keep_their_own_context(service):
    model = EchoModel(prompts=[])
    tools = list(service.catalog.values())
    marks = tokens(6)
    out, errors = {}, []

    def worker(mark):
        try:
            agent = DeepRetailAgent(tools, "Retail policy", model=model)
            state = agent.get_init_state()
            replies = []
            for turn in range(3):
                r, state = agent.generate_next_message(
                    UserMessage(role="user", content=f"{mark} #{turn}"), state
                )
                replies.append(r.content)
            out[mark] = (replies, state)
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(m,)) for m in marks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for mark, (replies, state) in out.items():
        assert replies == [f"echo:{mark} #{i}" for i in range(3)]
        seen = " ".join(str(m.content) for m in state.messages)
        assert all(other not in seen for other in marks if other != mark)
    for prompt in model.prompts:
        text = " ".join(prompt)
        assert sum(m in text for m in marks) == 1


def test_transfer_in_one_web_session_does_not_affect_another(service, pending_order):
    a = service.store.create_session()["id"]
    b = service.store.create_session()["id"]
    authenticate(service, a, pending_order["user_id"])
    service.call(a, "transfer_to_human_agents", {"summary": "customer asked"})
    assert service.store.session(a)["transferred"]
    assert not service.store.session(b)["transferred"]
    assert service.store.events(b) == []


def test_concurrent_web_sessions_keep_separate_histories(service):
    runner = AgentRunner(service)
    model = EchoModel(prompts=[])
    sids = [service.store.create_session()["id"] for _ in range(4)]
    marks = dict(zip(sids, tokens(4)))
    errors = []

    def worker(sid):
        try:
            for turn in range(2):
                runner.run(sid, f"{marks[sid]} #{turn}", model=model)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in sids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for sid in sids:
        session = service.store.session(sid)
        transcript = " ".join(m["content"] for m in session["messages"])
        history = " ".join(str(m["data"]["content"]) for m in session["history"])
        for other, mark in marks.items():
            assert (mark in transcript) == (other == sid)
            assert (mark in history) == (other == sid)
        assert session["messages"][-1]["content"] == f"echo:{marks[sid]} #1"
