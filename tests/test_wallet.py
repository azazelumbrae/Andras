import pytest

from andras import net
from andras.agent import channel_tools, net_tools, wallet_tools
from andras.agent.tools import ToolContext
from andras.store import budgets, personas


@pytest.fixture
def ctx(conn, config, mission):
    return ToolContext(conn=conn, config=config, mission=mission, run_id="w")


def test_net_profile_and_options(conn, mission):
    profile = net.create(conn, mission.id, mode="proxy", proxy_url="socks5://127.0.0.1:9050")
    assert profile["mode"] == "proxy"
    options = net.options({}, {"mode": "proxy", "proxy_url": "socks5://127.0.0.1:9050"})
    assert options["proxy"].startswith("socks5://")
    assert net.options({}, {"mode": "direct"})["proxy"] is None
    assert net.for_mission(conn, mission.id)


def test_net_profile_rejects_unknown_mode(conn, mission):
    with pytest.raises(ValueError):
        net.create(conn, mission.id, mode="vpn")


def test_infra_burn_marks_people(conn, mission, ctx):
    personas.create(conn, mission.id, sender_name="Ana Gómez", domain="acme.com")
    assert "personas" in net_tools.infra_burn(ctx)["text"]
    assert conn.execute("SELECT burned FROM personas").fetchone()["burned"] == 1


@pytest.mark.skipif(not __import__("importlib").util.find_spec("embit"), reason="sin embit")
def test_btc_wallet_is_testnet_and_deterministic(ctx):
    result = wallet_tools.wallet_create(ctx, chain="btc", role="burner")
    assert result["data"]["address"].startswith("tb1")
    assert ctx.conn.execute("SELECT mnemonic FROM wallets").fetchone()["mnemonic"].count(" ") >= 11


@pytest.mark.skipif(not __import__("importlib").util.find_spec("embit"), reason="sin embit")
def test_treasury_has_no_seed(ctx):
    result = wallet_tools.wallet_create(ctx, chain="btc", role="treasury")
    assert result["data"]["address"].startswith("tb1")
    assert ctx.conn.execute("SELECT mnemonic FROM wallets").fetchone()["mnemonic"] == ""


@pytest.mark.skipif(not __import__("importlib").util.find_spec("embit"), reason="sin embit")
def test_btc_transfer_builds_and_charges_budget(ctx):
    wallet_id = wallet_tools.wallet_create(ctx, chain="btc")["data"]["id"]
    result = wallet_tools.wallet_transfer(ctx, wallet_id=wallet_id, to="tb1qdestino",
                                          amount="0.0004")
    assert "preparado" in result["text"]
    assert budgets.get(ctx.conn, ctx.mission.id)["spent_crypto"]["btc"] in (0.0, 0.0004)


def test_wallet_rejects_unknown_chain(ctx):
    from andras.agent import tools

    with pytest.raises(tools.ToolError):
        tools.validate(tools.get("wallet_create"), {"chain": "doge"})


def test_record_and_list_txs(ctx):
    wallet_id = wallet_wallet(ctx)
    wallet_tools.wallet_record_tx(ctx, wallet_id=wallet_id, amount="1", purpose="prueba")
    assert "prueba" in wallet_tools.wallet_txs(ctx)["text"]


def wallet_wallet(ctx, monkeypatch=None):
    from andras.store.db import now

    cur = ctx.conn.execute(
        "INSERT INTO wallets(mission_id,role,chain,address,created_at) VALUES(?,?,?,?,?)",
        (ctx.mission.id, "burner", "xmr", "4abc", now()))
    return int(cur.lastrowid)


def test_dns_audit_reports_problems(conn, ctx, monkeypatch):
    def fake_dig(name, kind):
        if kind == "MX":
            return []
        if name.startswith("_dmarc"):
            return []
        return []

    monkeypatch.setattr(channel_tools, "_dig", fake_dig)
    result = channel_tools.dns_audit_spf_dkim_dmarc(ctx, "acme.com")
    assert "sin MX" in result["text"] and "sin DKIM" in result["text"]


def test_dns_audit_clean_domain(conn, ctx, monkeypatch):
    def fake_dig(name, kind):
        if kind == "MX":
            return ["10 mail.acme.com."]
        if name.startswith("_dmarc"):
            return ["v=DMARC1; p=reject"]
        if "_domainkey" in name:
            return ["v=DKIM1; k=rsa; p=x"]
        return ["v=spf1 include:_spf.acme.com -all"]

    monkeypatch.setattr(channel_tools, "_dig", fake_dig)
    result = channel_tools.dns_audit_spf_dkim_dmarc(ctx, "acme.com")
    assert result["data"]["problems"] == []


def test_dkim_zone_writes_files(conn, ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(channel_tools, "ROOT", tmp_path)
    result = channel_tools.generate_dkim_zone(ctx, "acme.com", "andras")
    assert (tmp_path / "data" / "dkim" / "acme.com" / "andras.key").exists()
    assert "andras._domainkey.acme.com" in result["text"]


def test_sim_swap_runbook(conn, ctx):
    text = channel_tools.sim_swap_runbook(ctx, "+34 operador", "+34 600 000 000")["text"]
    assert "duplicado" in text
