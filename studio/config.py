"""Global configuration for Trade Autopsy Video Studio.

Everything is local and free by default:
  * Skia for graphics (no browser, no GPU)
  * Edge TTS for the voice (free, needs internet) or Piper (fully offline)
  * numpy for the soundtrack
  * FFmpeg for encoding
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
DATA = Path(os.environ.get("DATA_DIR") or (ROOT / "data"))
PROJECTS = DATA / "projects"
CACHE = DATA / "cache"
UPLOADS = DATA / "uploads"
WEB = ROOT / "web"

for p in (DATA, PROJECTS, CACHE, UPLOADS):
    p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- canvas
W, H = 1080, 1920
FPS = 30
SR = 48000

# ---------------------------------------------------------------- ffmpeg
def find_ffmpeg() -> str:
    candidates = []
    env = os.environ.get("FFMPEG")
    if env:
        candidates.append(env)
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    candidates += [
        r"C:\OSPanel\addons\FFMpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return "ffmpeg"


FFMPEG = find_ffmpeg()

# Piper is optional. eSpeak inside Piper cannot load its data from a path with
# Cyrillic characters, so we copy the runtime once into an ASCII-local folder.
LEGACY_PIPER_DIR = Path(os.environ.get("PIPER_SOURCE") or (ROOT.parent / "_work" / "piper"))
PIPER_DIR = Path(os.environ.get("PIPER_DIR") or (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TradeAutopsy" / "piper"
))
PIPER_EXE = Path(os.environ.get("PIPER_EXE")) if os.environ.get("PIPER_EXE") else (
    PIPER_DIR / "piper" / "piper.exe"
    if (PIPER_DIR / "piper" / "piper.exe").exists()
    else PIPER_DIR / "piper" / "piper"
)


def ensure_piper() -> bool:
    """Copy the optional Piper runtime/models to an ASCII path on first use."""
    models = ["ru_RU-dmitri-medium.onnx", "ru_RU-denis-medium.onnx"]
    if PIPER_EXE.exists() and any((PIPER_DIR / m).exists() for m in models):
        return True
    src = LEGACY_PIPER_DIR
    if not (src / "piper" / "piper.exe").exists():
        return False
    try:
        PIPER_DIR.mkdir(parents=True, exist_ok=True)
        if not (PIPER_DIR / "piper" / "piper.exe").exists():
            shutil.copytree(src / "piper", PIPER_DIR / "piper", dirs_exist_ok=True)
        for f in src.glob("*.onnx"):
            shutil.copy2(f, PIPER_DIR / f.name)
        for f in src.glob("*.onnx.json"):
            shutil.copy2(f, PIPER_DIR / f.name)
    except Exception:
        return False
    return PIPER_EXE.exists() and any((PIPER_DIR / m).exists() for m in models)

# ---------------------------------------------------------------- styles
STYLES: dict[str, dict] = {
    "tech_blue": {
        "name": "Tech Blue",
        "desc": "Тёмно-синий градиент, голубое свечение. Как в референсе.",
        "bg": [(5, 7, 16), (10, 13, 32), (7, 8, 22), (3, 4, 11)],
        "accent": (58, 132, 255),
        "accent2": (168, 92, 250),
        "highlight": (40, 224, 255),
        "text": (245, 248, 255),
        "muted": (142, 158, 196),
        "card": (16, 22, 46),
        "good": (52, 225, 160),
        "warn": (255, 190, 92),
        "bad": (255, 92, 122),
        "title_font": "black",
        "mono": "mono",
    },
    "trade_lime": {
        "name": "Trade Lime",
        "desc": "Фирменный стиль Trade Autopsy: почти чёрный и лайм #c6ff3d.",
        "bg": [(5, 8, 5), (11, 15, 9), (7, 10, 6), (3, 4, 3)],
        "accent": (198, 255, 61),
        "accent2": (110, 231, 168),
        "highlight": (225, 255, 150),
        "text": (244, 248, 237),
        "muted": (151, 164, 140),
        "card": (17, 22, 14),
        "good": (110, 231, 168),
        "warn": (255, 198, 86),
        "bad": (255, 107, 107),
        "title_font": "black",
        "mono": "mono",
    },
    "violet": {
        "name": "Violet AI",
        "desc": "Фиолетово-розовый неон для AI и крипто-тем.",
        "bg": [(8, 5, 17), (15, 9, 32), (10, 6, 22), (4, 3, 10)],
        "accent": (167, 105, 255),
        "accent2": (255, 86, 190),
        "highlight": (110, 205, 255),
        "text": (247, 245, 255),
        "muted": (163, 153, 190),
        "card": (23, 16, 43),
        "good": (80, 230, 180),
        "warn": (255, 190, 92),
        "bad": (255, 92, 140),
        "title_font": "black",
        "mono": "mono",
    },
    "terminal": {
        "name": "Terminal",
        "desc": "Монохромный трейдинг-терминал с зелёным неоном.",
        "bg": [(6, 8, 8), (10, 14, 13), (7, 10, 9), (2, 4, 4)],
        "accent": (120, 255, 170),
        "accent2": (198, 255, 61),
        "highlight": (255, 214, 102),
        "text": (238, 247, 240),
        "muted": (140, 160, 150),
        "card": (13, 20, 17),
        "good": (120, 255, 170),
        "warn": (255, 206, 102),
        "bad": (255, 100, 100),
        "title_font": "monobold",
        "mono": "mono",
    },
}

# ---------------------------------------------------------------- voices
EDGE_VOICES = [
    {
        "id": "ru-RU-DmitryNeural",
        "name": "Дмитрий",
        "desc": "Молодой мужской · энергичный",
        "provider": "edge",
        "gender": "male",
    },
    {
        "id": "ru-RU-SvetlanaNeural",
        "name": "Светлана",
        "desc": "Женский · спокойный",
        "provider": "edge",
        "gender": "female",
    },
]

PIPER_VOICES = [
    {
        "id": "ru_RU-dmitri-medium",
        "name": "Дмитрий (офлайн)",
        "desc": "Мужской · естественный · CC0",
        "provider": "piper",
        "gender": "male",
        "model": "ru_RU-dmitri-medium.onnx",
    },
    {
        "id": "ru_RU-denis-medium",
        "name": "Денис (офлайн)",
        "desc": "Мужской · спокойный · CC0",
        "provider": "piper",
        "gender": "male",
        "model": "ru_RU-denis-medium.onnx",
    },
]

PROVIDERS = [
    {
        "id": "edge",
        "name": "Edge TTS",
        "free": True,
        "needs_key": False,
        "note": "Бесплатно, естественные русские голоса. Нужен интернет.",
    },
    {
        "id": "piper",
        "name": "Piper (локально)",
        "free": True,
        "needs_key": False,
        "note": "Полностью офлайн, голоса лежат в папке _work/piper.",
    },
    {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "free": False,
        "needs_key": True,
        "note": "Свой API-ключ. Платный, но самое высокое качество.",
    },
]

MUSIC_PRESETS = [
    {"id": "tech", "name": "Tech / Ambient", "desc": "Мягкий пульс, синты, без резких битов"},
    {"id": "ambient", "name": "Deep Ambient", "desc": "Спокойный фон для вдумчивого разбора"},
    {"id": "drive", "name": "Drive", "desc": "Быстрее и энергичнее для хуков"},
    {"id": "none", "name": "Без музыки", "desc": "Только голос и звуковые акценты"},
]

DURATIONS = [
    {"id": "auto", "name": "Авто", "desc": "По длине сценария"},
    {"id": "45", "name": "45 сек", "desc": "Короткий хук"},
    {"id": "60", "name": "60 сек", "desc": "Оптимально для TikTok"},
    {"id": "75", "name": "75 сек", "desc": "Подробный разбор"},
]

DEFAULT_SETTINGS: dict = {
    "provider": "piper",
    "voice": "ru_RU-dmitri-medium",
    "rate": 0,
    "auto_rate": True,
    "pitch": -1,
    "music": True,
    "music_preset": "tech",
    "music_gain": 0.22,
    "sfx": True,
    "custom_music": None,
    "style": "tech_blue",
    "quality": "quality",
    "duration": "60",
    "brand": "TRADE AUTOPSY",
    "cta_url": "trade-autopsy.dgchh0718.workers.dev",
    "cta_label": "Открыть журнал",
    "disclaimer": "Не является инвестиционной рекомендацией",
    "eleven_key": "",
    "eleven_voice": "",
}

DEFAULT_SCRIPT = """Ты снова закрыл месяц в минус? И опять не понимаешь, где именно потерял деньги.
Проблема не в стратегии. Ты просто не видишь своих ошибок.
Trade Autopsy — это журнал сделок, который разбирает твою торговлю как врач.
Ты вносишь P&L, сетап и таймфрейм. Или загружаешь отчёт брокера.
Дальше система показывает equity, просадку, winrate и R-мультипликатор.
Видишь, какие сетапы реально работают, а какие съедают депозит.
Детектор переторговки ловит тильт до того, как он заберёт ещё одну неделю.
Проп-режим следит за лимитами челленджа.
Раз в неделю — короткий отчёт: что сработало, что нарушил, что исправить.
Бесплатно можно вести журнал и смотреть базовую статистику. Без карты.
Premium — 490 рублей в месяц. Год — 4 884, это 407 в месяц и минус 17 процентов.
Плюс закрытый клуб: разборы рынка по SMC два-три раза в неделю.
Первые семь дней Premium — бесплатно.
Начни вести журнал сегодня. Ссылка в профиле."""

DEFAULT_TITLE = "ГДЕ ТЫ ТЕРЕШЬ ДЕНЬГИ"

TYPE_LABELS = {
    "hook": "Хук",
    "statement": "Тезис",
    "checklist": "Список",
    "stat": "Цифры",
    "chart": "График",
    "dashboard": "Журнал",
    "terminal": "Терминал",
    "diagram": "Схема",
    "compare": "Сравнение",
    "notification": "Уведомление",
    "bars": "Диаграмма",
    "timeline": "Шаги",
    "quote": "Цитата",
    "cta": "Призыв",
    "outro": "Финал",
}
