extends Control
## Точка входа рантайма: загружает проект, собирает сцену и интерфейс, связывает их с исполнителем.
##
## Аргументы после «--»:
##   --project=<папка>     проект из редактора (иначе упакованная игра res://game)
##   --start=<узел>        начать с узла (плейтест из редактора)
##   --command=<команда>   …и сразу с этой строки сцены
##   --lang=<язык>         язык текста
##   --seed=<число>        зерно случайности (воспроизводимые прогоны)
##   --editor-port=<порт>  подключиться к редактору
##   --embed               окно без рамки — для встраивания в редактор
##   --fullscreen          во весь экран (F11 переключает)
##   --menu                показать главное меню и при запуске из редактора
##   --autopilot=<шаги> --shots=<папка>   автопрогон со скриншотами (см. _autopilot)
##
## Без --start и --editor-port игра открывается главным меню (так её видит игрок).
## Клавиши: клик / пробел / Enter — дальше; Esc — меню; F5 / F9 — быстрое сохранение / загрузка;
## F11 — во весь экран. Для разработки: F3 — отладка, Ctrl+R — заново, L — язык.

const ProjectData = preload("res://vn/project_data.gd")
const GameState = preload("res://vn/game_state.gd")
const StoryRunner = preload("res://vn/story_runner.gd")
const AssetLoader = preload("res://vn/asset_loader.gd")
const StageScript = preload("res://vn/stage.gd")
const EditorLink = preload("res://vn/editor_link.gd")
const DialogueBox = preload("res://ui/dialogue_box.gd")
const ChoiceMenu = preload("res://ui/choice_menu.gd")
const Menus = preload("res://ui/menus.gd")
const SettingsScript = preload("res://vn/settings.gd")
const SavesScript = preload("res://vn/saves.gd")
const S = preload("res://ui/strings.gd")

var args := {}
var data
var state
var runner
var loader
var stage
var dialogue
var choices
var link
var _debug: Label
var _ending: Control
var _error: Label
var _wait_timer: Timer
var _window_placed := false

var settings                 ## vn/settings.gd
var saves                    ## vn/saves.gd
var menus                    ## ui/menus.gd
var mode := "game"           ## menu | game
var history: Array = []      ## [{name, color, text}] — для экрана «История» и сохранений
var playtime := 0.0
var auto := false
var dev := false             ## запуск из редактора: без меню, с отладочными клавишами
var _hud: HBoxContainer
var _auto_btn: Button
var _toast: Label
var _auto_timer: Timer
var _pause_shot: Image
var _last_auto_node := ""


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv: PackedStringArray = a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else "1"
	if args.has("embed"):
		DisplayServer.window_set_flag(DisplayServer.WINDOW_FLAG_BORDERLESS, true)
	_build_ui()
	link = EditorLink.new()
	link.name = "EditorLink"
	add_child(link)
	link.request.connect(_on_request)
	link.lost.connect(func(): get_tree().quit())
	link.connected.connect(func():
		if runner:
			link.notify("play.position", {"node": runner.current_node, "command": runner.current_command_id()}))
	dev = args.has("editor-port") or args.has("start")
	_load_project()
	if data and data.ok():
		var gid := String(data.project.get("id", "game"))
		settings = SettingsScript.new(gid)
		saves = SavesScript.new(gid)
		_apply_settings()
	if args.has("editor-port"):
		link.connect_to(int(args["editor-port"]), {
			"pid": OS.get_process_id(),
			"hwnd": DisplayServer.window_get_native_handle(DisplayServer.WINDOW_HANDLE),
			"godot": Engine.get_version_info()["string"],
			"platform": OS.get_name(),
			"project": data.base if data else "",
		})
	if data and data.ok():
		if args.has("start") and args.has("command"):     # плейтест с конкретной строки сцены
			state = GameState.new(data, int(args.get("seed", "-1")), saves.persistent["vars"])
			_new_runner()
			_set_mode("game")
			runner.goto(String(args["start"]), String(args["command"]))
		elif dev and not args.has("menu"):
			restart(args.get("start", ""))
		else:
			_set_mode("menu")
			menus.show_main()
	if args.has("autopilot"):
		_autopilot.call_deferred(String(args["autopilot"]).split(","))


# ---------------------------------------------------------------- проект

func _project_dir() -> String:
	return String(args.get("project", "res://game")).replace("\\", "/")


