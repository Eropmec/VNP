"""Операции над содержимым сцены. Команда адресуется путём: (3,) — четвёртая команда сцены,
(3, "then", 0) — первая команда ветки «то» внутри неё, (3, "else", 1) — вторая в ветке «иначе»."""
from __future__ import annotations

import copy
from typing import Any, Callable

from vnformat.story import scene_exits

from .document import ProjectDocument

Path = tuple

KINDS = {
    "say": "Реплика", "narrate": "Рассказчик", "choice": "Выбор", "bg": "Фон", "show": "Показать",
    "hide": "Убрать", "music": "Музыка", "sfx": "Звук", "stop_audio": "Стоп звук", "wait": "Пауза",
    "jump": "Переход", "if": "Условие", "set": "Переменные",
}


# ---------------------------------------------------------------- адресация

def container_of(scene: dict, path: Path) -> tuple[list, int]:
    """Список, в котором лежит команда по пути, и её индекс в нём."""
    lst = scene["commands"]
    for k in range(0, len(path) - 1, 2):
        lst = lst[path[k]][path[k + 1]]
    return lst, path[-1]


def get(scene: dict, path: Path) -> dict | None:
    try:
        lst, i = container_of(scene, path)
        return lst[i]
    except (IndexError, KeyError, TypeError):
        return None


def walk(cmds: list, prefix: Path = ()):
    """(путь, команда) для всех команд, включая вложенные."""
    for i, c in enumerate(cmds):
        p = prefix + (i,)
        yield p, c
        if c.get("cmd") == "if":
            yield from walk(c.get("then", []), p + ("then",))
            if "else" in c:
                yield from walk(c["else"], p + ("else",))


# ---------------------------------------------------------------- правка сцены

def edit_scene(doc: ProjectDocument, sid: str, fn: Callable[[dict], Any], text: str,
               texts: dict[str, str] | None = None, merge: str | None = None) -> dict:
    """Меняет сцену одной отменяемой правкой. Рёбра графа из выходов, которых больше нет, удаляются в той же правке."""
    after = copy.deepcopy(doc.scenes()[sid])
    fn(after)
    ports_after = {e.port for e in scene_exits(after)}
    users = {n["id"] for n in doc.nodes() if n.get("type") == "scene" and n.get("scene") == sid}

    def g(graph):
        graph["edges"] = [e for e in graph["edges"]
                          if not (e["from"]["node"] in users and e["from"]["port"] not in ports_after)]

    changes: dict = {("scene", sid): lambda _s: after, "graph": g}
    if texts:
        changes[("locale", doc.language)] = lambda loc: {**(loc or {}), **texts}
    doc.edit(text, changes, merge=merge)
    return after


def set_fields(doc: ProjectDocument, sid: str, path: Path, text: str, merge: str | None = None, **fields):
    """Поля команды; None удаляет поле."""
    def fn(scene):
        c = get(scene, path)
        for k, v in fields.items():
            if v is None:
                c.pop(k, None)
            else:
                c[k] = v
    edit_scene(doc, sid, fn, text, merge=merge)


def set_text(doc: ProjectDocument, key: str, value: str):
    doc.edit("Текст", {("locale", doc.language): lambda loc: {**(loc or {}), key: value}}, merge=f"text:{key}")


# ---------------------------------------------------------------- новые команды

def _cid(doc: ProjectDocument, scene: dict) -> str:
    taken = {c.get("id") for _p, c in walk(scene.get("commands", []))}
    while True:
        cid = doc.new_id("c")
        if cid not in taken:
            return cid


def _port(doc: ProjectDocument) -> str:
    return "p_" + doc.new_id("x")[2:]


def characters(doc: ProjectDocument) -> dict[str, dict]:
    return {k[1]: v for k, v in doc.files.items() if isinstance(k, tuple) and k[0] == "character"}


def assets(doc: ProjectDocument, kind: str) -> list[dict]:
    return [a for a in (doc.get("assets") or {}).get("assets", []) if a.get("kind") == kind]


