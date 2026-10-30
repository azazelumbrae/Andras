import asyncio

import pytest

from andras import preflight
from andras.agent import clarify as clarify_mod
from andras.agent.loop import LoopResult
from andras.tui import app as tui_app

pytest.importorskip("textual")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    config = {"database": str(tmp_path / "tui.sqlite3")}
    monkeypatch.setattr(tui_app, "load_config", lambda: config)
    monkeypatch.setattr(preflight, "run", lambda config=None: [
        preflight.Check("config", preflight.OK, "ok"),
        preflight.Check("modelos", preflight.OK, "ollama:test"),
    ])
    monkeypatch.setattr(preflight, "probe_models", lambda config: [
        {"provider": "ollama", "model": "test", "local": True, "ok": True, "detail": ""}])
    monkeypatch.setattr(tui_app.clarify_mod, "generate",
                        lambda config, mission, answers=None: clarify_mod.FALLBACK[:4])
    monkeypatch.setattr(tui_app.runner, "seed", lambda *a, **k: {})
    monkeypatch.setattr(tui_app.runner, "recon",
                        lambda ctx, policy, answers=None: LoopResult("done"))
    return config


def test_wizard_reaches_summary(wired):
    async def flow():
        app = tui_app.AndrasApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.__class__.__name__ == "PreflightScreen"
            app.screen.query_one("#next").press()
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ModelPickerScreen"
            app.screen.query_one("ListView").index = 0
            await pilot.pause()
            app.screen.on_list_view_selected(
                type("E", (), {"list_view": app.screen.query_one("ListView"),
                               "item": None})())
            await pilot.pause()
            assert app.screen.__class__.__name__ == "CampaignScreen"
            app.screen.query_one("ListView").index = 0
            await pilot.pause()
            app.screen.on_list_view_selected(
                type("E", (), {"list_view": app.screen.query_one("ListView"),
                               "item": type("I", (), {"id": "new"})()})())
            await pilot.pause()
            assert app.screen.__class__.__name__ == "NameScreen"
            app.screen.query_one("Input").value = "Campaña de prueba"
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ObjectiveScreen"
            app.screen.query_one("#target_name").value = "Ana Pérez"
            app.screen.query_one("#target_company").value = "Acme"
            app.screen.query_one("#goal").text = "que abra el enlace de la landing"
            app.screen._commit()
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ClarifyScreen"
            for _ in range(4):
                app.screen._answer("sí")
                await pilot.pause()
            for _ in range(20):
                await pilot.pause()
                if app.screen.__class__.__name__ == "ReviewScreen":
                    break
            assert app.screen.__class__.__name__ == "ReviewScreen"
            assert app.state.intent["plan_id"]
            assert app.state.mission_id
            await pilot.press("ctrl+q")

    asyncio.run(flow())


def test_blocked_preflight_does_not_advance(monkeypatch, tmp_path):
    monkeypatch.setattr(tui_app, "load_config", lambda: {"database": str(tmp_path / "x.sqlite3")})
    monkeypatch.setattr(preflight, "run", lambda config=None: [
        preflight.Check("modelos", preflight.FAIL, "nada", "arregla")])
    monkeypatch.setattr(preflight, "probe_models", lambda config: [])

    async def flow():
        app = tui_app.AndrasApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "PreflightScreen"

    asyncio.run(flow())
