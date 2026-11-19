extends RefCounted
## Состояние прохождения: переменные, счётчики посещений, генератор случайных чисел.
## to_dict()/from_dict() — основа будущих сохранений (этап 3).

var data                                  ## ProjectData
var vars: Dictionary = {}
var visits: Dictionary = {}
var rng := RandomNumberGenerator.new()
var rng_seed := 0
var persistent: Dictionary = {}           ## значения переменных scope = persistent (общие для всех сохранений)


func _init(project_data, seed_value: int = -1, persistent_store = null) -> void:
	data = project_data
	if persistent_store != null:
		persistent = persistent_store
	reset(seed_value)


func reset(seed_value: int = -1) -> void:
	vars.clear()
	visits.clear()
	for id in data.variables:
		vars[id] = _coerce(id, persistent.get(id, data.variables[id].get("default")) if _is_persistent(id)
			else data.variables[id].get("default"))
	rng_seed = seed_value if seed_value >= 0 else int(Time.get_unix_time_from_system() * 1000.0) % 2147483647
	rng.seed = rng_seed


func get_var(id: String) -> Variant:
	if not vars.has(id):
		push_warning("переменная %s не существует" % id)
		return null
	return vars[id]


func set_var(id: String, value) -> void:
	if not data.variables.has(id):
		push_warning("переменная %s не существует" % id)
		return
	vars[id] = _coerce(id, value)
	if _is_persistent(id):
		persistent[id] = vars[id]


func _is_persistent(id: String) -> bool:
	return String(data.variables.get(id, {}).get("scope", "")) == "persistent"


func visit(node_id: String) -> void:
	visits[node_id] = int(visits.get(node_id, 0)) + 1


func visit_count(node_id: String) -> int:
	return int(visits.get(node_id, 0))


## Значение приводится к типу переменной и её диапазону min/max.
func _coerce(id: String, value) -> Variant:
	var v: Dictionary = data.variables[id]
	match String(v.get("type", "")):
		"bool":
			return bool(value) if typeof(value) != TYPE_NIL else false
		"int":
			var i := int(roundf(float(value))) if typeof(value) in [TYPE_INT, TYPE_FLOAT, TYPE_BOOL] else 0
			if v.has("min"):
				i = maxi(i, int(v["min"]))
			if v.has("max"):
				i = mini(i, int(v["max"]))
			return i
		"float":
			var f := float(value) if typeof(value) in [TYPE_INT, TYPE_FLOAT, TYPE_BOOL] else 0.0
			if v.has("min"):
				f = maxf(f, float(v["min"]))
			if v.has("max"):
				f = minf(f, float(v["max"]))
			return f
		"string":
			return str(value) if typeof(value) != TYPE_NIL else ""
	return value


func to_dict() -> Dictionary:
	return {"vars": vars.duplicate(), "visits": visits.duplicate(), "rng_seed": rng_seed, "rng_state": rng.state}


func from_dict(d: Dictionary) -> void:
	vars.clear()
	for id in data.variables:
		if _is_persistent(id) and persistent.has(id):
			vars[id] = _coerce(id, persistent[id])        # «навсегда» — из профиля, а не из старого сохранения
		else:
			vars[id] = _coerce(id, d.get("vars", {}).get(id, data.variables[id].get("default")))
	visits = d.get("visits", {}).duplicate()
	rng_seed = int(d.get("rng_seed", 0))
	rng.seed = rng_seed
	if d.has("rng_state"):
		rng.state = int(d["rng_state"])
