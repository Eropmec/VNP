extends Control
## Меню игры: главное, пауза, сохранить/загрузить, настройки, история.
## Экраны складываются стопкой: «Назад» (Esc, кнопка «Назад» Android) закрывает верхний.
## Вся логика игры — в main.gd; здесь только экраны и вызовы его методов.

const S = preload("res://ui/strings.gd")
const SavesScript = preload("res://vn/saves.gd")

var main                     ## main.gd
var _stack: Array[Control] = []


func setup(main_node) -> void:
	main = main_node
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func t(key: String) -> String:
	return S.t(key, main.data.language if main.data else "ru")


func is_open() -> bool:
	return not _stack.is_empty()


func top_name() -> String:
	return String(_stack.back().name) if is_open() else ""


func close_all() -> void:
	for s in _stack:
		s.queue_free()
	_stack.clear()


## Esc / «Назад». Возвращает true, если что-то закрылось.
func back() -> bool:
	if not is_open():
		return false
	if _stack.size() == 1 and top_name() == "MainMenu":
		return false                              # из главного меню назад некуда
	_stack.pop_back().queue_free()
	if _stack.is_empty():
		main.on_menus_closed()
	return true


func _push(screen: Control) -> Control:
	add_child(screen)
	_stack.append(screen)
	return screen


# ---------------------------------------------------------------- общие детали

func _layer(n: String, dim := 0.72) -> Control:
	var root := Control.new()
	root.name = n
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_STOP           # клики не уходят в игру под меню
	var shade := ColorRect.new()
	shade.color = Color(0.02, 0.02, 0.04, dim)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(shade)
	return root


func _panel(root: Control, title: String, width := 820, height := 560) -> VBoxContainer:
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(center)
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(width, height)
	var st := StyleBoxFlat.new()
	st.bg_color = Color(0.07, 0.06, 0.1, 0.96)
	st.border_color = Color(1, 1, 1, 0.12)
	st.set_border_width_all(1)
	st.set_corner_radius_all(14)
	st.set_content_margin_all(28)
	panel.add_theme_stylebox_override("panel", st)
	center.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 14)
	panel.add_child(box)
	var head := HBoxContainer.new()
	var label := Label.new()
	label.text = title
	label.add_theme_font_size_override("font_size", 34)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	head.add_child(label)
	var close := _button(t("back"), func(): back(), Vector2(160, 48))
	head.add_child(close)
	box.add_child(head)
	return box


func _button(text: String, cb: Callable, min_size := Vector2(380, 58)) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = min_size
	b.add_theme_font_size_override("font_size", 24)
	b.focus_mode = Control.FOCUS_ALL
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var s := StyleBoxFlat.new()
		s.set_corner_radius_all(10)
		s.content_margin_left = 20
		s.content_margin_right = 20
		s.set_border_width_all(1)
		match state:
			"hover", "focus":
				s.bg_color = Color(0.22, 0.17, 0.3, 0.95)
				s.border_color = Color(0.85, 0.72, 1.0, 0.9)
			"pressed":
				s.bg_color = Color(0.32, 0.25, 0.42, 0.98)
				s.border_color = Color(0.85, 0.72, 1.0)
			"disabled":
				s.bg_color = Color(0.08, 0.08, 0.1, 0.6)
				s.border_color = Color(1, 1, 1, 0.06)
			_:
				s.bg_color = Color(0.1, 0.08, 0.14, 0.88)
				s.border_color = Color(1, 1, 1, 0.16)
		if state == "focus":
			s.draw_center = false
		b.add_theme_stylebox_override(state, s)
	b.add_theme_color_override("font_disabled_color", Color(1, 1, 1, 0.3))
	b.pressed.connect(cb)
	return b


# ---------------------------------------------------------------- главное меню

