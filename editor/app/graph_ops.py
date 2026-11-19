"""Операции над сюжетным графом. Каждая — одна отменяемая правка документа."""
from __future__ import annotations

from .document import ProjectDocument

NODE_TITLES = {"scene": "Сцена", "branch": "Ветвление", "ending": "Концовка", "chapter": "Глава"}


def _new_scene(doc: ProjectDocument, text: str) -> tuple[str, dict, str]:
    sid = doc.new_id("sc")
    key = doc.new_id("str")
    return sid, {"id": sid, "commands": [{"id": "c_" + sid[3:], "cmd": "narrate", "text": key}]}, key


def add_node(doc: ProjectDocument, kind: str, parent: str | None, x: float, y: float) -> str:
    """Создаёт узел. Сцена получает свой файл с одной репликой рассказчика; глава — первую сцену внутри."""
    nid = doc.new_id("n")
    node: dict = {"id": nid, "type": kind, "name": NODE_TITLES[kind]}
    if parent:
        node["parent"] = parent
    changes: dict = {}
    lang = ("locale", doc.language)
    texts: dict[str, str] = {}
    positions = {nid: {"x": x, "y": y}}
    extra_nodes: list[dict] = []

    if kind == "scene":
        sid, scene, key = _new_scene(doc, "")
        node["scene"] = sid
        changes[("scene", sid)] = lambda _none, s=scene: s
        texts[key] = "Новая сцена."
    elif kind == "branch":
        node["cases"] = [{"port": "p_yes", "label": "условие", "condition": True}]
    elif kind == "ending":
        key = doc.new_id("str")
        node["ending"] = {"title": key, "kind": "neutral"}
        node["importance"] = "key"
        texts[key] = "Концовка"
    elif kind == "chapter":
        inner = doc.new_id("n")
        sid, scene, key = _new_scene(doc, "")
        node["entry"] = inner
        node["importance"] = "key"
        extra_nodes.append({"id": inner, "type": "scene", "name": "Начало главы", "parent": nid, "scene": sid})
        changes[("scene", sid)] = lambda _none, s=scene: s
        texts[key] = "Новая глава начинается."
        positions[inner] = {"x": 0, "y": 0}

    def g(graph):
        graph["nodes"].append(node)
        graph["nodes"].extend(extra_nodes)

    def lay(layout):
        layout.setdefault("positions", {}).update(positions)

    changes["graph"] = g
    changes["layout"] = lay
    if texts:
        changes[lang] = lambda loc: {**(loc or {}), **texts}
    doc.edit(f"Создать: {NODE_TITLES[kind].lower()}", changes)
    return nid


def connect(doc: ProjectDocument, src: str, port: str, dst: str) -> None:
    """Ребро из выхода src.port в dst. Если выход уже куда-то вёл — ребро перенаправляется.
    Порт вида «узел|порт» — выход узла внутри главы, показанный на самой главе."""
    if "|" in port:
        src, port = port.split("|", 1)
    def g(graph):
        for e in graph["edges"]:
            if e["from"]["node"] == src and e["from"]["port"] == port:
                e["to"] = dst
                return
        graph["edges"].append({"id": doc.new_id("e"), "from": {"node": src, "port": port}, "to": dst})
    doc.edit("Соединить узлы", {"graph": g})


def disconnect(doc: ProjectDocument, edge_ids: set[str]) -> None:
    doc.edit("Удалить связь", {"graph": lambda g: g.update(edges=[e for e in g["edges"] if e.get("id") not in edge_ids])})


def delete_nodes(doc: ProjectDocument, ids: set[str]) -> None:
    """Удаляет узлы (главы — со всем содержимым), их рёбра, позиции и файлы сцен, которые больше никому не нужны."""
    nodes = doc.nodes()
    doomed = set(ids)
    grew = True
    while grew:
        children = {n["id"] for n in nodes if n.get("parent") in doomed} - doomed
        doomed |= children
        grew = bool(children)
    start = (doc.get("project") or {}).get("start")
    if start in doomed:
        doomed.discard(start)          # стартовый узел не удаляем — игре нужно с чего-то начинаться
    if not doomed:
        return
    used_scenes = {n["scene"] for n in nodes if n.get("type") == "scene" and n["id"] not in doomed}
    gone_scenes = {n["scene"] for n in nodes if n.get("type") == "scene" and n["id"] in doomed} - used_scenes

    def g(graph):
        graph["nodes"] = [n for n in graph["nodes"] if n.get("id") not in doomed]
        graph["edges"] = [e for e in graph["edges"]
                          if e["from"]["node"] not in doomed and e["to"] not in doomed]

    def lay(layout):
        for nid in doomed:
            layout.get("positions", {}).pop(nid, None)
        layout["collapsed"] = [c for c in layout.get("collapsed", []) if c not in doomed]

    changes = {"graph": g, "layout": lay}
    for sid in gone_scenes:
        changes[("scene", sid)] = None
    doc.edit("Удалить узлы" if len(doomed) > 1 else "Удалить узел", changes)


def move_nodes(doc: ProjectDocument, positions: dict[str, tuple[float, float]]) -> None:
    def lay(layout):
        for nid, (x, y) in positions.items():
            layout.setdefault("positions", {})[nid] = {"x": round(x), "y": round(y)}
    doc.edit("Переместить", {"layout": lay})


