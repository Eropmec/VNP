"""Документ проекта в редакторе: данные в памяти, правки с отменой, сохранение, проверка на лету.

Данные хранятся как JSON (dict/list) по «ключам файлов»:
    "project", "graph", "layout", "variables", "assets",
    ("scene", id), ("character", id), ("locale", язык)
Любая правка — снимок «до/после» затронутых файлов в QUndoStack. Это просто и надёжно:
отмена работает одинаково для графа, сцены, текста и всего, что появится дальше.
"""
from __future__ import annotations

import copy
import secrets
import shutil
import string
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from vnformat import io
from vnformat import project as P
from vnformat.story import Exit, node_exits
from vnformat.validate import Issue, validate_raw

Key = Any
SIMPLE_FILES = {
    "project": P.PROJECT_FILE, "graph": P.GRAPH_FILE, "layout": P.LAYOUT_FILE,
    "variables": P.VARIABLES_FILE, "assets": P.ASSETS_FILE,
}
_ALPHABET = string.ascii_lowercase + string.digits


class _Snapshot(QUndoCommand):
    MERGE_WINDOW = 2.0          # правки одного поля подряд в пределах 2 с — одна отмена

    def __init__(self, doc: "ProjectDocument", changes: dict[Key, tuple[Any, Any]], text: str, merge: str | None):
        super().__init__(text)
        self.doc, self.changes, self.merge, self.stamp = doc, changes, merge, time.monotonic()

    def id(self):
        return 1 if self.merge else -1

    def mergeWith(self, other):
        if not self.merge or other.merge != self.merge or other.stamp - self.stamp > self.MERGE_WINDOW:
            return False
        for key, (_b, after) in other.changes.items():
            before = self.changes[key][0] if key in self.changes else other.changes[key][0]
            self.changes[key] = (before, after)
        self.stamp = other.stamp
        return True

    def redo(self):
        for key, (_before, after) in self.changes.items():
            self.doc._put(key, after)
        self.doc._after_change(list(self.changes))

    def undo(self):
        for key, (before, _after) in self.changes.items():
            self.doc._put(key, before)
        self.doc._after_change(list(self.changes))


