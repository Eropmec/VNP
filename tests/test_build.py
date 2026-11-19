"""Сборка игры. Помощники проверяются всегда; настоящая сборка — если задан VN_GODOT
и шаблоны экспорта Godot для Linux/Windows уже скачаны (окно сборки скачивает их само)."""
import os
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import builder as B  # noqa: E402

GODOT = os.environ.get("VN_GODOT")
HOST = "windows" if sys.platform == "win32" else "linux"


def test_versions_and_names():
    assert B.template_version("4.7.2.stable.official.ed1daf0bf") == "4.7.2.stable"
    assert B.release_tag("4.7.2.stable.official") == ("4.7.2-stable", "godotengine/godot")
    assert B.release_tag("4.8.beta2.official") == ("4.8-beta2", "godotengine/godot-builds")
    assert B.templates_url("4.7.2.stable").endswith("4.7.2-stable/Godot_v4.7.2-stable_export_templates.tpz")
    assert B._version_code("1.2.3") == 10203 and B._version_code("0.1.0") == 100
    assert B._package("old_house") == "org.vnconstructor.oldhouse"
    assert B._package("42") == "org.vnconstructor.g42"


def test_stage_packs_game_and_rewrites_project(demo, tmp_path):
    p = demo.load("project.json")
    p["title"] = "Мой «дом»"
    p["version"] = "2.3.4"
    p["resolution"] = {"width": 1920, "height": 1080}
    demo.save("project.json", p)
    st = tmp_path / "stage"
    B.stage(demo.root, st, lambda _m: None)
    cfg = (st / "project.godot").read_text(encoding="utf-8")
    assert 'config/name="Мой «дом»"' in cfg and 'config/version="2.3.4"' in cfg
    assert "viewport_width=1920" in cfg and "viewport_height=1080" in cfg
    assert (st / "game" / "project.json").is_file()
    assert list((st / "game" / "locale").glob("*.json")) and not list((st / "game" / "locale").glob("*.csv"))
    assert not (st / "tests").exists()
    presets = (st / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'name="Windows Desktop"' in presets and 'name="Linux"' in presets and 'name="Android"' in presets
    assert "version/code=20304" in presets


def test_build_refuses_project_with_errors(demo, tmp_path):
    demo.edit("story/graph.json", lambda g: g["edges"].append({"id": "e_bad", "from": "n_intro", "to": "n_nope"}))
    with pytest.raises(B.BuildError, match="ошибки"):
        B.build(demo.root, HOST, tmp_path / "out", GODOT or "godot", False, lambda _m: None)


def test_android_paths_saved_to_godot_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    sdk, jdk = tmp_path / "sdk", tmp_path / "jdk"
    (sdk / "build-tools").mkdir(parents=True)
    jdk.mkdir()
    B.save_android_paths("4.7.2.stable", str(sdk), str(jdk))
    B.save_android_paths("4.7.2.stable", str(sdk), str(jdk))  # второй раз — замена, а не дубль
    text = B._settings_file("4.7.2.stable").read_text(encoding="utf-8")
    assert text.count("android_sdk_path") == 1
    a = B.android_setup("4.7.2.stable")
    assert a.problems == [] and a.sdk == sdk.as_posix()


@pytest.mark.skipif(not GODOT, reason="не задан VN_GODOT")
def test_real_build_runs(demo, tmp_path):
    ver = B.godot_version(GODOT)
    if B.missing_templates(ver, HOST):
        pytest.skip("нет шаблонов экспорта — их скачивает окно сборки")
    out = B.build(demo.root, HOST, tmp_path / "out", GODOT, True, print)
    assert out.is_file() and out.stat().st_size > 10_000_000
    if HOST == "linux":
        r = subprocess.run([str(out), "--headless", "--", "--start=n_intro", "--autopilot=n,n,n,n,n,n,0,p:pos,q"],
                           capture_output=True, text=True, timeout=120)
        assert "n_cellar" in r.stdout, r.stdout[-2000:]


def test_dialog_builds(qapp, demo, tmp_path):
    from app.build_dialog import BuildDialog
    from app.document import ProjectDocument
    doc = ProjectDocument()
    doc.load(demo.root)
    dlg = BuildDialog(None, doc, GODOT or "/nonexistent/godot", doc.save)
    if not GODOT:
        assert not dlg.build_btn.isEnabled()      # без Godot собрать нельзя, но окно открывается
        return
    for b in dlg.targets.buttons():
        b.setChecked(b.property("key") == HOST)
    assert dlg.out.text().endswith(HOST)
    if B.missing_templates(dlg.version, HOST):
        pytest.skip("нет шаблонов экспорта")
    dlg.out.setText(str(tmp_path / "out"))
    dlg.start()
    dlg.worker.wait(600_000)
    qapp.processEvents()
    assert dlg.result_path and "Игра собрана" in dlg.log.toPlainText()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