def make_command(doc: ProjectDocument, scene: dict, kind: str, near: dict | None = None) -> tuple[dict, dict[str, str]]:
    """Новая команда с разумными значениями по умолчанию и тексты, которые надо завести."""
    cid = _cid(doc, scene)
    chars = characters(doc)
    last_char = next((c.get("char") for _p, c in reversed(list(walk(scene.get("commands", []))))
                      if c.get("cmd") in ("say", "show") and c.get("char") in chars), None)
    who = (near or {}).get("char") if (near or {}).get("char") in chars else last_char or next(iter(chars), None)
    texts: dict[str, str] = {}

    def key():
        k = doc.new_id("str")
        while k in texts:
            k = doc.new_id("str")
        texts[k] = ""
        return k

    if kind == "say":
        if who is None:
            return make_command(doc, scene, "narrate")
        return {"id": cid, "cmd": "say", "char": who, "text": key()}, texts
    if kind == "narrate":
        return {"id": cid, "cmd": "narrate", "text": key()}, texts
    if kind == "choice":
        opts = []
        for n in (1, 2):
            k = key()
            texts[k] = f"Вариант {n}"
            opts.append({"id": "o_" + doc.new_id("x")[2:], "text": k, "port": _port(doc)})
        return {"id": cid, "cmd": "choice", "options": opts}, texts
    if kind == "bg":
        imgs = [a for a in assets(doc, "image") if "bg" in a.get("path", "").split("/")[0]] or assets(doc, "image")
        return {"id": cid, "cmd": "bg", "asset": imgs[0]["id"] if imgs else "a_none",
                "transition": {"type": "dissolve", "duration": 0.5}}, texts
    if kind == "show":
        if who is None:
            return {"id": cid, "cmd": "wait", "seconds": 1}, texts
        return {"id": cid, "cmd": "show", "char": who, "expr": chars[who].get("default_expression", ""),
                "at": "center", "transition": {"type": "dissolve", "duration": 0.3}}, texts
    if kind == "hide":
        if who is None:
            return {"id": cid, "cmd": "wait", "seconds": 1}, texts
        return {"id": cid, "cmd": "hide", "char": who, "transition": {"type": "dissolve", "duration": 0.3}}, texts
    if kind == "music":
        aud = assets(doc, "audio")
        return {"id": cid, "cmd": "music", "asset": aud[0]["id"] if aud else None, "fade": 1, "loop": True}, texts
    if kind == "sfx":
        aud = assets(doc, "audio")
        return {"id": cid, "cmd": "sfx", "asset": aud[0]["id"] if aud else "a_none"}, texts
    if kind == "stop_audio":
        return {"id": cid, "cmd": "stop_audio", "channel": "music", "fade": 1}, texts
    if kind == "wait":
        return {"id": cid, "cmd": "wait", "seconds": 1}, texts
    if kind == "jump":
        return {"id": cid, "cmd": "jump", "port": _port(doc)}, texts
    if kind == "set":
        vs = [v for v in (doc.get("variables") or {}).get("variables", []) if isinstance(v, dict)]
        v = vs[0] if vs else {"id": "v_none", "type": "int"}
        eff = {"op": "toggle", "var": v["id"]} if v["type"] == "bool" else \
            {"op": "add", "var": v["id"], "value": 1} if v["type"] in ("int", "float") else \
            {"op": "set", "var": v["id"], "value": ""}
        return {"id": cid, "cmd": "set", "effects": [eff]}, texts
    if kind == "if":
        return {"id": cid, "cmd": "if", "condition": True, "then": []}, texts
    raise ValueError(kind)


