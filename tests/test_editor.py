"""Редактор без окна (Qt offscreen): документ, граф, инспектор, сохранение."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vnformat import validate_project  # noqa: E402
from vnformat.template import create_project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc(qapp, demo):
    from app.document import ProjectDocument
    d = ProjectDocument()
    d.load(demo.root)
    return d


def errors(d):
    return [i for i in d.validate() if i.severity == "error"]


def test_loads_demo_without_problems(doc):
    assert doc.validate() == []
    assert len(doc.nodes()) == 8
    assert [e.port for e in doc.exits(doc.node("n_intro"))] == ["p_down", "p_leave"]
    assert [e.port for e in doc.exits(doc.node("n_hall"))] == ["next"]
    assert [e.port for e in doc.exits(doc.node("n_fate"))] == ["p_saved", "else"]


def test_add_scene_connect_undo_redo(doc):
    from app import graph_ops
    nid = graph_ops.add_node(doc, "scene", "n_ch1", 100, 100)
    node = doc.node(nid)
    assert node["parent"] == "n_ch1" and ("scene", node["scene"]) in doc.files
    assert doc.text(doc.scenes()[node["scene"]]["commands"][0]["text"]) == "Новая сцена."
    codes = {i.code for i in doc.validate()}
    assert "port.dangling" in codes and "node.unreachable" in codes      # новая сцена ни с чем не связана
    graph_ops.connect(doc, "n_hall", "next", nid)                        # перенаправить выход холла
    graph_ops.connect(doc, nid, "next", "n_fate")
    assert errors(doc) == []
    assert doc.dirty
    for _ in range(3):
        doc.undo.undo()
    assert doc.node(nid) is None and doc.validate() == []
    doc.undo.redo()
    assert doc.node(nid) is not None


def test_delete_node_removes_edges_and_scene_file(doc):
    from app import graph_ops
    graph_ops.delete_nodes(doc, {"n_hall"})
    assert doc.node("n_hall") is None
    assert not any(e["to"] == "n_hall" or e["from"]["node"] == "n_hall" for e in doc.edges())
    assert ("scene", "sc_hall") not in doc.files
    assert any(i.code == "port.dangling" for i in doc.validate())     # выход «Уговорить уйти» повис
    doc.save()
    assert not (doc.root / "story/scenes/sc_hall.json").exists()
    doc.undo.undo()
    doc.save()
    assert (doc.root / "story/scenes/sc_hall.json").exists()
    assert validate_project(doc.root) == []


def test_deleting_chapter_keeps_start(doc):
    from app import graph_ops
    graph_ops.delete_nodes(doc, {"n_ch1"})
    assert doc.node("n_ch1") is not None, "стартовый узел не удаляется"


def test_save_round_trip_is_valid(doc):
    from app import graph_ops
    graph_ops.update_node(doc, "n_cellar", "Переименовать", name="Тёмный подвал")
    graph_ops.set_text(doc, "str_end_saved", "Вместе до утра")
    graph_ops.move_nodes(doc, {"n_cellar": (11.6, 22.2)})
    written = {p.name for p in doc.save()}
    assert written == {"graph.json", "ru.csv", "layout.json"}
    assert not doc.dirty
    assert validate_project(doc.root) == []
    from app.document import ProjectDocument
    again = ProjectDocument()
    again.load(doc.root)
    assert again.node("n_cellar")["name"] == "Тёмный подвал"
    assert again.text("str_end_saved") == "Вместе до утра"
    assert again.position("n_cellar") == (12, 22)


def test_graph_view_levels(doc):
    from app.graph_view import EdgeItem, GraphView
    v = GraphView(doc)
    v.enter(None)
    assert set(v.items) == {"n_ch1"}
    v.enter("n_ch1")
    assert len(v.items) == 7
    edges = [i for i in v.scene().items() if isinstance(i, EdgeItem)]
    assert len(edges) == 7 and not any(e.aggregated or e.dst is None for e in edges)
    assert v.items["n_intro"].is_entry
    labels = [label for _p, label in v.items["n_intro"].exits]
    assert labels == ["Спуститься в подвал", "Уговорить Анну уйти"]


def test_errors_are_shown_on_nodes(doc):
    from app import graph_ops
    from app.graph_view import GraphView
    v = GraphView(doc)
    v.enter("n_ch1")
    graph_ops.disconnect(doc, {"e_hall_next"})
    doc.validate()
    assert any(i.code == "port.dangling" for i in v.items["n_hall"].issues)
    assert v.items["n_intro"].issues == []


def test_inspector_edits_ending(doc):
    from app.inspector import Inspector
    from PySide6.QtWidgets import QComboBox
    ins = Inspector(doc)
    ins.show_node("n_end_saved")
    combo = ins.widget().findChild(QComboBox)
    combo.setCurrentIndex(combo.findData("secret"))
    assert doc.node("n_end_saved")["ending"]["kind"] == "secret"
    doc.undo.undo()
    assert doc.node("n_end_saved")["ending"]["kind"] == "good"


def test_new_project_template(qapp, tmp_path):
    root = create_project(tmp_path / "game", "Моя игра")
    assert validate_project(root) == []
    from app.document import ProjectDocument
    from app import graph_ops
    d = ProjectDocument()
    d.load(root)
    ch = graph_ops.add_node(d, "chapter", None, 0, 300)
    assert d.node(d.node(ch)["entry"])["parent"] == ch
    d.save()
    issues = validate_project(root)
    assert not [i for i in issues if i.severity == "error" and i.code != "port.dangling"], issues


def test_main_window_opens_and_saves(qapp, demo):
    from app.main_window import MainWindow
    w = MainWindow()
    assert w.open(demo.root)
    assert "Старый дом" in w.windowTitle()
    w.graph.enter("n_ch1")
    w._create_center("branch")
    assert w.windowTitle().startswith("●")
    w.save()
    assert not w.doc.dirty and not w.windowTitle().startswith("●")
    w.doc.undo.setClean()
    w.close()


# ---------------------------------------------------------------- шаг 2

def test_chapter_shows_open_exits_and_links_chapters(doc):
    from app import graph_ops
    from app.graph_view import EdgeItem, GraphView
    ch2 = graph_ops.add_node(doc, "chapter", None, 400, 0)
    inner = doc.node(ch2)["entry"]
    v = GraphView(doc)
    v.enter(None)
    ports = [p for p, _l in v.items[ch2].exits]
    assert ports == [f"{inner}|next"], "у новой главы виден открытый выход её сцены"
    assert v.items["n_ch1"].exits == [], "у первой главы все выходы ведут внутрь неё"
    graph_ops.connect(doc, ch2, f"{inner}|next", "n_ch1")         # связь глава → глава на верхнем уровне
    assert any(e["from"] == {"node": inner, "port": "next"} and e["to"] == "n_ch1" for e in doc.edges())
    v.rebuild()
    edges = [i for i in v.scene().items() if isinstance(i, EdgeItem)]
    assert len(edges) == 1 and edges[0].src is v.items[ch2] and edges[0].dst is v.items["n_ch1"]


def test_copy_paste_nodes_with_scene_and_texts(doc, qapp):
    from app import graph_ops
    payload = graph_ops.copy_nodes(doc, {"n_cellar", "n_fate"})
    assert {n["id"] for n in payload["nodes"]} == {"n_cellar", "n_fate"}
    assert [e["id"] for e in payload["edges"]] == ["e_cellar_stay"]
    new = graph_ops.paste_nodes(doc, payload, "n_ch1", 900, 0)
    assert len(new) == 2
    copies = [doc.node(n) for n in new]
    scene_copy = next(c for c in copies if c["type"] == "scene")
    assert scene_copy["scene"] != "sc_cellar" and scene_copy["name"] == "Подвал (копия)"
    key = doc.scenes()[scene_copy["scene"]]["commands"][2]["text"]
    assert key != "str_cellar_1" and doc.text(key) == doc.text("str_cellar_1")
    assert doc.text(key, "en") == doc.text("str_cellar_1", "en")
    assert any(e["from"]["node"] == scene_copy["id"] and e["to"] in new for e in doc.edges()), "внутренняя связь скопирована"
    assert not [i for i in doc.validate() if i.severity == "error" and i.code != "port.dangling"]
    doc.undo.undo()
    assert all(doc.node(n) is None for n in new) and doc.validate() == []


def test_copy_chapter_copies_contents(doc):
    from app import graph_ops
    new = graph_ops.paste_nodes(doc, graph_ops.copy_nodes(doc, {"n_ch1"}), None, 600, 0)
    ch = doc.node(new[0])
    inside = [n for n in doc.nodes() if n.get("parent") == ch["id"]]
    assert len(inside) == 7 and doc.node(ch["entry"])["parent"] == ch["id"]
    assert {i.code for i in doc.validate() if i.severity == "error"} == set()


def test_scene_ops_insert_move_delete(doc):
    from app import scene_ops as S
    p = S.insert(doc, "sc_hall", (2,), "say")
    assert p == (3,) and S.get(doc.scenes()["sc_hall"], p)["char"] == "ch_anna"
    S.set_text(doc, S.get(doc.scenes()["sc_hall"], p)["text"], "Я тебя найду.")
    p = S.move(doc, "sc_hall", p, -1)
    assert p == (2,) and doc.text(S.get(doc.scenes()["sc_hall"], p)["text"]) == "Я тебя найду."
    inner = S.insert(doc, "sc_cellar", (4,), "narrate", inside="else")
    assert inner == (4, "else", 1)
    S.delete(doc, "sc_cellar", [inner])
    assert len(doc.scenes()["sc_cellar"]["commands"][4]["else"]) == 1
    assert [i for i in doc.validate() if i.severity == "error"] == []


def test_removing_choice_option_removes_its_edge(doc):
    from app import scene_ops as S
    S.edit_scene(doc, "sc_intro", lambda s: s["commands"][6]["options"].pop(1), "Удалить вариант")
    assert not any(e["id"] == "e_intro_leave" for e in doc.edges())
    assert [i.code for i in doc.validate() if i.severity == "error"] == []
    doc.undo.undo()
    assert any(e["id"] == "e_intro_leave" for e in doc.edges())


def test_typing_merges_into_one_undo(doc):
    from app import scene_ops as S
    before = doc.text("str_hall_1")
    for ch in " Обещаю.":
        S.set_text(doc, "str_hall_1", doc.text("str_hall_1") + ch)
    assert doc.undo.count() == 1
    doc.undo.undo()
    assert doc.text("str_hall_1") == before


def test_paste_commands_gets_new_ids_and_ports(doc):
    from app import scene_ops as S
    payload = S.copy_commands(doc, "sc_intro", [(6,), (5,)])
    new = S.paste_commands(doc, "sc_intro", (6,), payload)
    cmds = doc.scenes()["sc_intro"]["commands"]
    assert [cmds[p[0]]["cmd"] for p in new] == ["say", "choice"]
    pasted = cmds[new[1][0]]
    assert {o["port"] for o in pasted["options"]}.isdisjoint({"p_down", "p_leave"})
    assert doc.text(pasted["options"][0]["text"]) == "Спуститься в подвал"
    assert len({c["id"] for c in cmds}) == len(cmds)


def test_scene_editor_tab(qapp, demo):
    from PySide6.QtWidgets import QPlainTextEdit
    from app.main_window import MainWindow
    w = MainWindow()
    w.open(demo.root)
    w._activated("n_hall")
    ed = w.scene_tabs["sc_hall"]
    assert w.tabs.currentWidget() is ed and ed.tree.topLevelItemCount() == 6
    ed.select((2,))
    ed.add_like_current()
    assert ed.path == (3,) and w.doc.scenes()["sc_hall"]["commands"][3]["cmd"] == "say"
    box = ed.form_area.widget().findChild(QPlainTextEdit)
    box.insertPlainText("Новая реплика")
    assert w.doc.text(w.doc.scenes()["sc_hall"]["commands"][3]["text"]) == "Новая реплика"
    from app import graph_ops
    graph_ops.delete_nodes(w.doc, {"n_hall"})
    assert "sc_hall" not in w.scene_tabs, "вкладка удалённой сцены закрывается"
    w.doc.undo.setClean()
    w.close()


def test_opening_scene_does_not_move_game_but_play_here_does(qapp, demo):
    from app.main_window import MainWindow
    w = MainWindow()
    w.open(demo.root)
    previews, plays = [], []
    w._preview = lambda n, c: previews.append((n, c))
    w.playtest.run = lambda *a, **k: None          # не запускать настоящий Godot
    w._activated("n_cellar")
    ed = w.scene_tabs["sc_cellar"]
    ed.preview.connect(lambda n, c: previews.append((n, c)))
    ed.play_here.connect(lambda n, c: plays.append((n, c)))
    ed.sync.setChecked(True)
    w._activated("n_cellar")                       # повторное открытие тоже не трогает игру
    assert previews == []
    ed.select((6,))
    ed.play_from_here()
    assert plays == [("n_cellar", "c_s1")]
    ed.sync.setChecked(False)
    w.doc.undo.setClean()
    w.close()


def test_windows_menu_restores_panels(qapp, demo):
    from app.main_window import MainWindow
    w = MainWindow()
    w.show()
    for d in w.docks:
        d.close()
    assert not any(d.isVisible() for d in w.docks)
    w.default_layout()
    assert all(d.isVisible() for d in w.docks)
    w.close()


def test_project_settings_dialog(qapp, demo):
    from app.document import ProjectDocument
    from app.project_settings import ProjectSettingsDialog
    d = ProjectDocument()
    d.load(demo.root)
    dlg = ProjectSettingsDialog(d)
    dlg.title.setText("Старый дом")
    dlg.bg.setCurrentIndex(dlg.bg.findData("a_bg_cellar"))
    dlg.music.setCurrentIndex(dlg.music.findData("a_mus_ambient"))
    dlg._ok()
    p = d.get("project")
    assert p["title"] == "Старый дом" and p["menu"] == {"background": "a_bg_cellar", "music": "a_mus_ambient"}
    assert [i for i in d.validate() if i.severity == "error"] == []
    dlg2 = ProjectSettingsDialog(d)
    dlg2.version.setText("1.0")
    dlg2._ok()
    assert "три числа" in dlg2.err.text()


def test_repair_missing_texts(qapp, demo):
    """Сцена ссылается на текст, которого нет в таблице (старый редактор / ручная правка) — редактор
    заводит пустую строку: ошибка «нет текста» становится предупреждением и не мешает сборке."""
    from app.document import ProjectDocument
    csv = demo.root / "locale" / "ru.csv"
    csv.write_text("".join(ln for ln in csv.read_text(encoding="utf-8").splitlines(True)
                           if not ln.startswith(("str_cellar_1,", "str_hall_2,"))), encoding="utf-8")
    assert any(i.code == "locale.key_missing" and i.severity == "error" for i in demo.issues())
    d = ProjectDocument()
    d.load(demo.root)
    assert d.repair_missing_texts() == 2
    assert not errors(d)
    assert {"locale.empty"} <= {i.code for i in d.validate() if i.severity == "warning"}
    assert d.repair_missing_texts() == 0
    d.save()
    assert not [i for i in demo.issues() if i.severity == "error"]
    d.undo.undo()
    assert d.text("str_cellar_1") == "" and "str_cellar_1" not in d.get(("locale", "ru"))
