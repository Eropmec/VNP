import pytest

from vnformat.expr import to_text
from vnformat.expr_parse import ParseError, parse

VARS = [{"id": "v_s", "name": "рассудок"}, {"id": "v_c", "name": "смелость"}, {"id": "v_f", "name": "флаг"},
        {"id": "v_n", "name": "name"}]
NAMES = {v["id"]: v["name"] for v in VARS}


@pytest.mark.parametrize("text, tree", [
    ("рассудок > 3", {"op": ">", "l": {"var": "v_s"}, "r": 3}),
    ("рассудок>3 и флаг", {"op": "and", "args": [{"op": ">", "l": {"var": "v_s"}, "r": 3}, {"var": "v_f"}]}),
    ("a", None),
    ("не флаг", {"op": "not", "arg": {"var": "v_f"}}),
    ("!флаг || смелость ≥ 1,5", {"op": "or", "args": [{"op": "not", "arg": {"var": "v_f"}},
                                                      {"op": ">=", "l": {"var": "v_c"}, "r": 1.5}]}),
    ("visited(n_cellar)", {"op": "call", "fn": "visited", "args": ["n_cellar"]}),
    ("name = «Анна»", {"op": "==", "l": {"var": "v_n"}, "r": "Анна"}),
    ("смелость - -2", {"op": "-", "l": {"var": "v_c"}, "r": -2}),
    ("да", True),
    ("Рассудок ∧ ¬флаг", {"op": "and", "args": [{"var": "v_s"}, {"op": "not", "arg": {"var": "v_f"}}]}),
])
def test_parse(text, tree):
    if tree is None:
        with pytest.raises(ParseError):
            parse(text, VARS)
    else:
        assert parse(text, VARS) == tree


def test_flattens_and_but_keeps_parentheses():
    assert parse("флаг и флаг и флаг", VARS) == {"op": "and", "args": [{"var": "v_f"}] * 3}
    e = parse("(флаг и флаг) и флаг", VARS)
    assert e == {"op": "and", "args": [{"op": "and", "args": [{"var": "v_f"}] * 2}, {"var": "v_f"}]}


@pytest.mark.parametrize("tree", [
    {"op": "and", "args": [{"op": ">", "l": {"var": "v_s"}, "r": 3},
                           {"op": "or", "args": [{"var": "v_f"}, {"op": ">=", "l": {"var": "v_c"}, "r": 5}]}]},
    {"op": "not", "arg": {"op": "or", "args": [{"var": "v_f"}, {"op": "==", "l": {"var": "v_c"}, "r": 0}]}},
    {"op": "-", "l": 10, "r": {"op": "-", "l": 3, "r": 2}},
    {"op": "*", "l": {"op": "+", "l": 1, "r": 2}, "r": 3},
    {"op": "!=", "l": {"var": "v_n"}, "r": "Анна"},
    {"op": "call", "fn": "max", "args": [{"var": "v_s"}, {"op": "call", "fn": "visited", "args": ["n_x"]}]},
    {"op": "==", "l": {"var": "v_f"}, "r": False},
])
def test_round_trip_with_to_text(tree):
    assert parse(to_text(tree, NAMES), VARS) == tree


@pytest.mark.parametrize("text, msg", [
    ("рассудок >", "оборвалась"), ("(рассудок > 3", "скобки"), ("рассудок 3", "не хватает оператора"),
    ("нечто > 1", "нет переменной «нечто»"), ("1 < рассудок < 5", "цепочка"), ("магия(1)", "неизвестная функция"),
    ("рассудок @ 1", "непонятный символ"), ("", "пустая"),
])
def test_errors_are_human(text, msg):
    with pytest.raises(ParseError) as e:
        parse(text, VARS)
    assert msg in str(e.value)
