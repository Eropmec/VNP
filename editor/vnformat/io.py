"""Чтение и запись файлов проекта: JSON и таблицы локализации."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _normalize(value: Any) -> Any:
    """JSON не различает 3 и 3.0, а pydantic превращает целые в float там, где тип number.
    Чтобы сохранение не меняло файлы ради «.0», целые float пишутся как int."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def dumps_json(data: Any) -> str:
    return json.dumps(_normalize(data), ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps_json(data), encoding="utf-8")
    tmp.replace(path)          # атомарно: файл не останется полузаписанным при сбое


class LocaleError(ValueError):
    pass


def read_locale(path: Path) -> tuple[dict[str, str], list[str]]:
    """Возвращает (строки, дубликаты ключей). Формат: CSV UTF-8, колонки id,text."""
    strings: dict[str, str] = {}
    duplicates: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None or [h.strip() for h in header[:2]] != ["id", "text"]:
            raise LocaleError("первая строка должна быть заголовком: id,text")
        for row in reader:
            if not row or not row[0].strip():
                continue
            key = row[0].strip()
            text = row[1] if len(row) > 1 else ""
            if key in strings:
                duplicates.append(key)
            strings[key] = text
    return strings, duplicates


def write_locale(path: Path, strings: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "text"])
        for key in sorted(strings):
            w.writerow([key, strings[key]])
