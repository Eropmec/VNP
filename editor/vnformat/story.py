"""Структура сюжета: выходы узлов и сцен. Общая логика для редактора, валидатора и анализатора."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class Exit:
    port: str
    kind: str              # choice | jump | next | case | else
    text_key: str = ""     # ключ текста варианта выбора
    label: str = ""        # подпись случая ветвления
    condition: Any = None  # условие случая ветвления или варианта выбора
    origin: str = ""       # ID команды или варианта, которые создают выход


def walk_commands(cmds: list) -> Iterator[dict]:
    """Все команды сцены, включая вложенные в if, в порядке следования."""
    for c in cmds:
        if not isinstance(c, dict):
            continue
        yield c
        if c.get("cmd") == "if":
            yield from walk_commands(c.get("then", []) if isinstance(c.get("then"), list) else [])
            yield from walk_commands(c.get("else", []) if isinstance(c.get("else"), list) else [])


def falls_through(cmds: list) -> bool:
    """Может ли выполнение дойти до конца списка команд (и выйти из сцены через next)."""
    for c in cmds:
        if not isinstance(c, dict):
            continue
        if c.get("cmd") in ("choice", "jump"):
            return False
        if c.get("cmd") == "if" and "else" in c and not falls_through(c.get("then", [])) \
                and not falls_through(c.get("else", [])):
            return False
    return True


def scene_exits(scene: dict) -> list[Exit]:
    """Выходы сцены в порядке появления; один порт — один выход (первое упоминание)."""
    out: dict[str, Exit] = {}
    cmds = scene.get("commands", []) if isinstance(scene, dict) else []
    for c in walk_commands(cmds):
        if c.get("cmd") == "choice":
            for o in c.get("options", []):
                if isinstance(o, dict) and isinstance(o.get("port"), str):
                    out.setdefault(o["port"], Exit(o["port"], "choice", o.get("text", ""),
                                                   condition=o.get("condition"), origin=o.get("id", "")))
        elif c.get("cmd") == "jump" and isinstance(c.get("port"), str):
            out.setdefault(c["port"], Exit(c["port"], "jump", origin=c.get("id", "")))
    if falls_through(cmds):
        out.setdefault("next", Exit("next", "next"))
    return list(out.values())


def node_exits(node: dict, scenes: dict[str, dict]) -> list[Exit]:
    t = node.get("type")
    if t == "scene":
        return scene_exits(scenes.get(node.get("scene"), {}))
    if t == "branch":
        cases = [Exit(c["port"], "case", label=c.get("label", ""), condition=c.get("condition"))
                 for c in node.get("cases", []) if isinstance(c, dict) and "port" in c]
        return cases + [Exit("else", "else")]
    return []
