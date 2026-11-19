from vnformat.expr import TypeChecker, to_text

NAMES = {"v_s": "рассудок", "v_c": "смелость", "v_f": "флаг"}
TYPES = {"v_s": "int", "v_c": "int", "v_f": "bool", "v_x": "float"}


def check(e):
    found = []
    t = TypeChecker(TYPES, {"n_a"}, lambda code, path, msg: found.append((code, path))).infer(e, "e")
    return t, found


def test_to_text_precedence_and_symbols():
    e = {"op": "and", "args": [
        {"op": ">", "l": {"var": "v_s"}, "r": 3},
        {"op": "or", "args": [{"var": "v_f"}, {"op": ">=", "l": {"var": "v_c"}, "r": 5}]}]}
    assert to_text(e, NAMES) == "рассудок > 3 и (флаг или смелость ≥ 5)"
    assert to_text({"op": "not", "arg": {"var": "v_f"}}, NAMES) == "не флаг"
    assert to_text({"op": "-", "l": 10, "r": {"op": "-", "l": 3, "r": 2}}) == "10 - (3 - 2)"
    assert to_text({"op": "call", "fn": "visited", "args": ["n_a"]}) == "visited(n_a)"
    assert to_text({"op": "==", "l": {"var": "v_f"}, "r": True}, NAMES) == "флаг = да"


def test_types():
    assert check({"op": "+", "l": {"var": "v_s"}, "r": 1}) == ("int", [])
    assert check({"op": "/", "l": {"var": "v_s"}, "r": 2})[0] == "float"
    assert check({"op": "call", "fn": "max", "args": [{"var": "v_x"}, 1]})[0] == "float"
    assert check({"op": "call", "fn": "visited", "args": ["n_a"]}) == ("bool", [])


def test_type_errors():
    assert check({"op": "and", "args": [{"var": "v_s"}, True]})[1] == [("expr.type", "e.args[0]")]
    assert check({"op": "<", "l": {"var": "v_f"}, "r": 1})[1] == [("expr.type", "e")]
    assert check({"op": "call", "fn": "rand", "args": [1]})[1] == [("func.arity", "e")]
    assert check({"op": "call", "fn": "nope", "args": []})[1] == [("func.unknown", "e")]
    assert check({"op": "call", "fn": "visited", "args": ["n_b"]})[1] == [("node.unknown", "e.args[0]")]