func _load_project() -> bool:
	data = ProjectData.load_from(_project_dir())
	if not data.ok():
		_show_error("Проект не загрузился:\n" + "\n".join(data.errors))
		return false
	if args.has("lang") and data.locales.has(args["lang"]):
		data.language = args["lang"]
	var res: Vector2i = data.resolution()
	get_tree().root.content_scale_size = res
	if not _window_placed and not args.has("embed") and not OS.has_feature("mobile") and DisplayServer.get_name() != "headless":
		_window_placed = true
		var screen := DisplayServer.screen_get_usable_rect()
		var k := minf(1.0, minf(screen.size.x * 0.9 / res.x, screen.size.y * 0.9 / res.y))
		DisplayServer.window_set_size(Vector2i(int(res.x * k), int(res.y * k)))
		DisplayServer.window_set_position(screen.position + (screen.size - DisplayServer.window_get_size()) / 2)
		if args.has("fullscreen"):
			DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	DisplayServer.window_set_title(String(data.project.get("title", "VN")))
	loader = AssetLoader.new(data)
	stage.setup(data, loader)
	return true


## Новое прохождение (или продолжение с узла при start_node).
func restart(start_node := "", keep_state := false) -> void:
	if not keep_state or state == null:
		state = GameState.new(data, int(args.get("seed", "-1")), saves.persistent["vars"] if saves else null)
	else:
		state.data = data
	history.clear()
	playtime = 0.0
	_last_auto_node = ""
	_set_mode("game")
	_new_runner()
	stage.clear()
	dialogue.visible = false
	choices.close()
	_ending.visible = false
	_error.visible = false
	runner.start(start_node)


func _new_runner() -> void:
	runner = StoryRunner.new(data, state)
	runner.stage_command.connect(func(c, instant): stage.apply(c, instant))
	runner.line.connect(_on_line)
	runner.choice.connect(_on_choice)
	runner.wait.connect(func(sec): _wait_timer.start(sec))
	runner.ended.connect(_on_ended)
	runner.failed.connect(func(m):
		_show_error(m)
		link.notify("runtime.error", {"message": m}))
	runner.position.connect(func(n, c):
		link.notify("play.position", {"node": n, "command": c})
		if n != _last_auto_node and not c.is_empty():   # вошли в новый узел — автосохранение
			_last_auto_node = n
			_autosave_after_frame())


# ---------------------------------------------------------------- события исполнителя

func _on_line(char_id: String, key: String, cmd: Dictionary) -> void:
	choices.close()
	var name := ""
	var color := Color(0.85, 0.85, 0.9)
	if not char_id.is_empty():
		var ch: Dictionary = data.characters.get(char_id, {})
		name = data.text(ch.get("name", "")) if not ch.is_empty() else char_id
		color = Color.from_string(String(ch.get("color", "#ffffff")), Color.WHITE)
	stage.set_speaker(char_id)
	stage.play_voice(String(cmd.get("voice", "")))
	dialogue.show_line(name, color, data.text(key))
	history.append({"name": name, "color": "#" + color.to_html(false), "text": data.text(key)})
	if history.size() > 200:
		history.pop_front()
	_refresh_debug()


func _on_choice(options: Array) -> void:
	var items := []
	for o in options:
		items.append({"index": o["index"], "label": data.text(o["text"]), "enabled": o["enabled"]})
	choices.open(items)
	_refresh_debug()


func _on_ended(node_id: String) -> void:
	choices.close()
	dialogue.visible = false
	var n: Dictionary = data.nodes[node_id]
	var info: Dictionary = n.get("ending", {})
	var lang: String = data.language
	var kinds := {"good": [S.t("ending_good", lang), Color(0.6, 0.9, 0.65)], "bad": [S.t("ending_bad", lang), Color(0.95, 0.5, 0.5)],
		"neutral": [S.t("ending", lang), Color(0.85, 0.85, 0.9)], "secret": [S.t("ending_secret", lang), Color(0.85, 0.7, 1.0)]}
	if saves:
		saves.mark_ending(node_id)
		saves.save_persistent()
	_hud.visible = false
	_ending.get_node("Box/Buttons/Again").text = S.t("restart", lang)
	_ending.get_node("Box/Buttons/Menu").text = S.t("main_menu", lang)
	var k: Array = kinds.get(info.get("kind", "neutral"), kinds["neutral"])
	_ending.get_node("Box/Kind").text = k[0]
	_ending.get_node("Box/Kind").add_theme_color_override("font_color", k[1])
	_ending.get_node("Box/Title").text = data.text(info.get("title", ""))
	_ending.modulate.a = 0.0
	_ending.visible = true
	create_tween().tween_property(_ending, "modulate:a", 1.0, 1.2)
	link.notify("play.ended", {"node": node_id})
	_refresh_debug()