func show_main() -> void:
	close_all()
	var root := Control.new()
	root.name = "MainMenu"
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_STOP
	var menu_cfg: Dictionary = main.data.project.get("menu", {})
	var bg_id := String(menu_cfg.get("background", ""))
	if bg_id.is_empty():
		for id in main.data.assets:
			var a: Dictionary = main.data.assets[id]
			if a.get("kind") == "image" and String(a.get("path", "")).begins_with("bg/"):
				bg_id = id
				break
	var bg := TextureRect.new()
	bg.texture = main.loader.texture(bg_id) if not bg_id.is_empty() else null
	bg.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	bg.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(bg)
	var shade := ColorRect.new()
	shade.color = Color(0, 0, 0, 0.45)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(shade)
	var box := VBoxContainer.new()
	box.position = Vector2(96, 110)
	box.add_theme_constant_override("separation", 14)
	root.add_child(box)
	var title := Label.new()
	title.text = String(main.data.project.get("title", ""))
	title.add_theme_font_size_override("font_size", 58)
	title.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.8))
	title.add_theme_constant_override("shadow_offset_y", 3)
	box.add_child(title)
	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(0, 30)
	box.add_child(spacer)
	var latest: String = main.saves.latest()
	var cont := _button(t("continue"), func(): main.load_slot(latest))
	cont.disabled = latest.is_empty()
	if not cont.disabled:
		box.add_child(cont)
	box.add_child(_button(t("new_game"), func(): main.new_game()))
	var load_b := _button(t("load"), func(): show_saves("load"))
	load_b.disabled = latest.is_empty()
	box.add_child(load_b)
	box.add_child(_button(t("settings"), func(): show_settings()))
	if not OS.has_feature("mobile") and not OS.has_feature("web"):
		box.add_child(_button(t("quit"), func(): main.quit_app()))
	var endings: int = main.data.nodes.values().filter(func(n): return n.get("type") == "ending").size()
	if endings > 0:
		var found := Label.new()
		var seen: int = main.saves.persistent["endings"].filter(func(e): return main.data.nodes.has(e)).size()
		found.text = "%s: %d / %d" % [t("endings_found"), seen, endings]
		found.modulate = Color(1, 1, 1, 0.7)
		found.add_theme_font_size_override("font_size", 20)
		box.add_child(found)
	_push(root)
	var first: Button = cont if not cont.disabled else box.get_child(2) as Button
	if first and not OS.has_feature("mobile"):
		first.grab_focus.call_deferred()
	var music := String(menu_cfg.get("music", ""))
	main.stage.clear()
	if not music.is_empty():
		main.stage.apply({"cmd": "music", "asset": music, "fade": 1.5, "loop": true})


# ---------------------------------------------------------------- пауза

func show_pause() -> void:
	var root := _layer("Pause", 0.55)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(center)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	center.add_child(box)
	var resume := _button(t("resume"), func(): back())
	box.add_child(resume)
	var save := _button(t("save"), func(): show_saves("save"))
	save.disabled = not main.can_save()
	box.add_child(save)
	box.add_child(_button(t("load"), func(): show_saves("load")))
	box.add_child(_button(t("history"), func(): show_history()))
	box.add_child(_button(t("settings"), func(): show_settings()))
	box.add_child(_button(t("main_menu"), func(): main.quit_to_menu()))
	if not OS.has_feature("mobile") and not OS.has_feature("web"):
		box.add_child(_button(t("quit"), func(): main.quit_app()))
	_push(root)
	if not OS.has_feature("mobile"):
		resume.grab_focus.call_deferred()


# ---------------------------------------------------------------- сохранения

