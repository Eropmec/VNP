extends PanelContainer
## Диалоговое окно: имя говорящего и текст с эффектом печатной машинки.

signal finished_typing

@export var chars_per_second := 45.0

var _name: Label
var _text: Label
var _more: Label
var _shown := 0.0
var _typing := false
var _blink := 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	offset_left = 40
	offset_right = -40
	offset_top = -196
	offset_bottom = -24
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.06, 0.05, 0.08, 0.86)
	style.border_color = Color(1, 1, 1, 0.12)
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	style.content_margin_left = 28
	style.content_margin_right = 28
	style.content_margin_top = 16
	style.content_margin_bottom = 18
	add_theme_stylebox_override("panel", style)

	var box := VBoxContainer.new()
	box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	box.add_theme_constant_override("separation", 6)
	add_child(box)
	_name = Label.new()
	_name.add_theme_font_size_override("font_size", 26)
	box.add_child(_name)
	_text = Label.new()
	_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_text.add_theme_font_size_override("font_size", 26)
	_text.add_theme_color_override("font_color", Color(0.94, 0.92, 0.9))
	_text.add_theme_constant_override("line_spacing", 4)
	box.add_child(_text)
	_more = Label.new()
	_more.text = "▼"
	_more.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_more.add_theme_color_override("font_color", Color(1, 1, 1, 0.6))
	box.add_child(_more)
	_more.visible = false
	visible = false


func show_line(speaker: String, color: Color, text: String) -> void:
	visible = true
	_name.text = speaker
	_name.visible = not speaker.is_empty()
	_name.add_theme_color_override("font_color", color)
	_text.text = text
	_text.add_theme_color_override("font_color", Color(0.94, 0.92, 0.9) if not speaker.is_empty() else Color(0.86, 0.86, 0.92))
	_shown = 0.0
	_text.visible_characters = 0
	_typing = chars_per_second > 0.0
	if not _typing:
		complete()
	_more.visible = false


func is_typing() -> bool:
	return _typing


func complete() -> void:
	_typing = false
	_text.visible_characters = -1
	_more.visible = true
	finished_typing.emit()


func _process(delta: float) -> void:
	if _typing:
		_shown += delta * chars_per_second
		var total := _text.get_total_character_count()
		_text.visible_characters = int(_shown)
		if int(_shown) >= total:
			complete()
	elif _more.visible:
		_blink += delta
		_more.modulate.a = 0.35 + 0.65 * absf(sin(_blink * 3.0))
