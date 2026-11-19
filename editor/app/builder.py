"""Сборка игры: проверка проекта → сборочная копия рантайма с игрой → импорт и экспорт Godot.

Без Qt — используется окном «Собрать игру» и командой tools/build_game.py.

Шаблоны экспорта Godot весят 1,3 ГБ одним архивом. Нужны из него 2–3 файла (~100 МБ),
поэтому архив читается по частям (HTTP Range): сначала оглавление в конце файла, затем
только нужные файлы.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vnformat import validate_project
from vnformat.io import read_json
from vnformat.pack import pack
from vnformat.template import slug

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
Log = Callable[[str], None]

TARGETS = {
    "windows": {"title": "Windows", "preset": "Windows Desktop", "ext": ".exe",
                "templates": ["windows_release_x86_64.exe", "windows_debug_x86_64.exe"]},
    "linux": {"title": "Linux", "preset": "Linux", "ext": ".x86_64",
              "templates": ["linux_release.x86_64", "linux_debug.x86_64"]},
    "android": {"title": "Android (APK)", "preset": "Android", "ext": ".apk",
                "templates": ["android_release.apk", "android_debug.apk"]},
}


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- Godot и его шаблоны

def godot_version(exe: str) -> str:
    """«4.7.2.stable.official.ed1daf0bf»."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f"Godot не запускается: {exc}") from exc
    line = out.splitlines()[-1] if out else ""
    if not re.match(r"^\d+\.\d+", line):
        raise BuildError(f"не удалось узнать версию Godot (ответ: {out[:200]!r})")
    return line


def template_version(ver: str) -> str:
    """4.7.2.stable.official.x → 4.7.2.stable — так называется папка шаблонов."""
    parts = ver.split(".")
    for i, p in enumerate(parts):
        if not p.isdigit():
            return ".".join(parts[:i + 1])
    return ver


def release_tag(ver: str) -> tuple[str, str]:
    """(тег релиза, репозиторий): 4.7.2.stable → 4.7.2-stable; 4.8.beta2 → 4.8-beta2 (godot-builds)."""
    tv = template_version(ver).split(".")
    num, status = ".".join(tv[:-1]), tv[-1]
    return f"{num}-{status}", "godotengine/godot" if status == "stable" else "godotengine/godot-builds"


def godot_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Godot"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Godot"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "godot"


def godot_config_dir() -> Path:
    if sys.platform in ("win32", "darwin"):
        return godot_data_dir()
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "godot"


def templates_dir(ver: str) -> Path:
    return godot_data_dir() / "export_templates" / template_version(ver)


def missing_templates(ver: str, target: str) -> list[str]:
    d = templates_dir(ver)
    return [f for f in TARGETS[target]["templates"] if not (d / f).is_file()]


def templates_url(ver: str) -> str:
    tag, repo = release_tag(ver)
    return f"https://github.com/{repo}/releases/download/{tag}/Godot_v{tag}_export_templates.tpz"


class RangeZip:
    """Zip-архив на сервере, читаемый по частям."""

    def __init__(self, url: str):
        self.url = url
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.url = r.geturl()                       # после переадресации на хранилище
            self.size = int(r.headers["Content-Length"])
        self.members = self._directory()

    def _range(self, start: int, length: int) -> bytes:
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{start + length - 1}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status != 206:
                raise BuildError("сервер не отдаёт архив по частям")
            return r.read()

    def _directory(self) -> dict[str, tuple[int, int, int, int]]:
        tail = self._range(max(0, self.size - 65536), min(65536, self.size))
        pos = tail.rfind(b"PK\x05\x06")
        if pos < 0:
            raise BuildError("архив шаблонов повреждён (нет оглавления)")
        _, _, _, _, count, cd_size, cd_offset, _ = struct.unpack("<4sHHHHIIH", tail[pos:pos + 22])
        if cd_offset == 0xFFFFFFFF:
            raise BuildError("архив шаблонов в формате ZIP64 не поддерживается")
        cd = self._range(cd_offset, cd_size)
        members, i = {}, 0
        for _ in range(count):
            (_sig, _v1, _v2, _flags, method, _t, _d, _crc, csize, usize, nlen, xlen, clen, _dn, _ia, _ea,
             offset) = struct.unpack("<IHHHHHHIIIHHHHHII", cd[i:i + 46])
            name = cd[i + 46:i + 46 + nlen].decode("utf-8", "replace")
            members[name] = (method, csize, usize, offset)
            i += 46 + nlen + xlen + clen
        return members

    def extract(self, name: str, dest: Path, progress: Callable[[int, int], None] | None = None) -> None:
        method, csize, usize, offset = self.members[name]
        head = self._range(offset, 30)
        nlen, xlen = struct.unpack("<HH", head[26:30])
        start = offset + 30 + nlen + xlen
        dec = zlib.decompressobj(-15) if method == 8 else None
        tmp = dest.with_suffix(dest.suffix + ".part")
        done, chunk = 0, 4 << 20
        with open(tmp, "wb") as f:
            while done < csize:
                n = min(chunk, csize - done)
                data = self._range(start + done, n)
                f.write(dec.decompress(data) if dec else data)
                done += n
                if progress:
                    progress(done, csize)
            if dec:
                f.write(dec.flush())
        if tmp.stat().st_size != usize:
            tmp.unlink()
            raise BuildError(f"файл {name} скачался не полностью")
        tmp.replace(dest)