func show_saves(mode: String, page := -1) -> void:
	## mode: save | load. Страница 0 — авто и быстрое сохранение (только для загрузки).
	if page < 0:
		page = 0 if mode == "load" and (main.saves.exists("auto") or main.saves.exists("quick")) else 1
	var root := _layer("Saves_" + mode)
	var box := _panel(root, t("save") if mode == "save" else t("load"), 1060, 620)
	var tabs := HBoxContainer.new()
	tabs.add_theme_constant_override("separation", 8)
	box.add_child(tabs)
	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 16)
	grid.add_theme_constant_override("v_separation", 16)
	box.add_child(grid)
	var pages := []
	if mode == "load":
		pages.append(0)
	for p in range(1, SavesScript.PAGES + 1):
		pages.append(p)
	for p in pages:
		var label := "A/Q" if p == 0 else str(p)
		var b := _button(label, func(): _replace_top(func(): show_saves(mode, p)), Vector2(64, 44))
		if p == page:
			b.add_theme_color_override("font_color", Color(0.95, 0.8, 0.4))
		tabs.add_child(b)
	var slots: Array = ["auto", "quick"] if page == 0 else range((page - 1) * SavesScript.SLOTS_PER_PAGE + 1,
		page * SavesScript.SLOTS_PER_PAGE + 1).map(func(i): return SavesScript.slot_name(i))
	for slot in slots:
		grid.add_child(_slot_card(slot, mode))
	_push(root)


func _replace_top(builder: Callable) -> void:
	_stack.pop_back().queue_free()
	builder.call()


func _slot_card(slot: String, mode: String) -> Control:
	var info: Dictionary = main.saves.read(slot)
	var card := Button.new()
	card.custom_minimum_size = Vector2(320, 230)
	card.clip_text = true
	var st := StyleBoxFlat.new()
	st.bg_color = Color(0.1, 0.08, 0.14, 0.9)
	st.set_corner_radius_all(10)
	st.set_border_width_all(1)
	st.border_color = Color(1, 1, 1, 0.14)
	card.add_theme_stylebox_override("normal", st)
	var hover := st.duplicate()
	hover.border_color = Color(0.85, 0.72, 1.0, 0.9)
	card.add_theme_stylebox_override("hover", hover)
	card.add_theme_stylebox_override("focus", hover)
	var v := VBoxContainer.new()
	v.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	v.offset_left = 10
	v.offset_top = 10
	v.offset_right = -10
	v.offset_bottom = -8
	v.mouse_filter = Control.MOUSE_FILTER_IGNORE
	card.add_child(v)
	var pic := TextureRect.new()
	pic.custom_minimum_size = Vector2(300, 168)
	pic.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	pic.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	pic.mouse_filter = Control.MOUSE_FILTER_IGNORE
	pic.texture = main.saves.thumbnail(slot) if not info.is_empty() else null
	v.add_child(pic)
	var label := Label.new()
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", 16)
	var name := t("autosave") if slot == "auto" else t("quicksave") if slot == "quick" else "№ %d" % int(slot.substr(5))
	if info.is_empty():
		label.text = "%s · %s" % [name, t("empty_slot")]
		label.modulate = Color(1, 1, 1, 0.45)
	else:
		label.text = "%s · %s\n%s · %s %s" % [name, info.get("label", ""), info.get("saved_at_text", ""),
			_playtime(float(info.get("playtime", 0))), t("playtime")]
	v.add_child(label)
	card.disabled = mode == "load" and info.is_empty()
	card.pressed.connect(func():
		if mode == "save":
			if main.save_slot(slot):
				_replace_top(func(): show_saves("save", _page_of(slot)))
		else:
			main.load_slot(slot))
	return card


func _page_of(slot: String) -> int:
	return 0 if not slot.begins_with("slot_") else (int(slot.substr(5)) - 1) / SavesScript.SLOTS_PER_PAGE + 1


static func _playtime(sec: float) -> String:
	var m := int(sec) / 60
	return "%d:%02d" % [m / 60, m % 60] if m >= 60 else "%d мин" % maxi(m, 1) if sec >= 30 else "<1 мин"


# ---------------------------------------------------------------- настройки