func _show_error(message: String) -> void:
	_error.text = "Ошибка сюжета\n" + message
	_error.visible = true


# ---------------------------------------------------------------- ввод

## Клик/тап по экрану. Корневой Control перехватывает мышь как элемент интерфейса,
## поэтому до _unhandled_input клик не доходит — ловим его здесь. Кнопки выбора
## и «Начать заново» лежат выше и получают свои клики раньше.
## На Android тап приходит сюда же: Godot превращает касание в клик мыши.
func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		if mode == "game" and not menus.is_open():
			_next()
		accept_event()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		_escape()
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("ui_accept"):
		if mode == "game" and not menus.is_open():
			_next()
			get_viewport().set_input_as_handled()
	elif event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_F5:
				quick_save()
			KEY_F9:
				load_slot("quick")
			KEY_F11:
				_toggle_fullscreen()
			KEY_F3:
				if dev:
					_debug.visible = not _debug.visible
					_refresh_debug()
			KEY_R:
				if dev and event.ctrl_pressed and data and data.ok():
					restart()
			KEY_L:
				if dev:
					_cycle_language()


## Esc, кнопка «Назад» на Android, кнопка ≡: открыть паузу или закрыть верхнее меню.
func _escape() -> void:
	if menus.is_open():
		if not menus.back() and mode == "menu" and OS.has_feature("mobile"):
			quit_app()                       # «Назад» в главном меню на телефоне — выход
		return
	if mode == "game" and not _ending.visible:
		_pause_shot = _capture()
		_auto_timer.stop()
		choices.visible = false               # варианты выбора не просвечивают сквозь меню
		menus.show_pause()


func _toggle_fullscreen() -> void:
	if args.has("embed"):
		return
	var full := DisplayServer.window_get_mode() in [DisplayServer.WINDOW_MODE_FULLSCREEN, DisplayServer.WINDOW_MODE_EXCLUSIVE_FULLSCREEN]
	DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED if full else DisplayServer.WINDOW_MODE_FULLSCREEN)


func _next() -> void:
	if runner == null:
		return
	if dialogue.visible and dialogue.is_typing():
		dialogue.complete()
	elif runner.waiting == "line":
		runner.advance()
	_refresh_debug()


func _cycle_language() -> void:
	if data == null or data.locales.size() < 2:
		return
	var langs: Array = data.project.get("languages", [])
	data.language = langs[(langs.find(data.language) + 1) % langs.size()]
	_update_auto_btn()
	# перерисовать текущую реплику или выбор на новом языке — проще всего перемотать к текущей команде
	if runner.waiting in ["line", "choice"]:
		var snap: Dictionary = state.to_dict()
		var node: String = runner.current_node
		var cmd: String = runner.current_command_id()
		_jump(node, cmd, snap)


## Перейти к узлу/команде, сохранив значения переменных на момент снимка.
func _jump(node: String, cmd: String, snap := {}) -> void:
	if not snap.is_empty():
		state.from_dict(snap)
	_new_runner()
	stage.clear()
	choices.close()
	_ending.visible = false
	_error.visible = false
	runner.goto(node, cmd)
	if not snap.is_empty():
		state.from_dict(snap)       # эффекты, пройденные при перемотке, не должны копиться
	_refresh_debug()


func _notification(what: int) -> void:
	match what:
		NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_WM_CLOSE_REQUEST:
			autosave()                        # Android может закрыть приложение в фоне без предупреждения
			if saves:
				saves.save_persistent()
		NOTIFICATION_WM_GO_BACK_REQUEST:
			_escape()


func _process(delta: float) -> void:
	if mode == "game" and menus and not menus.is_open() and not _ending.visible:
		playtime += delta


# ---------------------------------------------------------------- режимы, сохранения, настройки

