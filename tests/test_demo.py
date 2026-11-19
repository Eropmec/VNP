import json

from conftest import DEMO

from vnformat import dump, io, load_project, load_raw, save_project, validate_project


def strict_equal(a, b, path="$"):
    """Сравнение JSON с учётом типов: True ≠ 1, 1 ≠ "1"."""
    assert type(a) is type(b), f"{path}: {type(a).__name__} {a!r} ≠ {type(b).__name__} {b!r}"
    if isinstance(a, dict):
        assert a.keys() == b.keys(), f"{path}: ключи {sorted(a)} ≠ {sorted(b)}"
        for k in a:
            strict_equal(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), f"{path}: длина {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            strict_equal(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} ≠ {b!r}"


def test_demo_has_no_issues_at_all():
    issues = validate_project(DEMO)
    assert issues == [], "\n".join(map(str, issues))


def test_demo_loads_into_models():
    p = load_project(DEMO)
    assert p.project.start == "n_ch1"
    assert {n.type for n in p.graph.nodes} == {"chapter", "scene", "branch", "ending"}
    assert set(p.scenes) == {"sc_intro", "sc_cellar", "sc_hall"}
    assert p.characters["ch_anna"].default_expression == "neutral"
    cellar_if = p.scenes["sc_cellar"].commands[4]
    assert cellar_if.cmd == "if" and cellar_if.else_[0].cmd == "narrate"


def test_models_round_trip_without_changes():
    raw, p = load_raw(DEMO), load_project(DEMO)
    pairs = [(raw.project, p.project), (raw.graph, p.graph), (raw.layout, p.layout),
             (raw.variables, p.variables), (raw.assets, p.assets)]
    pairs += [(d, p.scenes[d["id"]]) for d in raw.scenes.values()]
    pairs += [(d, p.characters[d["id"]]) for d in raw.characters.values()]
    for original, model in pairs:
        strict_equal(original, json.loads(io.dumps_json(dump(model))))


def test_save_is_lossless_and_idempotent(tmp_path):
    p = load_project(DEMO)
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "assets").mkdir(parents=True)
    save_project(p, a)
    save_project(load_project(a, check=False), b)
    for f in a.rglob("*"):
        if f.is_file():
            assert f.read_bytes() == (b / f.relative_to(a)).read_bytes(), f
    ra, rd = load_raw(a), load_raw(DEMO)
    strict_equal(ra.graph, rd.graph)
    strict_equal(ra.scenes, rd.scenes)
    assert ra.locales == rd.locales
