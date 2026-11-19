extends Node
## Связь с редактором: JSON-RPC 2.0 по TCP, одна строка — одно сообщение.
## Рантайм — клиент, редактор — сервер (порт передаётся аргументом --editor-port).

signal request(id, method: String, params: Dictionary)
signal lost
signal connected            ## hello отправлен — можно слать текущее состояние

var _peer := StreamPeerTCP.new()
var _port := 0
var _inbox := PackedByteArray()
var _hello: Dictionary = {}
var _hello_sent := false


func connect_to(port: int, hello: Dictionary) -> void:
	_port = port
	_hello = hello
	_peer.connect_to_host("127.0.0.1", port)


func is_connected_to_editor() -> bool:
	return _port > 0 and _peer.get_status() == StreamPeerTCP.STATUS_CONNECTED


func notify(method: String, params: Dictionary = {}) -> void:
	if is_connected_to_editor():
		_send({"jsonrpc": "2.0", "method": method, "params": params})


func reply(id, result: Dictionary) -> void:
	if id != null and is_connected_to_editor():
		_send({"jsonrpc": "2.0", "id": id, "result": result})


func fail(id, message: String) -> void:
	if id != null and is_connected_to_editor():
		_send({"jsonrpc": "2.0", "id": id, "error": {"code": -32000, "message": message}})


func _process(_dt: float) -> void:
	if _port == 0:
		return
	_peer.poll()
	var st := _peer.get_status()
	if st != StreamPeerTCP.STATUS_CONNECTED:
		if _hello_sent and st in [StreamPeerTCP.STATUS_ERROR, StreamPeerTCP.STATUS_NONE]:
			_port = 0
			lost.emit()
		return
	if not _hello_sent:
		_hello_sent = true
		_peer.set_no_delay(true)     # без алгоритма Нейгла: иначе ответы задерживаются на ~40 мс
		notify("hello", _hello)
		connected.emit()
	var n := _peer.get_available_bytes()
	if n <= 0:
		return
	var got: Array = _peer.get_data(n)
	if got[0] != OK:
		return
	_inbox.append_array(got[1])
	while true:
		var nl := _inbox.find(10)
		if nl < 0:
			break
		var raw := _inbox.slice(0, nl).get_string_from_utf8()
		_inbox = _inbox.slice(nl + 1)
		var msg = JSON.parse_string(raw)
		if typeof(msg) == TYPE_DICTIONARY and msg.has("method"):
			var params = msg.get("params", {})
			request.emit(msg.get("id"), String(msg["method"]), params if typeof(params) == TYPE_DICTIONARY else {})


func _send(obj: Dictionary) -> void:
	_peer.put_data((JSON.stringify(obj) + "\n").to_utf8_buffer())
