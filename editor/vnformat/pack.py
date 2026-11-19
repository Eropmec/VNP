"""Упаковка проекта в папку игры рантайма (runtime/game или сборочная копия)."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import io

PARTS = ["project.json", "story", "db", "assets"]


def pack(src: str | Path, target: str | Path) -> int:
    """Копирует проект в target; таблицы строк CSV превращает в JSON (Godot импортирует *.csv
    как свои переводы, и в сборку исходный файл не попадает). Возвращает число файлов."""
    src, target = Path(src), Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for part in PARTS:
        s = src / part
        if s.is_dir():
            shutil.copytree(s, target / part, ignore=shutil.ignore_patterns("*.import", ".*"))
        elif s.is_file():
            shutil.copy2(s, target / part)
    for csv_file in sorted((src / "locale").glob("*.csv")):
        strings, _ = io.read_locale(csv_file)
        io.write_json(target / "locale" / f"{csv_file.stem}.json", strings)
    return sum(1 for p in target.rglob("*") if p.is_file())
