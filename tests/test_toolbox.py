import pytest

from andras import toolbox
from andras.agent import toolbox_tools
from andras.agent.tools import ToolContext


@pytest.fixture
def ctx(conn, config, mission):
    return ToolContext(conn=conn, config=config, mission=mission, run_id="tb")


def test_catalog_complete_and_unique():
    keys = [tool.key for tool in toolbox.TOOLS]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 24
    for tool in toolbox.TOOLS:
        assert tool.category in toolbox.CATEGORIES
        assert tool.install and tool.use and tool.fit


def test_known_tools_present():
    for key in ("set", "httrack", "mitmproxy", "urlcrazy", "responder", "beef"):
        assert toolbox.get(key)


def test_unknown_tool_raises():
    with pytest.raises(toolbox.ToolboxError):
        toolbox.get("nmap-que-no-existe")


def test_filter_by_category():
    assert all(t.category == "proxy" for t in toolbox.all_tools("proxy"))
    with pytest.raises(toolbox.ToolboxError):
        toolbox.all_tools("cocina")


def test_installed_uses_which(monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: "/usr/bin/" + name)
    assert toolbox.installed(toolbox.get("set"))
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: None)
    assert not toolbox.installed(toolbox.get("set"))


def test_atk6_family_detected(monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which",
                        lambda name: "/usr/bin/" + name if name == "atk6-fake_router6" else None)
    assert toolbox.installed(toolbox.get("thc-ipv6"))


def test_blocker_explains_limits():
    assert "Linux" in toolbox.blocker(toolbox.get("wifi-honey"))
    assert "red" in toolbox.blocker(toolbox.get("responder"))
    assert toolbox.blocker(toolbox.get("httrack")) == ""


def test_card_and_table(monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: None)
    card = toolbox.card(toolbox.get("set"))
    assert "no instalada" in card and "Encaje" in card
    assert "set" in toolbox.table()


def test_snapshot_records_on_mission(ctx, monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: None)
    result = toolbox_tools.toolbox_snapshot(ctx)
    assert result["data"]["ready"] == []
    notes = ctx.conn.execute("SELECT notes FROM missions WHERE id=?",
                             (ctx.mission.id,)).fetchone()["notes"]
    assert "arsenal" in notes


def test_show_reports_state(ctx, monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: "/usr/bin/" + name)
    result = toolbox_tools.toolbox_show(ctx, "httrack")
    assert result["data"]["installed"] is True


def test_show_unknown(ctx):
    from andras.agent import tools

    with pytest.raises(tools.ToolError):
        toolbox_tools.toolbox_show(ctx, "nada")


def test_missing_lists_install_commands(ctx, monkeypatch):
    monkeypatch.setattr(toolbox.shutil, "which", lambda name: None)
    result = toolbox_tools.toolbox_install_hint(ctx, "clonado")
    assert "brew install httrack" in result["text"]
