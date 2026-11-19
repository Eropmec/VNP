"""Базы проекта: где что используется, импорт файлов в ассеты, персонажи, переменные."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from vnformat.template import slug

from .document import ProjectDocument

KIND_BY_EXT = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".wav": "audio", ".ogg": "audio", ".mp3": "audio",
    ".ogv": "video", ".webm": "video", ".ttf": "font", ".otf": "font",
}
FOLDER = {"bg": "bg", "sprite": "sprites", "image": "images", "audio": "audio", "video": "video", "font": "fonts"}


@dataclass
class Use:
    where: str          # человеку
    node: str | None    # узел графа, куда перейти
    scene: str | None   # сцена
    path: tuple | None  # путь команды в сцене


# ---------------------------------------------------------------- где используется

def _walk(x: Any) -> Iterator[Any]:
    yield x
    if isinstance(x, dict):
        for v in x.values():
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _mentions(x: Any, kind: str, ident: str) -> bool:
    for y in _walk(x):
        if kind == "var":
            if isinstance(y, dict) and (y.get("var") == ident):
                return True
        elif kind == "char":
            if isinstance(y, dict) and y.get("char") == ident:
                return True
        elif kind == "asset":
            if isinstance(y, dict) and ident in (y.get("asset"), y.get("voice")):
                return True
    return False


def find_uses(doc: ProjectDocument, kind: str, ident: str) -> list[Use]:
    """kind: var | char | asset."""
    from . import scene_ops as S
    out: list[Use] = []
    nodes = doc.nodes()
    scene_node = {n.get("scene"): n for n in nodes if n.get("type") == "scene"}
    for n in nodes:
        if n.get("type") == "branch" and _mentions(n.get("cases", []), kind, ident):
            out.append(Use(f"ветвление «{n.get('name')}»", n["id"], None, None))
    for sid, scene in doc.scenes().items():
        node = scene_node.get(sid)
        for path, c in S.walk(scene.get("commands", [])):
            shallow = {k: v for k, v in c.items() if k not in ("then", "else")}
            if _mentions(shallow, kind, ident):
                out.append(Use(f"сцена «{(node or {}).get('name', sid)}» → {S.KINDS.get(c.get('cmd'), c.get('cmd'))}",
                               (node or {}).get("id"), sid, path))
    if kind == "asset":
        for key, ch in doc.files.items():
            if isinstance(key, tuple) and key[0] == "character" and ident in ch.get("expressions", {}).values():
                out.append(Use(f"персонаж «{doc.text(ch.get('name')) or key[1]}» → эмоция", None, None, None))
    return out


# ---------------------------------------------------------------- ассеты

def asset_list(doc: ProjectDocument) -> list[dict]:
    return [a for a in (doc.get("assets") or {}).get("assets", []) if isinstance(a, dict) and "id" in a]


def asset_file(doc: ProjectDocument, aid: str) -> Path | None:
    a = next((a for a in asset_list(doc) if a["id"] == aid), None)
    return doc.root / "assets" / a["path"] if a and doc.root else None


def _free_name(folder: Path, name: str) -> Path:
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    stem = slug(stem).replace("-", "_") or "file"
    cand = folder / f"{stem}{suffix}"
    n = 2
    while cand.exists():
        cand = folder / f"{stem}_{n}{suffix}"
        n += 1
    return cand


def _asset_id(doc: ProjectDocument, stem: str) -> str:
    base = "a_" + (re.sub(r"[^a-z0-9_]", "_", slug(stem).replace("-", "_")).strip("_") or "file")
    taken = {a["id"] for a in asset_list(doc)}
    cand, n = base, 2
    while cand in taken:
        cand = f"{base}_{n}"
        n += 1
    return cand


def import_files(doc: ProjectDocument, files: list[str | Path], role: str | None = None) -> list[str]:
    """Копирует файлы в assets/<папка> и регистрирует их одной отменяемой правкой.
    role: bg | sprite | None (по расширению). Возвращает ID новых ассетов; неподходящие файлы пропускаются.
    Файл, уже лежащий внутри assets/, не копируется — только регистрируется."""
    if doc.root is None:
        return []
    added, ids = [], []
    known = {a["path"] for a in asset_list(doc)}
    for f in map(Path, files):
        kind = KIND_BY_EXT.get(f.suffix.lower())
        if kind is None or not f.is_file():
            continue
        assets_dir = (doc.root / "assets").resolve()
        try:
            rel = f.resolve().relative_to(assets_dir).as_posix()
        except ValueError:
            folder = assets_dir / FOLDER[role if (role and kind == "image") else kind]
            folder.mkdir(parents=True, exist_ok=True)
            target = _free_name(folder, f.name)
            shutil.copy2(f, target)
            rel = target.relative_to(assets_dir).as_posix()
        if rel in known:
            ids.append(next(a["id"] for a in asset_list(doc) if a["path"] == rel))
            continue
        aid = _asset_id(doc, Path(rel).stem)
        while aid in {a["id"] for a in added}:
            aid += "_x"
        added.append({"id": aid, "kind": kind, "path": rel})
        known.add(rel)
        ids.append(aid)
    if added:
        def reg(d):
            d = d or {"assets": []}
            d.setdefault("assets", []).extend(added)
            return d
        doc.edit(f"Добавить файлы ({len(added)})", {"assets": reg})
    return ids


def remove_assets(doc: ProjectDocument, ids: set[str]) -> None:
    """Убирает из реестра (сам файл остаётся в папке — чтобы ничего не потерять)."""
    doc.edit("Убрать ассеты", {"assets": lambda d: d.update(assets=[a for a in d["assets"] if a.get("id") not in ids])})


def placeholder_sprite(doc: ProjectDocument, name: str, color: str) -> Path:
    """Силуэт-заглушка для нового персонажа, пока художник не нарисовал спрайт."""
    folder = doc.root / "assets" / "sprites"
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_name(folder, f"{name}_neutral.png")
    img = QImage(420, 660, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(Qt.NoPen)
    p.setBrush(c.darker(130))
    body = QPainterPath()
    body.moveTo(70, 660)
    body.lineTo(110, 300)
    body.lineTo(310, 300)
    body.lineTo(350, 660)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(c)
    p.drawEllipse(QPointF(210, 175), 85, 100)
    p.setPen(QColor(255, 255, 255, 200))
    f = p.font()
    f.setPointSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 460, 420, 60), Qt.AlignCenter, "?")
    p.end()
    img.save(str(target))
    return target


# ---------------------------------------------------------------- персонажи

def characters(doc: ProjectDocument) -> dict[str, dict]:
    return {k[1]: v for k, v in doc.files.items() if isinstance(k, tuple) and k[0] == "character"}


def new_character(doc: ProjectDocument, title: str, color: str = "#8fb3ff", images: list | None = None) -> str:
    """Создаёт персонажа. Эмоции — из картинок (имя эмоции = имя файла) или силуэт-заглушка."""
    cid = "ch_" + (re.sub(r"[^a-z0-9_]", "_", slug(title).replace("-", "_")).strip("_") or "hero")
    base, n = cid, 2
    while ("character", cid) in doc.files:
        cid = f"{base}_{n}"
        n += 1
    files = list(images or []) or [placeholder_sprite(doc, cid[3:], color)]
    doc.undo.beginMacro(f"Новый персонаж {title}")          # импорт картинок + персонаж = одна отмена
    ids = import_files(doc, files, role="sprite")
    exprs: dict[str, str] = {}
    for f, aid in zip(files, ids):                 # имя эмоции — из исходного имени файла
        name = expression_name(Path(f), cid)
        base, n = name, 2
        while name in exprs:
            name = f"{base}_{n}"
            n += 1
        exprs[name] = aid
    key = doc.new_id("str")
    char = {"id": cid, "name": key, "color": color, "expressions": exprs, "default_expression": next(iter(exprs))}
    doc.edit(f"Новый персонаж {title}", {("character", cid): lambda _n: char,
                                         ("locale", doc.language): lambda loc: {**(loc or {}), key: title}})
    doc.undo.endMacro()
    return cid


def expression_name(path: Path, char_id: str = "") -> str:
    """anna_sad.png → sad; Анна-грустная.png → грустная."""
    stem = path.stem.lower()
    for prefix in (char_id[3:] + "_", char_id[3:] + "-") if char_id else ():
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    stem = re.sub(r"[^a-zа-яё0-9_]+", "_", stem).strip("_")
    parts = [p for p in stem.split("_") if p]
    name = parts[-1] if len(parts) > 1 and not parts[-1].isdigit() else stem
    if not name or not re.match(r"[a-zа-яё_]", name):
        name = "e_" + name
    return name


def delete_character(doc: ProjectDocument, cid: str) -> None:
    doc.edit("Удалить персонажа", {("character", cid): None})


# ---------------------------------------------------------------- переменные

def variables(doc: ProjectDocument) -> list[dict]:
    return [v for v in (doc.get("variables") or {}).get("variables", []) if isinstance(v, dict) and "id" in v]


def update_variable(doc: ProjectDocument, vid: str, text: str, merge: str | None = None, **fields) -> None:
    def fn(d):
        for v in d["variables"]:
            if v.get("id") == vid:
                for k, val in fields.items():
                    if val is None:
                        v.pop(k, None)
                    else:
                        v[k] = val
    doc.edit(text, {"variables": fn}, merge=merge)


def add_variable(doc: ProjectDocument) -> str:
    names = {v["name"].lower() for v in variables(doc)}
    n = 1
    while f"переменная_{n}" in names:
        n += 1
    vid = doc.new_id("v")
    var = {"id": vid, "name": f"переменная_{n}", "title": f"Переменная {n}", "type": "int", "default": 0,
           "scope": "playthrough"}

    def fn(d):
        d = d or {"variables": []}
        d.setdefault("variables", []).append(var)
        return d
    doc.edit("Новая переменная", {"variables": fn})
    return vid


def delete_variables(doc: ProjectDocument, ids: set[str]) -> None:
    doc.edit("Удалить переменные", {"variables": lambda d: d.update(
        variables=[v for v in d["variables"] if v.get("id") not in ids])})