func _set_mode(m: String) -> void:
	mode = m
	if _hud:
		_hud.visible = m == "game"
	if m == "menu":
		dialogue.visible = false
		choices.close()
		_ending.visible = false
		auto = false
		_update_auto_btn()


func new_game() -> void:
	menus.close_all()
	stage.clear()
	restart()


func quit_to_menu() -> void:
	autosave()
	menus.close_all()
	_set_mode("menu")
	menus.show_main()


func quit_app() -> void:
	autosave()
	if saves:
		saves.save_persistent()
	get_tree().quit()


func on_menus_closed() -> void:
	if mode == "game" and runner and runner.waiting == "choice":
		choices.visible = true


func can_save() -> bool:
	return mode == "game" and runner != null and runner.waiting in ["line", "choice"] and not _ending.visible


func _capture() -> Image:
	if DisplayServer.get_name() == "headless":
		return null
	var img := get_viewport().get_texture().get_image()
	return img if img and not img.is_empty() else null


func _save_data() -> Dictionary:
	var node: Dictionary = data.nodes.get(runner.current_node, {})
	var chapter: Dictionary = data.nodes.get(node.get("parent", ""), {})
	return {
		"game_version": data.project.get("version", ""),
		"label": ("%s · %s" % [chapter.get("name"), node.get("name", "")]) if not chapter.is_empty() else node.get("name", ""),
		"position": {"node": runner.current_node, "command": runner.current_command_id()},
		"state": state.to_dict(),
		"stage": stage.snapshot(),
		"playtime": playtime,
		"history": history.slice(maxi(0, history.size() - 60)),
	}


func save_slot(slot: String) -> bool:
	if not can_save():
		return false
	var ok: bool = saves.write(slot, _save_data(), _pause_shot if _pause_shot else _capture())
	toast(S.t("saved", data.language) if ok else "✖")
	return ok


func quick_save() -> void:
	if can_save() and not menus.is_open():
		_pause_shot = _capture()
		save_slot("quick")


func autosave() -> void:
	if saves and can_save():
		saves.write("auto", _save_data(), _capture())


func _autosave_after_frame() -> void:
	await get_tree().process_frame
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
	autosave()


func load_slot(slot: String) -> bool:
	var d: Dictionary = saves.read(slot) if saves else {}
	if d.is_empty():
		toast(S.t("no_save", data.language))
		return false
	menus.close_all()
	restore_save(d)
	toast(S.t("loaded", data.language))
	return true


## Вернуть игру в сохранённое место. Если место пропало (игру обновили) — к ближайшему узлу.
func restore_save(d: Dictionary) -> void:
	var pos: Dictionary = d.get("position", {})
	var node := String(pos.get("node", ""))
	var cmd := String(pos.get("command", ""))
	if not data.nodes.has(node):
		toast(S.t("save_missing", data.language))
		node = String(data.project.get("start", ""))
		cmd = ""
	elif not cmd.is_empty() and data.nodes[node].get("type") == "scene":
		var found := false
		var stack: Array = data.scenes.get(data.nodes[node]["scene"], {}).get("commands", []).duplicate()
		while not stack.is_empty():
			var c: Dictionary = stack.pop_back()
			if String(c.get("id", "")) == cmd:
				found = true
				break
			stack.append_array(c.get("then", []))
			stack.append_array(c.get("else", []))
		if not found:
			cmd = ""
	state = GameState.new(data, 1, saves.persistent["vars"])
	state.from_dict(d.get("state", {}))
	_set_mode("game")
	_new_runner()
	dialogue.visible = false
	choices.close()
	_ending.visible = false
	_error.visible = false
	stage.restore(d.get("stage", {}))
	runner.goto(node, cmd)
	state.from_dict(d.get("state", {}))      # эффекты, пройденные при перемотке, не должны копиться
	playtime = float(d.get("playtime", 0))
	history = d.get("history", []).duplicate()
	_last_auto_node = node
	_refresh_debug()


func _apply_settings() -> void:
	settings.apply_audio()
	dialogue.chars_per_second = float(settings.get_value("text_speed"))
	var lang := String(settings.get_value("language"))
	if not args.has("lang") and data.locales.has(lang):
		data.language = lang
	if bool(settings.get_value("fullscreen")) and not args.has("embed") and not dev:
		set_fullscreen.call_deferred(true)


func set_fullscreen(on: bool) -> void:
	if args.has("embed") or DisplayServer.get_name() == "headless":
		return
	DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN if on else DisplayServer.WINDOW_MODE_WINDOWED)


