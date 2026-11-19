"""Выражения: функции ядра, вывод типов и текстовая запись формулы.

Работает с выражениями как с прочитанным JSON (dict / литерал), поэтому одинаково
подходит валидатору, анализатору сюжета и будущему визуальному конструктору условий.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

NUMERIC = {"int", "float"}


@dataclass(frozen=True)
class FuncSig:
    params: tuple[str, ...]      # типы аргументов; "node" — литерал-ID узла графа
    returns: str                 # тип результата; "num" — как у числовых аргументов
    title: str


#: Функции ядра. Плагины на этапе 5 будут дополнять этот словарь по своим схемам.
CORE_FUNCTIONS: dict[str, FuncSig] = {
    "visited": FuncSig(("node",), "bool", "игрок уже проходил узел"),
    "times_visited": FuncSig(("node",), "int", "сколько раз пройден узел"),
    "rand": FuncSig(("int", "int"), "int", "случайное целое от a до b включительно"),
    "min": FuncSig(("number", "number"), "num", "меньшее из двух"),
    "max": FuncSig(("number", "number"), "num", "большее из двух"),
    "abs": FuncSig(("number",), "num", "модуль числа"),
    "clamp": FuncSig(("number", "number", "number"), "num", "ограничить значение диапазоном"),
}

TYPE_TITLES = {"bool": "логическое", "int": "целое", "float": "дробное", "string": "строка",
               "null": "пусто", "number": "число"}


def literal_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "string"


def fits(expected: str, actual: str) -> bool:
    """Можно ли значение типа actual использовать там, где ждут expected."""
    if "any" in (expected, actual):
        return True
    if expected == "number":
        return actual in NUMERIC
    if expected == "float":
        return actual in NUMERIC
    return expected == actual


class TypeChecker:
    """Выводит тип выражения и сообщает о проблемах через report(путь, сообщение).

    var_types: ID переменной → тип; node_ids: множество ID узлов (для visited()).
    """

    def __init__(self, var_types: dict[str, str], node_ids: set[str],
                 report: Callable[[str, str, str], None]):
        self.var_types = var_types
        self.node_ids = node_ids
        self.report = report      # (код, путь, сообщение)

    def infer(self, e: Any, path: str) -> str:
        if not isinstance(e, dict):
            return literal_type(e)
        if "var" in e:
            t = self.var_types.get(e["var"])
            if t is None:
                self.report("var.unknown", path, f"переменная {e['var']} не существует")
                return "any"
            return t
        op = e.get("op")
        if op in ("and", "or"):
            for i, a in enumerate(e["args"]):
                t = self.infer(a, f"{path}.args[{i}]")
                if not fits("bool", t):
                    self.report("expr.type", f"{path}.args[{i}]",
                                f"в «{'и' if op == 'and' else 'или'}» нужно условие (да/нет), а здесь {TYPE_TITLES.get(t, t)}")
            return "bool"
        if op == "not":
            t = self.infer(e["arg"], f"{path}.arg")
            if not fits("bool", t):
                self.report("expr.type", f"{path}.arg", f"«не» применяется к условию, а здесь {TYPE_TITLES.get(t, t)}")
            return "bool"
        if op in ("==", "!=", "<", "<=", ">", ">="):
            lt, rt = self.infer(e["l"], f"{path}.l"), self.infer(e["r"], f"{path}.r")
            if op in ("==", "!="):
                ok = "any" in (lt, rt) or (lt in NUMERIC and rt in NUMERIC) or lt == rt or "null" in (lt, rt)
            else:
                ok = fits("number", lt) and fits("number", rt)
            if not ok:
                self.report("expr.type", path,
                            f"нельзя сравнить {TYPE_TITLES.get(lt, lt)} и {TYPE_TITLES.get(rt, rt)} оператором {op}")
            return "bool"
        if op in ("+", "-", "*", "/", "mod"):
            lt, rt = self.infer(e["l"], f"{path}.l"), self.infer(e["r"], f"{path}.r")
            for side, t in (("l", lt), ("r", rt)):
                if not fits("number", t):
                    self.report("expr.type", f"{path}.{side}", f"арифметика работает с числами, а здесь {TYPE_TITLES.get(t, t)}")
            if "any" in (lt, rt):
                return "any"
            return "float" if op == "/" or "float" in (lt, rt) else "int"
        if op == "call":
            return self._call(e, path)
        return "any"

    def _call(self, e: dict, path: str) -> str:
        sig = CORE_FUNCTIONS.get(e["fn"])
        args = e.get("args", [])
        if sig is None:
            self.report("func.unknown", path, f"неизвестная функция {e['fn']}()")
            for i, a in enumerate(args):
                self.infer(a, f"{path}.args[{i}]")
            return "any"
        if len(args) != len(sig.params):
            self.report("func.arity", path, f"{e['fn']}() ждёт аргументов: {len(sig.params)}, передано: {len(args)}")
        num_result = "int"
        for i, (a, p) in enumerate(zip(args, sig.params)):
            ap = f"{path}.args[{i}]"
            if p == "node":
                if not isinstance(a, str):
                    self.report("func.arg", ap, f"{e['fn']}() ждёт ID узла, например \"n_intro\"")
                elif a not in self.node_ids:
                    self.report("node.unknown", ap, f"узел {a} не существует")
                continue
            t = self.infer(a, ap)
            if t == "float":
                num_result = "float"
            if not fits(p, t):
                self.report("func.arg", ap, f"{e['fn']}(): аргумент {i + 1} должен быть {TYPE_TITLES.get(p, p)}, а не {TYPE_TITLES.get(t, t)}")
        return num_result if sig.returns == "num" else sig.returns


# ---------------------------------------------------------------- текстовая запись

_PREC = {"or": 1, "and": 2, "not": 3, "==": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
         "+": 5, "-": 5, "*": 6, "/": 6, "mod": 6}
_SYM = {"and": "и", "or": "или", "==": "=", "!=": "≠", "<=": "≤", ">=": "≥", "*": "×", "/": "÷", "mod": "mod"}


def to_text(e: Any, var_names: dict[str, str] | None = None) -> str:
    """{"op":">","l":{"var":"v_sanity"},"r":3} → «рассудок > 3». Для подписей в графе и сообщений."""
    names = var_names or {}

    def lit(v):
        if isinstance(v, bool):
            return "да" if v else "нет"
        if v is None:
            return "пусто"
        if isinstance(v, str):
            return f"«{v}»"
        return str(v)

    def go(x, parent_prec=0):
        if not isinstance(x, dict):
            return lit(x)
        if "var" in x:
            return names.get(x["var"], x["var"])
        op = x["op"]
        if op == "call":
            sig = CORE_FUNCTIONS.get(x["fn"])
            kinds = sig.params if sig else ()
            args = [a if (i < len(kinds) and kinds[i] == "node" and isinstance(a, str)) else go(a)
                    for i, a in enumerate(x.get("args", []))]
            return f"{x['fn']}({', '.join(args)})"
        p = _PREC.get(op, 9)
        if op in ("and", "or"):
            s = f" {_SYM[op]} ".join(go(a, p) for a in x["args"])
        elif op == "not":
            s = f"не {go(x['arg'], p)}"
        else:
            s = f"{go(x['l'], p)} {_SYM.get(op, op)} {go(x['r'], p + 1)}"
        return f"({s})" if p < parent_prec else s

    return go(e)
