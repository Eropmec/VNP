"""Новый проект из шаблона: минимальная игра, которая сразу проходит проверку и запускается."""
from __future__ import annotations

import re
from pathlib import Path

from . import io
from .project import (
    ASSETS_FILE, CHARACTERS_DIR, GRAPH_FILE, LAYOUT_FILE, LOCALE_DIR, PROJECT_FILE, SCENES_DIR, VARIABLES_FILE,
)


def slug(title: str) -> str:
    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                   "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
    s = "".join(tr.get(ch, ch) for ch in title.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s if s and s[0].isalpha() else f"game-{s}" if s else "game"


def create_project(root: str | Path, title: str, language: str = "ru") -> Path:
    root = Path(root)
    if (root / PROJECT_FILE).exists():
        raise FileExistsError(f"в {root} уже есть проект")
    root.mkdir(parents=True, exist_ok=True)
    io.write_json(root / PROJECT_FILE, {
        "format_version": 1, "id": slug(title), "title": title, "version": "0.1.0", "start": "n_ch1",
        "languages": [language], "default_language": language,
        "resolution": {"width": 1280, "height": 720}, "platforms": ["windows", "android"], "modules": [],
    })
    io.write_json(root / GRAPH_FILE, {
        "nodes": [
            {"id": "n_ch1", "type": "chapter", "name": "Глава 1", "importance": "key", "entry": "n_start"},
            {"id": "n_start", "type": "scene", "name": "Начало", "parent": "n_ch1", "scene": "sc_start"},
            {"id": "n_end", "type": "ending", "name": "Конец", "parent": "n_ch1", "importance": "key",
             "ending": {"title": "str_end", "kind": "neutral"}},
        ],
        "edges": [{"id": "e_start_next", "from": {"node": "n_start", "port": "next"}, "to": "n_end"}],
    })
    io.write_json(root / LAYOUT_FILE, {"positions": {"n_ch1": {"x": 0, "y": 0}, "n_start": {"x": 0, "y": 0},
                                                     "n_end": {"x": 0, "y": 200}}, "collapsed": []})
    io.write_json(root / SCENES_DIR / "sc_start.json", {
        "id": "sc_start", "commands": [{"id": "c_n1", "cmd": "narrate", "text": "str_start_1"}]})
    io.write_json(root / VARIABLES_FILE, {"variables": []})
    io.write_json(root / ASSETS_FILE, {"assets": []})
    (root / CHARACTERS_DIR).mkdir(parents=True, exist_ok=True)
    for sub in ("bg", "sprites", "audio"):
        (root / "assets" / sub).mkdir(parents=True, exist_ok=True)
    io.write_locale(root / LOCALE_DIR / f"{language}.csv",
                    {"str_start_1": "Здесь начинается история.", "str_end": "Конец"})
    return root