func set_language(lang: String) -> void:
	if not data.locales.has(lang) or lang == data.language:
		return
	var langs: Array = data.project.get("languages", [])
	data.language = langs[(langs.find(lang) - 1 + langs.size()) % langs.size()]
	_cycle_language()


func toast(text: String) -> void:
	_toast.text = text
	_toast.modulate.a = 1.0
	_toast.visible = true
	var tw := create_tween()
	tw.tween_interval(1.2)
	tw.tween_property(_toast, "modulate:a", 0.0, 0.6)


func _toggle_auto() -> void:
	auto = not auto
	_update_auto_btn()
	if auto and runner and runner.waiting == "line" and not dialogue.is_typing():
		_schedule_auto()


func _update_auto_btn() -> void:
	if _auto_btn:
		_auto_btn.text = ("▶▶ " if auto else "") + S.t("auto", data.language if data else "ru")
		_auto_btn.modulate = Color(1, 0.85, 0.4) if auto else Color.WHITE


func _schedule_auto() -> void:
	if auto and mode == "game" and not menus.is_open():
		_auto_timer.start(float(settings.get_value("auto_delay")) if settings else 1.5)


# ---------------------------------------------------------------- редактор

func _on_request(id, method: String, params: Dictionary) -> void:
	var t0 := Time.get_ticks_usec()
	match method:
		"ping":
			link.reply(id, {"pong": true})
		"project.reload":
			# перечитать проект и вернуться на ту же команду с теми же переменными
			var node: String = runner.current_node if runner else ""
			var cmd: String = runner.current_command_id() if runner else ""
			var snap: Dictionary = state.to_dict() if state else {}
			if not _load_project():
				link.fail(id, "\n".join(data.errors))
				return
			state = GameState.new(data, 1)
			if not node.is_empty() and data.nodes.has(node):
				_jump(node, cmd, snap)
			else:
				restart()
			await _frame()
			link.reply(id, {"ms": (Time.get_ticks_usec() - t0) / 1000.0, "node": runner.current_node, "command": runner.current_command_id()})
		"play.goto":
			if not data.nodes.has(String(params.get("node", ""))):
				link.fail(id, "узел %s не найден" % params.get("node", ""))
				return
			_jump(String(params["node"]), String(params.get("command", "")), state.to_dict() if params.get("keep_vars", true) else {})
			await _frame()
			link.reply(id, {"ms": (Time.get_ticks_usec() - t0) / 1000.0, "node": runner.current_node, "command": runner.current_command_id(), "waiting": runner.waiting})
		"play.restart":
			restart()
			link.reply(id, {"node": runner.current_node})
		"play.next":
			_next()
			link.reply(id, {"node": runner.current_node, "command": runner.current_command_id(), "waiting": runner.waiting})
		"play.choose":
			var ok: bool = runner.choose(int(params.get("index", 0)))
			link.reply(id, {"ok": ok, "node": runner.current_node, "command": runner.current_command_id(), "waiting": runner.waiting})
		"state.get":
			link.reply(id, {"vars": state.vars, "visits": state.visits, "node": runner.current_node,
				"command": runner.current_command_id(), "waiting": runner.waiting})
		"state.set":
			state.set_var(String(params.get("var", "")), params.get("value"))
			_refresh_debug()
			link.reply(id, {"vars": state.vars})
		"app.quit":
			link.reply(id, {})
			get_tree().quit()
		_:
			link.fail(id, "неизвестный метод " + method)


## Ответ уходит после отрисовки кадра: замер задержки включает рендер.
func _frame() -> void:
	if DisplayServer.get_name() == "headless":
		await get_tree().process_frame
	else:
		await RenderingServer.frame_post_draw


# ---------------------------------------------------------------- интерфейс