def insert(doc: ProjectDocument, sid: str, where: Path | None, kind: str, inside: str | None = None) -> Path:
    """Вставить новую команду после where (или в конец сцены); inside="then"/"else" — внутрь условия where."""
    scene = doc.scenes()[sid]
    near = get(scene, where) if where else None
    cmd, texts = make_command(doc, scene, kind, near)
    result: list[Path] = []

    def fn(s):
        if where is None:
            s["commands"].append(cmd)
            result.append((len(s["commands"]) - 1,))
        elif inside:
            target = get(s, where).setdefault(inside, [])
            target.append(cmd)
            result.append(where + (inside, len(target) - 1))
        else:
            lst, i = container_of(s, where)
            lst.insert(i + 1, cmd)
            result.append(where[:-1] + (i + 1,))

    edit_scene(doc, sid, fn, f"Добавить: {KINDS[kind].lower()}", texts=texts)
    return result[0]


def delete(doc: ProjectDocument, sid: str, paths: list[Path]):
    def fn(s):
        for p in sorted(paths, key=lambda p: [x if isinstance(x, int) else -1 for x in p], reverse=True):
            lst, i = container_of(s, p)
            if 0 <= i < len(lst):
                lst.pop(i)
    edit_scene(doc, sid, fn, "Удалить команды" if len(paths) > 1 else "Удалить команду")


def move(doc: ProjectDocument, sid: str, path: Path, delta: int) -> Path:
    scene = doc.scenes()[sid]
    lst, i = container_of(copy.deepcopy(scene), path)
    j = i + delta
    if not 0 <= j < len(lst):
        return path

    def fn(s):
        ls, k = container_of(s, path)
        ls[k], ls[j] = ls[j], ls[k]
    edit_scene(doc, sid, fn, "Переместить команду")
    return path[:-1] + (j,)


# ---------------------------------------------------------------- копирование строк

CLIP_MIME = "application/x-vn-commands"


def copy_commands(doc: ProjectDocument, sid: str, paths: list[Path]) -> dict:
    scene = doc.scenes()[sid]
    top = [p for p in paths if not any(p[:len(q)] == q and p != q for q in paths)]   # без вложенных дублей
    cmds = [copy.deepcopy(get(scene, p)) for p in sorted(top)]
    keys: set[str] = set()

    def collect(x):
        if isinstance(x, str) and x.startswith("str_"):
            keys.add(x)
        elif isinstance(x, dict):
            for v in x.values():
                collect(v)
        elif isinstance(x, list):
            for v in x:
                collect(v)
    collect(cmds)
    return {"commands": cmds, "texts": {k: doc.text(k) for k in keys}}


def paste_commands(doc: ProjectDocument, sid: str, where: Path | None, payload: dict) -> list[Path]:
    """Вставка с новыми ID команд, вариантов и ключей текста; выходы выбора/переходов — новые
    (иначе копия выбора вела бы туда же, куда оригинал, и это было бы незаметно)."""
    scene = doc.scenes()[sid]
    kmap = {k: doc.new_id("str") for k in payload.get("texts", {})}
    taken = {c.get("id") for _p, c in walk(scene.get("commands", []))}

    def fresh(c):
        c = copy.deepcopy(c)
        while True:
            cid = doc.new_id("c")
            if cid not in taken:
                taken.add(cid)
                c["id"] = cid
                break
        for f in ("text",):
            if f in c:
                c[f] = kmap.get(c[f], c[f])
        if c.get("cmd") == "choice":
            for o in c.get("options", []):
                o["id"] = "o_" + doc.new_id("x")[2:]
                o["text"] = kmap.get(o["text"], o["text"])
                o["port"] = _port(doc)
        if c.get("cmd") == "jump":
            c["port"] = _port(doc)
        for branch in ("then", "else"):
            if branch in c:
                c[branch] = [fresh(x) for x in c[branch]]
        return c

    new = [fresh(c) for c in payload.get("commands", [])]
    texts = {kmap[k]: v for k, v in payload.get("texts", {}).items()}
    result: list[Path] = []

    def fn(s):
        if where is None:
            lst, at = s["commands"], len(s["commands"])
            prefix: Path = ()
        else:
            lst, i = container_of(s, where)
            at, prefix = i + 1, where[:-1]
        for k, c in enumerate(new):
            lst.insert(at + k, c)
            result.append(prefix + (at + k,))

    edit_scene(doc, sid, fn, "Вставить команды", texts=texts)
    return result
