extends CenterContainer
## Меню выбора. Недоступные варианты (when_unavailable: disable) видны, но не нажимаются.

signal chosen(index: int)

var _box: VBoxContainer


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	offset_bottom = -200                       # над диалоговым окном
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_box = VBoxContainer.new()
	_box.add_theme_constant_override("separation", 14)
	add_child(_box)
	visible = false


func open(options: Array) -> void:
	for c in _box.get_children():
		c.queue_free()
	var first: Button = null
	for o in options:
		var b := Button.new()
		b.text = o["label"]
		b.disabled = not o["enabled"]
		b.custom_minimum_size = Vector2(560, 64)
		b.add_theme_font_size_override("font_size", 24)
		b.focus_mode = Control.FOCUS_ALL
		for st in ["normal", "hover", "pressed", "disabled", "focus"]:
			b.add_theme_stylebox_override(st, _style(st))
		b.add_theme_color_override("font_disabled_color", Color(1, 1, 1, 0.35))
		b.add_theme_color_override("font_hover_color", Color(1, 0.95, 0.8))
		var idx: int = o["index"]
		b.pressed.connect(func(): chosen.emit(idx))
		_box.add_child(b)
		if first == null and o["enabled"]:
			first = b
	visible = true
	if first and not OS.has_feature("mobile"):
		first.grab_focus.call_deferred()


func close() -> void:
	visible = false
	for c in _box.get_children():
		c.queue_free()


func _style(state: String) -> StyleBoxFlat:
	var s := StyleBoxFlat.new()
	s.set_corner_radius_all(10)
	s.content_margin_left = 24
	s.content_margin_right = 24
	s.set_border_width_all(1)
	match state:
		"hover", "focus":
			s.bg_color = Color(0.22, 0.17, 0.3, 0.95)
			s.border_color = Color(0.85, 0.72, 1.0, 0.9)
			s.set_border_width_all(2)
		"pressed":
			s.bg_color = Color(0.32, 0.25, 0.42, 0.98)
			s.border_color = Color(0.85, 0.72, 1.0)
		"disabled":
			s.bg_color = Color(0.08, 0.08, 0.1, 0.7)
			s.border_color = Color(1, 1, 1, 0.08)
		_:
			s.bg_color = Color(0.1, 0.08, 0.14, 0.9)
			s.border_color = Color(1, 1, 1, 0.18)
	if state == "focus":
		s.draw_center = false
	return s
