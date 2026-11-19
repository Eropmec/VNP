extends RefCounted
## Загрузка ассетов по ID из реестра проекта, с кэшем.
##
## res://game/... — упакованная игра: файлы импортированы Godot, берём load().
## Абсолютный путь — проект из редактора: читаем файл напрямую, без импорта,
## поэтому правка картинки видна сразу после перезагрузки.

var data
var _cache: Dictionary = {}


func _init(project_data) -> void:
	data = project_data


func clear() -> void:
	_cache.clear()


func texture(asset_id: String) -> Texture2D:
	var res = _fetch(asset_id)
	return res if res is Texture2D else null


func audio(asset_id: String) -> AudioStream:
	var res = _fetch(asset_id)
	return res if res is AudioStream else null


func _fetch(asset_id: String) -> Resource:
	if _cache.has(asset_id):
		return _cache[asset_id]
	var path: String = data.asset_path(asset_id)
	if path.is_empty():
		push_warning("ассет %s не найден в реестре" % asset_id)
		return null
	var res: Resource = null
	if path.begins_with("res://"):
		if ResourceLoader.exists(path):
			res = load(path)
	else:
		res = _load_external(path)
	if res == null:
		push_warning("не удалось загрузить %s (%s)" % [asset_id, path])
	_cache[asset_id] = res
	return res


static func _load_external(path: String) -> Resource:
	if not FileAccess.file_exists(path):
		return null
	match path.get_extension().to_lower():
		"png", "jpg", "jpeg", "webp", "svg":
			var img := Image.load_from_file(path)
			return ImageTexture.create_from_image(img) if img != null else null
		"wav":
			return AudioStreamWAV.load_from_file(path)
		"ogg":
			return AudioStreamOggVorbis.load_from_file(path)
		"mp3":
			var mp3 := AudioStreamMP3.new()
			mp3.data = FileAccess.get_file_as_bytes(path)
			return mp3
	return null
