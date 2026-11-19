"""
Проверка связи редактор ↔ рантайм на настоящем проекте: запускает Godot с проектом,
проходит сюжет командами редактора, меряет перезагрузку и переход к команде.

    python tools/runtime_check.py --godot "C:/Godot/Godot_v4.7.2-stable_win64_console.exe"
    python tools/runtime_check.py --godot ./godot --headless          # без окна

Проект берётся из samples/demo и копируется во временную папку — оригинал не меняется.
"""
import argparse
import json
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Runtime:
    """Минимальный клиент протокола рантайма (редактор будет использовать такой же поверх Qt)."""

    def __init__(self, conn):
        self.conn, self.buf, self.next_id, self.notes = conn, b"", 1, []

    def _read(self, timeout):
        self.conn.settimeout(timeout)
        while b"\n" not in self.buf:
            chunk = self.conn.recv(65536)
            if not chunk:
                raise ConnectionError("рантайм закрыл соединение")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def wait_note(self, method, timeout=15):
        for i, m in enumerate(self.notes):
            if m.get("method") == method:
                return self.notes.pop(i)["params"]
        end = time.perf_counter() + timeout
        while True:
            msg = self._read(max(0.05, end - time.perf_counter()))
            if msg.get("method") == method:
                return msg["params"]
            self.notes.append(msg)

    def call(self, method, **params):
        rid = self.next_id
        self.next_id += 1
        t = time.perf_counter()
        self.conn.sendall((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
                                      ensure_ascii=False) + "\n").encode("utf-8"))
        while True:
            msg = self._read(10)
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']['message']}")
                return (time.perf_counter() - t) * 1000, msg["result"]
            self.notes.append(msg)


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    return bool(cond)


def p95(xs):
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * 0.95))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--godot", required=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("-n", type=int, default=50)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="vn_check_"))
    proj = tmp / "demo"
    shutil.copytree(ROOT / "samples" / "demo", proj)

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    cmd = [args.godot, "--path", str(ROOT / "runtime")]
    if args.headless:
        cmd.insert(1, "--headless")
    cmd += ["--", f"--project={proj.as_posix()}", f"--editor-port={port}", "--seed=1"]
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    try:
        srv.settimeout(30)
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        rt = Runtime(conn)
        hello = rt.wait_note("hello")
        print(f"Godot {hello['godot']} на {hello['platform']}, старт {(time.perf_counter() - t0) * 1000:.0f} мс")

        print("Протокол")
        pos = rt.wait_note("play.position")
        ok &= check(pos == {"node": "n_intro", "command": "c_n1"}, f"игра началась с n_intro / c_n1 ({pos})")
        _, st = rt.call("state.get")
        ok &= check(st["vars"]["v_sanity"] == 6 and st["waiting"] == "line", "state.get: рассудок 6, ждём клика")
        _, r = rt.call("play.goto", node="n_cellar", command="c_s1")
        ok &= check(r["command"] == "c_s1" and r["waiting"] == "line", "play.goto в середину сцены подвала")

        (proj / "locale" / "ru.csv").write_text(
            (proj / "locale" / "ru.csv").read_text(encoding="utf-8").replace("Не оставляй меня одну!", "Не уходи!"),
            encoding="utf-8")
        _, r = rt.call("project.reload")
        ok &= check(r["node"] == "n_cellar" and r["command"] == "c_s1", "после правки текста reload вернулся на ту же реплику")

        rt.call("state.set", var="v_sanity", value=1)
        _, r = rt.call("play.goto", node="n_intro", command="c_choice")
        ok &= check(r["waiting"] == "choice", "goto к выбору")
        _, r = rt.call("play.choose", index=0)
        ok &= check(not r["ok"], "«Спуститься» недоступен при рассудке 1")
        _, r = rt.call("play.choose", index=1)
        ok &= check(r["ok"] and r["node"] == "n_hall", "«Уговорить уйти» → холл")
        for _ in range(4):
            rt.call("play.next")
            rt.call("play.next")             # первый клик дописывает текст, второй — дальше
        end = rt.wait_note("play.ended")
        ok &= check(end["node"] == "n_end_whisper", f"концовка «Шёпот в темноте» ({end['node']})")

        print(f"Задержки, n={args.n}")
        pings = [rt.call("ping")[0] for _ in range(args.n)]
        reloads = [rt.call("project.reload")[0] for _ in range(args.n)]
        gotos = [rt.call("play.goto", node="n_cellar", command="c_s1")[0] for _ in range(args.n)]
        print(f"  ping (транспорт) медиана {statistics.median(pings):6.1f} мс   p95 {p95(pings):6.1f} мс")
        print(f"  reload проекта   медиана {statistics.median(reloads):6.1f} мс   p95 {p95(reloads):6.1f} мс")
        print(f"  goto к команде   медиана {statistics.median(gotos):6.1f} мс   p95 {p95(gotos):6.1f} мс")
        ok &= check(p95(reloads) <= 200 and p95(gotos) <= 100, "укладываемся в 200 / 100 мс")
        rt.call("app.quit")
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ИТОГ:", "ПРОЙДЕНО" if ok else "ЕСТЬ ОШИБКИ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
