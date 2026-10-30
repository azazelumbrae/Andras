import threading
from http.client import HTTPConnection
from http.server import HTTPServer

import pytest

from andras import server
from andras.artifacts import clone


@pytest.fixture
def portal(tmp_path):
    root = tmp_path / "mirror" / "acme.test"
    root.mkdir(parents=True)
    (root / "index.html").write_text(
        "<html><head><meta http-equiv='Content-Security-Policy' content='x'></head>"
        "<body><form action='/login' method='post'>"
        "<input name='email'><input name='password' type='password'>"
        "<button>Entrar</button></form><img src='logo.png'></body></html>")
    (root / "login.html").write_text("<html>login</html>")
    (root / "logo.png").write_bytes(b"\x89PNG")
    return tmp_path / "mirror"


def test_rewrite_points_forms_to_capture(portal):
    entry = portal / "acme.test" / "index.html"
    out = clone.rewrite(entry.read_text(), original="https://acme.test/", token="TOK")
    assert "action='/TOK/__capture'" in out
    assert "name='__next' value='https://acme.test/login'" in out
    assert "Content-Security-Policy" not in out


def test_rewrite_is_idempotent(portal):
    entry = portal / "acme.test" / "index.html"
    once = clone.rewrite(entry.read_text(), original="https://acme.test/", token="TOK")
    twice = clone.rewrite(once, original="https://acme.test/", token="TOK")
    assert twice.count("__next") == 1
    assert twice.count("__capture") == 1


def test_entry_for_nested_path_and_fallback(portal):
    url = "https://acme.test/login"
    assert clone.entry_for(portal, url).name == "login.html"
    assert clone.entry_for(portal, "https://acme.test/").name == "index.html"
    assert clone.entry_for(portal, "https://acme.test/no-existe").name == "index.html"


def test_entry_without_index_raises(tmp_path):
    (tmp_path / "x").mkdir()
    with pytest.raises(clone.CloneError):
        clone.entry_for(tmp_path, "https://acme.test/")


def test_resolve_stays_inside_root(portal, tmp_path):
    entry = portal / "acme.test" / "index.html"
    assert clone.resolve(portal, entry, "") == entry
    assert clone.resolve(portal, entry, "logo.png").name == "logo.png"
    assert clone.resolve(portal, entry, "../otro/index.html") == (portal / "otro" / "index.html").resolve()
    with pytest.raises(clone.CloneError):
        clone.resolve(portal, entry, "../../../etc/passwd")


def test_pick_uses_habitual_names():
    assert clone.pick({"email": ["ana@x"], "password": ["pw"]}, "user") == "ana@x"
    assert clone.pick({"pwd": ["pw"]}, "secret") == "pw"
    assert clone.pick({"code": ["123456"]}, "otp") == "123456"
    assert clone.pick({}, "otp") == ""


def test_create_and_attach(conn, mission, monkeypatch, tmp_path):
    root = tmp_path / "clon"
    root.mkdir()
    (root / "acme.test").mkdir()
    (root / "acme.test" / "index.html").write_text("<form action='/login'></form>")
    monkeypatch.setattr(clone, "root_for", lambda m, label: root)
    monkeypatch.setattr(clone, "fetch", lambda url, dest, **kw: dest / "acme.test" / "index.html")
    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('tok','s','h','2026-01-01')")
    clone_id = clone.create(conn, mission.id, "https://acme.test/", label="demo")
    clone.attach(conn, "tok", clone_id)
    row = conn.execute("SELECT clone_id FROM campaigns WHERE id='tok'").fetchone()
    assert row["clone_id"] == clone_id
    assert "action='/tok/__capture'" in (root / "acme.test" / "index.html").read_text()


def test_attach_unknown_clone_raises(conn):
    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('tok','s','h','2026-01-01')")
    with pytest.raises(clone.CloneError):
        clone.attach(conn, "tok", "nada")


def _serve(conn, tmp_path):
    entry = tmp_path / "site" / "index.html"
    entry.parent.mkdir(parents=True)
    entry.write_text("<h1>portal</h1>")
    (entry.parent / "app.js").write_text("console.log(1)")
    conn.execute("INSERT INTO campaigns(id,scenario,recipient_hash,created_at)"
                 " VALUES('tok','s','h','2026-01-01')")
    conn.execute("INSERT INTO clones(id,mission_id,url,root,entry,created_at)"
                 " VALUES('c1','m','https://acme.test/',?,?,'2026-01-01')",
                 (str(entry.parent), str(entry)))
    conn.execute("UPDATE campaigns SET clone_id='c1' WHERE id='tok'")
    httpd = HTTPServer(("127.0.0.1", 0), server.handler_for(conn, capture=True))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_clone_is_served_under_token(conn, tmp_path):
    httpd = _serve(conn, tmp_path)
    try:
        client = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        client.request("GET", "/tok/")
        response = client.getresponse()
        assert response.status == 200
        assert b"portal" in response.read()
        client.request("GET", "/tok/app.js")
        response = client.getresponse()
        assert response.getheader("Content-Type").startswith("application/javascript")
        client.request("GET", "/tok/__otp")
        assert client.getresponse().status == 200
        client.request("GET", "/tok/no-existe")
        assert client.getresponse().status == 404
        client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_capture_stores_credentials_and_asks_otp(conn, tmp_path):
    httpd = _serve(conn, tmp_path)
    try:
        client = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        client.request("POST", "/tok/__capture", body=b"email=ana%40x&password=pw",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = client.getresponse()
        assert response.status == 303
        assert response.getheader("Location") == "/tok/__otp"
        row = conn.execute("SELECT username, secret FROM credentials").fetchone()
        assert (row["username"], row["secret"]) == ("ana@x", "pw")
        client.request("POST", "/tok/__otp", body=b"otp=123456",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert client.getresponse().status == 303
        assert conn.execute("SELECT otp FROM credentials").fetchone()["otp"] == "123456"
        events = [r["event"] for r in conn.execute("SELECT event FROM events").fetchall()]
        assert "submitted" in events and "otp" in events
        client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_capture_is_landing_for_plain_token(conn, tmp_path):
    httpd = _serve(conn, tmp_path)
    try:
        client = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        client.request("POST", "/tok", body=b"username=ana&secret=pw&action=submitted",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert client.getresponse().status == 303
        client.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
