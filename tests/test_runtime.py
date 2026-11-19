"""Тесты рантайма Godot. Нужен путь к Godot в переменной окружения VN_GODOT, иначе пропускаются:

    set VN_GODOT=C:\\Godot\\Godot_v4.7.2-stable_win64_console.exe     (Windows)
    python -m pytest tests
"""
import os
import subprocess
import sys

import pytest

from conftest import DEMO, ROOT

GODOT = os.environ.get("VN_GODOT")
pytestmark = pytest.mark.skipif(not GODOT, reason="не задан VN_GODOT — путь к Godot 4.4+")


def test_runtime_core_in_godot():
    res = subprocess.run([GODOT, "--headless", "--path", str(ROOT / "runtime"), "-s", "res://tests/run_tests.gd",
                          "--", f"--project={DEMO.as_posix()}"], capture_output=True, text=True, timeout=180,
                         encoding="utf-8", errors="replace")
    assert "провалено: 0" in res.stdout, res.stdout[-3000:] + res.stderr[-2000:]
    assert res.returncode == 0


def test_editor_protocol_and_latency():
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "runtime_check.py"), "--godot", GODOT, "--headless",
                          "-n", "20"], capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    assert "ПРОЙДЕНО" in res.stdout, res.stdout + res.stderr


def _autopilot(steps: str, tmp_path) -> dict:
    """Запуск игры без окна по шагам автопилота; возвращает состояния, напечатанные шагами p:метка."""
    import json
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / ".local/share"), APPDATA=str(home))
    res = subprocess.run([GODOT, "--headless", "--path", str(ROOT / "runtime"), "--", f"--project={DEMO.as_posix()}",
                          f"--autopilot={steps},q"], capture_output=True, text=True, timeout=180, env=env,
                         encoding="utf-8", errors="replace")
    out = {}
    for line in res.stdout.splitlines():
        if line.startswith("STATE "):
            _, label, payload = line.split(" ", 2)
            out[label] = json.loads(payload)
    assert "SCRIPT ERROR" not in res.stdout + res.stderr, res.stdout[-2000:] + res.stderr[-2000:]
    return out


def test_menu_save_load_cycle(tmp_path):
    s = _autopilot("w:0.3,p:menu,b:Новая игра,n,n,n,n,n,n,save:slot_01,p:saved,0,n,p:cellar,"
                   "load:slot_01,p:loaded,esc,p:paused,b:Главное меню,p:back_in_menu,b:Продолжить,p:continued", tmp_path)
    assert s["menu"]["menu"] == "MainMenu" and s["menu"]["mode"] == "menu"
    assert s["saved"]["command"] == "c_choice"
    assert s["cellar"]["node"] == "n_cellar" and s["cellar"]["vars"]["v_sanity"] == 4
    assert s["loaded"]["node"] == "n_intro" and s["loaded"]["command"] == "c_choice"
    assert s["loaded"]["vars"] == s["saved"]["vars"], "загрузка вернула переменные на момент сохранения"
    assert s["paused"]["menu"] == "Pause"
    assert s["back_in_menu"]["menu"] == "MainMenu"
    assert s["continued"]["command"] == "c_choice", "«Продолжить» — из автосохранения при выходе в меню"


def test_ending_is_remembered_between_games(tmp_path):
    s = _autopilot("b:Новая игра,n,n,n,n,n,n,1,n,n,n,n,n,n,p:end,b:Главное меню,b:Новая игра,p:again", tmp_path)
    assert s["end"]["node"] == "n_end_whisper" and s["end"]["endings"] == ["n_end_whisper"]
    assert s["again"]["endings"] == ["n_end_whisper"] and s["again"]["node"] == "n_intro"
