"""Валидатор проекта: структура по JSON Schema + смысловые проверки, сообщения по-русски.

    python -m vnformat.validate samples/demo
    python -m vnformat.validate samples/demo --json     # для редактора и CI

Уровни:
  error   — игра не соберётся или сломается во время прохождения
  warning — скорее всего ошибка автора (недостижимый узел, нет перевода)
  info    — подсказка (неиспользуемый ассет, лишняя позиция в layout)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema.exceptions import ValidationError

from . import project as P
from . import schemas
from .expr import TYPE_TITLES, TypeChecker, fits, literal_type, to_text
from .story import falls_through

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_TITLES = {"error": "ОШИБКА", "warning": "ВНИМАНИЕ", "info": "подсказка"}


@dataclass
class Issue:
    severity: str           # error | warning | info
    code: str               # стабильный код для тестов и фильтров: edge.port_unknown
    file: str               # относительный путь файла
    where: str              # человеку: «сцена sc_intro → команда c_choice»
    message: str
    path: str = ""          # машине: путь к полю, по нему редактор откроет нужное место

    def __str__(self) -> str:
        loc = f"{self.file}: {self.where}" if self.where else self.file
        return f"[{SEVERITY_TITLES[self.severity]}] {loc} — {self.message}"


# ---------------------------------------------------------------- JSON Schema → понятный текст

def _schema_message(err: ValidationError) -> str:
    v, inst = err.validator, err.instance
    if v == "required":
        missing = err.message.split("'")[1] if "'" in err.message else err.message
        return f"не хватает обязательного поля «{missing}»"
    if v == "additionalProperties":
        extra = sorted(set(inst) - set(err.schema.get("properties", {}))) if isinstance(inst, dict) else []
        return f"лишнее поле: {', '.join(f'«{e}»' for e in extra)}" if extra else "лишние поля"
    if v == "pattern":
        hint = err.schema.get("description", "")
        return f"значение {json.dumps(inst, ensure_ascii=False)} не подходит по формату" + (f" ({hint})" if hint else "") \
            + f"; шаблон {err.validator_value}"
    if v == "type":
        names = {"string": "строка", "integer": "целое число", "number": "число", "boolean": "да/нет",
                 "object": "объект", "array": "список", "null": "null"}
        want = err.validator_value if isinstance(err.validator_value, list) else [err.validator_value]
        return f"ожидается {' или '.join(names.get(w, w) for w in want)}, а получено {json.dumps(inst, ensure_ascii=False)}"
    if v == "enum":
        return f"значение {json.dumps(inst, ensure_ascii=False)} недопустимо; возможные: {', '.join(map(str, err.validator_value))}"
    if v == "const":
        return f"значение должно быть {json.dumps(err.validator_value, ensure_ascii=False)}"
    if v in ("minItems", "minProperties"):
        return f"нужно хотя бы {err.validator_value} элемент(а)"
    if v in ("minimum", "exclusiveMinimum"):
        return f"значение {inst} меньше допустимого ({err.validator_value})"
    if v in ("maximum", "exclusiveMaximum"):
        return f"значение {inst} больше допустимого ({err.validator_value})"
    if v == "minLength":
        return "значение не может быть пустым"
    if v == "uniqueItems":
        return "значения в списке повторяются"
    if v == "oneOf":
        return f"значение {json.dumps(inst, ensure_ascii=False)[:80]} не подходит ни под один допустимый вариант"
    if v == "propertyNames":
        return "недопустимое имя ключа"
    return err.message


def _fmt_path(prefix: str, parts: Iterable[Any]) -> str:
    out = prefix
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


# ---------------------------------------------------------------- проверка

class Validator:
    def __init__(self, raw: P.RawProject):
        self.raw = raw
        self.issues: list[Issue] = []
        # индексы, заполняются по ходу
        self.var_types: dict[str, str] = {}
        self.var_names: dict[str, str] = {}
        self.assets: dict[str, dict] = {}
        self.chars: dict[str, dict] = {}
        self.scenes: dict[str, tuple[str, dict]] = {}    # id → (файл, данные)
        self.nodes: dict[str, dict] = {}
        self.node_index: dict[str, int] = {}
        self.used_keys: dict[str, list[tuple[str, str, str]]] = defaultdict(list)   # ключ → [(файл, где, путь)]
        self.used_assets: set[str] = set()
        self.used_vars: set[str] = set()

    # -- утилиты
    def add(self, severity, code, file, where, message, path=""):
        self.issues.append(Issue(severity, code, file, where, message, path))

    def schema_check(self, validator, data, file, where, path_prefix="") -> bool:
        ok = True
        for err in sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path))):
            ok = False
            path = _fmt_path(path_prefix, err.path)
            field = ".".join(str(p) for p in err.path)
            w = f"{where} → {field}" if field and where else (where or field)
            self.add("error", "schema", file, w, _schema_message(err), path)
        return ok

    def key(self, k: str | None, file: str, where: str, path: str):
        if k:
            self.used_keys[k].append((file, where, path))

    def asset(self, aid: str | None, kind: str, file: str, where: str, path: str):
        if aid is None:
            return
        self.used_assets.add(aid)
        a = self.assets.get(aid)
        if a is None:
            self.add("error", "asset.unknown", file, where, f"ассет {aid} не найден в реестре", path)
        elif a["kind"] != kind:
            kinds = {"image": "изображение", "audio": "звук", "video": "видео", "font": "шрифт"}
            self.add("error", "asset.kind", file, where,
                     f"ассет {aid} — {kinds[a['kind']]}, а здесь нужно {kinds[kind]}", path)

    def typechecker(self, file: str, where: str) -> TypeChecker:
        def report(code, path, msg):
            sev = "error"
            self.add(sev, code, file, where, msg, path)
        return TypeChecker(self.var_types, set(self.nodes), report)

    def condition(self, cond: Any, file: str, where: str, path: str):
        self._collect_vars(cond)
        t = self.typechecker(file, where).infer(cond, path)
        if not fits("bool", t):
            self.add("error", "expr.not_bool", file, where,
                     f"условие «{to_text(cond, self.var_names)}» должно давать да/нет, а даёт {TYPE_TITLES.get(t, t)}", path)

    def effects(self, effects: list, file: str, where: str, path: str):
        tc = self.typechecker(file, where)
        for i, ef in enumerate(effects):
            ep = f"{path}[{i}]"
            op = ef["op"]
            if op == "call":
                for j, a in enumerate(ef.get("args", [])):
                    self._collect_vars(a)
                tc._call({"op": "call", "fn": ef["fn"], "args": ef.get("args", [])}, ep)
                continue
            vid = ef["var"]
            self.used_vars.add(vid)
            vt = self.var_types.get(vid)
            if vt is None:
                self.add("error", "var.unknown", file, where, f"переменная {vid} не существует", f"{ep}.var")
                continue
            name = self.var_names.get(vid, vid)
            if op == "toggle":
                if vt != "bool":
                    self.add("error", "effect.type", file, where, f"переключать можно только логическую переменную, а «{name}» — {TYPE_TITLES[vt]}", ep)
                continue
            self._collect_vars(ef["value"])
            valt = tc.infer(ef["value"], f"{ep}.value")
            if op == "set":
                if not fits(vt, valt):
                    self.add("error", "effect.type", file, where,
                             f"в «{name}» ({TYPE_TITLES[vt]}) записывается {TYPE_TITLES.get(valt, valt)}", ep)
            else:
                if vt not in ("int", "float"):
                    self.add("error", "effect.type", file, where, f"«{name}» — {TYPE_TITLES[vt]}, к ней нельзя прибавлять или умножать", ep)
                elif not fits("number", valt):
                    self.add("error", "effect.type", file, where, f"изменение «{name}» должно быть числом", f"{ep}.value")
                elif vt == "int" and valt == "float":
                    self.add("error", "effect.type", file, where, f"«{name}» целая, а изменение дробное", f"{ep}.value")

    def _collect_vars(self, e: Any):
        if isinstance(e, dict):
            if "var" in e:
                self.used_vars.add(e["var"])
            for v in e.values():
                if isinstance(v, (dict, list)):
                    self._collect_vars(v)
        elif isinstance(e, list):
            for v in e:
                self._collect_vars(v)

    # -- этапы
    def run(self) -> list[Issue]:
        r = self.raw
        for rel in r.missing:
            self.add("error", "file.missing", rel, "", "обязательный файл отсутствует")
        for rel, msg in r.read_errors:
            self.add("error", "file.read", rel, "", msg)

        project_ok = r.project is not None and self.schema_check(schemas.validator("project"), r.project, P.PROJECT_FILE, "")
        if r.layout is not None:
            self.schema_check(schemas.validator("layout"), r.layout, P.LAYOUT_FILE, "")
        self.check_variables()
        self.check_assets()
        self.check_characters()
        self.load_scenes()
        self.check_graph_schema()
        for sid, (file, scene) in self.scenes.items():
            self.check_scene(sid, file, scene)
        self.check_graph()
        if project_ok:
            self.check_project()
            self.check_locales()
        self.check_layout()
        self.check_unused()
        self.issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.file, i.path))
        return self.issues

    def check_variables(self):
        data, file = self.raw.variables, P.VARIABLES_FILE
        if data is None or not self.schema_check(schemas.validator("variables"), data, file, ""):
            # даже при ошибках схемы запомним корректные переменные, чтобы не сыпать «не существует»
            for v in (data or {}).get("variables", []) if isinstance(data, dict) else []:
                if isinstance(v, dict) and isinstance(v.get("id"), str) and v.get("type") in ("bool", "int", "float", "string"):
                    self.var_types[v["id"]] = v["type"]
            return
        ids, names = Counter(v["id"] for v in data["variables"]), Counter(v["name"] for v in data["variables"])
        for i, v in enumerate(data["variables"]):
            where, path = f"переменная {v['id']} «{v['name']}»", f"variables[{i}]"
            if ids[v["id"]] > 1:
                self.add("error", "var.duplicate_id", file, where, "ID переменной повторяется", path)
            if names[v["name"]] > 1:
                self.add("error", "var.duplicate_name", file, where, f"имя «{v['name']}» уже занято другой переменной", path)
            t, d = v["type"], v["default"]
            if not fits(t, literal_type(d)):
                self.add("error", "var.default_type", file, where,
                         f"тип {TYPE_TITLES[t]}, а значение по умолчанию {json.dumps(d, ensure_ascii=False)}", f"{path}.default")
            if t in ("int", "float"):
                lo, hi = v.get("min"), v.get("max")
                if lo is not None and hi is not None and lo > hi:
                    self.add("error", "var.range", file, where, f"минимум {lo} больше максимума {hi}", path)
                elif isinstance(d, (int, float)) and not isinstance(d, bool) and \
                        ((lo is not None and d < lo) or (hi is not None and d > hi)):
                    self.add("error", "var.range", file, where, f"значение по умолчанию {d} вне диапазона [{lo}; {hi}]", f"{path}.default")
            elif "min" in v or "max" in v:
                self.add("warning", "var.range", file, where, "min/max имеют смысл только для чисел", path)
            self.var_types[v["id"]] = t
            self.var_names[v["id"]] = v["name"]

    def check_assets(self):
        data, file = self.raw.assets, P.ASSETS_FILE
        if data is None or not self.schema_check(schemas.validator("assets"), data, file, ""):
            return
        seen = Counter(a["id"] for a in data["assets"])
        for i, a in enumerate(data["assets"]):
            where, path = f"ассет {a['id']}", f"assets[{i}]"
            if seen[a["id"]] > 1:
                self.add("error", "asset.duplicate_id", file, where, "ID ассета повторяется", path)
            if not (self.raw.root / P.ASSETS_DIR / a["path"]).is_file():
                self.add("error", "asset.file_missing", file, where, f"файл assets/{a['path']} не найден", f"{path}.path")
            self.assets[a["id"]] = a

    def check_characters(self):
        for file, ch in self.raw.characters.items():
            if not self.schema_check(schemas.validator("character"), ch, file, ""):
                continue
            where = f"персонаж {ch['id']}"
            if Path(file).stem != ch["id"]:
                self.add("error", "char.filename", file, where, f"имя файла должно совпадать с ID: {ch['id']}.json")
            if ch["id"] in self.chars:
                self.add("error", "char.duplicate_id", file, where, "персонаж с таким ID уже есть")
            self.chars[ch["id"]] = ch
            self.key(ch["name"], file, where, "name")
            for e, aid in ch["expressions"].items():
                self.asset(aid, "image", file, f"{where} → эмоция {e}", f"expressions.{e}")
            if ch["default_expression"] not in ch["expressions"]:
                self.add("error", "char.default_expr", file, where,
                         f"эмоции «{ch['default_expression']}» нет в списке: {', '.join(ch['expressions'])}", "default_expression")

    def load_scenes(self):
        for file, sc in self.raw.scenes.items():
            if not isinstance(sc, dict) or not isinstance(sc.get("commands"), list) or not isinstance(sc.get("id"), str):
                self.schema_check(schemas.validator("scene"), sc, file, "")
                continue
            sid = sc["id"]
            extra = set(sc) - {"id", "commands"}
            if extra:
                self.add("error", "schema", file, "", f"лишнее поле: {', '.join(sorted(extra))}")
            if not schemas.validator("scene").is_valid({"id": sid, "commands": []}):
                self.add("error", "schema", file, "", f"ID сцены {sid!r} не подходит по формату (sc_…)")
            if Path(file).stem != sid:
                self.add("error", "scene.filename", file, f"сцена {sid}", f"имя файла должно совпадать с ID: {sid}.json")
            if sid in self.scenes:
                self.add("error", "scene.duplicate_id", file, f"сцена {sid}", "сцена с таким ID уже есть")
            self.scenes[sid] = (file, sc)

    # -- граф: структура
    def check_graph_schema(self):
        g, file = self.raw.graph, P.GRAPH_FILE
        if g is None:
            return
        if not isinstance(g, dict) or not isinstance(g.get("nodes"), list) or not isinstance(g.get("edges"), list):
            self.schema_check(schemas.validator("graph"), g, file, "")
            self.raw.graph = None
            return
        extra = set(g) - {"nodes", "edges"}
        if extra:
            self.add("error", "schema", file, "", f"лишнее поле: {', '.join(sorted(extra))}")
        valid_nodes = []
        for i, n in enumerate(g["nodes"]):
            path = f"nodes[{i}]"
            t = n.get("type") if isinstance(n, dict) else None
            where = f"узел {n.get('id', '?')}" if isinstance(n, dict) else f"узел №{i + 1}"
            if t not in schemas.NODE_DEFS:
                self.add("error", "node.type", file, where,
                         f"неизвестный тип узла {t!r}; возможные: {', '.join(schemas.NODE_DEFS)}", f"{path}.type")
                continue
            if self.schema_check(schemas.def_validator("graph.schema.json", schemas.NODE_DEFS[t]), n, file, where, path):
                valid_nodes.append((i, n))
        valid_edges = []
        for i, e in enumerate(g["edges"]):
            where = f"ребро {e.get('id', '?')}" if isinstance(e, dict) else f"ребро №{i + 1}"
            if self.schema_check(schemas.def_validator("graph.schema.json", "Edge"), e, file, where, f"edges[{i}]"):
                valid_edges.append((i, e))
        self.valid_nodes, self.valid_edges = valid_nodes, valid_edges
        ids = Counter(n["id"] for _, n in valid_nodes)
        for i, n in valid_nodes:
            if ids[n["id"]] > 1 and n["id"] in self.nodes:
                self.add("error", "node.duplicate_id", file, f"узел {n['id']}", "ID узла повторяется", f"nodes[{i}]")
                continue
            self.nodes[n["id"]] = n
            self.node_index[n["id"]] = i

    # -- сцены
    def check_scene(self, sid: str, file: str, sc: dict):
        cmd_ids, opt_ids = Counter(), Counter()
        self.scene_ports: dict[str, dict[str, str]] = getattr(self, "scene_ports", {})
        ports: dict[str, str] = {}         # порт → откуда (для сообщений)

        def walk(cmds: list, base: str):
            for i, c in enumerate(cmds):
                path = f"{base}[{i}]"
                cmd = c.get("cmd") if isinstance(c, dict) else None
                where = f"сцена {sid} → команда {c.get('id', i + 1) if isinstance(c, dict) else i + 1}"
                if cmd not in schemas.COMMAND_DEFS:
                    self.add("error", "command.type", file, where,
                             f"неизвестная команда {cmd!r}; возможные: {', '.join(schemas.COMMAND_DEFS)}", f"{path}.cmd")
                    continue
                shallow = dict(c, then=[], **({"else": []} if "else" in c else {})) if cmd == "if" else c
                if not self.schema_check(schemas.def_validator("scene.schema.json", schemas.COMMAND_DEFS[cmd]),
                                         shallow, file, where, path):
                    continue
                cmd_ids[c["id"]] += 1
                self.check_command(sid, file, c, where, path, ports, opt_ids)
                if cmd == "if":
                    if isinstance(c.get("then"), list):
                        walk(c["then"], f"{path}.then")
                    if isinstance(c.get("else"), list):
                        walk(c["else"], f"{path}.else")

        walk(sc["commands"], "commands")
        for cid, n in cmd_ids.items():
            if n > 1:
                self.add("error", "command.duplicate_id", file, f"сцена {sid}", f"ID команды {cid} повторяется {n} раза")
        for oid, n in opt_ids.items():
            if n > 1:
                self.add("error", "option.duplicate_id", file, f"сцена {sid}", f"ID варианта {oid} повторяется {n} раза")
        if not sc["commands"]:
            self.add("warning", "scene.empty", file, f"сцена {sid}", "сцена пустая")
        if falls_through(sc["commands"]):
            ports.setdefault("next", "конец сцены")
        self.scene_ports[sid] = ports

    def check_command(self, sid, file, c, where, path, ports, opt_ids):
        cmd = c["cmd"]
        if cmd == "bg":
            self.asset(c["asset"], "image", file, where, f"{path}.asset")
        elif cmd in ("show", "hide", "say"):
            ch = self.chars.get(c["char"])
            if ch is None:
                self.add("error", "char.unknown", file, where, f"персонаж {c['char']} не существует", f"{path}.char")
            elif c.get("expr") is not None and c["expr"] not in ch["expressions"]:
                self.add("error", "char.expr_unknown", file, where,
                         f"у персонажа {c['char']} нет эмоции «{c['expr']}»; есть: {', '.join(ch['expressions'])}", f"{path}.expr")
            if cmd == "say":
                self.key(c["text"], file, where, f"{path}.text")
        if cmd in ("say", "narrate"):
            if cmd == "narrate":
                self.key(c["text"], file, where, f"{path}.text")
            self.asset(c.get("voice"), "audio", file, where, f"{path}.voice")
        elif cmd == "choice":
            for j, o in enumerate(c["options"]):
                op = f"{path}.options[{j}]"
                ow = f"{where} → вариант {o['id']}"
                opt_ids[o["id"]] += 1
                self.key(o["text"], file, ow, f"{op}.text")
                if "condition" in o:
                    self.condition(o["condition"], file, ow, f"{op}.condition")
                if "effects" in o:
                    self.effects(o["effects"], file, ow, f"{op}.effects")
                self._port(o["port"], file, ow, f"{op}.port", ports)
        elif cmd == "jump":
            self._port(c["port"], file, where, f"{path}.port", ports)
        elif cmd == "set":
            self.effects(c["effects"], file, where, f"{path}.effects")
        elif cmd == "if":
            self.condition(c["condition"], file, where, f"{path}.condition")
        elif cmd in ("music", "sfx"):
            self.asset(c["asset"], "audio", file, where, f"{path}.asset")

    def _port(self, port, file, where, path, ports):
        if port == "else":
            self.add("error", "port.reserved", file, where, "порт else зарезервирован для ветвлений; дайте выходу имя p_…", path)
            return
        ports.setdefault(port, where)

    # -- граф: смысл
    def check_graph(self):
        if self.raw.graph is None or not hasattr(self, "valid_nodes"):
            return
        file = P.GRAPH_FILE
        nodes = self.nodes
        scene_ports = getattr(self, "scene_ports", {})

        def nw(nid):
            n = nodes.get(nid)
            return f"узел {nid} «{n['name']}»" if n else f"узел {nid}"

        def nw_gen(nid):
            n = nodes.get(nid)
            return f"узла {nid} «{n['name']}»" if n else f"узла {nid}"

        def npath(nid):
            return f"nodes[{self.node_index.get(nid, '?')}]"

        scene_users = defaultdict(list)
        out_ports: dict[str, set[str]] = {}
        for nid, n in nodes.items():
            if "parent" in n:
                parent = nodes.get(n["parent"])
                if parent is None:
                    self.add("error", "node.parent_unknown", file, nw(nid), f"родитель {n['parent']} не существует", f"{npath(nid)}.parent")
                elif parent["type"] != "chapter":
                    self.add("error", "node.parent_type", file, nw(nid), f"родителем может быть только глава, а {n['parent']} — {parent['type']}", f"{npath(nid)}.parent")
            t = n["type"]
            if t == "chapter":
                entry = nodes.get(n["entry"])
                if entry is None:
                    self.add("error", "chapter.entry_unknown", file, nw(nid), f"первый узел {n['entry']} не существует", f"{npath(nid)}.entry")
                elif entry.get("parent") != nid:
                    self.add("error", "chapter.entry_outside", file, nw(nid), f"первый узел {n['entry']} не лежит внутри этой главы", f"{npath(nid)}.entry")
                out_ports[nid] = set()
            elif t == "scene":
                if n["scene"] not in self.scenes:
                    self.add("error", "scene.unknown", file, nw(nid), f"сцена {n['scene']} не найдена (нет файла story/scenes/{n['scene']}.json)", f"{npath(nid)}.scene")
                scene_users[n["scene"]].append(nid)
                out_ports[nid] = set(scene_ports.get(n["scene"], {}))
            elif t == "branch":
                seen = Counter(c["port"] for c in n["cases"])
                for k, c in enumerate(n["cases"]):
                    cw = f"{nw(nid)} → случай {k + 1}"
                    if c["port"] in ("else", "next"):
                        self.add("error", "port.reserved", file, cw, f"порт {c['port']} зарезервирован; дайте случаю имя p_…", f"{npath(nid)}.cases[{k}].port")
                    elif seen[c["port"]] > 1:
                        self.add("error", "branch.duplicate_port", file, cw, f"порт {c['port']} уже занят другим случаем", f"{npath(nid)}.cases[{k}].port")
                    self.condition(c["condition"], file, cw, f"{npath(nid)}.cases[{k}].condition")
                out_ports[nid] = {c["port"] for c in n["cases"]} | {"else"}
            else:
                out_ports[nid] = set()
            if "player_flowchart" in n and "title" in n["player_flowchart"]:
                self.key(n["player_flowchart"]["title"], file, nw(nid), f"{npath(nid)}.player_flowchart.title")
            if t == "ending":
                self.key(n["ending"]["title"], file, nw(nid), f"{npath(nid)}.ending.title")

        # циклы родителей
        for nid in nodes:
            seen, cur = set(), nid
            while cur in nodes and "parent" in nodes[cur]:
                if cur in seen:
                    self.add("error", "node.parent_cycle", file, nw(nid), "вложенность глав зациклена")
                    break
                seen.add(cur)
                cur = nodes[cur]["parent"]

        for sid, users in scene_users.items():
            if len(users) > 1:
                self.add("warning", "scene.shared", file, f"сцена {sid}",
                         f"одна сцена используется в нескольких узлах ({', '.join(users)}); для повторного эпизода позже будет узел «вызов»")
        for sid, (sfile, _) in self.scenes.items():
            if sid not in scene_users:
                self.add("warning", "scene.unused", sfile, f"сцена {sid}", "сцена не привязана ни к одному узлу графа")

        # рёбра
        edge_ids = Counter(e["id"] for _, e in self.valid_edges)
        taken: dict[tuple[str, str], str] = {}
        succ: dict[str, list[str]] = defaultdict(list)
        for i, e in self.valid_edges:
            ew, ep = f"ребро {e['id']}", f"edges[{i}]"
            if edge_ids[e["id"]] > 1:
                self.add("error", "edge.duplicate_id", file, ew, "ID ребра повторяется", ep)
            src, port, dst = e["from"]["node"], e["from"]["port"], e["to"]
            if src not in nodes:
                self.add("error", "node.unknown", file, ew, f"узел-источник {src} не существует", f"{ep}.from.node")
                continue
            if dst not in nodes:
                self.add("error", "node.unknown", file, ew, f"узел-цель {dst} не существует", f"{ep}.to")
                continue
            st = nodes[src]["type"]
            if st == "chapter":
                self.add("error", "edge.from_chapter", file, ew, "ребро не может выходить из главы целиком: ведите его из узла внутри главы", f"{ep}.from")
                continue
            if st == "ending":
                self.add("error", "edge.from_ending", file, ew, f"концовка {src} — конец игры, из неё нельзя выйти", f"{ep}.from")
                continue
            if port not in out_ports[src]:
                have = ", ".join(sorted(out_ports[src])) or "нет ни одного"
                self.add("error", "edge.port_unknown", file, ew, f"у {nw_gen(src)} нет выхода {port}; есть: {have}", f"{ep}.from.port")
                continue
            if (src, port) in taken:
                self.add("error", "edge.port_taken", file, ew,
                         f"выход {port} у {nw_gen(src)} уже ведёт по ребру {taken[(src, port)]}: игра не будет знать, куда идти", f"{ep}.from.port")
                continue
            taken[(src, port)] = e["id"]
            succ[src].append(dst)

        for nid, ports in out_ports.items():
            for port in sorted(ports):
                if (nid, port) not in taken:
                    hint = ""
                    if nodes[nid]["type"] == "scene":
                        origin = scene_ports.get(nodes[nid]["scene"], {}).get(port, "")
                        hint = f" (выход создаёт: {origin})" if origin else ""
                    self.add("error", "port.dangling", file, nw(nid), f"выход {port} никуда не ведёт{hint}", npath(nid))

        self.check_reachability(succ)

    def check_reachability(self, succ):
        nodes, file = self.nodes, P.GRAPH_FILE
        start = (self.raw.project or {}).get("start") if isinstance(self.raw.project, dict) else None

        def resolve(nid, depth=0):
            n = nodes.get(nid)
            if n is not None and n["type"] == "chapter" and depth < 32:
                return resolve(n["entry"], depth + 1)
            return nid

        if start not in nodes:
            return            # сообщит check_project
        reach, queue = set(), deque([resolve(start)])
        while queue:
            cur = queue.popleft()
            if cur in reach or cur not in nodes:
                continue
            reach.add(cur)
            queue.extend(resolve(d) for d in succ.get(cur, []))
        # глава достижима, если достижим её первый узел
        reach |= {nid for nid, n in nodes.items() if n["type"] == "chapter" and resolve(nid) in reach}
        for nid, n in nodes.items():
            if nid not in reach:
                self.add("warning", "node.unreachable", file, f"узел {nid} «{n['name']}»",
                         "до узла нельзя дойти от начала игры", f"nodes[{self.node_index[nid]}]")
        endings = {nid for nid, n in nodes.items() if n["type"] == "ending"}
        if not endings & reach:
            self.add("warning", "ending.none_reachable", file, "", "ни одна концовка недостижима от начала игры")
            return
        # из каких узлов можно дойти до концовки
        pred = defaultdict(set)
        for src, dsts in succ.items():
            for d in dsts:
                pred[resolve(d)].add(src)
        good, queue = set(), deque(endings)
        while queue:
            cur = queue.popleft()
            if cur in good:
                continue
            good.add(cur)
            queue.extend(pred.get(cur, ()))
        for nid in sorted(reach - good):
            if nodes[nid]["type"] != "chapter":
                self.add("warning", "node.no_ending", file, f"узел {nid} «{nodes[nid]['name']}»",
                         "из этого узла нельзя дойти ни до одной концовки (тупик или замкнутый цикл)", f"nodes[{self.node_index[nid]}]")

    def check_project(self):
        p, file = self.raw.project, P.PROJECT_FILE
        if self.raw.graph is not None and hasattr(self, "valid_nodes") and p["start"] not in self.nodes:
            self.add("error", "project.start_unknown", file, "start", f"стартовый узел {p['start']} не существует", "start")
        if p["default_language"] not in p["languages"]:
            self.add("error", "project.default_language", file, "default_language",
                     f"язык по умолчанию {p['default_language']} не входит в список языков", "default_language")
        menu = p.get("menu", {})
        if "background" in menu:
            self.asset(menu["background"], "image", file, "главное меню → фон", "menu.background")
        if "music" in menu:
            self.asset(menu["music"], "audio", file, "главное меню → музыка", "menu.music")
        for lang in p["languages"]:
            if lang not in self.raw.locales and not any(e[0] == f"{P.LOCALE_DIR}/{lang}.csv" for e in self.raw.read_errors):
                self.add("error", "locale.missing", f"{P.LOCALE_DIR}/{lang}.csv", "", f"нет таблицы строк для языка {lang}")
        for lang in self.raw.locales:
            if lang not in p["languages"]:
                self.add("warning", "locale.extra", f"{P.LOCALE_DIR}/{lang}.csv", "", f"язык {lang} не указан в project.json → languages")

    def check_locales(self):
        p = self.raw.project
        for lang, dups in self.raw.locale_duplicates.items():
            for k in sorted(set(dups)):
                self.add("error", "locale.duplicate", f"{P.LOCALE_DIR}/{lang}.csv", k, "ключ повторяется; действует последняя строка")
        for k, uses in sorted(self.used_keys.items()):
            for lang in p["languages"]:
                strings = self.raw.locales.get(lang)
                if strings is None:
                    continue
                default = lang == p["default_language"]
                if k not in strings:
                    file, where, path = uses[0]
                    more = f" (и ещё мест: {len(uses) - 1})" if len(uses) > 1 else ""
                    # основной язык — ошибка (в игре будет пусто); перевод — подсказка: пока пишется
                    # история, переводов ещё нет, и это не должно засорять список проблем
                    self.add("error" if default else "info", "locale.key_missing", file, where,
                             f"нет текста «{k}» на языке {lang}{more}" if default else
                             f"нет перевода на {lang}{more}", path)
                elif not strings[k].strip():
                    file, where, path = uses[0]           # показываем там, где текст используется
                    self.add("warning" if default else "info", "locale.empty", file, where,
                             "текст пока не написан" if default else f"пустой перевод на {lang}", path)
        for lang, strings in self.raw.locales.items():
            for k in sorted(set(strings) - set(self.used_keys)):
                self.add("info", "locale.unused", f"{P.LOCALE_DIR}/{lang}.csv", k, "строка нигде не используется")

    def check_layout(self):
        lay = self.raw.layout
        if not isinstance(lay, dict) or not isinstance(lay.get("positions"), dict) or not self.nodes:
            return
        for nid in sorted(set(lay["positions"]) - set(self.nodes)):
            self.add("info", "layout.stale", P.LAYOUT_FILE, nid, "позиция для несуществующего узла", f"positions.{nid}")
        for nid in sorted(set(self.nodes) - set(lay["positions"])):
            self.add("info", "layout.missing", P.LAYOUT_FILE, nid, "у узла нет позиции, редактор расставит его сам")
        for nid in lay.get("collapsed", []):
            if self.nodes.get(nid, {}).get("type") != "chapter":
                self.add("warning", "layout.collapsed", P.LAYOUT_FILE, nid, "свернуть можно только главу")

    def check_unused(self):
        for aid in sorted(set(self.assets) - self.used_assets):
            self.add("info", "asset.unused", P.ASSETS_FILE, f"ассет {aid}", "ассет нигде не используется")
        for vid in sorted(set(self.var_types) - self.used_vars):
            self.add("info", "var.unused", P.VARIABLES_FILE, f"переменная {vid}", "переменная нигде не используется")


# ---------------------------------------------------------------- API и CLI

def validate_raw(raw: P.RawProject) -> list[Issue]:
    return Validator(raw).run()


def missing_texts(raw: P.RawProject) -> set[str]:
    """Ключи текстов, на которые ссылается проект, но которых нет в таблице основного языка."""
    v = Validator(raw)
    v.run()
    strings = raw.locales.get((raw.project or {}).get("default_language", ""))
    return set() if strings is None else {k for k in v.used_keys if k not in strings}


def validate_project(root: str | Path) -> list[Issue]:
    return validate_raw(P.load_raw(root))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Проверка проекта визуальной новеллы")
    ap.add_argument("project", help="папка проекта (где лежит project.json)")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ap.add_argument("--min", choices=["error", "warning", "info"], default="info", help="минимальный уровень")
    args = ap.parse_args(argv)
    issues = [i for i in validate_project(args.project) if SEVERITY_ORDER[i.severity] <= SEVERITY_ORDER[args.min]]
    if args.json:
        print(json.dumps([asdict(i) for i in issues], ensure_ascii=False, indent=2))
    else:
        for i in issues:
            print(i)
        c = Counter(i.severity for i in issues)
        print(f"\nОшибок: {c['error']}, предупреждений: {c['warning']}, подсказок: {c['info']}")
    return 1 if any(i.severity == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
