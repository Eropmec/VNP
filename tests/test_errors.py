"""Каждая типичная ошибка автора ловится и описывается понятно."""
import pytest

from conftest import codes

G, INTRO, CELLAR, HALL = "story/graph.json", "story/scenes/sc_intro.json", "story/scenes/sc_cellar.json", "story/scenes/sc_hall.json"


def only(issues, code):
    found = [i for i in issues if i.code == code]
    assert found, f"нет {code} среди:\n" + "\n".join(map(str, issues))
    return found


def test_edge_from_missing_port(demo):
    demo.edit(G, lambda g: demo.edge(g, "e_intro_down")["from"].update(port="p_dwn"))
    issues = demo.issues()
    msg = only(issues, "edge.port_unknown")[0].message
    assert "нет выхода p_dwn" in msg and "p_down" in msg and "p_leave" in msg
    assert "выход p_down никуда не ведёт" in only(issues, "port.dangling")[0].message


def test_scene_exit_without_edge(demo):
    demo.edit(G, lambda g: g["edges"].remove(demo.edge(g, "e_hall_next")))
    d = only(demo.issues(), "port.dangling")[0]
    assert d.severity == "error" and "n_hall" in d.where and "next" in d.message


def test_two_edges_from_one_port(demo):
    demo.edit(G, lambda g: g["edges"].append({"id": "e_dup", "from": {"node": "n_intro", "port": "p_down"}, "to": "n_hall"}))
    assert "уже ведёт по ребру e_intro_down" in only(demo.issues(), "edge.port_taken")[0].message


def test_edges_from_chapter_and_ending_are_rejected(demo):
    def f(g):
        g["edges"].append({"id": "e_bad1", "from": {"node": "n_ch1", "port": "next"}, "to": "n_hall"})
        g["edges"].append({"id": "e_bad2", "from": {"node": "n_end_saved", "port": "next"}, "to": "n_hall"})
    demo.edit(G, f)
    assert {"edge.from_chapter", "edge.from_ending"} <= codes(demo.issues())


def test_unknown_variable_in_condition(demo):
    demo.edit(INTRO, lambda s: demo.cmd(s, "c_choice")["options"][0]["condition"]["l"].update(var="v_sanityy"))
    i = only(demo.issues(), "var.unknown")[0]
    assert i.path == "commands[6].options[0].condition.l" and "o_down" in i.where


def test_comparing_bool_with_number(demo):
    demo.edit(INTRO, lambda s: demo.cmd(s, "c_choice")["options"][0]["condition"]["l"].update(var="v_saw_shadow"))
    assert "нельзя сравнить логическое и целое" in only(demo.issues(), "expr.type")[0].message


def test_condition_must_be_yes_no(demo):
    demo.edit(G, lambda g: demo.node(g, "n_fate")["cases"][0].update(condition={"var": "v_sanity"}))
    assert "должно давать да/нет" in only(demo.issues(), "expr.not_bool")[0].message


def test_effect_type_errors(demo):
    def f(s):
        demo.cmd(s, "c_fear")["effects"] = [
            {"op": "add", "var": "v_saw_shadow", "value": 1},
            {"op": "set", "var": "v_sanity", "value": "много"},
            {"op": "add", "var": "v_sanity", "value": 0.5},
            {"op": "toggle", "var": "v_courage"},
        ]
    demo.edit(CELLAR, f)
    assert len(only(demo.issues(), "effect.type")) == 4


def test_unknown_emotion_and_character(demo):
    def f(s):
        demo.cmd(s, "c_show")["expr"] = "happy"
        demo.cmd(s, "c_s1")["char"] = "ch_boris"
    demo.edit(INTRO, f)
    issues = demo.issues()
    assert "нет эмоции «happy»; есть: neutral, sad, scared" in only(issues, "char.expr_unknown")[0].message
    assert only(issues, "char.unknown")


def test_asset_wrong_kind_and_missing_file(demo):
    demo.edit(INTRO, lambda s: demo.cmd(s, "c_bg").update(asset="a_mus_ambient"))
    (demo.root / "assets/bg/cellar.png").unlink()
    issues = demo.issues()
    assert "звук, а здесь нужно изображение" in only(issues, "asset.kind")[0].message
    assert only(issues, "asset.file_missing")


