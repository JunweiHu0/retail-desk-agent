import copy
import os

import pytest

# Tests exercise the offline demo model. A developer's .env may set
# AGENT_MODE=live; set this before backend.config is imported (dotenv never
# overrides an existing variable).
os.environ["AGENT_MODE"] = "demo"

from backend.retail import RetailService  # noqa: E402
from backend.store import Store


@pytest.fixture(autouse=True)
def offline_model(monkeypatch):
    """Local .env may be live; ordinary tests must never call a paid provider."""
    from backend import config

    monkeypatch.setattr(config, "MODE", "demo")


@pytest.fixture
def service(tmp_path):
    return RetailService(Store(tmp_path / "test.sqlite3"))


@pytest.fixture
def session(service):
    return service.store.create_session()


@pytest.fixture
def pending_order(service):
    with service.store.tx() as cx:
        db = service.store.dataset(cx)
        return next(o for o in db["orders"].values() if o["status"] == "pending")


def authenticate(service, sid, user_id):
    with service.store.tx() as cx:
        email = service.store.dataset(cx)["users"][user_id]["email"]
    assert service.call(sid, "find_user_id_by_email", {"email": email}) == user_id


def dataset(service, sid=None):
    with service.store.tx() as cx:
        return service.store.dataset(cx, sid)

@pytest.fixture
def multi_order_episode(service, pending_order):
    data = dataset(service)
    uid = pending_order["user_id"]
    a, b = copy.deepcopy(pending_order), copy.deepcopy(pending_order)
    a["order_id"], b["order_id"] = "#W9000001", "#W9000002"
    data["users"] = {uid: copy.deepcopy(data["users"][uid])}
    data["users"][uid]["orders"] = [a["order_id"], b["order_id"]]
    data["orders"] = {a["order_id"]: a, b["order_id"]: b}
    return service.store.create_session(user_id=uid, variant="b1", initial_db=data)