def fetch_templates(ver: str, target: str, log: Log, progress: Callable[[int, int], None] | None = None) -> None:
    """Скачивает только нужные для цели шаблоны (а не весь архив на 1,3 ГБ)."""
    need = missing_templates(ver, target)
    if not need:
        return
    url = templates_url(ver)
    log(f"Читаю оглавление шаблонов Godot {template_version(ver)}…")
    z = RangeZip(url)
    d = templates_dir(ver)
    d.mkdir(parents=True, exist_ok=True)
    names = [f"templates/{n}" for n in need]
    absent = [n for n in names if n not in z.members]
    if absent:
        raise BuildError(f"в архиве шаблонов нет: {', '.join(absent)}")
    total = sum(z.members[n][1] for n in names)
    log(f"Скачиваю {len(names)} файла(ов), {total / 2**20:.0f} МБ из {z.size / 2**20:.0f} МБ архива")
    base = 0
    for n in names:
        z.extract(n, d / n.split("/", 1)[1], (lambda done, _s, b=base: progress(b + done, total)) if progress else None)
        base += z.members[n][1]
        log(f"  ✔ {n.split('/', 1)[1]}")
    if "templates/version.txt" in z.members and not (d / "version.txt").exists():
        z.extract("templates/version.txt", d / "version.txt")
    if sys.platform != "win32":
        for n in need:
            if not n.endswith((".exe", ".apk")):
                (d / n).chmod(0o755)


# ---------------------------------------------------------------- Android

@dataclass
class AndroidSetup:
    sdk: str
    java: str
    keystore: str
    problems: list[str]


def _settings_file(ver: str) -> Path:
    major_minor = ".".join(template_version(ver).split(".")[:2])
    return godot_config_dir() / f"editor_settings-{major_minor}.tres"


