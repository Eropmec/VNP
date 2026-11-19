extends RefCounted
## Вычисление выражений и эффектов формата v1. Зеркало editor/vnformat/expr.py.
##
## state должен уметь: get_var(id), set_var(id, value), visit_count(node_id), rng.


static func eval(e, state) -> Variant:
	if typeof(e) != TYPE_DICTIONARY:
		return e
	if e.has("var"):
		return state.get_var(e["var"])
	var op: String = e.get("op", "")
	match op:
		"and":
			for a in e["args"]:
				if not truthy(eval(a, state)):
					return false
			return true
		"or":
			for a in e["args"]:
				if truthy(eval(a, state)):
					return true
			return false
		"not":
			return not truthy(eval(e["arg"], state))
		"==":
			return _eq(eval(e["l"], state), eval(e["r"], state))
		"!=":
			return not _eq(eval(e["l"], state), eval(e["r"], state))
		"<":
			return _num(eval(e["l"], state)) < _num(eval(e["r"], state))
		"<=":
			return _num(eval(e["l"], state)) <= _num(eval(e["r"], state))
		">":
			return _num(eval(e["l"], state)) > _num(eval(e["r"], state))
		">=":
			return _num(eval(e["l"], state)) >= _num(eval(e["r"], state))
		"+":
			return _num(eval(e["l"], state)) + _num(eval(e["r"], state))
		"-":
			return _num(eval(e["l"], state)) - _num(eval(e["r"], state))
		"*":
			return _num(eval(e["l"], state)) * _num(eval(e["r"], state))
		"/":
			var d := _num(eval(e["r"], state))
			return 0.0 if d == 0.0 else _num(eval(e["l"], state)) / d
		"mod":
			var m := _num(eval(e["r"], state))
			return 0.0 if m == 0.0 else fposmod(_num(eval(e["l"], state)), m)
		"call":
			return _call(e["fn"], e.get("args", []), state)
	push_warning("неизвестная операция в выражении: %s" % op)
	return null


static func _call(fn: String, args: Array, state) -> Variant:
	match fn:
		"visited":
			return state.visit_count(str(args[0])) > 0
		"times_visited":
			return state.visit_count(str(args[0]))
		"rand":
			return state.rng.randi_range(int(_num(eval(args[0], state))), int(_num(eval(args[1], state))))
		"min":
			return minf(_num(eval(args[0], state)), _num(eval(args[1], state)))
		"max":
			return maxf(_num(eval(args[0], state)), _num(eval(args[1], state)))
		"abs":
			return absf(_num(eval(args[0], state)))
		"clamp":
			return clampf(_num(eval(args[0], state)), _num(eval(args[1], state)), _num(eval(args[2], state)))
	push_warning("неизвестная функция %s()" % fn)
	return null


static func apply_effects(effects: Array, state) -> void:
	for ef in effects:
		var op: String = ef["op"]
		match op:
			"set":
				state.set_var(ef["var"], eval(ef["value"], state))
			"add":
				state.set_var(ef["var"], _num(state.get_var(ef["var"])) + _num(eval(ef["value"], state)))
			"sub":
				state.set_var(ef["var"], _num(state.get_var(ef["var"])) - _num(eval(ef["value"], state)))
			"mul":
				state.set_var(ef["var"], _num(state.get_var(ef["var"])) * _num(eval(ef["value"], state)))
			"toggle":
				state.set_var(ef["var"], not truthy(state.get_var(ef["var"])))
			"call":
				push_warning("функция-эффект %s() не найдена (плагины — этап 5)" % ef["fn"])


static func truthy(v) -> bool:
	match typeof(v):
		TYPE_NIL:
			return false
		TYPE_BOOL:
			return v
		TYPE_INT, TYPE_FLOAT:
			return v != 0
		TYPE_STRING:
			return not v.is_empty()
	return true


## JSON в Godot отдаёт все числа как float, поэтому числа сравниваются как float.
static func _num(v) -> float:
	match typeof(v):
		TYPE_INT, TYPE_FLOAT:
			return float(v)
		TYPE_BOOL:
			return 1.0 if v else 0.0
	return 0.0


static func _eq(a, b) -> bool:
	var na := typeof(a) in [TYPE_INT, TYPE_FLOAT]
	var nb := typeof(b) in [TYPE_INT, TYPE_FLOAT]
	if na and nb:
		return is_equal_approx(float(a), float(b))
	if typeof(a) != typeof(b):
		return false
	return a == b