func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.03, 0.03, 0.04)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)
	stage = StageScript.new()
	stage.name = "Stage"
	stage.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(stage)
	dialogue = DialogueBox.new()
	dialogue.name = "Dialogue"
	add_child(dialogue)
	choices = ChoiceMenu.new()
	choices.name = "Choices"
	add_child(choices)
	choices.chosen.connect(func(i):
		choices.close()
		runner.choose(i)
		_refresh_debug())

	_ending = PanelContainer.new()
	_ending.name = "Ending"
	_ending.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	var es := StyleBoxFlat.new()
	es.bg_color = Color(0.02, 0.02, 0.03, 0.88)
	_ending.add_theme_stylebox_override("panel", es)
	var box := VBoxContainer.new()
	box.name = "Box"
	box.alignment = BoxContainer.ALIGNMENT_CENTER
	box.add_theme_constant_override("separation", 18)
	_ending.add_child(box)
	for spec in [["Kind", 24], ["Title", 52]]:
		var l := Label.new()
		l.name = spec[0]
		l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		l.add_theme_font_size_override("font_size", spec[1])
		box.add_child(l)
	var buttons := HBoxContainer.new()
	buttons.name = "Buttons"
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 16)
	box.add_child(buttons)
	for spec in [["Again", func(): restart()], ["Menu", func(): quit_to_menu()]]:
		var b := Button.new()
		b.name = spec[0]
		b.custom_minimum_size = Vector2(280, 56)
		b.add_theme_font_size_override("font_size", 22)
		b.pressed.connect(spec[1])
		buttons.add_child(b)
	_ending.visible = false
	add_child(_ending)

	_hud = HBoxContainer.new()
	_hud.name = "HUD"
	_hud.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	_hud.offset_left = -260
	_hud.offset_top = 14
	_hud.offset_right = -14
	_hud.alignment = BoxContainer.ALIGNMENT_END
	_hud.add_theme_constant_override("separation", 8)
	add_child(_hud)
	_auto_btn = _hud_button("Авто", func(): _toggle_auto())
	_hud_button("≡", func(): _escape()).custom_minimum_size = Vector2(56, 44)

	_toast = Label.new()
	_toast.name = "Toast"
	_toast.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	_toast.offset_top = 24
	_toast.offset_left = -200
	_toast.offset_right = 200
	_toast.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_toast.add_theme_font_size_override("font_size", 22)
	var ts := StyleBoxFlat.new()
	ts.bg_color = Color(0.05, 0.05, 0.08, 0.85)
	ts.set_corner_radius_all(8)
	ts.set_content_margin_all(10)
	_toast.add_theme_stylebox_override("normal", ts)
	_toast.visible = false
	_toast.mouse_filter = Control.MOUSE_FILTER_IGNORE

	menus = Menus.new()
	menus.name = "Menus"
	add_child(menus)
	menus.setup(self)
	add_child(_toast)

	_auto_timer = Timer.new()
	_auto_timer.one_shot = true
	_auto_timer.timeout.connect(func():
		if auto and mode == "game" and not menus.is_open() and runner and runner.waiting == "line":
			_next())
	add_child(_auto_timer)
	dialogue.finished_typing.connect(func(): _schedule_auto())

	_error = Label.new()
	_error.name = "Error"
	_error.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE)
	_error.offset_left = 24
	_error.offset_right = -24
	_error.offset_top = 24
	_error.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_error.add_theme_font_size_override("font_size", 20)
	_error.add_theme_color_override("font_color", Color(1, 0.85, 0.85))
	var errs := StyleBoxFlat.new()
	errs.bg_color = Color(0.45, 0.08, 0.1, 0.92)
	errs.set_content_margin_all(16)
	errs.set_corner_radius_all(8)
	_error.add_theme_stylebox_override("normal", errs)
	_error.visible = false
	add_child(_error)

	_debug = Label.new()
	_debug.name = "Debug"
	_debug.position = Vector2(16, 16)
	_debug.add_theme_font_size_override("font_size", 16)
	var ds := StyleBoxFlat.new()
	ds.bg_color = Color(0, 0, 0, 0.7)
	ds.set_content_margin_all(10)
	ds.set_corner_radius_all(6)
	_debug.add_theme_stylebox_override("normal", ds)
	_debug.visible = false
	add_child(_debug)

	_wait_timer = Timer.new()
	_wait_timer.one_shot = true
	_wait_timer.timeout.connect(func(): runner.advance())
	add_child(_wait_timer)


