extends SceneTree
## Автотесты ядра рантайма. Без окна:
##   godot --headless --path runtime -s res://tests/run_tests.gd -- --project=<папка демо>
## Без --project берётся упакованная игра res://game. Код выхода 0 — всё прошло.

const ProjectData = preload("res://vn/project_data.gd")
const GameState = preload("res://vn/game_state.gd")
const StoryRunner = preload("res://vn/story_runner.gd")
const Expr = preload("res://vn/expr.gd")

var failures := 0
var checks := 0
var dir := "res://game"


func _initialize() -> void:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--project="):
			dir = a.substr(10)
	var data = ProjectData.load_from(dir)
	check(data.ok(), "проект загружается: %s" % ", ".join(data.errors))
	if data.ok():
		test_expressions(data)
		test_state(data)
		test_playthroughs(data)
		test_disabled_option(data)
		test_goto_fast_forward(data)
		test_locale(data)
		test_saves()
	print("\nПроверок: %d, провалено: %d" % [checks, failures])
	quit(1 if failures > 0 else 0)


func check(cond: bool, what: String) -> void:
	checks += 1
	if cond:
		print("  ok  ", what)
	else:
		failures += 1
		print("  FAIL", " ", what)


# ---------------------------------------------------------------- выражения

func test_expressions(data) -> void:
	print("Выражения")
	var st = GameState.new(data, 7)
	var sanity := {"var": "v_sanity"}
	check(Expr.eval({"op": ">", "l": sanity, "r": 3.0}, st) == true, "рассудок 6 > 3")
	check(Expr.eval({"op": "and", "args": [true, {"op": "<", "l": sanity, "r": 3.0}]}, st) == false, "и с ложным")
	check(Expr.eval({"op": "or", "args": [false, {"op": "not", "arg": {"var": "v_saw_shadow"}}]}, st) == true, "или + не")
	check(is_equal_approx(Expr.eval({"op": "+", "l": sanity, "r": {"op": "*", "l": 2.0, "r": 3.0}}, st), 12.0), "6 + 2×3 = 12")
	check(is_equal_approx(Expr.eval({"op": "mod", "l": -1.0, "r": 3.0}, st), 2.0), "-1 mod 3 = 2")
	check(Expr.eval({"op": "/", "l": 1.0, "r": 0.0}, st) == 0.0, "деление на ноль не роняет игру")
	check(Expr.eval({"op": "==", "l": sanity, "r": 6.0}, st) == true, "int-переменная = float из JSON")
	check(Expr.eval({"op": "call", "fn": "visited", "args": ["n_cellar"]}, st) == false, "visited() до посещения")
	st.visit("n_cellar")
	check(Expr.eval({"op": "call", "fn": "visited", "args": ["n_cellar"]}, st) == true, "visited() после посещения")
	check(Expr.eval({"op": "call", "fn": "clamp", "args": [15.0, 0.0, 10.0]}, st) == 10.0, "clamp")
	var r = Expr.eval({"op": "call", "fn": "rand", "args": [1.0, 6.0]}, st)
	check(r >= 1 and r <= 6, "rand(1, 6) в диапазоне")


func test_state(data) -> void:
	print("Состояние")
	var st = GameState.new(data, 1)
	check(st.get_var("v_sanity") == 6 and typeof(st.get_var("v_sanity")) == TYPE_INT, "значение по умолчанию целое 6")
	Expr.apply_effects([{"op": "add", "var": "v_sanity", "value": 100.0}], st)
	check(st.get_var("v_sanity") == 10, "прибавка упирается в max = 10")
	Expr.apply_effects([{"op": "sub", "var": "v_sanity", "value": 100.0}], st)
	check(st.get_var("v_sanity") == 0, "вычитание упирается в min = 0")
	Expr.apply_effects([{"op": "toggle", "var": "v_saw_shadow"}], st)
	check(st.get_var("v_saw_shadow") == true, "toggle")
	var snap: Dictionary = st.to_dict()
	var st2 = GameState.new(data, 99)
	st2.from_dict(snap)
	check(st2.get_var("v_saw_shadow") == true and st2.get_var("v_sanity") == 0, "снимок состояния восстанавливается")


# ---------------------------------------------------------------- прохождения

## Проигрывает сюжет: на репликах жмёт «дальше», на выборах берёт варианты по очереди из choices.
func play(data, choices: Array, start_node := "") -> Dictionary:
	var st = GameState.new(data, 42)
	var runner = StoryRunner.new(data, st)
	var log := {"lines": [], "nodes": [], "stage": [], "ending": "", "error": "", "offered": []}
	runner.line.connect(func(who, key, _c): log["lines"].append(key))
	runner.node_entered.connect(func(n): log["nodes"].append(n))
	runner.stage_command.connect(func(c, instant): log["stage"].append([c["cmd"], instant]))
	runner.ended.connect(func(n): log["ending"] = n)
	runner.failed.connect(func(m): log["error"] = m)
	runner.choice.connect(func(opts): log["offered"].append(opts.map(func(o): return [o["id"], o["enabled"]])))
	runner.start(start_node)
	var queue := choices.duplicate()
	var guard := 0
	while runner.waiting in ["line", "choice", "wait"] and guard < 500:
		guard += 1
		if runner.waiting == "choice":
			if queue.is_empty():
				break
			runner.choose(queue.pop_front())
		else:
			runner.advance()
	log["state"] = st
	return log


