import pytest

from backend.retail import RetailService
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


def dataset(service):
    with service.store.tx() as cx:
        return service.store.dataset(cx)
