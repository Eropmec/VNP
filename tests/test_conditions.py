"""Конструктор условий и эффектов (Qt offscreen)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def doc(qapp, demo):
    from app.document import ProjectDocument
    d = ProjectDocument()
    d.load(demo.root)
    return d


FATE = {"op": "and", "args": [{"op": ">=", "l": {"var": "v_courage"}, "r": 1},
                              {"op": ">=", "l": {"var": "v_sanity"}, "r": 2}]}


def test_blocks_round_trip():
    from app.condition_editor import from_blocks, to_blocks
    for e in [FATE, True, {"op": "not", "arg": {"var": "v_saw_shadow"}},
              {"op": "or", "args": [{"op": "call", "fn": "visited", "args": ["n_cellar"]},
                                    {"op": "not", "arg": {"op": "and", "args": [True, {"var": "v_saw_shadow"}]}}]},
              {"op": "+", "l": 1, "r": 2}]:
        assert from_blocks(to_blocks(e)) == e


def test_condition_editor_shows_formula_and_blocks(doc):
    from app.condition_editor import ConditionEditor, _CmpRow
    ed = ConditionEditor(doc, FATE)
    assert ed.formula.text() == "смелость ≥ 1 и рассудок ≥ 2"
    assert len(ed.area.widget().findChildren(_CmpRow)) == 2
    assert ed.ok()


def test_typing_formula_rebuilds_blocks(doc):
    from app.condition_editor import ConditionEditor, _CmpRow, _VisitedRow
    ed = ConditionEditor(doc, True)
    ed.formula.setText("рассудок > 3 или visited(n_cellar)")
    ed._formula_done()
    assert ed.value() == {"op": "or", "args": [{"op": ">", "l": {"var": "v_sanity"}, "r": 3},
                                               {"op": "call", "fn": "visited", "args": ["n_cellar"]}]}
    root = ed.area.widget()
    assert len(root.findChildren(_CmpRow)) == 1 and len(root.findChildren(_VisitedRow)) == 1
    assert root.op.currentData() == "or"


def test_editing_blocks_updates_formula(doc):
    from app.condition_editor import ConditionEditor, _CmpRow
    ed = ConditionEditor(doc, FATE)
    row = ed.area.widget().findChildren(_CmpRow)[0]
    row.op.setCurrentIndex(row.op.findData("<"))
    row.value.setText("смелость + 2")
    row._value()
    assert ed.formula.text() == "смелость < смелость + 2 и рассудок ≥ 2"
    ed.area.widget().op.setCurrentIndex(1)
    assert ed.value()["op"] == "or"


def test_errors_are_reported(doc):
    from app.condition_editor import ConditionEditor
    ed = ConditionEditor(doc, True)
    ed.formula.setText("рассудок >")
    ed._formula_done()
    assert not ed.ok() and "оборвалась" in ed.status.text()
    ed.formula.setText("рассудок + 1")
    ed._formula_done()
    assert not ed.ok() and "да/нет" in ed.status.text()
    ed.formula.setText("видел_тень = 3")
    ed._formula_done()
    assert not ed.ok() and "нельзя сравнить" in ed.status.text()


def test_effects_editor(doc):
    from app.condition_editor import EffectsEditor
    ed = EffectsEditor(doc, [{"op": "add", "var": "v_courage", "value": 1}])
    ed._add()
    assert len(ed.value()) == 2
    edit = ed.findChildren(QLineEdit)[0]
    edit.setText("смелость * 2")
    edit.editingFinished.emit()
    assert ed.value()[0]["value"] == {"op": "*", "l": {"var": "v_courage"}, "r": 2}
    assert ed.ok()
    ed.effects[0] = {"op": "add", "var": "v_saw_shadow", "value": 1}
    ed._check()
    assert not ed.ok() and "нельзя прибавлять" in ed.status.text()


def test_new_variable_dialog(doc):
    from app.condition_editor import NewVariableDialog
    dlg = NewVariableDialog(doc)
    dlg.name.setText("доверие Анны")
    dlg.kind.setCurrentIndex(0)
    dlg.default.setText("2")
    dlg._ok()
    v = next(v for v in doc.get("variables")["variables"] if v["name"] == "доверие_Анны")
    assert v["type"] == "int" and v["default"] == 2 and dlg.created == v["id"]
    dlg2 = NewVariableDialog(doc)
    dlg2.name.setText("Доверие_анны")
    dlg2._ok()
    assert "уже есть" in dlg2.err.text()


def test_set_command_and_option_condition_in_scene_editor(qapp, demo):
    from app.main_window import MainWindow
    from app.condition_editor import EffectsEditor
    from app import scene_ops as S
    w = MainWindow()
    w.open(demo.root)
    ed = w.open_scene("sc_hall")
    ed.select((2,))
    ed.add("set")
    cmd = S.get(ed.scene, ed.path)
    assert cmd["cmd"] == "set" and cmd["effects"][0]["var"] == "v_sanity"
    eff = ed.form_area.widget().findChild(EffectsEditor)
    eff.findChildren(QComboBox)[1].setCurrentIndex(0)          # «станет»
    assert S.get(ed.scene, ed.path)["effects"][0]["op"] == "set"
    assert [i for i in w.doc.validate() if i.severity == "error"] == []
    ed2 = w.open_scene("sc_intro")
    ed2._set_option((6,), 1, "x", condition={"op": "call", "fn": "visited", "args": ["n_hall"]},
                    when_unavailable="disable")
    o = ed2.scene["commands"][6]["options"][1]
    assert o["condition"]["fn"] == "visited" and o["when_unavailable"] == "disable"
    w.doc.undo.setClean()
    w.close()