def update_node(doc: ProjectDocument, nid: str, text: str, **fields) -> None:
    """Меняет поля узла; значение None удаляет поле."""
    def g(graph):
        for n in graph["nodes"]:
            if n.get("id") == nid:
                for k, v in fields.items():
                    if v is None:
                        n.pop(k, None)
                    else:
                        n[k] = v
    doc.edit(text, {"graph": g})


def set_text(doc: ProjectDocument, key: str, value: str, text: str = "Изменить текст") -> None:
    doc.edit(text, {("locale", doc.language): lambda loc: {**(loc or {}), key: value}})


def set_chapter_entry(doc: ProjectDocument, nid: str) -> None:
    node = doc.node(nid)
    if not node or not node.get("parent"):
        return
    update_node(doc, node["parent"], "Сделать первым узлом главы", entry=nid)


def set_start(doc: ProjectDocument, nid: str) -> None:
    doc.edit("Сделать стартом игры", {"project": lambda p: p.update(start=nid)})


# ---------------------------------------------------------------- копирование

CLIP_MIME = "application/x-vn-nodes"


def copy_nodes(doc: ProjectDocument, ids: set[str]) -> dict | None:
    """Снимок узлов для буфера обмена: главы — с содержимым, сцены — с файлами и текстами,
    связи — только между копируемыми узлами."""
    nodes = {n["id"]: n for n in doc.nodes()}
    picked = {i for i in ids if i in nodes}
    grew = True
    while grew:
        children = {n for n, d in nodes.items() if d.get("parent") in picked} - picked
        picked |= children
        grew = bool(children)
    if not picked:
        return None
    scenes = {nodes[i]["scene"]: doc.scenes().get(nodes[i]["scene"]) for i in picked
              if nodes[i].get("type") == "scene" and nodes[i].get("scene") in doc.scenes()}
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
    payload_nodes = [nodes[i] for i in nodes if i in picked]
    collect(payload_nodes)
    collect(list(scenes.values()))
    return {
        "nodes": payload_nodes,
        "edges": [e for e in doc.edges() if e["from"]["node"] in picked and e["to"] in picked],
        "scenes": scenes,
        "texts": {lang: {k: v for k, v in (doc.get(("locale", lang)) or {}).items() if k in keys}
                  for lang in (doc.get("project") or {}).get("languages", [doc.language])},
        "positions": {i: list(doc.position(i) or (0, 0)) for i in picked},
    }


def paste_nodes(doc: ProjectDocument, payload: dict, container: str | None, x: float, y: float) -> list[str]:
    """Вставляет копию с новыми ID. Тексты копируются, а не делятся: правка копии не меняет оригинал."""
    nodes = payload.get("nodes", [])
    if not nodes:
        return []
    ids = {n["id"] for n in nodes}
    nmap = {old: doc.new_id("n") for old in ids}
    smap = {old: doc.new_id("sc") for old in payload.get("scenes", {})}
    taken = set()
    kmap: dict[str, str] = {}
    for strings in payload.get("texts", {}).values():
        for k in strings:
            if k not in kmap:
                while True:
                    cand = doc.new_id("str")
                    if cand not in taken:
                        taken.add(cand)
                        kmap[k] = cand
                        break

    def rekey(xv):
        if isinstance(xv, str):
            return kmap.get(xv, xv)
        if isinstance(xv, dict):
            return {k: rekey(v) for k, v in xv.items()}
        if isinstance(xv, list):
            return [rekey(v) for v in xv]
        return xv

    top_level = [n for n in nodes if n.get("parent") not in ids]
    ox = min(payload["positions"][n["id"]][0] for n in top_level)
    oy = min(payload["positions"][n["id"]][1] for n in top_level)
    new_nodes, positions = [], {}
    for n in nodes:
        m = rekey(dict(n))
        m["id"] = nmap[n["id"]]
        if n.get("parent") in ids:
            m["parent"] = nmap[n["parent"]]
        elif container:
            m["parent"] = container
        else:
            m.pop("parent", None)
        if "entry" in n:
            m["entry"] = nmap.get(n["entry"], n["entry"])
        if "scene" in n:
            m["scene"] = smap.get(n["scene"], n["scene"])
        if n in top_level:
            m["name"] = f"{n.get('name', '')} (копия)"
        new_nodes.append(m)
        px, py = payload["positions"][n["id"]]
        positions[m["id"]] = {"x": round(px - ox + x) if n in top_level else px,
                              "y": round(py - oy + y) if n in top_level else py}
    new_edges = [{"id": doc.new_id("e"), "from": {"node": nmap[e["from"]["node"]], "port": e["from"]["port"]},
                  "to": nmap[e["to"]]} for e in payload.get("edges", [])]

    def g(graph):
        graph["nodes"].extend(new_nodes)
        graph["edges"].extend(new_edges)

    changes = {"graph": g, "layout": lambda lay: lay.setdefault("positions", {}).update(positions)}
    for old, scene in payload.get("scenes", {}).items():
        new_scene = rekey(scene)
        new_scene["id"] = smap[old]
        changes[("scene", smap[old])] = lambda _none, s=new_scene: s
    for lang, strings in payload.get("texts", {}).items():
        if doc.get(("locale", lang)) is not None:
            add = {kmap[k]: v for k, v in strings.items()}
            changes[("locale", lang)] = lambda loc, a=add: {**loc, **a}
    doc.edit("Вставить узлы" if len(top_level) > 1 else "Вставить узел", changes)
    return [nmap[n["id"]] for n in top_level]
