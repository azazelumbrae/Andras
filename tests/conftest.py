import pytest

from andras.store import db, missions


@pytest.fixture
def config(tmp_path):
    return {"database": str(tmp_path / "test.sqlite3"), "authorized_recipients": []}


@pytest.fixture
def conn(config):
    connection = db.connect(config)
    yield connection
    connection.close()


@pytest.fixture
def mission(conn):
    return missions.create(conn, target_name="Ana Pérez", goal="que abra el enlace",
                           target_role="CFO", target_company="Acme", domain="acme.com")
