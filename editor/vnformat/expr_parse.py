"""Разбор текстовой формулы в дерево выражения — обратное к expr.to_text().

    рассудок > 3 и (есть_лампа или Внимательность ≥ 5)
    not visited(n_cellar) && смелость >= 1

Понимает: и/или/не, and/or/not, ∧/∨/¬, &&/||/!; сравнения = == ≠ != < <= ≤ > >= ≥;
арифметику + - * × / ÷ mod; скобки; числа; да/нет/true/false; пусто/null; строки «…» или "…";
имена переменных (как в db/variables.json → name); вызовы функций: visited(n_xxx), max(a, b).
Ошибки — по-русски, с позицией в строке.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class ParseError(ValueError):
    def __init__(self, message: str, pos: int):
        super().__init__(message)
        self.message, self.pos = message, pos

    def __str__(self):
        return f"{self.message} (позиция {self.pos + 1})"


@dataclass
class Tok:
    kind: str      # num str name op lp rp comma end
    value: Any
    pos: int


_WORD_OPS = {"и": "and", "and": "and", "или": "or", "or": "or", "не": "not", "not": "not", "mod": "mod"}
_LITERALS = {"да": True, "true": True, "нет": False, "false": False, "пусто": None, "null": None}
_SYM_OPS = [("&&", "and"), ("||", "or"), ("==", "=="), ("!=", "!="), ("<=", "<="), (">=", ">="),
            ("∧", "and"), ("∨", "or"), ("¬", "not"), ("!", "not"), ("≠", "!="), ("≤", "<="), ("≥", ">="),
            ("=", "=="), ("<", "<"), (">", ">"), ("+", "+"), ("-", "-"), ("−", "-"), ("*", "*"), ("×", "*"),
            ("/", "/"), ("÷", "/"), ("%", "mod")]
_NAME = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def tokenize(text: str) -> list[Tok]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "«\"":
            close = "»" if ch == "«" else '"'
            j = text.find(close, i + 1)
            if j < 0:
                raise ParseError("строка не закрыта кавычкой", i)
            out.append(Tok("str", text[i + 1:j], i))
            i = j + 1
            continue
        m = _NUM.match(text, i)
        if m:
            s = m.group().replace(",", ".")
            out.append(Tok("num", float(s) if "." in s else int(s), i))
            i = m.end()
            continue
        m = _NAME.match(text, i)
        if m:
            word = m.group()
            low = word.lower()
            if low in _WORD_OPS:
                out.append(Tok("op", _WORD_OPS[low], i))
            elif low in _LITERALS:
                out.append(Tok("lit", _LITERALS[low], i))
            else:
                out.append(Tok("name", word, i))
            i = m.end()
            continue
        if ch == "(":
            out.append(Tok("lp", ch, i))
            i += 1
            continue
        if ch == ")":
            out.append(Tok("rp", ch, i))
            i += 1
            continue
        if ch == ",":
            out.append(Tok("comma", ch, i))
            i += 1
            continue
        for sym, op in _SYM_OPS:
            if text.startswith(sym, i):
                out.append(Tok("op", op, i))
                i += len(sym)
                break
        else:
            raise ParseError(f"непонятный символ «{ch}»", i)
    out.append(Tok("end", None, len(text)))
    return out


_BINARY = {"or": 1, "and": 2, "==": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
           "+": 5, "-": 5, "*": 6, "/": 6, "mod": 6}
_NOT_PREC = 3


class _Parser:
    def __init__(self, text: str, var_ids: dict[str, str], functions: set[str] | None):
        self.toks = tokenize(text)
        self.i = 0
        self.var_ids = var_ids        # имя или ID → ID переменной
        self.functions = functions

    def peek(self) -> Tok:
        return self.toks[self.i]

    def take(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self) -> Any:
        if self.peek().kind == "end":
            raise ParseError("формула пустая", 0)
        e = self.expr(0)
        t = self.peek()
        if t.kind != "end":
            raise ParseError(f"лишнее «{self._show(t)}» — не хватает оператора (и, или, >, = …)?", t.pos)
        return e

    def _show(self, t: Tok) -> str:
        return {"lp": "(", "rp": ")", "comma": ","}.get(t.kind, str(t.value))

    def expr(self, min_prec: int) -> Any:
        left = self.unary()
        while True:
            t = self.peek()
            if t.kind != "op" or t.value not in _BINARY or _BINARY[t.value] < min_prec or t.value == "not":
                return left
            op = t.value
            prec = _BINARY[op]
            self.take()
            if op in ("and", "or"):
                right = self.expr(prec + 1)
                args = left["args"] if isinstance(left, dict) and left.get("op") == op and not left.get("_paren") else [left]
                left = {"op": op, "args": args + [right]}
            elif prec == 4:
                right = self.expr(prec + 1)
                if self.peek().kind == "op" and _BINARY.get(self.peek().value) == 4:
                    raise ParseError("цепочка сравнений вида 1 < x < 5 не поддерживается — раздели через «и»",
                                     self.peek().pos)
                left = {"op": op, "l": left, "r": right}
            else:
                right = self.expr(prec + 1)
                left = {"op": op, "l": left, "r": right}

    def unary(self) -> Any:
        t = self.peek()
        if t.kind == "op" and t.value == "not":
            self.take()
            return {"op": "not", "arg": self.expr(_NOT_PREC + 1)}
        if t.kind == "op" and t.value == "-":
            self.take()
            nxt = self.peek()
            if nxt.kind == "num":
                self.take()
                return -nxt.value
            return {"op": "-", "l": 0, "r": self.expr(6)}
        return self.atom()

    def atom(self) -> Any:
        t = self.take()
        if t.kind == "num" or t.kind == "str" or t.kind == "lit":
            return t.value
        if t.kind == "lp":
            e = self.expr(0)
            close = self.take()
            if close.kind != "rp":
                raise ParseError("не хватает закрывающей скобки «)»", close.pos)
            if isinstance(e, dict) and e.get("op") in ("and", "or"):
                e = dict(e, _paren=True)
            return e
        if t.kind == "name":
            if self.peek().kind == "lp":
                return self.call(t)
            if t.value.startswith("n_"):
                return t.value                         # ID узла — для visited(n_x) без кавычек
            vid = self.var_ids.get(t.value) or self.var_ids.get(t.value.lower())
            if vid is None:
                raise ParseError(f"нет переменной «{t.value}»", t.pos)
            return {"var": vid}
        if t.kind == "end":
            raise ParseError("формула оборвалась — чего-то не хватает в конце", t.pos)
        raise ParseError(f"неожиданное «{self._show(t)}»", t.pos)

    def call(self, name: Tok) -> Any:
        if self.functions is not None and name.value not in self.functions:
            raise ParseError(f"неизвестная функция {name.value}()", name.pos)
        self.take()  # (
        args = []
        if self.peek().kind != "rp":
            while True:
                args.append(self.expr(0))
                if self.peek().kind == "comma":
                    self.take()
                    continue
                break
        close = self.take()
        if close.kind != "rp":
            raise ParseError("не хватает «)» после аргументов функции", close.pos)
        return {"op": "call", "fn": name.value, "args": args}


def _strip(e: Any) -> Any:
    if isinstance(e, dict):
        return {k: _strip(v) for k, v in e.items() if k != "_paren"}
    if isinstance(e, list):
        return [_strip(v) for v in e]
    return e


def parse(text: str, variables: list[dict] | dict[str, str], functions: set[str] | None = None) -> Any:
    """text → дерево выражения. variables — список переменных проекта (или готовый словарь имя → ID)."""
    if isinstance(variables, dict):
        names = dict(variables)
    else:
        names = {}
        for v in variables:
            names[v["name"]] = v["id"]
            names[v["name"].lower()] = v["id"]
            names[v["id"]] = v["id"]
    if functions is None:
        from .expr import CORE_FUNCTIONS
        functions = set(CORE_FUNCTIONS)
    return _strip(_Parser(text, names, functions).parse())
