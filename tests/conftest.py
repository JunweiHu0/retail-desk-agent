import os

import pytest

# Tests exercise the offline demo model. A developer's .env may set
# AGENT_MODE=live; set this before backend.config is imported (dotenv never
# overrides an existing variable).
os.environ["AGENT_MODE"] = "demo"

from backend.retail import RetailService  # noqa: E402
from backend.store import Store


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