def test_missing_translation_is_error_only_for_default_language(demo):
    for lang in ("ru", "en"):
        p = demo.root / f"locale/{lang}.csv"
        lines = p.read_text(encoding="utf-8").splitlines()
        drop = "str_hall_2" if lang == "en" else "str_hall_1"
        p.write_text("\n".join(l for l in lines if not l.startswith(drop + ",")) + "\n", encoding="utf-8")
    missing = only(demo.issues(), "locale.key_missing")
    sev = {("ru" if "языке ru" in i.message else "en"): i.severity for i in missing}
    assert sev == {"ru": "error", "en": "info"}


def test_schema_errors_are_specific_and_russian(demo):
    def f(s):
        del demo.cmd(s, "c_s1")["text"]
        demo.cmd(s, "c_n1")["cmd"] = "narate"
        demo.cmd(s, "c_bg")["transition"]["type"] = "spin"
    demo.edit(INTRO, f)
    issues = demo.issues()
    msgs = [i.message for i in issues if i.code == "schema"]
    assert "не хватает обязательного поля «text»" in msgs
    assert any("spin" in m and "fade" in m for m in msgs)
    assert "неизвестная команда 'narate'" in only(issues, "command.type")[0].message
    assert not any("oneOf" in m or "is not valid under" in m for m in msgs)


def test_unreachable_node_and_dead_loop(demo):
    def f(g):
        g["nodes"].append({"id": "n_orphan", "type": "ending", "name": "Сирота", "parent": "n_ch1",
                           "ending": {"title": "str_end_alone", "kind": "secret"}})
        demo.edge(g, "e_hall_next")["to"] = "n_hall"          # холл зациклен сам на себя
    demo.edit(G, f)
    issues = demo.issues()
    assert any(i.code == "node.unreachable" and "n_orphan" in i.where for i in issues)
    assert any(i.code == "node.no_ending" and "n_hall" in i.where for i in issues)


def test_removing_choice_creates_next_exit(demo):
    demo.edit(CELLAR, lambda s: s["commands"].remove(demo.cmd(s, "c_choice")))
    issues = demo.issues()
    assert any(i.code == "port.dangling" and "n_cellar" in i.where and "next" in i.message for i in issues)
    assert len(only(issues, "edge.port_unknown")) == 2


def test_if_with_choice_in_both_branches_does_not_fall_through(demo):
    def f(s):
        opt = {"id": "o_x", "text": "str_cellar_opt_stay", "port": "p_x"}
        s["commands"].append({"id": "c_if2", "cmd": "if", "condition": True,
                              "then": [{"id": "c_j1", "cmd": "jump", "port": "p_x"}],
                              "else": [{"id": "c_ch2", "cmd": "choice", "options": [opt]}]})
    demo.edit(HALL, f)
    demo.edit(G, lambda g: g["edges"].__setitem__(
        slice(None), [e for e in g["edges"] if e["id"] != "e_hall_next"] +
        [{"id": "e_hall_x", "from": {"node": "n_hall", "port": "p_x"}, "to": "n_fate"}]))
    assert demo.issues() == []


def test_project_level_errors(demo):
    demo.edit("project.json", lambda p: p.update(start="n_nowhere", default_language="de"))
    assert {"project.start_unknown", "project.default_language"} <= codes(demo.issues(), "error")


def test_broken_json_is_reported_with_line(demo):
    p = demo.root / HALL
    p.write_text(p.read_text(encoding="utf-8").replace('"cmd": "bg",', '"cmd": "bg"'), encoding="utf-8")
    i = only(demo.issues(), "file.read")[0]
    assert i.file == HALL and "строке" in i.message


def test_chapter_entry_must_be_inside(demo):
    demo.edit(G, lambda g: demo.node(g, "n_intro").pop("parent"))
    assert only(demo.issues(), "chapter.entry_outside")


def test_scene_file_name_must_match_id(demo):
    (demo.root / HALL).rename(demo.root / "story/scenes/hall.json")
    assert only(demo.issues(), "scene.filename")


def test_visited_checks_node_id(demo):
    demo.edit(G, lambda g: demo.node(g, "n_fate")["cases"][0].update(
        condition={"op": "call", "fn": "visited", "args": ["n_celar"]}))
    assert "узел n_celar не существует" in only(demo.issues(), "node.unknown")[0].message


def test_load_project_refuses_broken_project(demo):
    from vnformat import ProjectLoadError, load_project
    demo.edit(G, lambda g: g["edges"].pop())
    with pytest.raises(ProjectLoadError):
        load_project(demo.root)
