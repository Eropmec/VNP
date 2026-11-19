"""Связь редактора с рантаймом Godot: JSON-RPC 2.0 по TCP, одна строка — одно сообщение.
Редактор — сервер на случайном порту, рантайм подключается по --editor-port. Протокол — runtime/README.md."""
import json
import time

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer


class RuntimeLink(QObject):
    """JSON-RPC 2.0 по TCP, одна строка — одно сообщение. Редактор — сервер."""
    connected = Signal()
    disconnected = Signal()
    notification = Signal(str, dict)
    response = Signal(str, float, dict)        # метод, задержка мс, результат
    failed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.listen(QHostAddress.LocalHost, 0)
        self.server.newConnection.connect(self._accept)
        self.sock, self.buf, self.next_id, self.pending = None, b"", 1, {}

    @property
    def port(self):
        return self.server.serverPort()

    def _accept(self):
        sock = self.server.nextPendingConnection()
        if self.sock is not None:              # новая игра сменяет старую (перезапуск в другом окне)
            old, self.sock = self.sock, None
            old.disconnected.disconnect(self._gone)
            old.readyRead.disconnect(self._read)
            old.close()
            self.buf = b""
            self.pending.clear()
        self.sock = sock
        sock.setSocketOption(QAbstractSocket.LowDelayOption, 1)
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self._gone)
        self.connected.emit()

    def _gone(self):
        self.sock, self.buf = None, b""
        self.pending.clear()
        self.disconnected.emit()

    def _read(self):
        self.buf += bytes(self.sock.readAll())
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            msg = json.loads(line.decode("utf-8"))
            if "method" in msg:
                self.notification.emit(msg["method"], msg.get("params") or {})
            elif msg.get("id") in self.pending:
                method, t = self.pending.pop(msg["id"])
                if "error" in msg:
                    self.failed.emit(method, msg["error"].get("message", "?"))
                else:
                    self.response.emit(method, (time.perf_counter() - t) * 1000, msg.get("result") or {})

    def call(self, method, **params):
        if self.sock is None:
            return
        rid = self.next_id
        self.next_id += 1
        self.pending[rid] = (method, time.perf_counter())
        data = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, ensure_ascii=False)
        self.sock.write(QByteArray((data + "\n").encode("utf-8")))
        self.sock.flush()
