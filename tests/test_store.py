
from andras.models import Finding
from andras.store import db, evidence, missions


def test_migrations_are_idempotent(config):
    conn = db.connect(config)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    again = db.connect(config)
    assert again.execute("PRAGMA user_version").fetchone()[0] == version
    again.close()


def test_single_source_stays_single(conn, mission):
    aid, created = evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="dork:x", source_domain="a.com"))
    assert created
    row = conn.execute("SELECT verification FROM artifacts WHERE id=?", (aid,)).fetchone()
    assert row["verification"] == "single_source"


def test_two_domains_corroborate_and_boost(conn, mission):
    aid, _ = evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com/x", source_domain="a.com",
        confidence=40))
    evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://b.org/y", source_domain="b.org",
        confidence=40))
    row = conn.execute("SELECT verification, confidence FROM artifacts WHERE id=?", (aid,)).fetchone()
    assert row["verification"] == "corroborated"
    assert row["confidence"] > 40


def test_same_domain_twice_does_not_corroborate(conn, mission):
    aid, _ = evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com/1", source_domain="a.com"))
    evidence.add(conn, mission.id, Finding(
        kind="email", value="ana@acme.com", source="https://a.com/2", source_domain="a.com"))
    row = conn.execute("SELECT verification FROM artifacts WHERE id=?", (aid,)).fetchone()
    assert row["verification"] == "single_source"


def test_llm_sources_stay_inferred(conn, mission):
    aid, _ = evidence.add(conn, mission.id, Finding(
        kind="phone", value="+34600000000", source="llm:https://a.com", source_domain="a.com"))
    row = conn.execute("SELECT verification FROM artifacts WHERE id=?", (aid,)).fetchone()
    assert row["verification"] == "inferred"


def test_duplicate_does_not_duplicate_rows(conn, mission):
    evidence.add(conn, mission.id, Finding(kind="email", value="Ana@Acme.com", source="a"))
    evidence.add(conn, mission.id, Finding(kind="email", value="ana@acme.com ", source="b"))
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1


def test_unknown_kind_rejected(conn, mission):
    import pytest

    with pytest.raises(ValueError):
        evidence.add(conn, mission.id, Finding(kind="raro", value="x", source="a"))


def test_mission_requires_goal(conn):
    import pytest

    with pytest.raises(ValueError):
        missions.create(conn, target_name="X", goal="")


def test_mission_cascade(conn, mission):
    evidence.add(conn, mission.id, Finding(kind="email", value="a@b.co", source="a"))
    conn.execute("DELETE FROM missions WHERE id=?", (mission.id,))
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