class ProjectDocument(QObject):
    changed = Signal(list)          # список изменившихся ключей
    reloaded = Signal()
    issues_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root: Path | None = None
        self.files: dict[Key, Any] = {}
        self.issues: list[Issue] = []
        self.undo = QUndoStack(self)
        self._touched: set[Key] = set()
        self._validate_timer = QTimer(self, singleShot=True, interval=250)
        self._validate_timer.timeout.connect(self.validate)

    # ----------------------------------------------------------- загрузка и сохранение
    def load(self, root: str | Path) -> None:
        raw = P.load_raw(root)
        self.root = Path(root).resolve()
        self.files = {}
        for key in SIMPLE_FILES:
            value = getattr(raw, key)
            if value is not None:
                self.files[key] = value
        self.files.setdefault("layout", {"positions": {}, "collapsed": []})
        for data in raw.scenes.values():
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                self.files[("scene", data["id"])] = data
        for data in raw.characters.values():
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                self.files[("character", data["id"])] = data
        for lang, strings in raw.locales.items():
            self.files[("locale", lang)] = dict(strings)
        self.undo.clear()
        self._touched.clear()
        self.load_problems = [f"{f}: {m}" for f, m in raw.read_errors] + [f"нет файла {f}" for f in raw.missing]
        self.reloaded.emit()
        self.validate()

    def path_of(self, key: Key) -> Path:
        if key in SIMPLE_FILES:
            return self.root / SIMPLE_FILES[key]
        kind, ident = key
        if kind == "scene":
            return self.root / P.SCENES_DIR / f"{ident}.json"
        if kind == "character":
            return self.root / P.CHARACTERS_DIR / f"{ident}.json"
        if kind == "locale":
            return self.root / P.LOCALE_DIR / f"{ident}.csv"
        raise KeyError(key)

    def save(self) -> list[Path]:
        written = []
        for key in sorted(self._touched, key=str):
            path = self.path_of(key)
            value = self.files.get(key)
            if value is None:
                if path.exists():
                    path.unlink()
            elif isinstance(key, tuple) and key[0] == "locale":
                io.write_locale(path, value)
            else:
                io.write_json(path, value)
            written.append(path)
        self._touched.clear()
        self.undo.setClean()
        return written

    def save_as(self, new_root: str | Path) -> None:
        """Копирует ассеты и записывает все файлы в новую папку."""
        new_root = Path(new_root).resolve()
        if self.root and (self.root / P.ASSETS_DIR).is_dir():
            shutil.copytree(self.root / P.ASSETS_DIR, new_root / P.ASSETS_DIR, dirs_exist_ok=True)
        self.root = new_root
        self._touched = set(self.files)
        self.save()

    @property
    def dirty(self) -> bool:
        return not self.undo.isClean()

    # ----------------------------------------------------------- правки
    def get(self, key: Key, default=None) -> Any:
        """Живые данные — только читать. Менять — через edit()."""
        return self.files.get(key, default)

    def edit(self, text: str, changes: dict[Key, Callable[[Any], Any] | None], merge: str | None = None) -> bool:
        """Одна отменяемая правка над несколькими файлами.

        changes: ключ → функция, меняющая копию данных на месте (или возвращающая новые данные);
        None удаляет файл; для нового файла функция получает None и возвращает данные.
        merge: одинаковый ключ у правок подряд (набор текста) склеивает их в одну отмену."""
        snap = {}
        for key, fn in changes.items():
            before = copy.deepcopy(self.files.get(key))
            if fn is None:
                after = None
            else:
                work = copy.deepcopy(before)
                result = fn(work)
                after = result if result is not None else work
            if after != before:
                snap[key] = (before, after)
        if not snap:
            return False
        self.undo.push(_Snapshot(self, snap, text, merge))
        return True

    def _put(self, key: Key, value: Any) -> None:
        if value is None:
            self.files.pop(key, None)
        else:
            self.files[key] = copy.deepcopy(value)
        self._touched.add(key)

    def _after_change(self, keys: list[Key]) -> None:
        self.changed.emit(keys)
        self._validate_timer.start()

    # ----------------------------------------------------------- проверка
    def raw(self) -> P.RawProject:
        raw = P.RawProject(root=self.root or Path("."))
        for key in SIMPLE_FILES:
            setattr(raw, key, copy.deepcopy(self.files.get(key)))
        for (kind, ident), value in ((k, v) for k, v in self.files.items() if isinstance(k, tuple)):
            if kind == "scene":
                raw.scenes[f"{P.SCENES_DIR}/{ident}.json"] = copy.deepcopy(value)
            elif kind == "character":
                raw.characters[f"{P.CHARACTERS_DIR}/{ident}.json"] = copy.deepcopy(value)
            elif kind == "locale":
                raw.locales[ident] = dict(value)
                raw.locale_duplicates[ident] = []
        return raw

    def repair_missing_texts(self) -> int:
        """Сцены, ссылающиеся на тексты, которых нет в таблице (старые версии редактора, ручная правка),
        получают пустые строки: «нет текста» → «текст пока не написан». Одна отменяемая правка."""
        if self.root is None:
            return 0
        from vnformat.validate import missing_texts
        missing = missing_texts(self.raw())
        if missing:
            self.edit("Восстановить пропавшие тексты",
                      {("locale", self.language): lambda loc: {**{k: "" for k in missing}, **(loc or {})}})
        return len(missing)

    def validate(self) -> list[Issue]:
        self.issues = validate_raw(self.raw()) if self.root else []
        self.issues_changed.emit(self.issues)
        return self.issues

    # ----------------------------------------------------------- удобный доступ
    @property
    def language(self) -> str:
        return (self.get("project") or {}).get("default_language", "ru")

    def text(self, key: str | None, lang: str | None = None) -> str:
        if not key:
            return ""
        return (self.get(("locale", lang or self.language)) or {}).get(key, "")

    def nodes(self) -> list[dict]:
        return [n for n in (self.get("graph") or {}).get("nodes", []) if isinstance(n, dict) and "id" in n]

    def node(self, nid: str) -> dict | None:
        return next((n for n in self.nodes() if n["id"] == nid), None)

    def edges(self) -> list[dict]:
        return [e for e in (self.get("graph") or {}).get("edges", []) if isinstance(e, dict) and "from" in e]

    def scenes(self) -> dict[str, dict]:
        return {k[1]: v for k, v in self.files.items() if isinstance(k, tuple) and k[0] == "scene"}

    def exits(self, node: dict) -> list[Exit]:
        return node_exits(node, self.scenes())

    def position(self, nid: str) -> tuple[float, float] | None:
        p = (self.get("layout") or {}).get("positions", {}).get(nid)
        return (p["x"], p["y"]) if p else None

    def all_ids(self) -> set[str]:
        ids = {n["id"] for n in self.nodes()} | {e.get("id") for e in self.edges()}
        ids |= {k[1] for k in self.files if isinstance(k, tuple)}
        for scene in self.scenes().values():
            for c in scene.get("commands", []):
                ids.add(c.get("id"))
        for strings in (v for k, v in self.files.items() if isinstance(k, tuple) and k[0] == "locale"):
            ids |= set(strings)
        return ids

    def new_id(self, prefix: str, hint: str = "") -> str:
        """Короткий уникальный ID: n_k3f9a. Случайный, а не счётчик — чтобы правки двух авторов не столкнулись."""
        taken = self.all_ids()
        while True:
            cand = f"{prefix}_{''.join(secrets.choice(_ALPHABET) for _ in range(5))}"
            if cand not in taken:
                return cand