def _guess_sdk() -> str:
    cands = [os.environ.get("ANDROID_HOME", ""), os.environ.get("ANDROID_SDK_ROOT", "")]
    if sys.platform == "win32":
        cands.append(str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"))
    elif sys.platform == "darwin":
        cands.append(str(Path.home() / "Library/Android/sdk"))
    else:
        cands.append(str(Path.home() / "Android/Sdk"))
    return next((c for c in cands if c and (Path(c) / "platform-tools").is_dir()), "")


def _guess_java() -> str:
    cands = [os.environ.get("JAVA_HOME", "")]
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
            cands.append(str(Path(base) / "Android" / "Android Studio" / "jbr"))
            cands += [str(d) for d in sorted((Path(base) / "Eclipse Adoptium").glob("jdk-17*"))] \
                if (Path(base) / "Eclipse Adoptium").is_dir() else []
    elif sys.platform == "darwin":
        cands.append("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
    else:
        cands += [str(Path.home() / "android-studio/jbr"), "/opt/android-studio/jbr"]
    exe = "java.exe" if sys.platform == "win32" else "java"
    return next((c for c in cands if c and (Path(c) / "bin" / exe).is_file()), "")


def android_setup(ver: str, sdk: str = "", java: str = "") -> AndroidSetup:
    """Пути Android SDK и JDK: заданные явно → из настроек Godot → найденные в обычных местах."""
    f = _settings_file(ver)
    text = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""

    def get(key):
        m = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', text, re.M)
        return m.group(1) if m else ""
    sdk = sdk or get("export/android/android_sdk_path") or _guess_sdk()
    java = java or get("export/android/java_sdk_path") or _guess_java()
    problems = []
    if not sdk or not Path(sdk).is_dir():
        problems.append("не найден Android SDK")
    elif not (Path(sdk) / "build-tools").is_dir():
        problems.append("в Android SDK нет build-tools (поставь их в Android Studio → SDK Manager)")
    if not java or not Path(java).is_dir():
        problems.append("не найден JDK (Java 17+)")
    return AndroidSetup(sdk, java, get("export/android/debug_keystore"), problems)


def save_android_paths(ver: str, sdk: str, java: str) -> None:
    """Записывает пути в настройки Godot — так же, как если бы их указали в Editor Settings."""
    f = _settings_file(ver)
    f.parent.mkdir(parents=True, exist_ok=True)
    text = f.read_text(encoding="utf-8") if f.exists() else '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
    for key, val in (("export/android/android_sdk_path", sdk), ("export/android/java_sdk_path", java)):
        line = f'{key} = "{Path(val).as_posix()}"'
        pat = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        text = pat.sub(lambda _m: line, text) if pat.search(text) else text.rstrip("\n") + "\n" + line + "\n"
    f.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- сборка

def _version_code(version: str) -> int:
    nums = [int(x) for x in re.findall(r"\d+", version)[:3]] + [0, 0, 0]
    return max(1, nums[0] * 10000 + nums[1] * 100 + nums[2])


def _package(pid: str) -> str:
    name = re.sub(r"[^a-z0-9]", "", pid.lower()) or "game"
    return f"org.vnconstructor.{name if name[0].isalpha() else 'g' + name}"


def stage(project_root: Path, staging: Path, log: Log) -> dict:
    """Сборочная копия рантайма с упакованной игрой. Кэш импорта Godot (.godot) между сборками сохраняется."""
    p = read_json(project_root / "project.json")
    staging.mkdir(parents=True, exist_ok=True)
    keep = {".godot"}
    for item in staging.iterdir():
        if item.name not in keep:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    for item in RUNTIME.iterdir():
        if item.name in (".godot", "tests", "game", "export_presets.cfg") or item.name.endswith(".import"):
            continue
        dst = staging / item.name
        shutil.copytree(item, dst, ignore=shutil.ignore_patterns("*.import")) if item.is_dir() else shutil.copy2(item, dst)
    n = pack(project_root, staging / "game")
    log(f"Игра упакована: файлов {n}")

    title = p.get("title", "Game").replace('"', "'")
    res = p.get("resolution", {"width": 1280, "height": 720})
    cfg = (staging / "project.godot").read_text(encoding="utf-8")
    cfg = re.sub(r'config/name="[^"]*"', f'config/name="{title}"', cfg)
    cfg = cfg.replace('config/features=', f'config/version="{p.get("version", "0.1.0")}"\nconfig/features=')
    cfg = re.sub(r"window/size/viewport_width=\d+", f"window/size/viewport_width={res['width']}", cfg)
    cfg = re.sub(r"window/size/viewport_height=\d+", f"window/size/viewport_height={res['height']}", cfg)
    (staging / "project.godot").write_text(cfg, encoding="utf-8")

    common = ('runnable=true\ndedicated_server=false\ncustom_features=""\nexport_filter="all_resources"\n'
              'include_filter="game/*.json"\nexclude_filter=""\nexport_path=""\nencryption_include_filters=""\n'
              'encryption_exclude_filters=""\nencrypt_pck=false\nencrypt_directory=false\nscript_export_mode=2\n')
    presets = (
        f'[preset.0]\n\nname="Windows Desktop"\nplatform="Windows Desktop"\n{common}\n[preset.0.options]\n\n'
        f'binary_format/embed_pck=true\napplication/modify_resources=false\n'
        f'application/product_name="{title}"\napplication/file_description="{title}"\n\n'
        f'[preset.1]\n\nname="Linux"\nplatform="Linux"\n{common}\n[preset.1.options]\n\nbinary_format/embed_pck=true\n\n'
        f'[preset.2]\n\nname="Android"\nplatform="Android"\n{common}\n[preset.2.options]\n\n'
        f'gradle_build/use_gradle_build=false\npackage/unique_name="{_package(p.get("id", "game"))}"\n'
        f'package/name="{title}"\npackage/signed=true\nscreen/immersive_mode=true\n'
        f'version/code={_version_code(p.get("version", "0.1.0"))}\nversion/name="{p.get("version", "0.1.0")}"\n'
    )
    (staging / "export_presets.cfg").write_text(presets, encoding="utf-8")
    return p


ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOISE = ("Godot Engine", "ALSA", "WARNING: All audio drivers", "at: ", "ERROR: Condition \"status < 0\"")


def console_exe(godot: str) -> str:
    """В Windows обычный Godot.exe не пишет в консоль — берём соседний *_console.exe, если он есть."""
    p = Path(godot)
    c = p.with_name(p.stem + "_console" + p.suffix)
    return str(c) if sys.platform == "win32" and c.is_file() else godot


def _run(cmd: list[str], log: Log, env=None) -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, creationflags=flags)
    shown = set()
    for line in proc.stdout:
        line = ANSI.sub("", line).strip()
        if not line or line.startswith(NOISE):
            continue
        m = re.match(r"\[\s*\d+% \]\s*(\w+)", line)
        if m:                                   # «[ 42% ] savepack | Storing File…» — один раз на этап
            if m.group(1) not in shown:
                shown.add(m.group(1))
                log(f"  godot: {m.group(1)}…")
            continue
        if "[ DONE ]" in line:
            continue
        log("  godot> " + line)
    return proc.wait()


def build(project_root: str | Path, target: str, out_dir: str | Path, godot: str, debug: bool, log: Log,
          android_sdk: str = "", android_java: str = "") -> Path:
    """Собирает игру и возвращает путь к файлу. BuildError — с понятной причиной."""
    project_root, out_dir = Path(project_root).resolve(), Path(out_dir).resolve()
    t = TARGETS[target]
    log("1/4 Проверка проекта…")
    errors = [i for i in validate_project(project_root) if i.severity == "error"]
    if errors:
        raise BuildError("в проекте есть ошибки:\n" + "\n".join(f"• {e}" for e in errors[:15]))
    godot = console_exe(godot)
    ver = godot_version(godot)
    missing = missing_templates(ver, target)
    need = t["templates"][1] if debug else t["templates"][0]
    if need in missing:
        raise BuildError(f"нет шаблона экспорта {need} для Godot {template_version(ver)} — скачай шаблоны")
    env = dict(os.environ)
    if target == "android":
        a = android_setup(ver, android_sdk, android_java)
        if a.problems:
            raise BuildError("Android: " + "; ".join(a.problems) + ".\nПроще всего поставить Android Studio "
                             "(https://developer.android.com/studio) — SDK и Java придут вместе с ней, "
                             "после этого сборка найдёт их сама. Или укажи пути в окне сборки.")
        save_android_paths(ver, a.sdk, a.java)
        env["ANDROID_HOME"], env["JAVA_HOME"] = a.sdk, a.java
        if not debug:
            # Своего ключа пока нет — релиз подписывается отладочным ключом Godot (для Google Play понадобится свой)
            ks = a.keystore or str(godot_data_dir() / "keystores" / "debug.keystore")
            env.setdefault("GODOT_ANDROID_KEYSTORE_RELEASE_PATH", ks)
            env.setdefault("GODOT_ANDROID_KEYSTORE_RELEASE_USER", "androiddebugkey")
            env.setdefault("GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD", "android")
            log("  APK подписывается отладочным ключом: ставить на свои устройства можно, в Google Play — нет")

    staging = project_root / "build" / ".staging"
    log("2/4 Подготовка сборочной копии…")
    p = stage(project_root, staging, log)
    log("3/4 Импорт ресурсов в Godot (первый раз дольше)…")
    if _run([godot, "--headless", "--path", str(staging), "--import"], log, env) != 0:
        log("  (импорт завершился с предупреждениями — продолжаю)")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = (slug(p.get("title", "game")) or "game") + ("-debug" if debug and target == "android" else "")
    out = out_dir / f"{name}{t['ext']}"
    if out.exists():
        out.unlink()
    log(f"4/4 Экспорт: {t['title']} → {out}")
    code = _run([godot, "--headless", "--path", str(staging), "--export-debug" if debug else "--export-release",
                 t["preset"], str(out)], log, env)
    if code != 0 or not out.is_file():
        raise BuildError(f"Godot не собрал игру (код {code}). Подробности — в журнале выше.")
    if target == "linux":
        out.chmod(0o755)
    log(f"Готово: {out.name}, {out.stat().st_size / 2**20:.1f} МБ")
    return out