func test_playthroughs(data) -> void:
	print("Прохождения «Старого дома»")
	var a := play(data, [0, 0])
	check(a["ending"] == "n_end_saved", "подвал → взять за руку → «Вместе до рассвета» (%s)" % a["ending"])
	var s = a["state"]
	check(s.get_var("v_sanity") == 4 and s.get_var("v_courage") == 2 and s.get_var("v_saw_shadow") == true,
		"переменные: рассудок 4, смелость 2, видел тень")
	check("str_cellar_3" in a["lines"] and not "str_cellar_2" in a["lines"], "при рассудке 4 срабатывает ветка else")
	check(a["nodes"] == ["n_intro", "n_cellar", "n_fate", "n_end_saved"], "порядок узлов, глава раскрыта в первый узел")

	var b := play(data, [1])
	check(b["ending"] == "n_end_whisper", "уйти → холл → «Шёпот в темноте» (%s)" % b["ending"])
	check(b["state"].get_var("v_courage") == 0, "смелость 0 → ветка else в n_fate")
	check(["stop_audio", false] in b["stage"], "в холле музыка останавливается")

	var c := play(data, [0, 1])
	check(c["ending"] == "n_end_alone", "подвал → бежать → «Один на пороге» (%s)" % c["ending"])
	check(c["error"] == "", "ни одно прохождение не упало")


func test_disabled_option(data) -> void:
	print("Недоступный вариант")
	var st = GameState.new(data, 1)
	st.set_var("v_sanity", 2)
	var runner = StoryRunner.new(data, st)
	var offered := []
	runner.choice.connect(func(opts): offered.append(opts))
	runner.start()
	while runner.waiting == "line":
		runner.advance()
	check(runner.waiting == "choice", "дошли до выбора")
	var down = offered[0][0]
	check(down["id"] == "o_down" and down["enabled"] == false, "«Спуститься» показан, но неактивен (when_unavailable: disable)")
	check(runner.choose(0) == false and runner.waiting == "choice", "неактивный вариант нельзя выбрать")
	check(runner.choose(1) == true, "доступный вариант выбирается")


func test_goto_fast_forward(data) -> void:
	print("Превью: переход к команде")
	var st = GameState.new(data, 1)
	var runner = StoryRunner.new(data, st)
	var stage := []
	var lines := []
	runner.stage_command.connect(func(c, instant): stage.append([c["cmd"], c.get("asset", c.get("char", "")), instant]))
	runner.line.connect(func(who, key, _c): lines.append(key))
	runner.goto("n_cellar", "c_s1")
	check(lines == ["str_cellar_4"], "реплики до c_s1 пропущены, показана c_s1")
	check(["bg", "a_bg_cellar", true] in stage, "фон выставлен мгновенно")
	check(["show", "ch_anna", true] in stage, "Анна показана мгновенно")
	check(stage.filter(func(x): return x[0] == "sfx").is_empty(), "скрип при перемотке не играет")
	check(st.get_var("v_sanity") == 4, "эффекты до команды применены (рассудок 6 → 4)")
	check(runner.current_command_id() == "c_s1", "текущая команда c_s1")


func test_locale(data) -> void:
	print("Локализация")
	check(data.text("str_anna") == "Анна", "русский по умолчанию")
	data.language = "en"
	check(data.text("str_anna") == "Anna", "английский")
	data.locales["en"].erase("str_hall_2")
	check(data.text("str_hall_2").begins_with("Дверь"), "нет перевода — берётся основной язык")
	check(data.text("str_nope") == "[str_nope]", "нет строки вовсе — виден ключ")
	data.language = data.project["default_language"]


func test_saves() -> void:
	print("Сохранения")
	var Saves = load("res://vn/saves.gd")
	var sv = Saves.new("vn_test_%d" % Time.get_ticks_usec())
	check(sv.latest() == "", "пусто — «Продолжить» неактивно")
	check(sv.write("slot_01", {"label": "один", "position": {"node": "n_intro", "command": "c_n1"}}), "запись слота")
	OS.delay_msec(1100)
	sv.write("auto", {"label": "авто"})
	check(sv.read("slot_01")["label"] == "один" and sv.read("slot_01").has("saved_at_text"), "чтение слота")
	check(sv.latest() == "auto", "самое свежее — автосохранение")
	sv.mark_ending("n_end_saved")
	var again = Saves.new(sv.dir.get_slice("/", 2))
	check("n_end_saved" in again.persistent["endings"], "концовки помнятся между запусками")
	sv.delete("slot_01")
	check(not sv.exists("slot_01"), "удаление слота")
