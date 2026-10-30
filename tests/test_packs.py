
from andras.brain import packs


def test_packs_load_and_validate():
    items, errors = packs.load_all()
    assert items, "debe haber al menos un pack"
    assert not errors
    for pack in items:
        assert pack.turns


def test_pack_requires_fields(tmp_path):
    (tmp_path / "malo.yaml").write_text("id: x\nname: y\nchannel: email\n")
    items, errors = packs.load_all(tmp_path)
    assert not items
    assert "faltan campos" in errors[0]


def test_pack_rejects_bad_channel(tmp_path):
    (tmp_path / "c.yaml").write_text(
        "id: x\nname: y\nchannel: fax\npurpose: z\nturns:\n- {role: a, goal: b, success: c}\n")
    _, errors = packs.load_all(tmp_path)
    assert "canal inválido" in errors[0]


def test_choose_prefers_packs_without_missing_leverage():
    with_leverage = {"phone", "target_name", "target_company", "target_phone", "recovery_fact"}
    chosen = packs.choose(channel="phone", has=with_leverage, limit=1)
    assert chosen
    assert all(p.channel == "phone" for p in chosen)


def test_prompt_renders_turns():
    items, _ = packs.load_all()
    text = items[0].as_prompt()
    assert "SECUENCIA" in text and "1." in text