func show_settings() -> void:
	var root := _layer("Settings")
	var box := _panel(root, t("settings"), 820, 560)
	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 20)
	grid.add_theme_constant_override("v_separation", 14)
	box.add_child(grid)
	var st = main.settings
	for spec in [["master", "vol_master"], ["music", "vol_music"], ["sfx", "vol_sfx"], ["voice", "vol_voice"]]:
		_slider_row(grid, t(spec[1]), 0, 100, float(st.get_value(spec[0])) * 100.0,
			func(v): st.set_value(spec[0], v / 100.0), func(v): return "%d%%" % v)
	_slider_row(grid, t("text_speed"), 0, 120, float(st.get_value("text_speed")),
		func(v):
			st.set_value("text_speed", v)
			main.dialogue.chars_per_second = v,
		func(v): return t("instant") if v <= 0 else str(int(v)))
	_slider_row(grid, t("auto_delay"), 0.5, 6, float(st.get_value("auto_delay")),
		func(v): st.set_value("auto_delay", v), func(v): return "%.1f %s" % [v, t("seconds")], 0.5)
	if not OS.has_feature("mobile") and not OS.has_feature("web") and not main.args.has("embed"):
		var fs := CheckButton.new()
		fs.text = t("fullscreen")
		fs.add_theme_font_size_override("font_size", 22)
		fs.button_pressed = DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_FULLSCREEN
		fs.toggled.connect(func(on):
			st.set_value("fullscreen", on)
			main.set_fullscreen(on))
		box.add_child(fs)
	var langs: Array = main.data.project.get("languages", [])
	if langs.size() > 1:
		var row := HBoxContainer.new()
		var l := Label.new()
		l.text = t("language")
		l.add_theme_font_size_override("font_size", 22)
		l.custom_minimum_size = Vector2(260, 0)
		row.add_child(l)
		var opt := OptionButton.new()
		opt.add_theme_font_size_override("font_size", 22)
		var names := {"ru": "Русский", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
			"uk": "Українська", "zh": "中文", "ja": "日本語"}
		for code in langs:
			opt.add_item(names.get(String(code).substr(0, 2), code))
		opt.selected = maxi(0, langs.find(main.data.language))
		opt.item_selected.connect(func(i):
			st.set_value("language", langs[i])
			main.set_language(langs[i])
			_replace_top(func(): show_settings()))
		row.add_child(opt)
		box.add_child(row)
	_push(root)


func _slider_row(grid: GridContainer, title: String, lo: float, hi: float, value: float, on_change: Callable,
		fmt: Callable, step := 1.0) -> void:
	var l := Label.new()
	l.text = title
	l.add_theme_font_size_override("font_size", 22)
	l.custom_minimum_size = Vector2(260, 0)
	grid.add_child(l)
	var s := HSlider.new()
	s.min_value = lo
	s.max_value = hi
	s.step = step
	s.value = value
	s.custom_minimum_size = Vector2(320, 32)
	s.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	grid.add_child(s)
	var v := Label.new()
	v.text = fmt.call(value)
	v.add_theme_font_size_override("font_size", 20)
	v.custom_minimum_size = Vector2(120, 0)
	grid.add_child(v)
	s.value_changed.connect(func(x):
		v.text = fmt.call(x)
		on_change.call(x))


# ---------------------------------------------------------------- история

func show_history() -> void:
	var root := _layer("History")
	var box := _panel(root, t("history"), 980, 600)
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(920, 480)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	box.add_child(scroll)
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 12)
	scroll.add_child(list)
	for entry in main.history:
		var r := RichTextLabel.new()
		r.bbcode_enabled = true
		r.fit_content = true
		r.scroll_active = false
		r.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		r.add_theme_font_size_override("normal_font_size", 22)
		r.add_theme_font_size_override("bold_font_size", 22)
		var who := String(entry.get("name", ""))
		var text := String(entry.get("text", "")).replace("[", "[lb]")
		r.text = ("[b][color=%s]%s[/color][/b]  %s" % [entry.get("color", "#ffffff"), who, text]) if not who.is_empty() \
			else "[i][color=#c8c8d4]%s[/color][/i]" % text
		list.add_child(r)
	_push(root)
	scroll.set_deferred("scroll_vertical", 1 << 20)
