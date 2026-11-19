"""
Рисует ассеты-заглушки для samples/demo: два фона, три эмоции Анны, эмбиент и скрип.
Нужен Pillow. Повторный запуск перезаписывает файлы одинаково (фиксированный seed).

    python tools/make_demo_assets.py
"""
import math
import random
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "samples" / "demo" / "assets"
W, H = 1280, 720


def gradient(top, bottom):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def bg_hall():
    img = gradient((52, 44, 40), (22, 18, 16))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 520, W, H], fill=(36, 28, 22))                     # пол
    for x in range(0, W, 80):
        d.line([(x, 520), (x - 160, H)], fill=(44, 34, 27), width=2)
    d.rectangle([540, 170, 740, 520], fill=(28, 20, 16), outline=(70, 56, 44), width=6)   # дверь
    d.ellipse([705, 340, 719, 354], fill=(150, 120, 70))
    d.rectangle([150, 160, 330, 380], fill=(60, 72, 92), outline=(70, 56, 44), width=8)    # окно
    d.line([(240, 160), (240, 380)], fill=(70, 56, 44), width=6)
    d.line([(150, 270), (330, 270)], fill=(70, 56, 44), width=6)
    d.rectangle([900, 230, 1080, 330], outline=(90, 74, 50), width=5)   # картина
    return img.filter(ImageFilter.GaussianBlur(1.2))


def bg_cellar():
    img = gradient((18, 22, 30), (6, 7, 10))
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    for row in range(0, 520, 40):                                         # кладка
        off = 0 if (row // 40) % 2 else 50
        for x in range(-100 + off, W, 100):
            shade = rnd.randint(22, 34)
            d.rectangle([x + 2, row + 2, x + 98, row + 38], fill=(shade, shade + 2, shade + 6))
    for i in range(7):                                                    # ступени
        y = 520 + i * 28
        d.rectangle([40 + i * 30, y, 380, y + 26], fill=(40 - i * 3, 38 - i * 3, 36 - i * 3))
    d.polygon([(980, 260), (1060, 250), (1080, 480), (990, 500)], fill=(14, 14, 18))  # «тень»
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([300, 120, 980, 680], fill=110)          # свет фонаря
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    light = Image.new("RGB", (W, H), (120, 100, 60))
    return Image.composite(light, img, glow).filter(ImageFilter.GaussianBlur(1.0))


def anna(expression):
    w, h = 420, 660
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    coat, skin, hair, ink = (96, 70, 120, 255), (232, 205, 186, 255), (70, 44, 34, 255), (40, 30, 30, 255)
    d.polygon([(70, h), (110, 300), (310, 300), (350, h)], fill=coat)   # плащ
    d.rectangle([185, 250, 235, 310], fill=skin)                          # шея
    d.ellipse([120, 60, 300, 270], fill=hair)                             # волосы
    d.ellipse([140, 90, 280, 260], fill=skin)                             # лицо
    d.rectangle([128, 100, 150, 330], fill=hair)
    d.rectangle([270, 100, 292, 330], fill=hair)
    ey = 165
    if expression == "scared":
        for cx in (183, 237):
            d.ellipse([cx - 12, ey - 12, cx + 12, ey + 12], fill=(255, 255, 255, 255), outline=ink, width=2)
            d.ellipse([cx - 4, ey - 4, cx + 4, ey + 4], fill=ink)
        d.ellipse([195, 212, 225, 240], fill=(120, 50, 60, 255))
    else:
        for cx in (183, 237):
            d.ellipse([cx - 9, ey - 6, cx + 9, ey + 6], fill=ink)
        if expression == "sad":
            d.line([(170, 152), (195, 144)], fill=ink, width=3)   # внутренние концы бровей вверх
            d.line([(250, 152), (225, 144)], fill=ink, width=3)
            d.arc([190, 215, 230, 245], 200, 340, fill=ink, width=3)
        else:
            d.line([(170, 148), (195, 146)], fill=ink, width=3)
            d.line([(225, 146), (250, 148)], fill=ink, width=3)
            d.arc([190, 200, 230, 230], 20, 160, fill=ink, width=3)
    return img


def write_wav(path, samples, rate=22050):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32000)) for s in samples))


def ambient(rate=22050, seconds=6.0):
    rnd = random.Random(1)
    out, lp = [], 0.0
    n = int(rate * seconds)
    for i in range(n):
        t = i / rate
        lp += 0.02 * (rnd.uniform(-1, 1) - lp)                            # «ветер»
        hum = 0.12 * math.sin(2 * math.pi * 55 * t) + 0.06 * math.sin(2 * math.pi * 82.5 * t)
        env = min(1.0, t / 0.5, (seconds - t) / 0.5)                       # без щелчков на стыке
        out.append((hum + 1.6 * lp) * env * 0.6)
    return out


def creak(rate=22050, seconds=0.6):
    out, phase = [], 0.0
    for i in range(int(rate * seconds)):
        t = i / rate
        f = 180 + 260 * t + 40 * math.sin(2 * math.pi * 9 * t)
        phase += 2 * math.pi * f / rate
        env = math.sin(math.pi * t / seconds) ** 2
        out.append(0.5 * env * (math.sin(phase) + 0.4 * math.sin(3 * phase)) * (0.8 + 0.2 * math.sin(2 * math.pi * 31 * t)))
    return out


def main():
    for sub in ("bg", "sprites", "audio"):
        (ASSETS / sub).mkdir(parents=True, exist_ok=True)
    bg_hall().save(ASSETS / "bg" / "hall.png", optimize=True)
    bg_cellar().save(ASSETS / "bg" / "cellar.png", optimize=True)
    for e in ("neutral", "sad", "scared"):
        anna(e).save(ASSETS / "sprites" / f"anna_{e}.png", optimize=True)
    write_wav(ASSETS / "audio" / "ambient.wav", ambient())
    write_wav(ASSETS / "audio" / "creak.wav", creak())
    print("Ассеты демо записаны в", ASSETS.relative_to(ROOT))


if __name__ == "__main__":
    main()