func _hud_button(text: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.focus_mode = Control.FOCUS_NONE
	b.custom_minimum_size = Vector2(96, 44)
	b.add_theme_font_size_override("font_size", 20)
	var st := StyleBoxFlat.new()
	st.bg_color = Color(0.05, 0.05, 0.08, 0.55)
	st.set_corner_radius_all(8)
	b.add_theme_stylebox_override("normal", st)
	var hv := st.duplicate()
	hv.bg_color = Color(0.2, 0.16, 0.28, 0.85)
	b.add_theme_stylebox_override("hover", hv)
	b.add_theme_stylebox_override("pressed", hv)
	b.pressed.connect(cb)
	_hud.add_child(b)
	return b


func _refresh_debug() -> void:
	if not _debug.visible or runner == null:
		return
	var lines := ["узел: %s" % runner.current_node, "команда: %s" % runner.current_command_id(),
		"ждём: %s" % runner.waiting, "язык: %s" % data.language, ""]
	for id in state.vars:
		var v: Dictionary = data.variables[id]
		lines.append("%s = %s" % [v.get("name", id), str(state.vars[id])])
	_debug.text = "\n".join(lines)


# ---------------------------------------------------------------- автопрогон

## Шаги через запятую: n — следующая реплика (дописать и перейти), c — клик мышью, 0..9 — выбрать вариант,
## s:имя — скриншот в папку --shots, w:сек — подождать, d — отладочная панель, esc — меню/назад,
## b:Текст — нажать кнопку, save:слот / load:слот, p:метка — вывести состояние, q — выйти.
## Пример: --autopilot=w:1.5,s:01_intro,n,n,n,0 --shots=/tmp/shots
func _autopilot(steps: PackedStringArray) -> void:
	var shots := String(args.get("shots", "user://shots"))
	DirAccess.make_dir_recursive_absolute(shots)
	for raw in steps:
		var step := raw.strip_edges()
		if step.is_empty():
			continue
		if step == "n":
			if dialogue.is_typing():
				dialogue.complete()
			_next()
			await get_tree().create_timer(0.9).timeout
		elif step == "c":                      # настоящий клик мышью в центр экрана
			for pressed in [true, false]:
				var ev := InputEventMouseButton.new()
				ev.button_index = MOUSE_BUTTON_LEFT
				ev.pressed = pressed
				ev.position = get_viewport().get_visible_rect().size / 2.0
				ev.global_position = ev.position
				Input.parse_input_event(ev)
				await get_tree().process_frame
			await get_tree().create_timer(0.9).timeout
		elif step.is_valid_int():
			if runner.waiting == "choice":
				choices.close()
				runner.choose(int(step))
			await get_tree().create_timer(1.2).timeout
		elif step.begins_with("w:"):
			await get_tree().create_timer(float(step.substr(2))).timeout
		elif step.begins_with("s:"):
			if dialogue.visible and dialogue.is_typing():
				dialogue.complete()
			await RenderingServer.frame_post_draw
			var img := get_viewport().get_texture().get_image()
			img.save_png("%s/%s.png" % [shots, step.substr(2)])
			print("скриншот: %s/%s.png" % [shots, step.substr(2)])
		elif step == "d":
			_debug.visible = not _debug.visible
			_refresh_debug()
		elif step == "esc":
			_escape()
			await get_tree().create_timer(0.6).timeout
		elif step.begins_with("b:"):          # нажать видимую кнопку с таким текстом
			var target := step.substr(2)
			var btn := _find_button(self, target)
			if btn:
				btn.pressed.emit()
			else:
				print("кнопка не найдена: ", target)
			await get_tree().create_timer(0.9).timeout
		elif step.begins_with("save:"):
			if not menus.is_open():
				_pause_shot = _capture()
			save_slot(step.substr(5))
			await get_tree().create_timer(0.3).timeout
		elif step.begins_with("load:"):
			load_slot(step.substr(5))
			await get_tree().create_timer(1.0).timeout
		elif step.begins_with("p:"):          # напечатать состояние — для автотестов
			print("STATE ", step.substr(2), " ", JSON.stringify({"mode": mode, "node": runner.current_node if runner else "",
				"command": runner.current_command_id() if runner else "", "waiting": runner.waiting if runner else "",
				"vars": state.vars if state else {}, "menu": menus.top_name(), "endings": saves.persistent["endings"] if saves else []}))
		elif step == "q":
			break
	get_tree().quit()


func _find_button(node: Node, text: String) -> Button:
	for c in node.get_children():
		if c is Button and c.is_visible_in_tree() and not c.disabled and (c.text == text or c.text.ends_with(text)):
			return c
		var found := _find_button(c, text)
		if found:
			return found
	return null
