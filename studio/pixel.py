"""Pixel-art renderer for the second Video Studio format.

The visuals are drawn on a small 270x480 canvas (pixel units) and upscaled
with nearest-neighbour sampling. The character is a reusable 26-frame sprite
sheet generated once from the project's character settings: idle, blink,
talk, walk, point, wave, happy, sad, think, scared, show, victory and error
poses with alternating gesture frames. Scene clips are silent; the existing
audio mixer provides the voice + music track.
"""
from __future__ import annotations

import base64
import copy
import io
import math
import shutil
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import skia

from . import config, gfx, render

FRAME_W = 40
FRAME_H = 60
SHEET_FRAMES = 26
SW, SH = 270, 480
SCALE = 4

DEFAULT_CHARACTER = {
    "type": "human",
    "gender": "male",
    "skin": "#f2c9a0",
    "hair": "#2b1b12",
    "shirt": "#3a84ff",
    "pants": "#1b2430",
    "shoes": "#0e1116",
    "eye_color": "#161a1d",
    "hair_style": "short",
    "accessory": "none",
    "expression": "neutral",
    "height": "normal",
    "proportions": "normal",
    "pixel_style": "16bit",
    "custom_image": "",
}

ICONS = {
    "coin": ("0011100", "0111110", "1110111", "1101011", "1110111", "0111110", "0011100"),
    "arrow_up": ("0001000", "0011100", "0111110", "1111111", "0001000", "0001000", "0001000"),
    "arrow_down": ("0001000", "0001000", "0001000", "1111111", "0111110", "0011100", "0001000"),
    "check": ("0000001", "0000011", "0000110", "1001100", "1111000", "0110000", "0000000"),
    "cross": ("1000001", "1100011", "0110110", "0011100", "0110110", "1100011", "1000001"),
    "star": ("0001000", "0011100", "1111111", "0111110", "0011100", "0110110", "0100010"),
    "heart": ("0110110", "1111111", "1111111", "1111111", "0111110", "0011100", "0001000"),
    "question": ("0011100", "0110110", "0000110", "0001100", "0011000", "0000000", "0011000"),
    "wave": ("0010000", "0111000", "0010100", "0010100", "0011000", "0110000", "0000000"),
}

VISUALS = ("room", "chart", "phone", "board", "terminal", "none")
ANIMATIONS = (
    "auto", "idle", "talk", "explain", "point", "surprise", "happy", "sad",
    "think", "scared", "show", "victory", "error",
)

TOPIC_KEYWORDS = {
    "trading": (
        "сделк", "сделок", "сделка", "сделки", "торгов", "журнал", "трейд",
        "прибыл", "убыт", "депозит", "форекс", "крипт", "битко", "btc",
        "pnl", "просадк", "стоп-лосс", "тейк-профит", "лонг", "шорт",
        "свеч", "бирж", "трейдер", "минус", "профит", "позици",
    ),
    "fitness": (
        "трениров", "фитнес", "зал", "мышц", "жир", "похуд", "калор",
        "белок", "упражн", "спорт", "бег", "штанг", "пресс", "отжим",
        "присед", "гантел", "кардио", "растяж",
    ),
    "cooking": (
        "рецепт", "готов", "кухн", "блюд", "ингредиент", "духовк", "суп",
        "мясо", "тесто", "завтрак", "обед", "ужин", "салат", "соус",
        "выпеч", "специ", "порци",
    ),
    "realestate": (
        "недвиж", "квартир", "ипотек", "аренд", "новострой", "риелтор",
        "участок", "жилье", "недвижим", "дом", "коттедж", "планировк",
    ),
    "education": (
        "урок", "школ", "учеб", "курс", "экзамен", "студент", "лекц",
        "знани", "обучен", "книг", "конспект", "задач", "репетитор",
    ),
    "tech": (
        "код", "программ", "разработ", "сервер", "api", "нейросет",
        "алгоритм", "сайт", "приложен", "баг", "данн", "ит-",
    ),
    "health": (
        "здоров", "врач", "симптом", "лечен", "болезн", "клиник",
        "давлен", "сердц", "таблет", "иммунитет", "пульс", "сон",
    ),
    "travel": (
        "путешеств", "билет", "отел", "тур", "страна", "самолет",
        "чемодан", "виза", "экскурс", "поездк", "рейс", "курорт",
    ),
    "business": (
        "бизнес", "маркет", "продаж", "клиент", "воронк", "бренд",
        "стартап", "стратег", "продукт", "конверси", "выручк", "лид",
    ),
}

COLOR_KEYS = {
    "accent": ("ACCENT",),
    "accent2": ("ACCENT2",),
    "green": ("GREEN",),
    "bad": ("BAD",),
    "highlight": ("HIGHLIGHT",),
}

TOPIC_PROFILES = {
    "trading": {
        "tint": (64, 140, 255), "chart": "candles", "prop": "trading", "set": "trading",
        "visual_by_kind": {
            "hook": "chart", "problem": "board", "insight": "room",
            "solution": "terminal", "cta": "room", "chart": "chart",
            "stat": "chart", "bars": "chart", "dashboard": "terminal",
            "terminal": "terminal", "checklist": "board",
            "timeline": "board", "compare": "board", "quote": "room",
            "notification": "phone", "diagram": "phone",
        },
        "cards": [("СДЕЛКИ", "12", "accent"), ("ВИНРЕЙТ", "58%", "green")],
        "cards_by_kind": {
            "hook": [("МИНУС", "-$420", "bad"), ("ПРИЧИНА", "?", "accent")],
            "problem": [("ОШИБКИ", "3", "bad"), ("РИСК", "3 : 1", "accent")],
            "insight": [("СДЕЛКИ", "12", "accent"), ("ВИНРЕЙТ", "58%", "green")],
            "solution": [("PNL", "+$1 240", "green"), ("РИСК", "1 : 3", "accent")],
            "cta": [("ЖУРНАЛ", "7 ДНЕЙ", "accent"), ("СТАРТ", "СЕГОДНЯ", "green")],
        },
        "ticker": ("BTC +2.4%    ETH -1.1%    S&P +0.6%    EUR/USD 1.08    "
                   "GOLD +0.3%    NASDAQ -0.4%"),
    },
    "fitness": {
        "tint": (255, 150, 70), "chart": "progress", "prop": "fitness", "set": "gym",
        "visual_by_kind": {
            "hook": "room", "problem": "chart", "insight": "chart",
            "solution": "chart", "cta": "room", "chart": "chart",
            "stat": "chart", "bars": "chart", "checklist": "board",
        },
        "cards": [("ТРЕНИРОВКИ", "4", "accent"), ("ПРОГРЕСС", "+18%", "green")],
        "cards_by_kind": {
            "hook": [("ЦЕЛЬ", "-5 КГ", "accent"), ("СРОК", "8 НЕДЕЛЬ", "accent2")],
            "problem": [("СРЫВЫ", "3", "bad"), ("МОТИВАЦИЯ", "12%", "accent")],
            "insight": [("ТРЕНИРОВКИ", "4", "accent"), ("ПУЛЬС", "128", "green")],
            "solution": [("ПРОГРЕСС", "+18%", "green"), ("СИЛА", "+24%", "accent")],
            "cta": [("СТАРТ", "СЕГОДНЯ", "accent"), ("ПЛАН", "8 НЕДЕЛЬ", "green")],
        },
        "ticker": "ШАГИ 8 240    ПУЛЬС 128    КАЛОРИИ 420    СОН 7.5 Ч",
    },
    "cooking": {
        "tint": (255, 182, 92), "chart": "timer", "prop": "cooking", "set": "kitchen",
        "visual_by_kind": {
            "hook": "room", "problem": "chart", "insight": "chart",
            "solution": "chart", "cta": "room",
        },
        "cards": [("РЕЦЕПТ", "3", "accent"), ("ВРЕМЯ", "25 МИН", "accent2")],
        "cards_by_kind": {
            "hook": [("БЛЮДО", "3", "accent"), ("ВРЕМЯ", "25 МИН", "accent2")],
            "problem": [("ОШИБКИ", "2", "bad"), ("ВКУС", "?", "accent")],
            "insight": [("ПОРЦИИ", "4", "accent"), ("ККАЛ", "420", "green")],
            "cta": [("ГОТОВИТЬ", "СЕЙЧАС", "accent"), ("ПОРЦИИ", "4", "green")],
        },
        "ticker": "БЕЛКИ 30    ЖИРЫ 12    УГЛЕВОДЫ 45    ККАЛ 420",
    },
    "realestate": {
        "tint": (60, 200, 160), "chart": "line", "prop": "realestate", "set": "apartment",
        "visual_by_kind": {
            "hook": "room", "problem": "chart", "insight": "chart",
            "solution": "chart", "cta": "room",
        },
        "cards": [("ОБЪЕКТЫ", "7", "accent"), ("ДОХОД", "8%", "green")],
        "cards_by_kind": {
            "hook": [("ЦЕНА", "$240K", "accent"), ("СТАВКА", "6.2%", "accent2")],
            "problem": [("РИСКИ", "3", "bad"), ("ЛИКВИДНОСТЬ", "?", "accent")],
            "insight": [("АРЕНДА", "$1 200", "accent"), ("ДОХОД", "8%", "green")],
            "cta": [("СМОТРЕТЬ", "СЕЙЧАС", "accent"), ("ОБЪЕКТЫ", "7", "green")],
        },
        "ticker": "СТАВКА 6.2%    ЦЕНА $240K    АРЕНДА $1 200    ДОХОД 8%",
    },
    "education": {
        "tint": (255, 206, 92), "chart": "progress", "prop": "education", "set": "classroom",
        "visual_by_kind": {
            "hook": "board", "problem": "board", "insight": "chart",
            "solution": "board", "cta": "room",
        },
        "cards": [("УРОК", "3", "accent"), ("ПРОГРЕСС", "68%", "green")],
        "cards_by_kind": {
            "hook": [("ТЕМА", "3", "accent"), ("УРОВЕНЬ", "A1", "accent2")],
            "problem": [("ОШИБКИ", "4", "bad"), ("ПРОГРЕСС", "32%", "accent")],
            "insight": [("ЗАДАЧИ", "12", "accent"), ("ПРОГРЕСС", "68%", "green")],
            "cta": [("УЧИТЬСЯ", "СЕГОДНЯ", "accent"), ("КУРС", "8 НЕДЕЛЬ", "green")],
        },
        "ticker": "УРОК 3    ЗАДАЧИ 12    ЭКЗАМЕН 85%    СЕРИЯ 7 ДНЕЙ",
    },
    "tech": {
        "tint": (150, 110, 255), "chart": "line", "prop": "tech", "set": "server",
        "visual_by_kind": {
            "hook": "terminal", "problem": "chart", "insight": "terminal",
            "solution": "chart", "cta": "room",
        },
        "cards": [("СЕРВЕР", "99.9%", "green"), ("ЗАПРОСЫ", "1.2K", "accent")],
        "cards_by_kind": {
            "hook": [("API", "120 MS", "accent"), ("CPU", "42%", "accent2")],
            "problem": [("ОШИБКИ", "5", "bad"), ("ЛАТЕНСИЯ", "480 MS", "accent")],
            "insight": [("ЗАПРОСЫ", "1.2K", "accent"), ("АПТАЙМ", "99.9%", "green")],
            "solution": [("ЛАТЕНСИЯ", "120 MS", "green"), ("CPU", "42%", "accent")],
            "cta": [("ЗАПУСК", "СЕЙЧАС", "accent"), ("СЕРВЕР", "99.9%", "green")],
        },
        "ticker": "API 120MS    CPU 42%    RAM 68%    UPTIME 99.9%",
    },
    "health": {
        "tint": (40, 214, 176), "chart": "ecg", "prop": "health", "set": "clinic",
        "visual_by_kind": {
            "hook": "room", "problem": "chart", "insight": "chart",
            "solution": "chart", "cta": "room",
        },
        "cards": [("ПУЛЬС", "72", "green"), ("СОН", "7.5 Ч", "accent")],
        "cards_by_kind": {
            "hook": [("ПУЛЬС", "72", "green"), ("ДАВЛЕНИЕ", "120/80", "accent")],
            "problem": [("РИСК", "3", "bad"), ("СОН", "5.2 Ч", "accent")],
            "insight": [("ШАГИ", "8 240", "accent"), ("ПУЛЬС", "72", "green")],
            "cta": [("ПРОВЕРИТЬ", "СЕЙЧАС", "accent"), ("НОРМА", "72", "green")],
        },
        "ticker": "ПУЛЬС 72    ДАВЛЕНИЕ 120/80    ШАГИ 8 240    СОН 7.5 Ч",
    },
    "travel": {
        "tint": (255, 170, 90), "chart": "line", "prop": "travel", "set": "airport",
        "visual_by_kind": {
            "hook": "room", "problem": "chart", "insight": "chart",
            "solution": "chart", "cta": "room",
        },
        "cards": [("ДНЕЙ", "7", "accent"), ("БЮДЖЕТ", "$1 200", "green")],
        "cards_by_kind": {
            "hook": [("РЕЙС", "SU 204", "accent"), ("ОТЕЛЬ", "4*", "accent2")],
            "problem": [("РИСКИ", "2", "bad"), ("ВИЗА", "?", "accent")],
            "insight": [("ДНЕЙ", "7", "accent"), ("БЮДЖЕТ", "$1 200", "green")],
            "cta": [("ЛЕТЕТЬ", "СКОРО", "accent"), ("МЕСТА", "2", "green")],
        },
        "ticker": "РЕЙС SU 204    ОТЕЛЬ 4*    ВИЗА OK    БЮДЖЕТ $1 200",
    },
    "business": {
        "tint": (80, 140, 255), "chart": "funnel", "prop": "business", "set": "office",
        "visual_by_kind": {
            "hook": "board", "problem": "chart", "insight": "board",
            "solution": "chart", "cta": "room",
        },
        "cards": [("ПРОДАЖИ", "24", "accent"), ("КОНВЕРСИЯ", "18%", "green")],
        "cards_by_kind": {
            "hook": [("ЛИДЫ", "120", "accent"), ("СДЕЛКИ", "24", "accent2")],
            "problem": [("ОТКАЗЫ", "18", "bad"), ("КОНВЕРСИЯ", "6%", "accent")],
            "insight": [("ЛИДЫ", "120", "accent"), ("КОНВЕРСИЯ", "18%", "green")],
            "solution": [("ВЫРУЧКА", "$8K", "green"), ("СДЕЛКИ", "24", "accent")],
            "cta": [("ЗАПУСК", "СЕЙЧАС", "accent"), ("ПЛАН", "30 ДНЕЙ", "green")],
        },
        "ticker": "ЛИДЫ 120    СДЕЛКИ 24    КОНВЕРСИЯ 18%    ВЫРУЧКА $8K",
    },
    "story": {
        "tint": (120, 150, 220), "chart": "bars", "prop": "story", "set": "studio",
        "visual_by_kind": {
            "hook": "room", "problem": "board", "insight": "chart",
            "solution": "room", "cta": "room",
        },
        "cards": [("ГЛАВНОЕ", "3", "accent"), ("ИТОГ", "1", "green")],
        "cards_by_kind": {
            "hook": [("ИДЕЯ", "1", "accent"), ("ВОПРОС", "?", "accent2")],
            "problem": [("ПРИЧИНЫ", "3", "bad"), ("ИТОГ", "?", "accent")],
            "insight": [("ФАКТЫ", "3", "accent"), ("ВЫВОД", "1", "green")],
            "solution": [("ШАГИ", "4", "accent"), ("ИТОГ", "1", "green")],
            "cta": [("НАЧАТЬ", "СЕЙЧАС", "accent"), ("ШАГ", "1", "green")],
        },
        "ticker": "ИДЕЯ    ФАКТ    ПРИЧИНА    ВЫВОД    ДЕЙСТВИЕ",
    },
}


def detect_topic(plan: dict) -> str:
    text = " ".join(
        f"{s.get('title', '')} {s.get('accent', '')} {s.get('text', '')}"
        for s in plan.get("scenes", [])
    ).lower()
    text += " " + str(plan.get("title", "")).lower()
    best, score = "story", 0
    for topic, words in TOPIC_KEYWORDS.items():
        current = sum(text.count(word) for word in words)
        if current > score:
            best, score = topic, current
    return best if score >= 2 else "story"



def _kf(phase: float, keys: list, loop: float):
    """Smoothly interpolate a looping keyframe track."""
    phase = phase % max(0.001, loop)
    for i in range(len(keys) - 1):
        t0, v0 = keys[i]
        t1, v1 = keys[i + 1]
        if t0 <= phase <= t1:
            u = (phase - t0) / max(1e-6, t1 - t0)
            u = u * u * (3.0 - 2.0 * u)
            if isinstance(v0, (tuple, list)):
                return tuple(a + (b - a) * u for a, b in zip(v0, v1))
            return v0 + (v1 - v0) * u
    return keys[-1][1]


ARM_KEYS = {
    "idle": (8.0, [
        (0.0, (96, 10)), (2.0, (92, 8)), (3.5, (98, 14)),
        (4.6, (78, 18)), (5.2, (-98, -6)), (5.9, (92, 10)), (8.0, (96, 10)),
    ], [
        (0.0, (84, 10)), (2.0, (88, 8)), (3.5, (82, 14)),
        (4.6, (86, 10)), (5.9, (84, 10)), (8.0, (84, 10)),
    ]),
    "talk": (4.0, [
        (0.0, (96, 10)), (1.0, (104, 18)), (2.0, (92, 12)),
        (3.0, (100, 18)), (4.0, (96, 10)),
    ], [
        (0.0, (80, 12)), (0.4, (50, 45)), (0.9, (30, 25)), (1.3, (45, 40)),
        (1.8, (20, 18)), (2.3, (55, 50)), (2.8, (70, 25)), (3.4, (85, 10)),
        (4.0, (80, 12)),
    ]),
    "explain": (4.0, [
        (0.0, (96, 10)), (0.6, (122, 25)), (1.2, (82, 35)),
        (1.8, (112, 20)), (2.4, (96, 10)), (3.2, (122, 25)), (4.0, (96, 10)),
    ], [
        (0.0, (80, 12)), (0.4, (50, 45)), (0.9, (30, 25)), (1.3, (45, 40)),
        (1.8, (20, 18)), (2.3, (55, 50)), (2.8, (70, 25)), (3.4, (85, 10)),
        (4.0, (80, 12)),
    ]),
    "point": (3.0, [
        (0.0, (100, 8)), (1.0, (96, 12)), (2.0, (102, 8)), (3.0, (100, 8)),
    ], [
        (0.0, (85, 10)), (0.4, (10, -2)), (1.0, (18, 4)), (1.3, (4, -3)),
        (1.8, (14, 0)), (2.3, (88, 8)), (3.0, (85, 10)),
    ]),
    "wave": (2.0, [
        (0.0, (96, 10)), (2.0, (96, 10)),
    ], [
        (0.0, (-70, -20)), (0.3, (-64, -48)), (0.6, (-70, -20)),
        (0.9, (-64, -48)), (1.2, (-70, -20)), (1.5, (-64, -48)),
        (2.0, (-70, -20)),
    ]),
    "think": (4.0, [
        (0.0, (96, 10)), (1.5, (105, 18)), (2.5, (96, 10)), (4.0, (96, 10)),
    ], [
        (0.0, (90, 10)), (0.5, (-125, -55)), (1.2, (-118, -65)),
        (1.6, (-122, -58)), (2.2, (-70, -10)), (2.7, (-80, -20)),
        (3.2, (80, 10)), (4.0, (90, 10)),
    ]),
    "victory": (2.0, [
        (0.0, (-105, -20)), (0.5, (-95, -40)), (1.0, (-110, -18)),
        (1.5, (-95, -40)), (2.0, (-105, -20)),
    ], [
        (0.0, (-75, 20)), (0.5, (-85, 40)), (1.0, (-70, 18)),
        (1.5, (-85, 40)), (2.0, (-75, 20)),
    ]),
    "happy": (2.0, [
        (0.0, (-90, -20)), (0.5, (-120, -40)), (1.0, (-90, -20)),
        (1.5, (-120, -40)), (2.0, (-90, -20)),
    ], [
        (0.0, (-90, 20)), (0.5, (-60, 40)), (1.0, (-90, 20)),
        (1.5, (-60, 40)), (2.0, (-90, 20)),
    ]),
    "sad": (4.0, [
        (0.0, (110, 15)), (2.0, (106, 18)), (4.0, (110, 15)),
    ], [
        (0.0, (70, -15)), (2.0, (74, -18)), (4.0, (70, -15)),
    ]),
    "scared": (1.6, [
        (0.0, (120, 20)), (0.4, (125, 35)), (0.8, (118, 20)),
        (1.2, (125, 35)), (1.6, (120, 20)),
    ], [
        (0.0, (-120, -20)), (0.4, (-125, -35)), (0.8, (-118, -20)),
        (1.2, (-125, -35)), (1.6, (-120, -20)),
    ]),
    "error": (3.0, [
        (0.0, (90, 10)), (0.3, (150, 20)), (0.8, (100, 8)),
        (1.4, (150, 20)), (2.0, (90, 10)), (2.5, (150, 20)), (3.0, (90, 10)),
    ], [
        (0.0, (90, 10)), (0.3, (30, -20)), (0.8, (-130, -60)),
        (1.4, (30, -20)), (2.0, (90, 10)), (2.5, (30, -20)), (3.0, (90, 10)),
    ]),
    "show": (3.0, [
        (0.0, (90, 10)), (0.5, (155, -15)), (1.5, (160, -20)),
        (2.2, (155, -15)), (3.0, (90, 10)),
    ], [
        (0.0, (90, 10)), (0.5, (25, 15)), (1.5, (20, 20)),
        (2.2, (25, 15)), (3.0, (90, 10)),
    ]),
}

LEG_KEYS = {
    "idle": (8.0, [
        (0.0, (88, 5, 92, 5)), (1.5, (87, 8, 93, 5)), (3.0, (88, 5, 91, 9)),
        (4.5, (87, 7, 93, 6)), (6.0, (88, 5, 92, 5)), (8.0, (88, 5, 92, 5)),
    ]),
    "talk": (4.0, [
        (0.0, (88, 6, 92, 6)), (1.2, (87, 8, 93, 5)),
        (2.4, (89, 5, 91, 8)), (4.0, (88, 6, 92, 6)),
    ]),
    "point": (3.0, [
        (0.0, (90, 5, 90, 5)), (0.8, (82, 10, 98, 5)),
        (2.2, (82, 10, 98, 5)), (3.0, (90, 5, 90, 5)),
    ]),
    "think": (4.0, [
        (0.0, (88, 5, 92, 5)), (1.5, (87, 8, 93, 5)),
        (2.5, (89, 5, 91, 8)), (4.0, (88, 5, 92, 5)),
    ]),
    "victory": (2.0, [
        (0.0, (80, 20, 85, 15)), (0.5, (95, 5, 95, 5)),
        (1.0, (75, 30, 80, 25)), (1.5, (95, 5, 95, 5)),
        (2.0, (80, 20, 85, 15)),
    ]),
    "happy": (2.0, [
        (0.0, (84, 12, 88, 10)), (0.5, (92, 4, 94, 4)),
        (1.0, (82, 16, 86, 14)), (1.5, (92, 4, 94, 4)),
        (2.0, (84, 12, 88, 10)),
    ]),
    "sad": (4.0, [
        (0.0, (88, 2, 92, 2)), (2.0, (89, 6, 91, 6)), (4.0, (88, 2, 92, 2)),
    ]),
    "scared": (1.6, [
        (0.0, (86, 6, 94, 6)), (0.4, (88, 2, 92, 2)),
        (0.8, (86, 6, 94, 6)), (1.2, (88, 2, 92, 2)),
        (1.6, (86, 6, 94, 6)),
    ]),
    "error": (3.0, [
        (0.0, (90, 5, 90, 5)), (0.5, (82, 10, 98, 8)),
        (1.5, (82, 10, 98, 8)), (2.5, (90, 5, 90, 5)),
    ]),
}


def _rgb(value, fallback):
    try:
        value = str(value).strip()
        if value.startswith("#") and len(value) == 7:
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    except Exception:
        pass
    return fallback


def character_settings(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    ch = {**DEFAULT_CHARACTER, **raw}
    ch["skin"] = _rgb(ch.get("skin"), (242, 201, 160))
    ch["hair"] = _rgb(ch.get("hair"), (43, 27, 18))
    ch["shirt"] = _rgb(ch.get("shirt"), (58, 132, 255))
    ch["pants"] = _rgb(ch.get("pants"), (27, 36, 48))
    ch["shoes"] = _rgb(ch.get("shoes"), (14, 17, 22))
    ch["eye_color"] = _rgb(ch.get("eye_color"), (22, 26, 29))
    if ch.get("type") not in ("human", "robot", "animal", "fantasy", "custom"):
        ch["type"] = "human"
    if ch.get("type") == "custom" and not str(ch.get("custom_image") or "").startswith("data:image/"):
        ch["type"] = "human"
    if ch.get("gender") not in ("male", "female"):
        ch["gender"] = "male"
    if ch.get("hair_style") not in ("short", "long", "cap", "bob"):
        ch["hair_style"] = "short"
    if ch.get("accessory") not in ("none", "glasses", "headphones"):
        ch["accessory"] = "none"
    if ch.get("expression") not in ("neutral", "smile", "sad", "angry", "surprised"):
        ch["expression"] = "neutral"
    if ch.get("height") not in ("short", "normal", "tall"):
        ch["height"] = "normal"
    if ch.get("proportions") not in ("slim", "normal", "wide"):
        ch["proportions"] = "normal"
    if ch.get("pixel_style") not in ("8bit", "16bit", "detailed", "minimal"):
        ch["pixel_style"] = "16bit"
    return ch


def _rect(c, x, y, w, h, rgb, a=255):
    p = skia.Paint(AntiAlias=False)
    p.setColor(gfx.col(rgb, a))
    c.drawRect(skia.Rect.MakeXYWH(float(x), float(y), float(w), float(h)), p)


def _pixel(c, x, y, rgb, a=255):
    _rect(c, x, y, 1, 1, rgb, a)


def _draw_icon(c, name, x, y, color, scale=1, alpha=210):
    pattern = ICONS.get(name)
    if not pattern:
        return
    for row, line in enumerate(pattern):
        for col, ch in enumerate(line):
            if ch == "1":
                _rect(c, x + col * scale, y + row * scale, scale, scale, color, alpha)


def _draw_character(c, ox, oy, frame: int, ch: dict, limbs: bool = True):
    skin = ch["skin"]
    hair = ch["hair"]
    shirt = ch["shirt"]
    pants = ch["pants"]
    shoes = ch["shoes"]
    accent = tuple(gfx.ACCENT)
    dark = (18, 22, 28)
    outline = (8, 10, 14)
    skin_shadow = gfx.blend(skin, (0, 0, 0), 0.16)
    shirt_shadow = gfx.blend(shirt, (0, 0, 0), 0.20)
    shirt_light = gfx.blend(shirt, (255, 255, 255), 0.18)
    pants_light = gfx.blend(pants, (255, 255, 255), 0.12)
    ctype = ch.get("type", "human")
    style = ch.get("pixel_style", "16bit")
    gender = ch.get("gender", "male")
    eye = ch.get("eye_color", dark)
    expression = ch.get("expression", "neutral")

    if style == "8bit":
        q = lambda color: tuple((int(v) // 64) * 64 for v in color)
        skin, hair, shirt, pants = q(skin), q(hair), q(shirt), q(pants)
    if style == "minimal":
        hair = gfx.blend(hair, skin, 0.25)

    walk = frame in (4, 5, 6, 7)
    talk = frame in (2, 3)
    point = frame in (8, 17)
    point_alt = frame == 17
    wave = frame in (9, 18)
    wave_alt = frame == 18
    sad = frame in (10, 24)
    sad_alt = frame == 24
    happy = frame in (11, 19)
    happy_alt = frame == 19
    think = frame in (12, 20)
    think_alt = frame == 20
    scared = frame in (13, 25)
    scared_alt = frame == 25
    show = frame in (14, 22)
    show_alt = frame == 22
    victory = frame in (15, 21)
    victory_alt = frame == 21
    error = frame in (16, 23)
    error_alt = frame == 23
    blink = frame == 1

    slim = ch.get("proportions") == "slim"
    wide = ch.get("proportions") == "wide"
    body_x = 14 if slim else 11 if wide else 12
    body_w = 12 if slim else 18 if wide else 16
    if gender == "female":
        body_x += 1
        body_w = max(10, body_w - 2)
    leg_l = 14 if slim else 12 if wide else 13
    leg_r = 22 if slim else 24 if wide else 21

    if ctype == "animal":
        # tail
        _rect(c, ox + 27, oy + 35, 11, 5, outline)
        _rect(c, ox + 34, oy + 31, 5, 8, outline)
        _rect(c, ox + 28, oy + 36, 9, 3, skin)
        _rect(c, ox + 35, oy + 32, 3, 6, skin)
        _rect(c, ox + 36, oy + 33, 1, 3, gfx.blend(skin, (255, 255, 255), 0.22))

    if limbs:
        if walk:
            left = (frame - 4) in (0, 1)
            leg_l += 2 if left else 0
            leg_r -= 2 if left else 0
        leg_w = 5 if slim else 6
        _rect(c, ox + leg_l - 1, oy + 41, leg_w + 2, 14, outline)
        _rect(c, ox + leg_r - 1, oy + 41, leg_w + 2, 14, outline)
        _rect(c, ox + leg_l - 2, oy + 53, 9, 6, outline)
        _rect(c, ox + leg_r - 2, oy + 53, 9, 6, outline)
        _rect(c, ox + leg_l, oy + 42, leg_w, 12, pants)
        _rect(c, ox + leg_r, oy + 42, leg_w, 12, pants)
        _rect(c, ox + leg_l, oy + 44, 1, 8, pants_light)
        _rect(c, ox + leg_r, oy + 44, 1, 8, pants_light)
        _rect(c, ox + leg_l - 1, oy + 54, 7, 4, shoes)
        _rect(c, ox + leg_r - 1, oy + 54, 7, 4, shoes)
        _rect(c, ox + leg_l, oy + 55, 3, 1, gfx.blend(shoes, (255, 255, 255), 0.18))
        _rect(c, ox + leg_r, oy + 55, 3, 1, gfx.blend(shoes, (255, 255, 255), 0.18))
        _rect(c, ox + leg_l, oy + 57, 5, 1, gfx.blend(shoes, (255, 255, 255), 0.10))
        _rect(c, ox + leg_r, oy + 57, 5, 1, gfx.blend(shoes, (255, 255, 255), 0.10))

    # body
    _rect(c, ox + body_x - 1, oy + 21, body_w + 2, 22, outline)
    _rect(c, ox + body_x, oy + 22, body_w, 20, shirt)
    _rect(c, ox + body_x, oy + 22, body_w, 3, shirt_light)
    _rect(c, ox + body_x + body_w - 2, oy + 25, 2, 15, shirt_shadow)
    # collar, buttons, pockets and belt
    _rect(c, ox + body_x + 3, oy + 22, max(3, body_w - 6), 1,
          gfx.blend(shirt, (255, 255, 255), 0.35))
    _rect(c, ox + body_x + body_w // 2 - 1, oy + 25, 1, 1, shirt_shadow)
    _rect(c, ox + body_x + body_w // 2 - 1, oy + 30, 1, 1, shirt_shadow)
    _rect(c, ox + body_x + 2, oy + 33, 3, 1, shirt_shadow)
    _rect(c, ox + body_x + body_w - 5, oy + 33, 3, 1, shirt_shadow)
    _rect(c, ox + body_x, oy + 38, body_w, 2, outline)
    _rect(c, ox + body_x + body_w // 2 - 1, oy + 38, 2, 2, accent)
    # jacket / vest detail — reads as tailoring even at 40x60
    jacket = gfx.blend(shirt, (10, 12, 16), 0.55)
    jacket_light = gfx.blend(jacket, (255, 255, 255), 0.10)
    _rect(c, ox + body_x, oy + 22, 3, 18, jacket)
    _rect(c, ox + body_x + body_w - 3, oy + 22, 3, 18, jacket)
    _rect(c, ox + body_x + 3, oy + 22, 1, 6, jacket_light)
    _rect(c, ox + body_x + body_w - 4, oy + 22, 1, 6, jacket_light)
    _rect(c, ox + body_x + 4, oy + 29, 1, 9, jacket)
    _rect(c, ox + body_x + body_w - 5, oy + 29, 1, 9, jacket)
    _rect(c, ox + body_x + 4, oy + 30, 2, 2, accent)
    _pixel(c, ox + body_x + 4, oy + 30, (255, 255, 255), 170)
    _rect(c, ox + body_x + 4, oy + 21, max(2, body_w - 8), 2, skin_shadow)
    if style == "detailed":
        _rect(c, ox + body_x + 2, oy + 27, 1, 9, gfx.blend(shirt, (0, 0, 0), 0.22))

    # arms
    if limbs:
        if point or show:
            dy = 3 if point_alt else 0
            _rect(c, ox + body_x + body_w - 2, oy + 21 + dy, 12, 4, shirt)
            _rect(c, ox + body_x + body_w + 8, oy + 20 + dy, 4, 4, skin)
            if show:
                lift = -3 if show_alt else 0
                _rect(c, ox + body_x + body_w + 10, oy + 18 + lift, 5, 5, (255, 198, 86))
                _rect(c, ox + body_x + body_w + 11, oy + 19 + lift, 3, 3, (255, 255, 220))
            _rect(c, ox + body_x - 5, oy + 22, 6, 15, shirt)
            _rect(c, ox + body_x - 5, oy + 35, 6, 5, skin)
            _rect(c, ox + body_x - 5, oy + 22, 1, 3, shirt_light)
            _rect(c, ox + body_x - 1, oy + 22, 3, 3, shirt)
            _rect(c, ox + body_x - 6, oy + 32, 5, 2, (18, 22, 28))
            _rect(c, ox + body_x - 5, oy + 32, 1, 1, accent, 220)
        elif wave or happy or victory or scared:
            lift = 4 if wave_alt else 0
            _rect(c, ox + body_x + body_w - 2, oy + 12 + lift, 4, 13, shirt)
            _rect(c, ox + body_x + body_w - 1, oy + 6 + lift, 5, 7, skin)
            _rect(c, ox + body_x - 6, oy + 25, 5, 12, shirt)
            _rect(c, ox + body_x - 6, oy + 36, 5, 4, skin)
            _rect(c, ox + body_x - 6, oy + 32, 5, 2, (18, 22, 28))
            _rect(c, ox + body_x - 5, oy + 32, 1, 1, accent, 220)
            left_up = (victory and not victory_alt) or happy_alt or scared_alt
            if left_up:
                _rect(c, ox + body_x - 5, oy + 12, 5, 15, shirt)
                _rect(c, ox + body_x - 6, oy + 6, 6, 7, skin)
                _rect(c, ox + body_x - 6, oy + 8, 1, 1, skin_shadow)
                _rect(c, ox + body_x - 6, oy + 10, 1, 1, skin_shadow)
                _rect(c, ox + body_x - 1, oy + 20, 3, 4, shirt)
            elif victory_alt:
                _rect(c, ox + body_x - 5, oy + 19, 5, 15, shirt)
                _rect(c, ox + body_x - 6, oy + 14, 6, 7, skin)
                _rect(c, ox + body_x - 1, oy + 21, 3, 3, shirt)
        elif think:
            hand_y = 6 if think_alt else 10
            _rect(c, ox + body_x + body_w - 2, oy + 16, 7, 4, shirt)
            _rect(c, ox + body_x + body_w + 3, oy + hand_y, 4, 8, skin)
            _rect(c, ox + body_x - 5, oy + 22, 6, 15, shirt)
            _rect(c, ox + body_x - 5, oy + 35, 6, 5, skin)
            _rect(c, ox + body_x - 5, oy + 22, 1, 3, shirt_light)
            _rect(c, ox + body_x - 1, oy + 22, 3, 3, shirt)
            _rect(c, ox + body_x - 6, oy + 32, 5, 2, (18, 22, 28))
            _rect(c, ox + body_x - 5, oy + 32, 1, 1, accent, 220)
        elif sad:
            drop = 2 if sad_alt else 0
            _rect(c, ox + body_x - 6, oy + 28 + drop, 5, 12, shirt)
            _rect(c, ox + body_x - 6, oy + 38 + drop, 5, 4, skin)
            _rect(c, ox + body_x + body_w + 1, oy + 28 + drop, 5, 12, shirt)
            _rect(c, ox + body_x + body_w + 1, oy + 38 + drop, 5, 4, skin)
        elif walk:
            swing = 2 if (frame - 4) in (0, 1) else -2
            _rect(c, ox + body_x - 6, oy + 24 + swing, 5, 12, shirt)
            _rect(c, ox + body_x + body_w + 1, oy + 24 - swing, 5, 12, shirt)
        else:
            _rect(c, ox + body_x - 5, oy + 22, 6, 14, shirt)
            _rect(c, ox + body_x + body_w - 1, oy + 22, 6, 14, shirt)
            _rect(c, ox + body_x - 5, oy + 33, 6, 5, skin)
            _rect(c, ox + body_x + body_w - 1, oy + 33, 6, 5, skin)
            _rect(c, ox + body_x - 5, oy + 22, 1, 3, shirt_light)
            _rect(c, ox + body_x + body_w + 4, oy + 22, 1, 3, shirt_light)
            _rect(c, ox + body_x - 1, oy + 22, 3, 3, shirt)
            _rect(c, ox + body_x + body_w - 2, oy + 22, 3, 3, shirt)
            _rect(c, ox + body_x - 5, oy + 31, 6, 2, (18, 22, 28))
            _rect(c, ox + body_x - 4, oy + 31, 1, 1, accent, 220)

    # head
    head_x = 12 if not wide else 11
    head_y = 5
    head_w = 16 if not wide else 18
    _rect(c, ox + head_x - 1, oy + head_y - 1, head_w + 2, 19, outline)
    _rect(c, ox + head_x, oy + head_y, head_w, 16, skin)
    _rect(c, ox + head_x - 1, oy + head_y + 13, head_w + 2, 3, skin)
    _rect(c, ox + head_x + head_w - 3, oy + head_y + 1, 2, 14, skin_shadow)
    # ears and nose
    _rect(c, ox + head_x - 1, oy + head_y + 7, 2, 3, skin_shadow)
    _rect(c, ox + head_x + head_w - 1, oy + head_y + 7, 2, 3, skin_shadow)
    if ctype in ("human", "fantasy"):
        _rect(c, ox + head_x + 7, oy + head_y + 9, 1, 2, skin_shadow)
        _rect(c, ox + head_x + 5, oy + head_y + 8, 5, 1, gfx.blend(skin, (0, 0, 0), 0.08))

    if ctype == "robot":
        _rect(c, ox + 12, oy + 5, 16, 16, skin)
        _rect(c, ox + 13, oy + 9, 14, 5, dark)
        _rect(c, ox + 15, oy + 11, 3, 2, eye)
        _rect(c, ox + 23, oy + 11, 3, 2, eye)
        _rect(c, ox + 18, oy + 17, 4, 2, dark)
        _rect(c, ox + 19, oy + 0, 2, 5, accent)
        _rect(c, ox + 18, oy - 1, 4, 2, accent)
        _rect(c, ox + 14, oy + 24, 12, 4, gfx.blend(shirt, (255, 255, 255), 0.2))
        _rect(c, ox + 18, oy + 27, 4, 2, accent)
        # side panels
        _rect(c, ox + 8, oy + 10, 4, 8, gfx.blend(skin, (0, 0, 0), 0.2))
        _rect(c, ox + 28, oy + 10, 4, 8, gfx.blend(skin, (0, 0, 0), 0.2))
        _rect(c, ox + 13, oy + 10, 1, 1, (245, 255, 255))
        _rect(c, ox + 18, oy + 27, 4, 2, accent)
        _rect(c, ox + 19, oy + 27, 2, 1, (245, 255, 255))
    elif ctype == "animal":
        # ears
        _rect(c, ox + 10, oy + 1, 5, 6, skin)
        _rect(c, ox + 25, oy + 1, 5, 6, skin)
        _rect(c, ox + 11, oy + 2, 3, 4, gfx.blend(skin, (255, 255, 255), 0.2))
        _rect(c, ox + 26, oy + 2, 3, 4, gfx.blend(skin, (255, 255, 255), 0.2))
        # muzzle
        _rect(c, ox + 16, oy + 15, 8, 6, gfx.blend(skin, (255, 255, 255), 0.35))
        _rect(c, ox + 19, oy + 16, 3, 2, dark)
        _rect(c, ox + 18, oy + 19, 5, 1, dark)
        # fur tuft
        _rect(c, ox + 12, oy + 3, 16, 3, hair)
        _rect(c, ox + 13, oy + 1, 5, 3, hair)
        _rect(c, ox + 14, oy + 3, 10, 1, gfx.blend(hair, (255, 255, 255), 0.24))
        _rect(c, ox + 17, oy + 16, 6, 1, gfx.blend(skin, (0, 0, 0), 0.10))
        # eyes
        _rect(c, ox + 14, oy + 11, 3, 3, eye)
        _rect(c, ox + 23, oy + 11, 3, 3, eye)
        _rect(c, ox + 15, oy + 12, 1, 1, (245, 245, 255))
        _rect(c, ox + 24, oy + 12, 1, 1, (245, 245, 255))
    elif ctype == "fantasy":
        # pointed ears / antenna
        _rect(c, ox + 7, oy + 8, 5, 3, skin)
        _rect(c, ox + 28, oy + 8, 5, 3, skin)
        _rect(c, ox + 18, oy - 2, 4, 4, accent)
        _rect(c, ox + 19, oy - 4, 2, 3, accent)
        _rect(c, ox + 15, oy + 11, 2, 2, eye)
        _rect(c, ox + 23, oy + 11, 2, 2, eye)
        _rect(c, ox + 15, oy + 11, 1, 1, (245, 255, 255))
        _rect(c, ox + 23, oy + 11, 1, 1, (245, 255, 255))
        _rect(c, ox + 18, oy - 5, 2, 1, tuple(gfx.HIGHLIGHT))
        _rect(c, ox + 18, oy + 16, 4, 1, dark)
    else:
        # human hair
        hair_style = ch.get("hair_style")
        if hair_style == "cap":
            _rect(c, ox + 10, oy + 3, 20, 6, accent)
            _rect(c, ox + 8, oy + 8, 24, 3, accent)
        else:
            _rect(c, ox + 11, oy + 3, 18, 5, hair)
            _rect(c, ox + 10, oy + 6, 3, 9 if hair_style != "bob" else 13, hair)
            _rect(c, ox + 27, oy + 6, 3, 9 if hair_style != "bob" else 13, hair)
            if hair_style == "long":
                _rect(c, ox + 10, oy + 12, 3, 10, hair)
                _rect(c, ox + 27, oy + 12, 3, 10, hair)
            _rect(c, ox + 12, oy + 4, 7, 1, gfx.blend(hair, (255, 255, 255), 0.24))
            _rect(c, ox + 13, oy + 4, 1, 6, gfx.blend(hair, (0, 0, 0), 0.25))
            _rect(c, ox + 24, oy + 5, 1, 5, gfx.blend(hair, (255, 255, 255), 0.12))
        # eyes / mouth
        if blink:
            _rect(c, ox + 15, oy + 12, 2, 1, eye)
            _rect(c, ox + 23, oy + 12, 2, 1, eye)
        elif scared or expression == "surprised":
            _rect(c, ox + 14, oy + 10, 4, 4, (250, 250, 255))
            _rect(c, ox + 15, oy + 11, 2, 2, eye)
            _rect(c, ox + 22, oy + 10, 4, 4, (250, 250, 255))
            _rect(c, ox + 23, oy + 11, 2, 2, eye)
        elif sad or expression == "sad":
            _rect(c, ox + 15, oy + 12, 2, 1, eye)
            _rect(c, ox + 23, oy + 12, 2, 1, eye)
        elif think or expression == "angry":
            _rect(c, ox + 15, oy + 10, 2, 2, eye)
            _rect(c, ox + 23, oy + 10, 2, 2, eye)
        else:
            _rect(c, ox + 15, oy + 11, 2, 2, eye)
            _rect(c, ox + 23, oy + 11, 2, 2, eye)
        if not blink and not (scared or expression == "surprised"):
            _rect(c, ox + 15, oy + 11, 1, 1, (245, 245, 255))
            _rect(c, ox + 23, oy + 11, 1, 1, (245, 245, 255))
        if gender == "female" and not blink:
            _rect(c, ox + 14, oy + 9, 4, 1, dark)
            _rect(c, ox + 22, oy + 9, 4, 1, dark)

    # mouth / expression (human and fantasy; robot/animal handled above)
    if ctype in ("human", "fantasy"):
        if talk or scared:
            _rect(c, ox + 18, oy + 16, 4, 2, dark)
        elif happy or victory or expression == "smile":
            _rect(c, ox + 17, oy + 16, 6, 2, dark)
            _rect(c, ox + 18, oy + 15, 4, 1, dark)
        elif sad or expression == "sad":
            _rect(c, ox + 18, oy + 17, 4, 1, dark)
            _rect(c, ox + 19, oy + 16, 2, 1, dark)
        elif expression == "surprised":
            _rect(c, ox + 18, oy + 16, 4, 3, dark)
            _rect(c, ox + 19, oy + 17, 2, 1, (220, 90, 100))
        elif expression == "angry":
            _rect(c, ox + 18, oy + 16, 4, 1, dark)
            _rect(c, ox + 15, oy + 8, 4, 1, dark)
            _rect(c, ox + 23, oy + 8, 4, 1, dark)
        else:
            _rect(c, ox + 18, oy + 16, 4, 1, dark)

    # accessory
    if ctype in ("human", "fantasy"):
        if ch.get("accessory") == "glasses":
            _rect(c, ox + 14, oy + 10, 5, 4, dark)
            _rect(c, ox + 15, oy + 11, 3, 2, (200, 220, 235))
            _rect(c, ox + 22, oy + 10, 5, 4, dark)
            _rect(c, ox + 23, oy + 11, 3, 2, (200, 220, 235))
            _rect(c, ox + 19, oy + 11, 3, 1, dark)
        elif ch.get("accessory") == "headphones":
            _rect(c, ox + 9, oy + 5, 22, 3, dark)
            _rect(c, ox + 7, oy + 8, 4, 9, dark)
            _rect(c, ox + 29, oy + 8, 4, 9, dark)
            _rect(c, ox + 8, oy + 11, 2, 4, accent)
            _rect(c, ox + 30, oy + 11, 2, 4, accent)

    if error:
        dy = -2 if error_alt else 0
        _rect(c, ox + 18, oy - 4 + dy, 2, 7, (255, 92, 92))
        _rect(c, ox + 15, oy - 1 + dy, 8, 2, (255, 92, 92))
        if error_alt:
            _rect(c, ox + 24, oy - 3, 2, 2, (255, 198, 86))
    if victory:
        _rect(c, ox + 18, oy - 3, 2, 2, (255, 198, 86))
        _rect(c, ox + 15, oy - 5, 3, 3, (255, 198, 86))
        if victory_alt:
            _rect(c, ox + 22, oy - 5, 2, 2, (255, 198, 86))


def build_sprite_sheet(character: dict, path: Path, limbs: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = SHEET_FRAMES if limbs else 1
    surf = skia.Surface(FRAME_W * frames, FRAME_H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    for frame in range(frames):
        _draw_character(c, frame * FRAME_W, 0, frame, character, limbs=limbs)
    surf.makeImageSnapshot().save(str(path), skia.kPNG)
    return path


def _default_visual(kind: str, profile: dict | None = None) -> str:
    if profile:
        mapped = profile.get("visual_by_kind", {}).get(kind)
        if mapped:
            return mapped
        return profile.get("visual", "room")
    return {
        "hook": "room", "cta": "room", "statement": "room",
        "checklist": "board", "compare": "board", "timeline": "board",
        "chart": "chart", "stat": "chart", "bars": "chart",
        "dashboard": "terminal", "terminal": "terminal",
        "diagram": "phone", "notification": "phone", "quote": "phone",
    }.get(kind, "room")


def _default_animation(kind: str, has_text: bool) -> str:
    if kind in ("hook", "cta"):
        return "wave"
    if kind in ("chart", "stat", "bars"):
        return "point"
    if kind == "timeline":
        return "walk"
    return "talk" if has_text else "idle"


def auto_animation(text: str, kind: str) -> str:
    low = str(text or "").lower()
    if any(w in low for w in ("ошиб", "убыт", "минус", "слил", "потер", "провал", "наруш", "упал")):
        return "error" if any(w in low for w in ("ошиб", "провал", "наруш")) else "sad"
    if any(w in low for w in ("прибыл", "заработ", "успех", "вырос", "плюс", "хорош", "побед")):
        return "victory" if kind == "cta" else "happy"
    if any(w in low for w in ("почему", "разбер", "сложн", "дума", "вопрос", "причин")):
        return "think"
    if any(w in low for w in ("опас", "страх", "паник", "риск", "боишься")):
        return "scared"
    if any(w in low for w in ("смотри", "график", "схем", "показ", "указ", "сравн")):
        return "point"
    if any(w in low for w in ("предмет", "интерфейс", "кнопк", "экран", "телефон")):
        return "show"
    if any(w in low for w in ("объясн", "как это работает", "шаг", "механизм")):
        return "explain"
    return "talk" if low.strip() else "idle"


class PixelRenderer:
    def __init__(self, plan: dict, settings: dict, workdir: Path):
        self.plan = plan
        self.settings = settings
        self.topic = detect_topic(plan)
        forced_topic = str(settings.get("pixel_topic") or "auto")
        if forced_topic in TOPIC_PROFILES:
            self.topic = forced_topic
        self.profile = TOPIC_PROFILES.get(self.topic, TOPIC_PROFILES["story"])
        self.workdir = workdir
        gfx.set_theme(settings.get("style", "tech_blue"))
        self.character = character_settings(settings.get("character"))
        self.custom_image = None
        custom = str(self.character.get("custom_image") or "")
        if self.character.get("type") == "custom" and custom.startswith("data:image/") and ";base64," in custom:
            try:
                raw = base64.b64decode(custom.split(",", 1)[1])
                self.custom_image = skia.Image.open(io.BytesIO(raw))
            except Exception:
                self.custom_image = None
        if self.custom_image is not None:
            self.sheet_path = None
            self.sheet = None
        else:
            self.sheet_path = build_sprite_sheet(
                self.character, workdir / "character_body.png", limbs=False
            )
            self.sheet = skia.Image.open(str(self.sheet_path))
        self.quality = str(settings.get("quality") or "quality")
        if self.quality not in ("fast", "quality", "ultra"):
            self.quality = "quality"
        self.text_scale = 4 / 3 if self.quality == "ultra" else 1.0
        self.out_w = int(round(config.W * self.text_scale))
        self.out_h = int(round(config.H * self.text_scale))
        self.low = skia.Surface(SW, SH)
        self.full = skia.Surface(self.out_w, self.out_h)
        self.nearest = skia.SamplingOptions(skia.FilterMode.kNearest)
        self.linear = skia.SamplingOptions(skia.FilterMode.kLinear)
        self.starts = [float(s.get("start", 0)) for s in plan.get("scenes", [])]
        self.duration = float(plan.get("duration", 0) or 0)
        self._caption = render.Renderer(
            {"title": plan.get("title", ""), "scenes": [], "phrases": [], "duration": 1},
            settings, fast=False,
        )
        self._caption._scrim = self._caption._make_scrim()
        self.audio_env: list[float] = []
        self.vignette = None
        self.grain: list = []
        try:
            self.vignette = gfx.make_vignette()
        except Exception:
            self.vignette = None
        try:
            self.grain = gfx.make_grain(1, (540, 960), seed=round(time.time()) % 997)
        except Exception:
            self.grain = []
        self.grain_paint = skia.Paint()
        self.grain_paint.setAlphaf(0.55)

    def set_audio(self, path: Path) -> None:
        """Voice envelope per video frame — drives mouth, head and equalizer."""
        try:
            with wave.open(str(path), "rb") as w:
                sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
                raw = w.readframes(n)
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            step = max(1, int(sr / config.FPS))
            frames = max(1, len(x) // step)
            env = np.array([
                float(np.sqrt(np.mean(x[i * step:(i + 1) * step] ** 2)))
                for i in range(frames)
            ], dtype=np.float32)
            if env.size:
                env = np.convolve(env, np.ones(3, dtype=np.float32) / 3, mode="same")
                peak = float(np.percentile(env, 95)) or 1.0
                env = np.clip(env / (peak * 1.08), 0.0, 1.0)
            out: list[float] = []
            level = 0.0
            for value in env:
                if value > level:
                    level = level * 0.45 + value * 0.55
                else:
                    level = level * 0.82 + value * 0.18
                out.append(level)
            self.audio_env = out
        except Exception:
            self.audio_env = []

    def _env_at(self, global_t: float) -> float:
        if not self.audio_env:
            return 0.0
        idx = int(max(0.0, global_t) * config.FPS)
        if idx >= len(self.audio_env):
            return 0.0
        return self.audio_env[idx]

    # ---------------------------------------------------------------- world
    def _palette(self):
        theme = gfx.THEME
        bg = tuple(theme.get("bg", [(8, 8, 11)])[0])
        card = tuple(theme.get("card", (16, 22, 46)))
        accent = tuple(gfx.ACCENT)
        accent2 = tuple(gfx.ACCENT2)
        highlight = tuple(gfx.HIGHLIGHT)
        good = tuple(gfx.GREEN)
        bad = tuple(gfx.BAD)
        text = tuple(gfx.TEXT)
        muted = tuple(gfx.MUTED)
        return bg, card, accent, accent2, highlight, good, bad, text, muted

    def _draw_backdrop(self, c, t, scene_index):
        """Four backdrop variants so consecutive scenes do not look identical."""
        bg, card, accent, accent2, highlight, good, bad, text, muted = self._palette()
        variant = int(scene_index) % 4
        if variant == 0:
            # night city behind the scene
            for i in range(11):
                x = (i * 37 + 13) % SW
                y = 36 + (i * 19) % 90
                a = 80 + int(80 * (0.5 + 0.5 * math.sin(t * 2.0 + i)))
                _pixel(c, x, y, highlight if i % 3 else text, a)
            _rect(c, 202, 54, 20, 18, gfx.blend(card, highlight, 0.35), 150)
            _rect(c, 206, 58, 12, 10, gfx.blend(bg, highlight, 0.55), 120)
            for b in range(9):
                bx = b * 31 - 4
                bh = 20 + (b * 17) % 48
                by = 192 - bh
                _rect(c, bx, by, 27, bh, gfx.blend(bg, accent, 0.10), 150)
                _rect(c, bx, by, 27, 2, gfx.blend(accent, (0, 0, 0), 0.3), 90)
                for wy in range(by + 7, 188, 12):
                    for wx in range(bx + 5, bx + 24, 9):
                        if (wx + wy + int(t * 2)) % 7 < 3:
                            _rect(c, wx, wy, 2, 3, highlight, 70)
        elif variant == 1:
            # neon grid / synthwave wall
            for y in range(58, 200, 18):
                _rect(c, 0, y, SW, 1, accent, 22)
            for x in range(0, SW, 24):
                _rect(c, x, 44, 1, 168, accent2, 18)
            for r in range(4):
                rr = 22 + r * 18
                _rect(c, SW // 2 - rr, 150 - rr // 3, rr * 2, 2, accent2, 24)
            for i in range(7):
                x = (i * 41 + int(t * 4)) % SW
                y = 55 + (i * 23) % 130
                _rect(c, x, y, 4, 4, highlight if i % 2 else accent2, 45)
        elif variant == 2:
            # editorial poster wall
            for i, (x, y, w, h) in enumerate(((24, 60, 62, 50), (98, 46, 44, 72), (180, 70, 64, 44))):
                _rect(c, x, y, w, h, gfx.blend(card, accent if i % 2 == 0 else accent2, 0.14), 130)
                _rect(c, x + 5, y + 5, w - 10, 4, accent if i % 2 == 0 else accent2, 55)
                for bar in range(3):
                    _rect(c, x + 5, y + 16 + bar * 9, max(8, w - 18 - bar * 7), 3, muted, 38)
            _rect(c, 18, 140, 96, 4, gfx.blend(card, (0, 0, 0), 0.2), 150)
            _rect(c, 24, 132, 6, 8, good, 80)
            _rect(c, 36, 130, 5, 10, accent2, 80)
            _rect(c, 48, 134, 7, 6, highlight, 70)
        else:
            # abstract diagonal studio panels
            for i in range(5):
                x = -30 + i * 66
                _rect(c, x, 42, 24, 168, gfx.blend(bg, accent2, 0.06 + i * 0.012), 95)
                _rect(c, x + 8, 42, 2, 168, accent, 20)
            for i in range(6):
                x = (i * 53 + int(t * 7)) % SW
                y = 52 + (i * 31) % 120
                _rect(c, x, y, 3, 3, highlight, 55)

    def _draw_sky(self, c, t, scene_index, tint, accent, accent2, highlight, text, bg):
        for i in range(16):
            u = i / 15.0
            shade = gfx.blend(gfx.blend(bg, tint, 0.05 + 0.14 * u), (0, 0, 0), 0.22 * (1.0 - u))
            _rect(c, 0, i * 16, SW, 18, shade)
        gfx.orb(c, SW * 0.52, 226, 156, tint, 24, 5)
        mx, my, mr = 218, 58, 8
        for dy in range(-mr, mr + 1):
            half = int(math.sqrt(max(0, mr * mr - dy * dy)))
            _rect(c, mx - half, my + dy, half * 2, 1, (226, 232, 214), 150)
        _rect(c, mx - 3, my - 2, 2, 2, (196, 204, 188), 120)
        _rect(c, mx + 2, my + 2, 3, 1, (196, 204, 188), 110)
        _rect(c, mx - 1, my + 5, 2, 1, (196, 204, 188), 90)
        for layer, (count, speed, alpha) in enumerate(((46, 2, 80), (24, 4, 110), (12, 7, 150))):
            for i in range(count):
                sx = (i * 73 + layer * 31 + int(t * speed)) % SW
                sy = (i * 29 + layer * 17) % 214
                tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 2.4 + i * 1.7 + layer))
                _pixel(c, sx, sy, highlight if i % 4 else text, int(alpha * tw))
        for i in range(3):
            cx = (i * 118 + int(t * 3.5)) % (SW + 90) - 45
            cy = 92 + i * 26
            for j in range(4):
                _rect(c, cx + j * 8, cy + (j % 2), 12, 4, gfx.blend(bg, tint, 0.26), 38)
            _rect(c, cx + 5, cy - 3, 18, 3, gfx.blend(bg, tint, 0.30), 30)

    def _draw_city(self, c, t, scene_index, tint, accent, accent2, highlight, bg):
        dx = int(math.sin(t * 0.16 + scene_index * 0.9) * 4)
        for i in range(12):
            w = 18 + (i * 7) % 14
            h = 26 + (i * 13) % 46
            x = (i * 26 + dx) % (SW + 30) - 20
            y = 208 - h
            _rect(c, x, y, w, h, gfx.blend(bg, tint, 0.10), 175)
            _rect(c, x, y, w, 2, gfx.blend(accent, (0, 0, 0), 0.3), 70)
            for wy in range(y + 6, 204, 9):
                for wx in range(x + 3, x + w - 2, 7):
                    if (wx + wy + i) % 5 < 2:
                        _rect(c, wx, wy, 2, 3, highlight, 38)
        for i in range(8):
            w = 22 + (i * 11) % 16
            h = 40 + (i * 17) % 58
            x = (i * 39 + dx * 2) % (SW + 40) - 25
            y = 210 - h
            _rect(c, x, y, w, h, gfx.blend(gfx.blend(bg, tint, 0.17), (0, 0, 0), 0.18), 215)
            _rect(c, x, y, w, 2, gfx.blend(accent, (0, 0, 0), 0.25), 90)
            for wy in range(y + 6, 204, 11):
                for wx in range(x + 4, x + w - 3, 9):
                    if (wx * 3 + wy + i) % 7 < 3:
                        _rect(c, wx, wy, 3, 3, highlight if i % 3 else accent2, 50)
            _rect(c, x + w // 2, max(0, y - 9), 1, 9, gfx.blend(tint, (0, 0, 0), 0.2), 130)
            _pixel(c, x + w // 2, max(0, y - 10), (255, 96, 96),
                   90 + int(60 * (0.5 + 0.5 * math.sin(t * 5 + i))))
            if i in (1, 4, 6):
                col = accent2 if i % 2 else accent
                _rect(c, x + 2, y + 10, 2, max(2, h - 18), col, 40)
                _rect(c, x + 2, y + 10, 2, 2, (255, 255, 255), 70)
        drone_x = int(t * 11 + scene_index * 47) % (SW + 20) - 10
        drone_y = 68 + int(math.sin(t * 1.7) * 6)
        _rect(c, drone_x, drone_y, 3, 1, (10, 12, 16), 200)
        _pixel(c, drone_x - 1, drone_y, (255, 80, 80), 160)
        _pixel(c, drone_x + 3, drone_y, (80, 220, 255), 160)

    def _draw_beams(self, c, t, accent2, highlight):
        for i in range(3):
            alpha = 4 + i * 2
            for y in range(54, 340, 6):
                x = 148 + i * 26 + int((y - 54) * 0.42)
                _rect(c, x, y, 12 + i * 5, 6, accent2 if i % 2 else highlight, alpha)

    def _draw_floor(self, c, t, scene_index, tint, accent, accent2, highlight):
        for i in range(-2, 9):
            for step in range(10):
                u = step / 9.0
                x = SW / 2 + (i * 42 - SW / 2) * (0.15 + 0.85 * u)
                y = 340 + 140 * u
                _rect(c, x, y, 1, 4, accent, 9)
        for y in range(350, 480, 14):
            _rect(c, 0, y, SW, 1, accent, 9)
        for i in range(4):
            y = 392 + i * 20
            _rect(c, 26 + i * 16, y, 74 - i * 8, 2, tint, 16)
            _rect(c, 150 - i * 10, y + 6, 56 + i * 10, 1, accent2, 13)
        for i in range(3):
            _rect(c, 0, 318 + i * 7, SW, 7, gfx.blend(tint, (0, 0, 0), 0.4), 12)

    def _draw_foreground(self, c, t, scene_index, anim, env, accent, accent2, highlight):
        for i in range(18):
            x = (i * 47 + int(t * (3 + i % 4))) % SW
            y = (i * 31 + int(t * (2 + i % 3))) % 342
            a = 34 + (i * 17) % 86
            if env > 0.4 and abs(x - SW / 2) < 70:
                a += 30
            _pixel(c, x, y, highlight if i % 3 else accent2, a)
        if anim in ("sad", "error"):
            for i in range(16):
                x = (i * 41 + int(t * 70)) % SW
                y = (i * 53 + int(t * 120)) % 480
                _rect(c, x, y, 1, 4, highlight, 30)
        if anim in ("victory", "happy"):
            for i in range(14):
                x = (i * 37 + int(t * 20)) % SW
                y = (i * 43 + int(t * 35)) % 300
                _rect(c, x, y, 2, 2, (accent, accent2, highlight)[i % 3], 80)

    def _draw_face_overlay(self, c, x, y, scale, ch, t, anim, env, scene_index, yaw=0.0):
        if ch.get("type") not in ("human", "fantasy"):
            return
        s = scale
        head_x = 12.0
        eye_y = 11.0
        shift = int(round(yaw * 1.5))
        eye1, eye2 = head_x + 3 + shift, head_x + 11 + shift
        phase = (t + scene_index * 0.7) % 4.4
        blink = phase < 0.13
        if blink:
            _rect(c, x + eye1 * s, y + eye_y * s, 2 * s, 1 * s, ch["skin"], 255)
            _rect(c, x + eye2 * s, y + eye_y * s, 2 * s, 1 * s, ch["skin"], 255)
        else:
            dx = 0
            dy = 0
            if anim in ("point", "show"):
                dx = 1
            elif anim == "think":
                dx, dy = -1, -1
            elif anim in ("scared", "surprise"):
                dy = -1
            dx = max(-1, min(1, dx + int(round(math.sin(t * 1.1) * 0.5))))
            for ex in (eye1, eye2):
                _rect(c, x + (ex + dx) * s, y + (eye_y + dy) * s, 1 * s, 1 * s,
                      ch["eye_color"], 255)
                _pixel(c, x + (ex + dx) * s, y + (eye_y + dy) * s, (245, 245, 255), 190)
        brow_y = 8.0 if anim not in ("scared", "surprise") else 7.0
        brow = (18, 22, 28)
        if anim in ("error", "scared", "surprise"):
            _rect(c, x + (eye1 - 1) * s, y + brow_y * s, 4 * s, 1 * s, brow, 220)
            _rect(c, x + (eye2 - 1) * s, y + brow_y * s, 4 * s, 1 * s, brow, 220)
        elif anim in ("think", "sad"):
            _rect(c, x + eye1 * s, y + (brow_y + 1) * s, 3 * s, 1 * s, brow, 200)
            _rect(c, x + (eye2 - 1) * s, y + brow_y * s, 3 * s, 1 * s, brow, 200)
        mouth_x = head_x + 6 + shift
        mouth_y = 16.0
        dark = (18, 22, 28)
        if anim in ("victory", "happy") or ch.get("expression") == "smile":
            _rect(c, x + mouth_x * s, y + mouth_y * s, 3 * s, 1 * s, dark, 240)
            _rect(c, x + (mouth_x - 1) * s, y + (mouth_y - 1) * s, 1 * s, 1 * s, dark, 220)
            _rect(c, x + (mouth_x + 3) * s, y + (mouth_y - 1) * s, 1 * s, 1 * s, dark, 220)
        elif anim == "sad" or ch.get("expression") == "sad":
            _rect(c, x + mouth_x * s, y + (mouth_y + 1) * s, 3 * s, 1 * s, dark, 230)
        elif env > 0.08:
            mh = 1 + int(env * 1.8)
            _rect(c, x + mouth_x * s, y + (mouth_y - 1) * s, 3 * s, 1 * s,
                  (120, 70, 60), 230)
            _rect(c, x + mouth_x * s, y + mouth_y * s, 3 * s, mh * s,
                  (42, 18, 26), 245)
            if mh > 1:
                _rect(c, x + (mouth_x + 1) * s, y + (mouth_y + mh - 1) * s,
                      1 * s, 1 * s, (176, 88, 94), 220)
        else:
            _rect(c, x + mouth_x * s, y + mouth_y * s, 3 * s, 1 * s, dark, 230)
        if anim in ("victory", "happy"):
            _rect(c, x + (head_x + 1) * s, y + 14 * s, 2 * s, 1 * s, (235, 110, 130), 90)
            _rect(c, x + (head_x + 11) * s, y + 14 * s, 2 * s, 1 * s, (235, 110, 130), 90)
        if anim in ("scared", "error"):
            _rect(c, x + (head_x + 14) * s, y + 9 * s, 1 * s, 2 * s, (120, 220, 255), 170)
        if ch.get("accessory") == "glasses":
            gx = head_x + 3 + shift + int((math.sin(t * 2.4) + 1) * 1.5)
            _pixel(c, x + gx * s, y + 11 * s, (255, 255, 255), 150)
        hair = ch.get("hair")
        if hair:
            sway = int(round(math.sin(t * 2.2 + scene_index) * 1.2 + yaw * 1.5))
            _rect(c, x + (head_x - 2) * s + sway, y + 7 * s, 1 * s, 4 * s, hair, 190)
            _rect(c, x + (head_x + 15) * s + sway, y + 8 * s, 1 * s, 3 * s, hair, 170)

    def _draw_voice_bars(self, c, x, y, char_w, scale, t, env):
        base_y = 302
        for i in range(7):
            h = 2 + int(12 * env * (0.55 + 0.45 * math.sin(t * 7 + i * 1.25)))
            bx = x + char_w + 5 + i * 3
            if bx > SW - 3:
                break
            _rect(c, bx, base_y - h, 2, h,
                  (tuple(gfx.ACCENT) if i % 2 else tuple(gfx.HIGHLIGHT)), 135)

    def _draw_set(self, c, t, scene_index, set_id, tint, accent, accent2, highlight, good, bad, bg, card, muted):
        for i in range(15):
            u = i / 14.0
            shade = gfx.blend(gfx.blend(bg, tint, 0.05 + 0.10 * u), (0, 0, 0), 0.18 * (1 - u))
            _rect(c, 0, i * 16, SW, 18, shade)
        _rect(c, 0, 340, SW, 140, gfx.blend(gfx.blend(bg, tint, 0.08), (0, 0, 0), 0.28))
        _rect(c, 0, 338, SW, 3, accent)
        for i in range(9):
            _rect(c, 0, 348 + i * 15, SW, 1, gfx.blend(tint, (0, 0, 0), 0.4), 22)
        for x in (18, 112, 206):
            _rect(c, x, 9, 46, 3, highlight, 45)
            gfx.orb(c, x + 23, 12, 34, tint, 16, 2)

        if set_id == "gym":
            for x in (6, 212):
                _rect(c, x, 82, 50, 176, (10, 16, 22), 240)
                _rect(c, x + 2, 84, 46, 172, gfx.blend(bg, tint, 0.18), 220)
                _rect(c, x + 4, 86, 2, 168, highlight, 25)
                _rect(c, x + 2, 84, 46, 2, accent, 60)
                _rect(c, x + 18, 160, 10, 40, gfx.blend(accent, bg, 0.4), 35)
                _rect(c, x + 14, 200, 18, 3, highlight, 20)
            _rect(c, 12, 120, 4, 200, (30, 38, 46), 240)
            _rect(c, 42, 120, 4, 200, (30, 38, 46), 240)
            _rect(c, 10, 118, 38, 4, (50, 60, 70), 240)
            _rect(c, 8, 160, 42, 3, (170, 180, 190), 220)
            _rect(c, 4, 150, 6, 22, bad, 200)
            _rect(c, 48, 150, 6, 22, bad, 200)
            _rect(c, 10, 300, 40, 6, (20, 26, 32), 230)
            _rect(c, 16, 306, 4, 16, (40, 46, 56), 230)
            _rect(c, 40, 306, 4, 16, (40, 46, 56), 230)
            _rect(c, 206, 268, 58, 8, (20, 26, 32), 230)
            _rect(c, 210, 300, 50, 4, (50, 60, 70), 230)
            _rect(c, 214, 220, 34, 40, (20, 26, 32), 230)
            _rect(c, 218, 226, 26, 18, gfx.blend(bg, accent, 0.3), 230)
            _rect(c, 220, 230, 18, 2, highlight, 160)
            for i in range(3):
                _rect(c, 10 + i * 14, 318 - i * 4, 10, 4, (60, 60, 70), 230)
                _rect(c, 8 + i * 14, 314 - i * 4, 4, 10, accent, 160)
                _rect(c, 18 + i * 14, 314 - i * 4, 4, 10, accent, 160)
            _rect(c, 196, 56, 52, 3, accent2, 200)
            _rect(c, 200, 62, 44, 2, accent2, 120)
        elif set_id == "kitchen":
            for x in range(0, SW, 14):
                _rect(c, x, 40, 1, 300, (220, 210, 190), 12)
            for y in range(44, 340, 14):
                _rect(c, 0, y, SW, 1, (220, 210, 190), 10)
            for x in (6, 192):
                _rect(c, x, 62, 72, 62, (54, 40, 30), 240)
                _rect(c, x + 3, 65, 66, 56, (76, 56, 40), 240)
                _rect(c, x + 8, 108, 18, 3, (200, 180, 120), 200)
                _rect(c, x + 50, 108, 18, 3, (200, 180, 120), 200)
            _rect(c, 94, 76, 82, 92, (30, 26, 24), 240)
            _rect(c, 98, 80, 74, 84, gfx.blend(bg, tint, 0.25), 230)
            _rect(c, 134, 80, 2, 84, (30, 26, 24), 220)
            _rect(c, 98, 120, 74, 2, (30, 26, 24), 220)
            for i in range(7):
                _pixel(c, 104 + (i * 13) % 66, 88 + (i * 17) % 64, highlight, 80)
            _rect(c, 104, 54, 62, 6, (60, 60, 66), 240)
            _rect(c, 110, 60, 50, 12, (40, 44, 50), 220)
            _rect(c, 0, 300, SW, 10, (120, 86, 58), 240)
            _rect(c, 0, 310, SW, 30, (54, 40, 30), 240)
            for i in range(6):
                _rect(c, 8 + i * 44, 316, 32, 18, (72, 54, 40), 220)
                _rect(c, 20 + i * 44, 322, 8, 2, (200, 180, 120), 160)
            _rect(c, 66, 284, 54, 16, (40, 44, 50), 240)
            _rect(c, 72, 268, 26, 16, (60, 66, 76), 240)
            _rect(c, 70, 264, 30, 4, (90, 96, 106), 240)
            for i in range(3):
                sy = 256 - int((t * 14 + i * 7) % 14)
                _rect(c, 76 + i * 7, sy, 3, 4, (235, 235, 245), 55)
            _rect(c, 170, 288, 50, 10, (140, 100, 66), 230)
            _rect(c, 176, 282, 9, 7, (210, 70, 60), 230)
            _rect(c, 188, 281, 7, 8, (90, 180, 70), 230)
            _rect(c, 198, 283, 8, 6, (240, 180, 60), 230)
            for x in (80, 190):
                _rect(c, x, 30, 2, 18, (40, 40, 46), 220)
                _rect(c, x - 7, 48, 16, 4, (240, 200, 120), 220)
                gfx.orb(c, x, 52, 22, (255, 200, 120), 18, 2)
        elif set_id == "apartment":
            _rect(c, 62, 54, 146, 164, (16, 22, 30), 240)
            _rect(c, 66, 58, 138, 156, gfx.blend(bg, tint, 0.28), 230)
            _rect(c, 134, 58, 2, 156, (16, 22, 30), 220)
            _rect(c, 66, 130, 138, 2, (16, 22, 30), 220)
            for i in range(7):
                x = 70 + i * 19
                h = 18 + (i * 13) % 34
                y = 210 - h
                _rect(c, x, y, 16, h, gfx.blend(bg, accent, 0.25), 210)
                for wy in range(y + 6, 206, 10):
                    _rect(c, x + 3, wy, 3, 2, highlight, 60)
            _pixel(c, 186, 74, (230, 230, 220), 160)
            _rect(c, 50, 50, 14, 180, (40, 30, 34), 220)
            _rect(c, 206, 50, 14, 180, (40, 30, 34), 220)
            _rect(c, 4, 258, 62, 34, (40, 50, 60), 230)
            _rect(c, 8, 250, 54, 14, (50, 64, 76), 230)
            _rect(c, 12, 266, 20, 10, (70, 90, 100), 180)
            _rect(c, 36, 266, 20, 10, (70, 90, 100), 180)
            _rect(c, 224, 292, 14, 22, (60, 44, 34), 230)
            _rect(c, 226, 276, 10, 18, good, 200)
            _rect(c, 222, 270, 4, 8, gfx.blend(good, (255, 255, 255), 0.2), 180)
            _rect(c, 20, 80, 28, 20, (30, 40, 48), 230)
            _rect(c, 24, 84, 20, 12, accent2, 80)
        elif set_id == "classroom":
            _rect(c, 46, 64, 178, 150, (34, 40, 34), 240)
            _rect(c, 50, 68, 170, 142, (28, 54, 42), 240)
            for i in range(5):
                _rect(c, 60, 84 + i * 22, 60 + (i * 17) % 60, 2, (160, 210, 170), 80)
            _rect(c, 180, 150, 26, 2, (200, 220, 200), 60)
            _rect(c, 74, 180, 20, 2, (200, 220, 200), 60)
            _rect(c, 6, 286, 64, 10, (90, 66, 44), 240)
            _rect(c, 10, 296, 6, 30, (60, 44, 30), 240)
            _rect(c, 58, 296, 6, 30, (60, 44, 30), 240)
            _rect(c, 16, 270, 30, 16, (200, 200, 190), 210)
            _rect(c, 210, 160, 54, 170, (60, 44, 30), 240)
            for i in range(5):
                _rect(c, 214, 170 + i * 30, 46, 3, (90, 66, 44), 220)
                for j in range(5):
                    _rect(c, 216 + j * 9, 158 + i * 30, 6, 12,
                          (180, 60, 60) if (i + j) % 3 == 0 else
                          (60, 120, 180) if (i + j) % 3 == 1 else (220, 190, 80), 200)
            _rect(c, 226, 300, 16, 12, (60, 100, 160), 220)
            _rect(c, 230, 312, 8, 6, (180, 160, 120), 220)
        elif set_id == "server":
            for x in (6, 218):
                _rect(c, x, 80, 46, 260, (12, 16, 22), 240)
                for i in range(7):
                    y = 86 + i * 34
                    _rect(c, x + 3, y, 40, 28, (22, 28, 38), 240)
                    _rect(c, x + 7, y + 5, 4, 4,
                          good if (i + int(t * 4)) % 2 else accent, 220)
                    _rect(c, x + 14, y + 5, 4, 4, accent2, 180)
                    for j in range(4):
                        _rect(c, x + 7 + j * 8, y + 16, 6, 2, (80, 100, 120), 120)
            for i in range(3):
                _rect(c, 58 + i * 4, 60 + i * 6, 150 - i * 8, 2, accent2, 50)
            _rect(c, 196, 90, 60, 40, (10, 14, 20), 230)
            _rect(c, 200, 94, 52, 32, (16, 40, 60), 230)
            for i in range(5):
                _rect(c, 204, 100 + i * 5, 30 - i * 3, 2, good, 100)
        elif set_id == "clinic":
            _rect(c, 92, 66, 86, 86, (20, 30, 34), 240)
            _rect(c, 96, 70, 78, 78, gfx.blend(bg, tint, 0.25), 230)
            for i in range(7):
                _rect(c, 96, 72 + i * 11, 78, 2, (200, 220, 220), 40)
            _rect(c, 8, 96, 58, 46, (10, 16, 20), 240)
            _rect(c, 12, 100, 50, 38, (12, 40, 40), 230)
            for i in range(9):
                _rect(c, 16 + i * 5, 120 - (10 if i % 4 == 1 else 0), 4, 2, good, 180)
            _rect(c, 212, 160, 52, 170, (200, 210, 210), 230)
            for i in range(4):
                _rect(c, 216, 170 + i * 38, 44, 2, (140, 160, 160), 200)
                _rect(c, 230, 174 + i * 38, 16, 3, (120, 140, 140), 160)
            _rect(c, 222, 230, 12, 5, (240, 240, 250), 220)
            _rect(c, 222, 235, 12, 5, bad, 220)
        elif set_id == "airport":
            _rect(c, 56, 48, 158, 154, (20, 24, 34), 240)
            for i in range(10):
                u = i / 9.0
                _rect(c, 60, 52 + i * 14, 150, 16,
                      gfx.blend((255, 140, 80), (40, 40, 80), u), 200)
            _pixel(c, 190, 70, (255, 230, 180), 180)
            _rect(c, 100, 120, 50, 5, (20, 20, 26), 220)
            _rect(c, 118, 112, 18, 4, (20, 20, 26), 220)
            _rect(c, 122, 126, 12, 4, (20, 20, 26), 220)
            _rect(c, 6, 70, 44, 90, (10, 14, 20), 240)
            for i in range(6):
                _rect(c, 10, 80 + i * 13, 36, 2, accent if i % 2 else muted, 120)
            for i in range(3):
                _rect(c, 6 + i * 20, 280, 16, 10, (40, 50, 60), 230)
                _rect(c, 8 + i * 20, 270, 12, 12, (50, 64, 76), 230)
            _rect(c, 220, 286, 28, 22, (180, 90, 60), 230)
            _rect(c, 228, 280, 12, 6, (120, 60, 40), 220)
        elif set_id == "office":
            _rect(c, 68, 54, 142, 176, (14, 22, 30), 240)
            _rect(c, 72, 58, 134, 168, gfx.blend(bg, tint, 0.20), 220)
            for x in (104, 140, 176):
                _rect(c, x, 58, 1, 168, (200, 220, 240), 20)
            for i in range(6):
                x = 76 + i * 22
                h = 20 + (i * 17) % 40
                y = 220 - h
                _rect(c, x, y, 18, h, gfx.blend(bg, accent, 0.2), 200)
            _rect(c, 6, 80, 54, 74, (200, 210, 210), 230)
            for i in range(4):
                _rect(c, 12, 94 + i * 13, 40 - i * 5, 2, (60, 80, 90), 140)
            _rect(c, 6, 280, 84, 10, (50, 40, 34), 240)
            _rect(c, 10, 290, 6, 34, (30, 24, 20), 240)
            _rect(c, 72, 290, 6, 34, (30, 24, 20), 240)
            _rect(c, 16, 250, 40, 28, (12, 16, 22), 230)
            _rect(c, 20, 254, 32, 20, (18, 36, 54), 230)
            _rect(c, 80, 268, 8, 12, (200, 180, 150), 220)
            _rect(c, 228, 292, 14, 24, (60, 44, 34), 230)
            _rect(c, 230, 274, 10, 20, good, 200)
        elif set_id == "trading":
            for x, w in ((24, 92), (124, 118)):
                _rect(c, x, 60, w, 92, (10, 14, 22), 240)
                _rect(c, x + 3, 63, w - 6, 86, gfx.blend(bg, accent, 0.16), 230)
                for j in range(8):
                    _rect(c, x + 8 + j * 10, 120 - (j * 7) % 44, 5,
                          3 + (j * 5) % 18, good if j % 2 else bad, 140)
            _rect(c, 0, 300, SW, 12, (28, 30, 40), 240)
            _rect(c, 0, 312, SW, 26, (18, 20, 28), 240)
            _rect(c, 6, 220, 18, 80, (20, 24, 32), 230)
            for i in range(4):
                _rect(c, 9, 228 + i * 17, 12, 10, (30, 38, 50), 230)
                _pixel(c, 12, 232 + i * 17, good, 200)
            _rect(c, 214, 292, 24, 8, (220, 220, 210), 200)
            _rect(c, 220, 286, 16, 8, (200, 200, 190), 180)

    def _draw_topic_props(self, c, t, kind):
        prop = self.profile.get("prop")
        accent = tuple(gfx.ACCENT)
        accent2 = tuple(gfx.ACCENT2)
        highlight = tuple(gfx.HIGHLIGHT)
        good = tuple(gfx.GREEN)
        bad = tuple(gfx.BAD)
        muted = tuple(gfx.MUTED)
        if prop == "fitness":
            _rect(c, 10, 224, 34, 4, (12, 16, 20), 220)
            _rect(c, 6, 216, 8, 20, (30, 38, 46), 230)
            _rect(c, 40, 216, 8, 20, (30, 38, 46), 230)
            _rect(c, 7, 218, 3, 16, accent, 160)
            _rect(c, 41, 218, 3, 16, accent, 160)
            _rect(c, 232, 218, 10, 28, (40, 120, 180), 200)
            _rect(c, 234, 212, 6, 7, (20, 30, 40), 220)
            _rect(c, 234, 224, 6, 8, (120, 220, 255), 100)
            _rect(c, 196, 80, 58, 40, (6, 10, 16), 200)
            _rect(c, 198, 82, 54, 2, bad, 180)
            for i in range(9):
                _rect(c, 202 + i * 5, 100 - (10 if i % 4 == 1 else 0), 3, 2, bad, 160)
            _rect(c, 70, 326, 70, 4, (20, 60, 70), 150)
        elif prop == "cooking":
            _rect(c, 8, 236, 95, 16, (54, 38, 30), 230)
            _rect(c, 8, 236, 95, 3, (90, 66, 50), 220)
            _rect(c, 24, 218, 28, 18, (40, 44, 50), 240)
            _rect(c, 22, 215, 32, 4, (70, 76, 86), 240)
            _rect(c, 34, 212, 8, 3, (20, 22, 26), 200)
            for i in range(3):
                sy = 204 - int((t * 14 + i * 7) % 16)
                _rect(c, 29 + i * 7, sy, 3, 4, (230, 230, 240), 60)
            _rect(c, 150, 234, 60, 12, (120, 86, 58), 230)
            _rect(c, 158, 228, 10, 8, (210, 70, 60), 230)
            _rect(c, 172, 227, 8, 9, (90, 180, 70), 230)
            _rect(c, 184, 229, 9, 7, (240, 180, 60), 230)
            _rect(c, 204, 80, 50, 36, (6, 10, 16), 200)
            _rect(c, 206, 82, 46, 2, accent, 180)
            _rect(c, 212, 94, 38, 3, accent2, 160)
        elif prop == "realestate":
            _rect(c, 14, 200, 62, 54, (18, 30, 40), 220)
            for i in range(6):
                _rect(c, 14 + i * 10, 200 - i * 4, 62 - i * 20, 8, (28, 50, 60), 210)
            _rect(c, 24, 224, 10, 12, highlight, 120)
            _rect(c, 44, 224, 10, 12, highlight, 120)
            _rect(c, 34, 242, 10, 12, accent, 150)
            _rect(c, 70, 232, 14, 5, (240, 200, 90), 220)
            _rect(c, 74, 236, 6, 18, (90, 70, 50), 200)
            _rect(c, 226, 230, 16, 4, (200, 180, 90), 220)
            _rect(c, 238, 226, 6, 6, (200, 180, 90), 220)
            _rect(c, 242, 228, 3, 3, (6, 10, 16), 220)
        elif prop == "education":
            for i, col in enumerate(((200, 70, 70), (70, 140, 220), (220, 190, 80))):
                _rect(c, 12, 236 - i * 6, 34 - i * 3, 6, col, 230)
            _rect(c, 16, 216, 4, 20, (180, 180, 190), 220)
            _rect(c, 16, 214, 4, 3, (240, 160, 120), 240)
            _rect(c, 210, 100, 30, 6, (20, 24, 30), 230)
            _rect(c, 218, 94, 14, 6, (30, 36, 44), 230)
            _rect(c, 224, 106, 2, 10, (240, 200, 90), 220)
            for i in range(4):
                _rect(c, 200, 124 + i * 8, 40 - i * 5, 2, (140, 220, 170), 100)
        elif prop == "tech":
            _rect(c, 10, 96, 46, 86, (14, 20, 28), 230)
            for i in range(3):
                y = 102 + i * 26
                _rect(c, 14, y, 38, 20, (24, 34, 46), 240)
                _rect(c, 17, y + 5, 5, 4, good if int(t * 3 + i) % 2 else accent, 220)
                _rect(c, 26, y + 5, 5, 4, accent2, 180)
                _rect(c, 35, y + 5, 5, 4, bad if int(t * 2 + i) % 3 else muted, 180)
                for j in range(3):
                    _rect(c, 17 + j * 10, y + 13, 8, 2, (80, 100, 120), 120)
            for i in range(5):
                _rect(c, 196, 110 + i * 10, 50 - i * 6, 2, accent2, 60)
                _pixel(c, 250 - i * 6, 110 + i * 10, highlight, 120)
        elif prop == "health":
            for dx, dy in ((4, 4), (7, 7), (10, 4), (13, 7), (10, 13), (7, 13)):
                _rect(c, 20 + dx * 2, 170 + dy * 2, 8, 8, bad, 180)
            _rect(c, 196, 84, 58, 40, (6, 10, 16), 200)
            for i in range(10):
                y = 104 - (10 if i % 4 == 1 else 0)
                _rect(c, 200 + i * 5, y, 4, 2, good, 180)
            _rect(c, 220, 230, 14, 6, (240, 240, 250), 220)
            _rect(c, 220, 236, 14, 6, (200, 70, 80), 220)
        elif prop == "travel":
            px = 200 + int(math.sin(t * 0.3) * 4)
            _rect(c, px, 92, 30, 5, (220, 230, 240), 220)
            _rect(c, px + 10, 86, 14, 4, (220, 230, 240), 220)
            _rect(c, px + 12, 98, 8, 4, (220, 230, 240), 220)
            _rect(c, px + 26, 90, 4, 10, (220, 230, 240), 220)
            _rect(c, 14, 226, 34, 24, (180, 90, 60), 230)
            _rect(c, 22, 220, 18, 6, (120, 60, 40), 220)
            _rect(c, 18, 232, 4, 12, (240, 200, 90), 200)
            _rect(c, 70, 154, 8, 12, bad, 220)
            _rect(c, 68, 146, 12, 12, bad, 220)
            _rect(c, 72, 150, 4, 4, (240, 240, 250), 230)
        elif prop == "business":
            _rect(c, 10, 244, 96, 14, (44, 34, 28), 230)
            _rect(c, 18, 210, 54, 34, (12, 16, 22), 230)
            _rect(c, 22, 214, 46, 26, (20, 40, 60), 230)
            for i in range(4):
                _rect(c, 26 + i * 10, 234 - i * 5, 7, 4 + i * 4, accent, 200)
            _rect(c, 80, 234, 8, 10, (200, 180, 150), 220)
            _rect(c, 120, 244, 24, 8, (220, 220, 210), 200)

    def _draw_chart_panel(self, c, t, chart, accent, accent2, highlight, good, bad, bg, card, muted):
        _rect(c, 52, 70, 168, 172, gfx.blend(card, (0, 0, 0), 0.06))
        _rect(c, 58, 76, 156, 160, gfx.blend(bg, accent, 0.12))
        _rect(c, 52, 70, 168, 2, accent, 170)
        _rect(c, 52, 70, 2, 172, accent, 70)
        for i in range(5):
            _rect(c, 60, 88 + i * 28, 152, 1, gfx.blend(muted, bg, 0.55))
        if chart == "progress":
            for i in range(5):
                y = 92 + i * 26
                w = 24 + 104 * (0.30 + 0.12 * i) + int(5 * math.sin(t * 1.4 + i))
                _rect(c, 64, y, 132, 10, gfx.blend(bg, muted, 0.35), 210)
                _rect(c, 64, y, min(132, int(w)), 10, accent if i % 2 else accent2, 225)
                _rect(c, 64, y, min(132, int(w)), 2, highlight, 200)
                _rect(c, 200, y + 2, 8, 6, good if i > 2 else muted, 180)
            _rect(c, 64, 226, 90, 2, muted, 120)
        elif chart == "timer":
            cx, cy, r = 136, 144, 50
            progress = 0.55 + 0.25 * math.sin(t * 0.25)
            for a in range(0, 360, 6):
                rad = math.radians(a)
                x = cx + math.cos(rad) * r
                y = cy + math.sin(rad) * r
                on = a / 360.0 <= progress
                _rect(c, x - 2, y - 2, 4, 4,
                      accent if on else gfx.blend(muted, bg, 0.55), 220 if on else 80)
            _rect(c, cx - 16, cy - 4, 32, 8, gfx.blend(card, accent, 0.2), 220)
            _rect(c, cx - 12, cy - 1, 24, 2, highlight, 200)
            for i in range(3):
                sy = 84 - int((t * 12 + i * 9) % 20)
                _rect(c, cx - 10 + i * 8, sy, 3, 3,
                      gfx.blend(highlight, bg, 0.4), 90)
        elif chart == "ecg":
            pts = []
            for i in range(56):
                x = 64 + i * 2.6
                base = 150
                u = (i * 0.35 + t * 2.2) % 6.0
                y = base
                if 2.5 < u < 2.8:
                    y = base - 44
                elif 2.8 <= u < 3.05:
                    y = base + 22
                elif 3.05 <= u < 3.3:
                    y = base - 14
                pts.append((x, y))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, good, 190)
            _rect(c, 64, 220, 144, 1, muted, 80)
        elif chart == "funnel":
            for i, w in enumerate((150, 120, 90, 60)):
                y = 88 + i * 34
                _rect(c, 136 - w // 2, y, w, 26, accent if i < 2 else accent2, 210)
                _rect(c, 136 - w // 2, y, w, 3, highlight, 180)
                _rect(c, 136 - w // 2 + 4, y + 6, max(8, w - 30), 2, bg, 90)
        elif chart == "line":
            pts = []
            for i in range(14):
                x = 64 + i * 10
                y = 190 - i * 6 - (i * 13) % 28 + int(math.sin(t * 0.7 + i) * 4)
                pts.append((x, y))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, accent2, 180)
            for x, y in pts[::3]:
                _rect(c, x - 1, y - 1, 3, 3, highlight, 200)
            for x in range(62, 210, 8):
                _rect(c, x, 120, 4, 1, highlight, 70)
        elif chart == "bars":
            for i in range(10):
                x = 64 + i * 13
                h = 18 + (i * 17) % 60
                _rect(c, x, 220 - h, 9, h, accent if i % 2 else accent2, 210)
                _rect(c, x, 220 - h, 9, 2, highlight, 180)
        else:
            closes = []
            for i in range(12):
                x = 64 + i * 12
                wobble = math.sin(t * 0.55 + i * 0.7) * 3
                base_y = 198 - i * 7 - (i * 13) % 24
                oy = base_y + wobble
                cy = oy - (8 + (i * 11) % 16)
                hi = min(oy, cy) - 5 - (i * 7) % 10
                lo = max(oy, cy) + 4 + (i * 5) % 8
                color = good if cy < oy else bad
                _rect(c, x + 3, hi, 1, max(2, lo - hi), color, 190)
                _rect(c, x, min(oy, cy), 7, max(3, abs(oy - cy)), color, 230)
                if i == 11:
                    _rect(c, x - 2, hi - 2, 11, max(4, lo - hi) + 4, highlight, 35)
                closes.append((x + 3, cy))
            for (x1, y1), (x2, y2) in zip(closes, closes[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, accent2, 150)
            for x in range(62, 210, 8):
                _rect(c, x, 108, 4, 1, highlight, 80)
            _rect(c, 198, 105, 12, 6, highlight, 120)
            for i in range(12):
                x = 64 + i * 12
                h = 4 + (i * 7) % 12
                _rect(c, x, 232 - h, 7, h, accent if i % 3 else accent2, 60)
            sx = 60 + int((t * 26) % 150)
            _rect(c, sx, 78, 1, 156, highlight, 18)
            _lx, ly = closes[-1]
            _rect(c, 196, ly - 3, 14, 6, good, 180)
            _rect(c, 197, ly - 2, 5, 1, (10, 14, 10), 180)

    def _draw_chart_panel_v2(self, c, t, chart, accent, accent2, highlight, good, bad, bg, card, muted):
        _rect(c, 52, 70, 168, 172, gfx.blend(card, (0, 0, 0), 0.06))
        _rect(c, 58, 76, 156, 160, gfx.blend(bg, accent, 0.12))
        _rect(c, 52, 70, 168, 2, accent, 170)
        _rect(c, 52, 70, 2, 172, accent, 70)
        # HUD corners + live tag
        for cx, cy, sx, sy in ((54, 72, 1, 1), (218, 72, -1, 1),
                               (54, 240, 1, -1), (218, 240, -1, -1)):
            _rect(c, min(cx, cx + 7 * sx), cy, 7, 1, accent, 150)
            _rect(c, cx, min(cy, cy + 7 * sy), 1, 7, accent, 150)
        _rect(c, 56, 74, 3, 3, bad, 210)
        _rect(c, 61, 75, 8, 1, muted, 100)
        for i in range(5):
            _rect(c, 60, 88 + i * 28, 152, 1, gfx.blend(muted, bg, 0.55))
        sx = 60 + int((t * 22) % 150)
        _rect(c, sx, 78, 1, 156, highlight, 14)

        if chart == "progress":
            for i in range(5):
                y = 92 + i * 26
                grow = gfx.ease_out(gfx.clamp((t - 0.10 - i * 0.07) / 0.4))
                base = 24 + 104 * (0.30 + 0.12 * i) + int(4 * math.sin(t * 1.4 + i))
                w = max(2, int(base * grow))
                _rect(c, 64, y, 132, 10, gfx.blend(bg, muted, 0.35), 210)
                _rect(c, 64, y, min(132, w), 10, accent if i % 2 else accent2, 225)
                _rect(c, 64, y, min(132, w), 2, highlight, 200)
                hx = 64 + min(132, w)
                _rect(c, hx - 2, y - 2, 2, 14, highlight, 180)
                _rect(c, 64 + int(132 * 0.8), y - 3, 1, 16, highlight, 60)
            _rect(c, 64, 226, 90, 2, muted, 120)
        elif chart == "timer":
            cx, cy, r = 136, 144, 50
            progress = 0.15 + 0.75 * gfx.ease_out(gfx.clamp(t / 2.8))
            for a in range(0, 360, 6):
                rad = math.radians(a)
                x = cx + math.cos(rad) * r
                y = cy + math.sin(rad) * r
                on = a / 360.0 <= progress
                _rect(c, x - 2, y - 2, 4, 4,
                      accent if on else gfx.blend(muted, bg, 0.55), 220 if on else 80)
            for a in range(0, 360, 30):
                rad = math.radians(a)
                _rect(c, cx + math.cos(rad) * (r + 5) - 1, cy + math.sin(rad) * (r + 5) - 1,
                      2, 2, muted, 100)
            hx = cx + math.cos(math.radians(progress * 360)) * r
            hy = cy + math.sin(math.radians(progress * 360)) * r
            _rect(c, hx - 2, hy - 2, 4, 4, highlight, 240)
            _rect(c, cx - 16, cy - 4, 32, 8, gfx.blend(card, accent, 0.2), 220)
            _rect(c, cx - 12, cy - 1, 24, 2, highlight, 200)
            for i in range(3):
                sy = 84 - int((t * 12 + i * 9) % 20)
                _rect(c, cx - 10 + i * 8, sy, 3, 3,
                      gfx.blend(highlight, bg, 0.4), 90)
        elif chart == "ecg":
            pts = []
            for i in range(56):
                x = 64 + i * 2.6
                base = 150
                u = (i * 0.35 + t * 2.2) % 6.0
                y = base
                if 2.5 < u < 2.8:
                    y = base - 44
                elif 2.8 <= u < 3.05:
                    y = base + 22
                elif 3.05 <= u < 3.3:
                    y = base - 14
                pts.append((x, y))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, good, 190)
            if pts:
                hx, hy = pts[-1]
                _rect(c, hx - 2, hy - 2, 4, 4, highlight, 240)
                _rect(c, hx, 78, 1, 150, good, 22)
            _rect(c, 64, 220, 144, 1, muted, 80)
        elif chart == "funnel":
            for i, w in enumerate((150, 120, 90, 60)):
                grow = gfx.ease_out(gfx.clamp((t - 0.10 - i * 0.08) / 0.4))
                ww = max(4, int(w * grow))
                y = 88 + i * 34
                _rect(c, 136 - ww // 2, y, ww, 26, accent if i < 2 else accent2, 210)
                _rect(c, 136 - ww // 2, y, ww, 3, highlight, 180)
                _rect(c, 136 - ww // 2 + 4, y + 6, max(8, ww - 30), 2, bg, 90)
        elif chart == "line":
            pts = []
            for i in range(14):
                x = 64 + i * 10
                y = 190 - i * 6 - (i * 13) % 28 + int(math.sin(t * 0.7 + i) * 4)
                pts.append((x, y))
            draw = gfx.ease_out(gfx.clamp((t - 0.10) / 0.9))
            n = max(2, int(len(pts) * draw))
            shown = pts[:n]
            for (x1, y1), (x2, y2) in zip(shown, shown[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, accent2, 180)
            for x, y in shown[::3]:
                _rect(c, x - 1, y - 1, 3, 3, highlight, 200)
            if shown:
                hx, hy = shown[-1]
                _rect(c, hx - 2, hy - 2, 4, 4, highlight, 240)
                _rect(c, hx, 78, 1, 150, highlight, 22)
            for x in range(62, 210, 8):
                _rect(c, x, 120, 4, 1, highlight, 70)
        elif chart == "bars":
            for i in range(10):
                grow = gfx.ease_out(gfx.clamp((t - 0.10 - i * 0.04) / 0.4))
                x = 64 + i * 13
                h = max(2.0, (18 + (i * 17) % 60) * grow)
                _rect(c, x, 220 - h, 9, h, accent if i % 2 else accent2, 210)
                _rect(c, x, 220 - h, 9, 2, highlight, 180)
                if i == 9:
                    _rect(c, x - 1, 220 - h - 3, 11, 1, highlight, 110)
        else:
            closes = []
            built = 0
            for i in range(12):
                build = gfx.ease_out(gfx.clamp((t - 0.08 - i * 0.045) / 0.34))
                if build <= 0.01:
                    continue
                built += 1
                x = 64 + i * 12
                wobble = math.sin(t * 0.55 + i * 0.7) * 3
                base_y = 198 - i * 7 - (i * 13) % 24
                oy = base_y + wobble
                cy = oy - (8 + (i * 11) % 16)
                cy_b = oy + (cy - oy) * build
                hi = min(oy, cy_b) - (5 + (i * 7) % 10) * build
                lo = max(oy, cy_b) + (4 + (i * 5) % 8) * build
                color = good if cy < oy else bad
                _rect(c, x + 3, hi, 1, max(2, lo - hi), color, int(190 * build))
                _rect(c, x, min(oy, cy_b), 7, max(2, abs(cy_b - oy)), color, int(230 * build))
                if i == 11:
                    pulse = 0.5 + 0.5 * math.sin(t * 4.0)
                    _rect(c, x - 2, hi - 2, 11, max(4, lo - hi) + 4, highlight,
                          int(25 + 30 * pulse))
                closes.append((x + 3, cy_b))
            for (x1, y1), (x2, y2) in zip(closes, closes[1:]):
                _pixel_line(c, x1, y1, x2, y2, 1, accent2, 150)
            # target / entry / stop levels
            for x in range(62, 210, 8):
                _rect(c, x, 108, 4, 1, highlight, 80)
                _rect(c, x, 168, 4, 1, accent2, 55)
                _rect(c, x, 208, 4, 1, bad, 45)
            _rect(c, 198, 105, 12, 6, highlight, 120)
            _rect(c, 198, 165, 12, 6, accent2, 100)
            _rect(c, 198, 205, 12, 6, bad, 90)
            for i in range(12):
                grow = gfx.ease_out(gfx.clamp((t - 0.22 - i * 0.04) / 0.4))
                h = max(1.0, (4 + (i * 7) % 12) * grow)
                x = 64 + i * 12
                _rect(c, x, 232 - h, 7, h, accent if i % 3 else accent2, 60)
            if closes:
                lx, ly = closes[-1]
                _rect(c, lx - 1, ly - 1, 3, 3, highlight, 230)
                for yy in range(int(ly) + 4, 232, 4):
                    _rect(c, lx, yy, 1, 2, highlight, 55)
                _rect(c, 196, ly - 3, 14, 6, good, 180)
                _rect(c, 197, ly - 2, 5, 1, (10, 14, 10), 180)
                for s in range(3):
                    _rect(c, lx + math.sin(t * 6 + s) * 4, ly - 6 - s * 3,
                          1, 1, highlight, 120)

    def _draw_cards(self, c, scene, t):
        kind = str(scene.get("kind") or "")
        profile = self.profile
        raw = (profile.get("cards_by_kind", {}).get(kind)
               or profile.get("cards")
               or [("ГЛАВНОЕ", "3", "accent"), ("ИТОГ", "1", "green")])
        color_map = {
            "accent": tuple(gfx.ACCENT), "accent2": tuple(gfx.ACCENT2),
            "green": tuple(gfx.GREEN), "bad": tuple(gfx.BAD),
            "highlight": tuple(gfx.HIGHLIGHT),
        }
        sparks = (
            (0.18, 0.32, 0.26, 0.52, 0.44, 0.72, 0.92),
            (0.74, 0.61, 0.68, 0.45, 0.52, 0.34, 0.28),
        )
        cards = []
        for i, item in enumerate(raw[:2]):
            label, value = item[0], item[1]
            color = color_map.get(item[2] if len(item) > 2 else "accent",
                                  tuple(gfx.ACCENT))
            spark = item[3] if len(item) > 3 else sparks[i % 2]
            if kind in ("problem", "error") and i == 0:
                color = tuple(gfx.BAD)
                spark = tuple(reversed(spark))
            cards.append((label, value, color, spark))
        positions = ((30, 1076, 276, 138, -1, 0.38), (774, 1110, 276, 132, 1, 0.52))

        for card_index, ((label, value, color, spark), (x, y, w, h, side, delay)) in enumerate(zip(cards, positions)):
            k = gfx.clamp((t - delay) / 0.55)
            if k <= 0.01:
                continue
            slide = gfx.ease_out_back(k, 1.5)
            dx = int((1 - slide) * side * 210)
            yy = y + int(math.sin(t * 1.3 + side) * 1.6)
            xx = x + dx
            panel = skia.Rect.MakeXYWH(xx, yy, w, h)
            pulse = 0.5 + 0.5 * math.sin(t * 3.4 + side)
            border_a = int(150 + 70 * pulse * k)
            gfx.rrect(c, xx, yy, w, h, 16, fill=(4, 8, 14), alpha=int(220 * k),
                      stroke=color, sw=1.4)
            gfx.rrect(c, xx + 2, yy + 2, w - 4, h - 4, 14, fill=None,
                      stroke=color, sw=0.6, alpha=border_a)
            # HUD corner brackets
            arm = 14
            for cx, cy, sx, sy in ((xx + 8, yy + 8, 1, 1), (xx + w - 8, yy + 8, -1, 1),
                                   (xx + 8, yy + h - 8, 1, -1), (xx + w - 8, yy + h - 8, -1, -1)):
                gfx.line(c, cx, cy, cx + arm * sx, cy, color, 2, int(190 * k), cap=False)
                gfx.line(c, cx, cy, cx, cy + arm * sy, color, 2, int(190 * k), cap=False)
            # header
            gfx.dot(c, xx + 18, yy + 24, 3.5, color, int(220 * k))
            gfx.draw_text(c, label, xx + 28, yy + 30, "mono", 15, gfx.MUTED,
                          int(220 * k), tracking=1.4)
            gfx.draw_text(c, f"{card_index + 1:02d}", xx + w - 16, yy + 29,
                          "mono", 11, color, int(150 * k), "right", tracking=1.0)
            # big value
            gfx.draw_text(c, _count_value(value, k), xx + 18, yy + 68, "black", 34,
                          color, int(250 * k), tracking=-0.7)

            # chart area
            cx0, cy0 = xx + 18, yy + 82
            cw, chh = w - 36, h - 94
            c.save()
            c.clipRect(skia.Rect.MakeXYWH(cx0, cy0, cw, chh))
            for gi in range(3):
                gy = cy0 + chh * (0.25 + gi * 0.25)
                for gx in range(int(cx0), int(cx0 + cw), 10):
                    _rect(c, gx, gy, 4, 1, gfx.MUTED, 26)
            draw_k = gfx.clamp((t - delay - 0.10) / 0.70)
            if card_index == 0:
                # glowing area/line chart
                n = len(spark)
                pts = []
                for i, v in enumerate(spark):
                    px = cx0 + cw * i / (n - 1)
                    py = cy0 + chh - 3 - v * (chh - 7)
                    pts.append((px, py))
                visible = 1 + int(draw_k * (n - 1))
                shown = pts[:visible]
                if visible < n and shown:
                    nxt = pts[visible]
                    u = (draw_k * (n - 1)) - (visible - 1)
                    shown = shown + [(shown[-1][0] + (nxt[0] - shown[-1][0]) * u,
                                      shown[-1][1] + (nxt[1] - shown[-1][1]) * u)]
                if len(shown) >= 2:
                    area = skia.Path()
                    area.moveTo(shown[0][0], cy0 + chh)
                    for px, py in shown:
                        area.lineTo(px, py)
                    area.lineTo(shown[-1][0], cy0 + chh)
                    area.close()
                    fill = skia.Paint(AntiAlias=True)
                    fill.setShader(skia.GradientShader.MakeLinear(
                        [skia.Point(0, cy0), skia.Point(0, cy0 + chh)],
                        [gfx.col(color, 95), gfx.col(color, 0)],
                        [0.0, 1.0],
                    ))
                    c.drawPath(area, fill)
                    for (x1, y1), (x2, y2) in zip(shown, shown[1:]):
                        gfx.glow_line(c, x1, y1, x2, y2, color, 3, int(230 * k))
                    lx, ly = shown[-1]
                    gfx.dot(c, lx, ly, 5, color, int(250 * k))
                    gfx.dot(c, lx, ly, 11, color, int(55 * k))
                    _rect(c, lx, cy0 + 1, 1, chh - 2, color, 40)
                    # trailing sparks
                    for si in range(3):
                        sx = lx - 10 - si * 9
                        sy = ly + math.sin(t * 5 + si) * 4
                        gfx.dot(c, sx, sy, max(1.5, 3 - si * 0.6), color, int(90 * k))
            else:
                # animated bars with staggered bounce
                n = len(spark)
                bw = cw / n * 0.62
                for i, v in enumerate(spark):
                    bx = cx0 + cw * i / n + (cw / n - bw) / 2
                    bk = gfx.clamp((t - delay - 0.14 - i * 0.045) / 0.38)
                    bk = gfx.ease_out_back(bk, 1.8) if bk < 1.0 else 1.0
                    bh = max(2.0, (chh - 4) * v * bk)
                    by = cy0 + chh - bh
                    bar_color = color if i % 2 == 0 else tuple(gfx.ACCENT2)
                    gfx.rrect(c, bx, by, bw, bh, 2.5, fill=bar_color,
                              alpha=int(210 * k))
                    gfx.rrect(c, bx, by, bw, min(3, bh), 2.5, fill=tuple(gfx.HIGHLIGHT),
                              alpha=int(190 * k))
                    if i == n - 1:
                        gfx.dot(c, bx + bw / 2, by - 3, 3, tuple(gfx.HIGHLIGHT),
                                int(220 * k))
                # target line
                ty = cy0 + chh * 0.28
                for gx in range(int(cx0), int(cx0 + cw), 10):
                    _rect(c, gx, ty, 5, 1, tuple(gfx.HIGHLIGHT), 70)
            c.restore()

            # scan shine
            scan = (t * 0.42 + side * 0.23) % 1.0
            bx = xx + scan * (w + 80) - 40
            shine = skia.Path()
            shine.moveTo(bx, yy + 4)
            shine.lineTo(bx + 26, yy + 4)
            shine.lineTo(bx + 8, yy + h - 4)
            shine.lineTo(bx - 18, yy + h - 4)
            shine.close()
            sp = skia.Paint(AntiAlias=True)
            sp.setColor(gfx.col(tuple(gfx.TEXT), int(16 * k)))
            c.drawPath(shine, sp)

    def _draw_ticker(self, c, t):
        text = str(self.profile.get("ticker") or "").strip()
        if not text:
            return
        y = 1632
        gfx.rrect(c, 40, y, config.W - 80, 34, 10, fill=(4, 8, 12), alpha=120)
        tw = gfx.text_w(text, "mono", 18, 1.2)
        span = tw + 90
        start = 54 - int((t * 48) % span)
        for k in range(2):
            gfx.draw_text(c, text, start + k * span, y + 23, "mono", 18,
                          gfx.MUTED, 150, tracking=1.2)

    def _draw_disclaimer(self, c):
        text = str(self.settings.get("disclaimer") or "").strip()
        if not text:
            return
        gfx.draw_text(c, text.upper(), config.W / 2, 1808, "mono", 15,
                      gfx.MUTED, 120, "center", tracking=1.0)

    def _draw_mascot(self, c, t, anim, tint):
        if self.settings.get("pixel_mascot", True) is False:
            return
        jump = 0
        shake = 0
        if anim in ("victory", "happy"):
            jump = int(abs(math.sin(t * 7.0)) * 4)
        elif anim == "error":
            shake = int(math.sin(t * 22.0) * 2)
        bob = int(math.sin(t * 3.1) * 1.2)
        x = SW - 34 + shake
        y = 312 - jump + bob
        body = (228, 78, 60)
        light = (255, 148, 96)
        dark = (118, 32, 34)
        _rect(c, x + 1, y + 15, 14, 3, (0, 0, 0), 90)
        _rect(c, x + 2, y + 2, 12, 13, body)
        _rect(c, x + 3, y + 1, 10, 2, body)
        _rect(c, x + 4, y + 3, 5, 2, light, 220)
        _rect(c, x + 3, y + 12, 10, 3, dark, 180)
        # feet
        _rect(c, x + 4, y + 14, 3, 3, dark)
        _rect(c, x + 10, y + 14, 3, 3, dark)
        blink = int(t * 2.2) % 6 == 0
        if anim == "error":
            _rect(c, x + 5, y + 6, 1, 1, dark)
            _rect(c, x + 7, y + 6, 1, 1, dark)
            _rect(c, x + 5, y + 8, 1, 1, dark)
            _rect(c, x + 7, y + 8, 1, 1, dark)
            _rect(c, x + 9, y + 6, 1, 1, dark)
            _rect(c, x + 11, y + 6, 1, 1, dark)
            _rect(c, x + 9, y + 8, 1, 1, dark)
            _rect(c, x + 11, y + 8, 1, 1, dark)
        elif blink:
            _rect(c, x + 5, y + 7, 3, 1, dark)
            _rect(c, x + 9, y + 7, 3, 1, dark)
        else:
            _rect(c, x + 5, y + 6, 3, 3, (248, 248, 255))
            _rect(c, x + 9, y + 6, 3, 3, (248, 248, 255))
            _rect(c, x + 6, y + 7, 1, 1, dark)
            _rect(c, x + 10, y + 7, 1, 1, dark)
        if anim in ("victory", "happy"):
            _rect(c, x + 6, y + 11, 4, 1, dark)
            _rect(c, x + 5, y + 10, 1, 1, dark)
            _rect(c, x + 11, y + 10, 1, 1, dark)
        elif anim in ("sad", "error"):
            _rect(c, x + 7, y + 12, 3, 1, dark)
        elif anim in ("talk", "explain", "point", "show"):
            _rect(c, x + 7, y + 11, 3, 2, dark)
        else:
            _rect(c, x + 7, y + 11, 3, 1, dark)
        _rect(c, x + 3, y + 5, 1, 2, light, 180)

    def _draw_character_fx(self, c, scene, t, x, y, char_w, scale, anim):
        bg, card, accent, accent2, highlight, good, bad, text, muted = self._palette()
        kind = scene.get("kind", "statement")
        fade = min(1.0, max(0.0, t / 0.5))
        if anim in ("victory", "happy") or kind == "cta":
            for i in range(18):
                px = (i * 47 + int(t * 26)) % SW
                py = (i * 29 + int(t * (18 + i % 5))) % 210
                color = (good, accent, accent2, highlight)[i % 4]
                _rect(c, px, py, 2, 2, color, int(150 * fade))
        if anim == "error":
            for i in range(4):
                gy = 30 + (i * 37 + int(t * 13)) % 170
                _rect(c, (i * 53) % SW, gy, 18 + (i * 7) % 24, 1, bad, 80)
        left = x - 24
        right = x + char_w + 6
        rows = (y + 16, y + 52, y + 86)
        if kind in ("chart", "stat", "bars", "dashboard", "terminal"):
            icons = (("arrow_up", good), ("coin", (255, 198, 86)))
        elif kind in ("checklist", "timeline", "compare"):
            icons = (("check", good), ("star", highlight))
        elif kind == "cta":
            icons = (("heart", accent2), ("star", (255, 198, 86)))
        elif anim == "error":
            icons = (("cross", bad), ("question", (255, 198, 86)))
        elif anim == "think":
            icons = (("question", highlight), ("coin", (255, 198, 86)))
        elif anim == "show":
            icons = (("coin", (255, 198, 86)), ("check", good))
        else:
            icons = (("question", accent), ("star", (255, 198, 86)))
        for i, (name, color) in enumerate(icons):
            bob = math.sin(t * 2.4 + i * 1.7) * 4
            ix = left if i % 2 == 0 else right
            iy = rows[i] + bob
            _draw_icon(c, name, ix, iy, color, 2, int(190 * fade))
        if t < 0.55:
            k = 1.0 - t / 0.55
            for i in range(14):
                ang = i * math.pi * 2 / 14
                r = 14 + 62 * (t / 0.55)
                px = x + char_w / 2 + math.cos(ang) * r
                py = y + 58 * scale + math.sin(ang) * r * 0.7
                _rect(c, px, py, 2, 2, accent if i % 2 else highlight, int(150 * k))

    def _draw_world(self, c, scene, t, scene_index):
        bg, card, accent, accent2, highlight, good, bad, text, muted = self._palette()
        parallax = bool(self.settings.get("pixel_parallax", True))
        if parallax:
            bg_shift = math.sin(t * 0.25 + scene_index * 0.8) * 2.8
            bg_lift = math.sin(t * 0.19 + scene_index) * 1.6
            c.save()
            c.translate(SW / 2, SH / 2)
            c.scale(1.035, 1.035)
            c.translate(-SW / 2, -SH / 2)
            c.translate(bg_shift, bg_lift)
        visual = scene.get("pixel_visual")
        if not visual or visual == "auto":
            visual = self.settings.get("pixel_background") or _default_visual(
                scene.get("kind", "statement"), self.profile)
        if visual not in VISUALS:
            visual = _default_visual(scene.get("kind", "statement"), self.profile)

        _rect(c, 0, 0, SW, SH, bg)
        kind = str(scene.get("kind") or "")
        tint = tuple(self.profile.get("tint", (64, 140, 255)))
        if kind == "problem":
            tint = gfx.blend(tint, (255, 82, 120), 0.55)
        elif kind == "cta":
            tint = gfx.blend(tint, (255, 188, 78), 0.35)
        scene_start = float(scene.get("start", 0) or 0)
        env = self._env_at(scene_start + t)
        set_id = str(self.profile.get("set") or "studio")
        if set_id == "studio":
            self._draw_sky(c, t, scene_index, tint, accent, accent2, highlight, text, bg)
            self._draw_beams(c, t, accent2, highlight)
            self._draw_city(c, t, scene_index, tint, accent, accent2, highlight, bg)
            # dotted tech grid, slowly scrolling
            gx_off = int(t * 2) % 12
            for gx in range(6 - gx_off, SW, 12):
                for gy in range(64, 252, 12):
                    _pixel(c, gx, gy, tint if (gx + gy) % 3 else highlight, 18)
            _rect(c, 0, 200, SW, 2, gfx.blend(bg, tint, 0.55), 90)
            _rect(c, 0, 340, SW, 140, gfx.blend(gfx.blend(bg, tint, 0.08), (0, 0, 0), 0.25))
            _rect(c, 0, 338, SW, 3, accent)
            self._draw_floor(c, t, scene_index, tint, accent, accent2, highlight)
            self._draw_backdrop(c, t, scene_index)
        else:
            self._draw_set(c, t, scene_index, set_id, tint, accent, accent2,
                           highlight, good, bad, bg, card, muted)
        # cinematic scanlines
        for sy in range(0, SH, 4):
            _rect(c, 0, sy, SW, 1, (0, 0, 0), 8)

        if visual == "room":
            # window
            _rect(c, 150, 70, 86, 92, gfx.blend(bg, accent2, 0.2))
            _rect(c, 154, 74, 78, 84, gfx.blend(bg, (0, 0, 0), 0.35))
            _rect(c, 192, 74, 2, 84, gfx.blend(bg, accent, 0.4))
            _rect(c, 154, 112, 78, 2, gfx.blend(bg, accent, 0.4))
            for i in range(6):
                twinkle = 115 + int(90 * (0.5 + 0.5 * math.sin(t * 2.2 + i * 0.9)))
                _pixel(c, 162 + (i * 17) % 62, 82 + (i * 13) % 54, highlight, twinkle)
            # poster
            if scene.get("kind") not in ("hook", "cta"):
                _rect(c, 36, 62, 62, 44, gfx.blend(card, accent, 0.16))
                _rect(c, 40, 66, 54, 5, accent)
                _rect(c, 40, 76, 38, 3, muted)
                _rect(c, 40, 83, 48, 3, muted)
                _rect(c, 40, 90, 30, 3, accent2)
            # desk + laptop
            _rect(c, 8, 320, 254, 16, gfx.blend(card, (0, 0, 0), 0.18))
            _rect(c, 8, 336, 254, 6, gfx.blend(card, (0, 0, 0), 0.35))
            _rect(c, 24, 286, 58, 38, gfx.blend(card, (0, 0, 0), 0.05))
            _rect(c, 28, 290, 50, 28, gfx.blend(bg, accent, 0.28))
            _rect(c, 32, 294, 28, 2, highlight)
            _rect(c, 32, 300, 38, 2, accent)
            _rect(c, 32, 306, 22, 2, muted)
            _rect(c, 42, 328, 22, 4, gfx.blend(card, (0, 0, 0), 0.3))
            # plant
            _rect(c, 220, 304, 12, 18, gfx.blend(good, (0, 0, 0), 0.35))
            _rect(c, 222, 294, 8, 10, good)
            _rect(c, 218, 290, 4, 7, gfx.blend(good, (255, 255, 255), 0.15))
        elif visual == "chart":
            self._draw_chart_panel_v2(c, t, str(self.profile.get("chart", "candles")),
                                   accent, accent2, highlight, good, bad, bg, card, muted)
        elif visual == "board":
            _rect(c, 42, 66, 178, 164, (34, 40, 42))
            _rect(c, 45, 69, 172, 158, (150, 160, 152))
            _rect(c, 45, 69, 172, 3, accent)
            _rect(c, 56, 84, 80, 5, accent)
            # sticky notes and marker annotations
            _rect(c, 172, 78, 32, 28, (255, 208, 86), 230)
            _rect(c, 178, 84, 20, 2, (60, 50, 30), 180)
            _rect(c, 178, 90, 15, 2, (60, 50, 30), 160)
            _rect(c, 154, 120, 40, 26, (255, 136, 116), 215)
            _rect(c, 160, 127, 26, 2, (80, 40, 36), 170)
            _rect(c, 92, 150, 18, 2, (220, 70, 70), 200)
            _rect(c, 90, 146, 2, 8, (220, 70, 70), 200)
            for i in range(4):
                _rect(c, 56, 102 + i * 22, 6, 6, good if i != 3 else bad)
                _rect(c, 68, 103 + i * 22, 112 - (i * 8), 3, (40, 52, 48))
                _rect(c, 68, 109 + i * 22, 70, 2, (100, 112, 105))
            _rect(c, 46, 70, 1, 156, (120, 130, 122), 140)
        elif visual == "phone":
            _rect(c, 150, 56, 92, 196, gfx.blend(card, (0, 0, 0), 0.04), 255)
            _rect(c, 156, 64, 80, 180, gfx.blend(bg, accent, 0.2))
            _rect(c, 160, 68, 72, 22, gfx.blend(card, accent2, 0.12))
            _rect(c, 166, 74, 38, 3, text, 190)
            _rect(c, 160, 96, 52, 20, gfx.blend(card, accent, 0.2))
            _rect(c, 166, 102, 38, 3, muted)
            _rect(c, 196, 122, 44, 18, gfx.blend(card, accent2, 0.25))
            _rect(c, 202, 128, 30, 3, text, 190)
            _rect(c, 160, 148, 46, 18, gfx.blend(card, accent, 0.2))
            _rect(c, 166, 154, 32, 3, muted)
            _rect(c, 204, 174, 32, 16, accent, 190 + int(65 * (0.5 + 0.5 * math.sin(t * 3))))
            _rect(c, 210, 180, 20, 3, (10, 12, 10))
        elif visual == "terminal":
            _rect(c, 48, 66, 174, 168, gfx.blend(card, (0, 0, 0), 0.18))
            _rect(c, 52, 70, 166, 160, gfx.blend(bg, good, 0.06))
            _rect(c, 52, 70, 166, 12, gfx.blend(card, good, 0.18))
            _rect(c, 58, 74, 4, 4, bad)
            _rect(c, 66, 74, 4, 4, (255, 190, 92))
            _rect(c, 74, 74, 4, 4, good)
            for i in range(8):
                _rect(c, 60, 92 + i * 16, 54 + (i * 17) % 70, 3, good if i % 3 else accent)
                _rect(c, 60, 97 + i * 16, 26 + (i * 11) % 40, 2, muted, 150)
            _rect(c, 60, 220, 74, 3, highlight)
            if int(t * 2) % 2 == 0:
                _rect(c, 60, 226, 10, 2, highlight)
        else:
            _rect(c, 0, 340, SW, 140, gfx.blend(bg, accent, 0.08))

        if set_id == "studio":
            self._draw_topic_props(c, t, kind)
        # extra reusable props: object count controls density
        try:
            object_count = max(1, min(6, int(self.settings.get("pixel_objects", 3) or 3)))
        except (TypeError, ValueError):
            object_count = 3
        if visual != "none":
            for i in range(object_count):
                ox = 12 + (i * 47) % 240
                oy = 54 + (i * 31) % 120
                _rect(c, ox, oy, 3, 3, accent2 if i % 2 else highlight, 150)
                _rect(c, ox + 1, oy + 1, 1, 1, text, 190)

        # Push the scene graphics behind the character. The character is the
        # storyteller; charts and windows are supporting context.
        _rect(c, 0, 44, SW, 196, (0, 0, 0), 26)
        # foreground silhouettes frame the stage and add depth
        for i in range(10):
            _rect(c, i * 3, 350 + i * 4, 26 - i * 2, 4, (2, 4, 6), 120)
            _rect(c, SW - 26 + i * 2, 350 + i * 4, 26 - i * 2, 4, (2, 4, 6), 120)

        mascot_anim = scene.get("pixel_animation") or "auto"
        if mascot_anim == "auto":
            mascot_anim = auto_animation(scene.get("text", ""), scene.get("kind", ""))
        if mascot_anim not in ANIMATIONS:
            mascot_anim = "talk" if scene.get("text") else "idle"
        self._draw_mascot(c, t, mascot_anim, tint)

        # character
        if parallax:
            c.restore()
        character_on = scene.get("character")
        if character_on is False or self.settings.get("pixel_character") is False:
            return
        anim = scene.get("pixel_animation") or "auto"
        if anim == "auto":
            anim = auto_animation(scene.get("text", ""), scene.get("kind", ""))
        if anim not in ANIMATIONS:
            anim = "talk" if scene.get("text") else "idle"
        scene_end = float(scene.get("end", scene_start + 1) or scene_start + 1)
        speech_start = max(0.0, float(scene.get("place", scene_start) or scene_start) - scene_start)
        speech_dur = float(scene.get("dur", 0) or 0)
        speech_end = speech_start + speech_dur if speech_dur > 0 else scene_end - scene_start
        talking = bool(scene.get("text")) and speech_start - 0.06 <= t <= speech_end + 0.12
        if talking and (scene_end - scene_start) > 4.2 and anim in ("talk", "explain", "idle"):
            beat = int(max(0.0, t - speech_start) // 2.6)
            if beat % 2 == 1:
                anim = "point" if visual in ("chart", "board", "terminal", "phone") else (
                    "happy" if scene.get("kind") == "cta" else "explain")
        intensity = str(self.settings.get("pixel_animation_intensity") or "medium")
        speed = {"low": 5.0, "medium": 8.5, "high": 12.5}.get(intensity, 8.5)
        frame = self._frame(anim, t * (speed / 7.0))
        position = scene.get("character_position") or self.settings.get("pixel_position") or "auto"
        if position == "auto":
            position = "center"
        size = scene.get("character_size") or self.settings.get("pixel_size") or "medium"
        size_scale = {"small": 2.0, "medium": 2.8, "large": 3.3}.get(size, 2.8)
        height_scale = {"short": 0.90, "normal": 1.0, "tall": 1.12}.get(
            self.character.get("height", "normal"), 1.0)
        scale = size_scale * height_scale
        char_w = FRAME_W * scale
        if position == "left":
            x = 12
        elif position == "right":
            x = SW - char_w - 12
        else:
            x = (SW - char_w) / 2
        if anim == "walk" and position == "center":
            walk_start = float(scene.get("start", 0) or 0)
            walk_end = float(scene.get("end", walk_start + 1) or walk_start + 1)
            u = gfx.ease_in_out(gfx.clamp(t / max(0.1, walk_end - walk_start)))
            x = 18 + (SW - char_w - 36) * u
        elif anim == "walk":
            x += math.sin(t * speed * 0.3) * 8
        elif anim in ("talk", "idle", "explain", "think") or talking:
            x += math.sin(t * speed * 0.34) * (2.0 if talking else 1.2)
        bob_speed = 0.82 if talking else 0.55
        bob = math.sin(t * speed * bob_speed) * (3.8 if talking else (3.2 if intensity == "high" else 2.0))
        bob += env * (2.6 if talking else 0.4)
        # Keep the feet on the same baseline regardless of height/size.
        ground_y = 328 - FRAME_H * scale + bob
        hop = 0.0
        if anim in ("victory", "happy"):
            hop = max(0.0, math.sin(t * math.pi)) * 6.0
        y = ground_y - hop
        # soft stage light + floor highlight where the character stands
        if t < 0.6:
            dust_k = 1.0 - t / 0.6
            for i in range(3):
                _rect(c, x + char_w / 2 + (i - 1) * 10 * scale,
                      ground_y - 1, 4 * scale, 2 * scale,
                      (190, 190, 180), int(55 * dust_k))
        gfx.orb(c, x + char_w / 2, ground_y + FRAME_H * scale * 0.52,
                max(20, char_w * 0.78), tint, 10, 2)
        _rect(c, x - 5, ground_y + FRAME_H * scale - 2, char_w + 10, 3,
              gfx.blend(bg, accent, 0.45), 150)
        _rect(c, x + 4, ground_y + FRAME_H * scale - 2, max(6.0, char_w - 8), 3, (0, 0, 0), 110)
        # ---------- character acting: entrance, lean, procedural limbs
        feet_x = x + char_w / 2
        feet_y = y + FRAME_H * scale
        c.save()
        if t < 0.55:
            k = gfx.ease_out(gfx.clamp(t / 0.55))
            side = -1 if scene_index % 2 == 0 else 1
            c.translate(side * (1.0 - k) * 70, (1.0 - k) * 24)
        lean = math.sin(t * 0.85) * 0.7
        if anim in ("point", "show"):
            lean += -1.8
        elif anim == "error":
            lean += math.sin(t * 28.0) * 2.4
        elif anim in ("victory", "happy"):
            lean += math.sin(t * 5.5) * 1.2
        elif anim == "sad":
            lean += 1.6
        c.translate(feet_x, feet_y)
        c.rotate(lean)
        c.translate(-feet_x, -feet_y)
        if self.custom_image is not None:
            _draw_image_sprite(c, self.custom_image, x, y, char_w, FRAME_H * scale, self.nearest)
        else:
            # mirrored floor reflection (body only, subtle)
            c.save()
            c.clipRect(skia.Rect.MakeXYWH(x - 4, y + FRAME_H * scale - 2, char_w + 8, 62))
            c.translate(0, y + FRAME_H * scale * 2 - 2)
            c.scale(1, -1)
            _draw_sprite(c, self.sheet, x, y, 0, self.nearest, scale, 34)
            c.restore()
            body_dx = 0.0
            if anim in ("idle", "talk", "explain", "think") or talking:
                body_dx = math.sin(t * 0.9 + scene_index) * 0.8 * scale
            elif anim == "walk":
                body_dx = math.sin(t * 3.6) * 0.6 * scale
            elif anim in ("victory", "happy"):
                body_dx = math.sin(t * 5.0) * 0.5 * scale
            elif anim in ("error", "scared"):
                body_dx = math.sin(t * 18.0) * 0.5 * scale
            _draw_limbs(c, x, y, scale, self.character, anim, t, env, part="legs")
            rim = None
            try:
                rim = skia.Paint()
                rim.setColorFilter(skia.ColorFilters.Blend(
                    gfx.col(tint, 255), skia.BlendMode.kSrcIn))
                rim.setAlphaf(0.30)
                src_body = skia.Rect.MakeXYWH(0, 21, FRAME_W, FRAME_H - 21)
                dst_body = skia.Rect.MakeXYWH(
                    x + body_dx + 1.2 * scale, y + 19.8 * scale,
                    FRAME_W * scale, (FRAME_H - 21) * scale)
                c.drawImageRect(self.sheet, src_body, dst_body, self.nearest, rim)
            except Exception:
                rim = None
            if self.settings.get("pixel_cloth", True):
                for i in range(3):
                    lag = math.sin(t * 2.2 + scene_index - i * 0.35) * (1.1 + i * 0.45)
                    _rect(c, x + body_dx + 10 * scale + lag,
                          y + (37 + i * 2.4) * scale,
                          (4.0 - i * 0.6) * scale, 2.6 * scale,
                          gfx.blend(self.character["shirt"], (0, 0, 0), 0.55 - i * 0.06), 205)
            else:
                _rect(c, x + body_dx + 10 * scale, y + 37 * scale,
                      4 * scale, 7 * scale,
                      gfx.blend(self.character["shirt"], (0, 0, 0), 0.55), 210)
            breath = 1.0 + 0.006 * math.sin(t * 2.1)
            waist_x = x + body_dx + 20 * scale
            waist_y = y + 40 * scale
            c.save()
            c.translate(waist_x, waist_y)
            c.scale(1.0, breath)
            c.translate(-waist_x, -waist_y)
            _draw_sprite_part(c, self.sheet, 0, 21, FRAME_W, FRAME_H - 21,
                              x + body_dx, y + 21 * scale, self.nearest, scale)
            c.restore()
            if self.settings.get("pixel_cloth", True):
                lx = x + body_dx + 19 * scale
                for i in range(3):
                    px = lx + math.sin(t * 2.4 - i * 0.4) * (0.5 + i * 0.35) * scale
                    _rect(c, px, y + (22 + i * 3.2) * scale, 1 * scale, 2 * scale,
                          (28, 34, 42), 215)
                _rect(c, lx + math.sin(t * 2.4 - 0.8) * 0.8 * scale,
                      y + 31.5 * scale, 2 * scale, 2 * scale, tuple(gfx.ACCENT), 225)
            else:
                _rect(c, x + body_dx + 19 * scale, y + 22 * scale,
                      1 * scale, 9 * scale, (28, 34, 42), 220)
                _rect(c, x + body_dx + 19 * scale, y + 30 * scale,
                      2 * scale, 2 * scale, tuple(gfx.ACCENT), 225)
            _draw_limbs(c, x + body_dx, y, scale, self.character, anim, t, env, part="arms")
            # articulated head: tilt, nod, yaw and reaction
            head_dx = 0.0
            head_dy = 0.0
            tilt = math.sin(t * 0.9) * 0.9
            yaw = 0.0
            if anim in ("point", "show"):
                head_dx = 0.4 * scale
                tilt = -1.6
                yaw = 0.55
            elif anim == "think":
                head_dx = -0.3 * scale
                head_dy = 0.4 * scale
                tilt = 2.6
                yaw = 0.30
            elif anim in ("error", "scared"):
                head_dx = math.sin(t * 20) * 0.7 * scale
                head_dy = -0.4 * scale
                tilt = math.sin(t * 18) * 1.5
            elif anim == "walk":
                yaw = 0.40
            elif anim in ("victory", "happy"):
                head_dy = -0.4 * scale
                tilt = -1.5
            elif talking:
                head_dy = -env * 1.0 * scale
                tilt = math.sin(t * 2.2) * 0.6
                yaw = 0.12 * math.sin(t * 0.8)
            head_yaw_dx = yaw * 1.2 * scale
            neck_x = x + body_dx + 20 * scale
            neck_y = y + 21 * scale
            # solid neck column stays with the torso, the head moves above it
            _rect(c, x + body_dx + 18 * scale, y + 17.5 * scale, 4 * scale, 6 * scale,
                  self.character["skin"], 255)
            _rect(c, x + body_dx + 18 * scale, y + 21 * scale, 4 * scale, 2 * scale,
                  gfx.blend(self.character["skin"], (0, 0, 0), 0.16), 180)
            c.save()
            c.translate(neck_x, neck_y)
            c.rotate(tilt)
            c.scale(1.0 - abs(yaw) * 0.10, 1.0)
            c.translate(-neck_x, -neck_y)
            if rim is not None:
                src_head = skia.Rect.MakeXYWH(0, 0, FRAME_W, 21)
                dst_head = skia.Rect.MakeXYWH(
                    x + body_dx + head_dx + head_yaw_dx + 1.2 * scale,
                    y + head_dy - 1.2 * scale,
                    FRAME_W * scale, 21 * scale)
                c.drawImageRect(self.sheet, src_head, dst_head, self.nearest, rim)
            _draw_sprite_part(c, self.sheet, 0, 0, FRAME_W, 21,
                              x + body_dx + head_dx + head_yaw_dx, y + head_dy,
                              self.nearest, scale)
            self._draw_face_overlay(c, x + body_dx + head_dx + head_yaw_dx, y + head_dy,
                                    scale, self.character, t, anim, env, scene_index, yaw)
            c.restore()
            if talking:
                self._draw_voice_bars(c, x, y, char_w, scale, t, env)
        c.restore()
        self._draw_character_fx(c, scene, t, x, y, char_w, scale, anim)
        self._draw_foreground(c, t, scene_index, anim, env, accent, accent2, highlight)

    def _frame(self, anim: str, t: float) -> int:
        frames = {
            "idle": (0, 1), "talk": (2, 3), "explain": (2, 8, 17, 3),
            "point": (8, 17), "wave": (9, 18), "surprise": (13, 25, 11, 19),
            "happy": (11, 19), "sad": (10, 24), "think": (12, 20),
            "scared": (13, 25), "show": (14, 22), "victory": (15, 21),
            "error": (16, 23), "walk": (4, 5, 6, 7),
        }.get(anim, (0, 1))
        return frames[int(t * 3) % len(frames)]

    # ---------------------------------------------------------------- text
    def _draw_title(self, c, scene, t, scene_index=0):
        kind = scene.get("kind", "statement")
        title = str(scene.get("title") or "").strip()
        accent = str(scene.get("accent") or "").strip()
        kicker = str(scene.get("kicker") or scene.get("label") or "").strip()
        if not title and not accent:
            return
        accent_rgb = tuple(gfx.ACCENT)
        text_rgb = tuple(gfx.TEXT)
        muted = tuple(gfx.MUTED)
        a_kick = min(1.0, max(0.0, t / 0.28))
        a_title = min(1.0, max(0.0, (t - 0.06) / 0.42))
        a_accent = min(1.0, max(0.0, (t - 0.24) / 0.42))
        a_plate = min(1.0, max(0.0, (t - 0.02) / 0.30))
        rise_title = int((1 - a_title) * 34)
        rise_accent = int((1 - a_accent) * 22)
        size = 56 if kind != "hook" else 64
        title_font = "monobold" if self.settings.get("pixel_font") == "mono" else "black"
        title_lines = _wrap_text(title.upper(), title_font, size, 900)[:3] if title else []
        accent_lines = _wrap_text(accent.upper(), "bold", 27, 880)[:2] if accent else []
        widths = [gfx.text_w(line, title_font, size, -1.0) for line in title_lines]
        widths += [gfx.text_w(line, "bold", 27, 0.4) for line in accent_lines]
        if kicker:
            widths.append(gfx.text_w(kicker.upper(), "mono", 15, 2.0))
        plate_w = min(config.W - 72, int(max(widths or [320]) + 46))
        plate_h = 248 + len(title_lines) * int(size * 1.06) + (8 + len(accent_lines) * 34 if accent_lines else 0) - 178
        _rect(c, 36, 180, plate_w, plate_h, (4, 6, 8), int(192 * a_plate))
        _rect(c, 36, 180, 4, plate_h, accent_rgb, int(210 * a_plate))
        _rect(c, 36, 180 + plate_h - 2, plate_w, 2, gfx.blend(accent_rgb, (0, 0, 0), 0.35),
              int(120 * a_plate))
        for sy in range(180, 180 + plate_h, 4):
            _rect(c, 36, sy, plate_w, 1, (255, 255, 255), 4)
        # index badge
        gfx.rrect(c, 36, 136, 54, 30, 6, fill=(6, 10, 14),
                  alpha=int(220 * a_plate), stroke=accent_rgb, sw=1.0)
        gfx.draw_text(c, f"{scene_index + 1:02d}", 63, 158, "mono", 16, accent_rgb,
                      int(240 * a_plate), "center", tracking=1.0)
        if kicker:
            gfx.draw_text(c, kicker.upper(), 52, 196, "mono", 15, accent_rgb,
                          int(230 * a_kick), tracking=2.0)
        y = 248
        for line in title_lines:
            yy = y + rise_title
            wx = 49.0
            words = line.split()
            for wi, word in enumerate(words):
                word_a = min(a_title, gfx.ease_out(
                    gfx.clamp((t - 0.10 - wi * 0.055) / 0.30)))
                alpha = int(255 * word_a)
                if alpha > 0:
                    color = accent_rgb if (wi == 0 and len(words) > 1) else text_rgb
                    gfx.draw_text(c, word, wx + 3, yy + 3, title_font, size,
                                  (0, 0, 0), int(alpha * 0.60), tracking=-1.0)
                    gfx.draw_text(c, word, wx, yy - int((1 - word_a) * 10),
                                  title_font, size, color, alpha, tracking=-1.0,
                                  glow=accent_rgb, glow_a=64, glow_w=18)
                wx += gfx.text_w(word + " ", title_font, size, -1.0)
            y += int(size * 1.06)
        if accent_lines:
            y += 8
            for line in accent_lines:
                gfx.draw_text(c, line, 52, y + rise_accent, "bold", 27, accent_rgb,
                              int(235 * a_accent), tracking=0.4)
                y += 34
        # pixel underline grows in
        k = min(1.0, max(0.0, (t - 0.34) / 0.42))
        if k > 0:
            _rect(c, 52, y + 2, int(90 * k), 4, accent_rgb)
            _rect(c, 52 + int(96 * k), y + 2, int(22 * k), 4, tuple(gfx.ACCENT2))

    def _draw_hud(self, c, scene_index, t):
        # top bar
        _rect(c, 0, 0, config.W, 4, tuple(gfx.ACCENT), 80)
        gfx.draw_text(c, str(self.settings.get("brand", "TRADE AUTOPSY")).upper(),
                      52, 82, "mono", 19, tuple(gfx.TEXT), 220, tracking=2.4)
        gfx.draw_text(c, f"{scene_index + 1:02d}/{len(self.starts):02d}",
                      config.W - 52, 82, "mono", 17, tuple(gfx.MUTED), 180,
                      "right", tracking=1.4)
        if int(t * 2) % 2 == 0:
            _rect(c, config.W - 196, 74, 8, 8, tuple(gfx.BAD), 220)
        gfx.draw_text(c, "LIVE", config.W - 182, 84, "mono", 15, tuple(gfx.BAD),
                      210, tracking=1.4)
        n = len(self.starts)
        for i in range(n):
            x = config.W - 52 - (n - 1 - i) * 20
            active = i <= scene_index
            _rect(c, x, 106, 10, 4,
                  tuple(gfx.ACCENT) if active else (80, 90, 105),
                  190 if active else 90)
        # progress (global timeline, not the local scene time)
        x0, x1, y = 52, config.W - 52, 1848
        global_t = float(self.starts[scene_index]) + t if scene_index < n else t
        p = skia.Paint(AntiAlias=True)
        p.setColor(gfx.col((80, 90, 105), 90))
        c.drawRect(skia.Rect.MakeXYWH(x0, y, x1 - x0, 3), p)
        prog = max(0.0, min(1.0, global_t / max(0.01, self.duration)))
        q = skia.Paint(AntiAlias=True)
        q.setColor(gfx.col(tuple(gfx.ACCENT), 220))
        c.drawRect(skia.Rect.MakeXYWH(x0, y, (x1 - x0) * prog, 3), q)

    # ---------------------------------------------------------------- scene frame
    def render_scene(self, scene_index: int, t: float):
        scenes = self.plan.get("scenes") or []
        scene = scenes[scene_index] if scenes else {}
        low = self.low.getCanvas()
        low.resetMatrix()
        try:
            self._draw_world(low, scene, t, scene_index)
        except Exception:
            _rect(low, 0, 0, SW, SH, (8, 8, 11))
            _rect(low, 20, 200, 230, 80, tuple(gfx.ACCENT))
        full = self.full.getCanvas()
        full.resetMatrix()
        full.clear(gfx.col((8, 8, 11)))
        scene_start = float(scene.get("start", 0) or 0)
        duration = max(0.5, float(scene.get("end", scene_start + 1) or scene_start + 1) - scene_start)
        kind = str(scene.get("kind") or "")
        anim = scene.get("pixel_animation") or "auto"
        if anim == "auto":
            anim = auto_animation(scene.get("text", ""), kind)
        # cinematic scene-specific camera + impact shake
        intro = gfx.ease_out(min(1.0, t / max(0.6, min(2.2, duration * 0.35))))
        progress = gfx.clamp(t / max(0.1, duration))
        if kind == "hook":
            zoom = 1.045 + 0.045 * intro + 0.008 * math.sin(t * 0.45)
        elif kind == "problem":
            zoom = 1.055 - 0.018 * gfx.ease_out(progress)
        elif kind == "insight":
            zoom = 1.035 + 0.012 * math.sin(t * 0.4)
        elif kind == "solution":
            zoom = 1.025 + 0.05 * intro
        elif kind == "cta":
            zoom = 1.07 - 0.035 * gfx.ease_out(progress)
        else:
            zoom = 1.0 + 0.03 * intro
        if kind in ("hook", "problem"):
            zoom += 0.025
        zoom = max(1.0, zoom)
        # impact punch at the scene start
        zoom *= 1.0 + 0.06 * (1.0 - gfx.ease_out(min(1.0, t / 0.38)))
        shake_x = shake_y = 0.0
        if anim in ("error", "scared"):
            shake_x = math.sin(t * 55) * 1.6
            shake_y = math.cos(t * 47) * 1.2
        src_w = SW / zoom
        src_h = SH / zoom
        cx = SW / 2 + math.sin(t * 0.27 + scene_index * 1.3) * 1.8 + shake_x
        if kind == "insight":
            cx += math.sin(t * 0.35) * 2.5
        cy = SH * 0.53 + shake_y
        x0 = max(0.0, min(SW - src_w, cx - src_w / 2))
        y0 = max(0.0, min(SH - src_h, cy - src_h / 2))
        full.save()
        if kind in ("hook", "problem"):
            angle = math.sin(t * 0.6 + scene_index) * 0.45
            full.translate(self.out_w / 2, self.out_h / 2)
            full.rotate(angle)
            full.translate(-self.out_w / 2, -self.out_h / 2)
        full.drawImageRect(
            low_img := self.low.makeImageSnapshot(),
            skia.Rect.MakeXYWH(x0, y0, src_w, src_h),
            skia.Rect.MakeWH(self.out_w, self.out_h),
            self.nearest,
            None,
        )
        full.restore()
        if t < 0.22:
            k = 1.0 - t / 0.22
            blur = skia.Paint()
            blur.setAlphaf(0.28 * k)
            for dx in (-7, 7):
                full.save()
                full.translate(dx, 0)
                full.drawImageRect(
                    low_img,
                    skia.Rect.MakeXYWH(x0, y0, src_w, src_h),
                    skia.Rect.MakeWH(self.out_w, self.out_h),
                    self.nearest,
                    blur,
                )
                full.restore()
        if self.quality != "fast" and self.settings.get("pixel_bloom", True):
            try:
                bloom = skia.Paint()
                bloom.setAlphaf(0.22)
                bloom.setBlendMode(skia.BlendMode.kScreen)
                bloom.setImageFilter(skia.ImageFilters.Blur(5.0, 5.0))
                full.drawImageRect(
                    low_img,
                    skia.Rect.MakeXYWH(x0, y0, src_w, src_h),
                    skia.Rect.MakeWH(self.out_w, self.out_h),
                    self.nearest,
                    bloom,
                )
            except Exception:
                pass
        # scene color script
        tint = tuple(self.profile.get("tint", (120, 140, 200)))
        if kind == "problem":
            tint = gfx.blend(tint, (255, 82, 120), 0.55)
        elif kind == "cta":
            tint = gfx.blend(tint, (255, 188, 78), 0.35)
        grade = skia.Paint()
        grade.setShader(skia.GradientShader.MakeLinear(
            [skia.Point(0, 0), skia.Point(0, self.out_h)],
            [gfx.col(tint, 0), gfx.col(tint, 10), gfx.col(tint, 0)],
            [0.0, 0.55, 1.0],
        ))
        full.drawRect(skia.Rect.MakeWH(self.out_w, self.out_h), grade)
        leak = skia.Paint()
        leak.setShader(skia.GradientShader.MakeRadial(
            skia.Point(self.out_w * 0.9, self.out_h * 0.12), self.out_w * 0.75,
            [gfx.col(tint, 22), gfx.col(tint, 0)],
            [0.0, 1.0],
        ))
        full.drawRect(skia.Rect.MakeWH(self.out_w, self.out_h), leak)
        if kind == "hook" and t < 0.55:
            k = 1.0 - t / 0.55
            for i in range(5):
                y = self.out_h * (0.14 + i * 0.15)
                w = 80 + (i * 47) % 140
                x = self.out_w - int((t * 1500 + i * 110) % (self.out_w + 200))
                _rect(full, x, y, w, 2, (255, 255, 255), int(26 * k))
        if kind in ("problem", "error") and t < 0.35:
            k = 1.0 - t / 0.35
            for i in range(3):
                sy = int((i + 1) * SH / 4)
                sh = 6
                dx = int(math.sin(t * 70 + i * 2) * 10 * k)
                src = skia.Rect.MakeXYWH(0, sy, SW, sh)
                dst = skia.Rect.MakeXYWH(dx, sy * self.out_h / SH,
                                         self.out_w, sh * self.out_h / SH)
                full.drawImageRect(low_img, src, dst, self.nearest, None)
        if self.vignette is not None:
            full.drawImageRect(
                self.vignette,
                skia.Rect.MakeWH(config.W, config.H),
                skia.Rect.MakeWH(self.out_w, self.out_h),
                self.linear,
                None,
            )
        if self.text_scale != 1.0:
            full.save()
            full.scale(self.text_scale, self.text_scale)
        try:
            self._draw_title(full, scene, t, scene_index)
        except Exception:
            pass
        try:
            self._draw_cards(full, scene, t)
        except Exception:
            pass
        try:
            self._draw_captions(full, scene, t)
        except Exception:
            pass
        try:
            self._draw_hud(full, scene_index, t)
            self._draw_ticker(full, scene_start + t)
            self._draw_disclaimer(full)
        except Exception:
            pass
        if self.text_scale != 1.0:
            full.restore()
        # light wipe + flash at the scene start
        if t < 0.34:
            k = t / 0.34
            _rect(full, 0, 0, self.out_w, self.out_h, (255, 255, 255),
                  int(18 * (1 - k)))
            band_w = 130 * (self.out_w / config.W)
            bx = -band_w + k * (self.out_w + band_w * 2)
            path = skia.Path()
            path.moveTo(bx, 0)
            path.lineTo(bx + band_w, 0)
            path.lineTo(bx + band_w - 140, self.out_h)
            path.lineTo(bx - 140, self.out_h)
            path.close()
            paint = skia.Paint(AntiAlias=True)
            paint.setColor(gfx.col(gfx.ACCENT, int(28 * (1 - k))))
            full.drawPath(path, paint)
        sweep = (t * 70) % self.out_h
        _rect(full, 0, sweep, self.out_w, 2, (255, 255, 255), 9)
        if self.grain:
            img = self.grain[0]
            full.drawImageRect(
                img,
                skia.Rect.MakeWH(540, 960),
                skia.Rect.MakeWH(self.out_w, self.out_h),
                self.linear,
                self.grain_paint,
            )
        return self.full

    def _draw_captions(self, c, scene, local_t):
        start = float(scene.get("start", 0))
        end = float(scene.get("end", start + 1))
        phrases = []
        for p in self.plan.get("phrases", []):
            if p.get("scene") == scene.get("id"):
                source = p
            elif start - 0.01 <= float(p.get("t0", 0)) <= end + 0.01:
                source = p
            else:
                continue
            phrases.append({
                **source,
                "t0": float(source.get("t0", 0)) - start,
                "t1": float(source.get("t1", 0)) - start,
                "words": [
                    {**w, "t": float(w.get("t", 0)) - start}
                    for w in source.get("words", [])
                ],
            })
        if not phrases:
            text = str(scene.get("text") or "").strip()
            if not text:
                return
            # Safety net: never ship a pixel scene without subtitles, even if
            # the TTS timeline is missing for this render.
            words = [w for w in text.split() if w]
            duration = max(1.2, end - start)
            mid = max(1, len(words) // 2) if len(words) > 10 else len(words)
            groups = [words[:mid], words[mid:]] if mid < len(words) else [words]
            parts = max(1, len(groups))
            phrases = []
            for gi, group in enumerate(groups):
                if not group:
                    continue
                offset = gi * duration / parts
                span = duration / parts
                step = span / max(1, len(group))
                timed = [
                    {"w": w, "display": w, "t": offset + i * step, "d": step * 0.9}
                    for i, w in enumerate(group)
                ]
                phrases.append({
                    "t0": offset,
                    "t1": offset + span,
                    "text": " ".join(group),
                    "words": timed,
                })
        self._caption.phrases = phrases
        self._caption.p_starts = [float(p["t0"]) for p in phrases]
        self._caption.duration = max(0.1, end - start)
        self._caption.draw_subs(c, local_t)

    def preview_scene(self, scene_index: int, t: float, path: Path):
        self.render_scene(scene_index, t).makeImageSnapshot().save(str(path), skia.kPNG)
        return path


def _draw_talk_overlay(c, x, y, scale: float, ch: dict, t: float):
    """Mouth open/close + tiny voice bars layered over any gesture pose."""
    ctype = ch.get("type", "human")
    mouth_x = 18.0
    mouth_y = 19.0 if ctype == "animal" else 17.0 if ctype == "robot" else 16.0
    open_mouth = int(t * 10) % 2 == 0
    mw = max(2, int(4 * scale))
    mh = max(1, int((2 if open_mouth else 1) * scale))
    _rect(c, x + mouth_x * scale, y + mouth_y * scale, mw, mh, (18, 22, 28), 240)
    if open_mouth:
        _rect(c, x + (mouth_x + 1) * scale, y + (mouth_y + 1) * scale,
              max(1, int(2 * scale)), max(1, int(scale)), (112, 38, 46), 220)
    accent = tuple(gfx.ACCENT)
    ex = x + (31.0 if ctype == "animal" else 30.0) * scale
    ey = y + (16.0 if ctype == "animal" else 13.0) * scale
    step = max(2, int(2.2 * scale))
    w = max(2, int(1.2 * scale))
    for i in range(3):
        h = max(2, int(scale * (1 + (int(t * 13) + i) % 4)))
        _rect(c, ex + i * step, ey - h, w, h, accent, 205)


def _draw_sprite_part(c, sheet, sx, sy, sw, sh, x, y, sampling, scale: float = 1.0, alpha: int = 255):
    src = skia.Rect.MakeXYWH(sx, sy, sw, sh)
    dst = skia.Rect.MakeXYWH(float(x), float(y), sw * scale, sh * scale)
    paint = None
    if alpha < 255:
        paint = skia.Paint()
        paint.setAlphaf(max(0.0, min(1.0, alpha / 255.0)))
    c.drawImageRect(sheet, src, dst, sampling, paint)


def _draw_sprite(c, sheet, x, y, frame: int, sampling, scale: float = 1.0, alpha: int = 255):
    src = skia.Rect.MakeXYWH(frame * FRAME_W, 0, FRAME_W, FRAME_H)
    dst = skia.Rect.MakeXYWH(float(x), float(y), FRAME_W * scale, FRAME_H * scale)
    paint = None
    if alpha < 255:
        paint = skia.Paint()
        paint.setAlphaf(max(0.0, min(1.0, alpha / 255.0)))
    c.drawImageRect(sheet, src, dst, sampling, paint)


def _pixel_line(c, x0, y0, x1, y1, width, color, alpha=255):
    """Thick pixel line with no anti-aliasing (keeps the 8/16-bit look)."""
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    w = max(1, int(round(width)))
    for i in range(steps + 1):
        u = i / max(1, steps)
        x = x0 + (x1 - x0) * u
        y = y0 + (y1 - y0) * u
        _rect(c, round(x - w / 2), round(y - w / 2), w, w, color, alpha)


def _draw_limbs(c, ox, oy, scale, ch, anim, t, env, part="arms"):
    """Procedural arms and legs: continuous angles, elbows, hands and shoes."""
    slim = ch.get("proportions") == "slim"
    wide = ch.get("proportions") == "wide"
    body_x = 14 if slim else 11 if wide else 12
    body_w = 12 if slim else 18 if wide else 16
    if ch.get("gender") == "female":
        body_x += 1
        body_w = max(10, body_w - 2)
    skin = ch["skin"]
    shirt = ch["shirt"]
    pants = ch["pants"]
    shoes = ch["shoes"]
    outline = (8, 10, 14)
    skin_shadow = gfx.blend(skin, (0, 0, 0), 0.18)
    cuff = gfx.blend(shirt, (0, 0, 0), 0.28)
    sway = math.sin(t * 1.65) * 4.0
    breath = math.sin(t * 2.1) * 2.0

    def arm(sh, a1, a2, sleeve=shirt, side="r"):
        a1r = math.radians(a1)
        a2r = math.radians(a1 + a2)
        ex = sh[0] + math.cos(a1r) * 7.4
        ey = sh[1] + math.sin(a1r) * 7.4
        hx = ex + math.cos(a2r) * 7.8
        hy = ey + math.sin(a2r) * 7.8
        sx, sy = ox + sh[0] * scale, oy + sh[1] * scale
        exx, eyy = ox + ex * scale, oy + ey * scale
        hxx, hyy = ox + hx * scale, oy + hy * scale
        _pixel_line(c, sx, sy, exx, eyy, 4.6 * scale, outline)
        _pixel_line(c, exx, eyy, hxx, hyy, 4.2 * scale, outline)
        _pixel_line(c, sx, sy, exx, eyy, 4.0 * scale, sleeve)
        _pixel_line(c, exx, eyy, hxx, hyy, 3.6 * scale, skin)
        _pixel_line(c, sx, sy, sx + (exx - sx) * 0.35, sy + (eyy - sy) * 0.35,
                    1.2 * scale, gfx.blend(sleeve, (255, 255, 255), 0.20))
        # cuff + watch
        _rect(c, exx - 2.0 * scale, eyy - 2.0 * scale, 4 * scale, 4 * scale, cuff)
        _rect(c, exx - 2.0 * scale, eyy - 2.0 * scale, 4 * scale, 1 * scale,
              tuple(gfx.ACCENT), 210)
        # hand + fingers
        hw = max(2, int(round(4.0 * scale)))
        _rect(c, hxx - hw / 2, hyy - hw / 2, hw, hw, skin)
        _rect(c, hxx - hw / 2, hyy - hw / 2, hw, max(1, int(scale * 0.7)),
              gfx.blend(skin, (255, 255, 255), 0.18))
        _rect(c, hxx - hw / 2 + hw * 0.18, hyy - hw / 2 + hw * 0.62,
              max(1, int(scale * 0.55)), max(1, int(scale * 0.55)), skin_shadow)
        _rect(c, hxx - hw / 2 + hw * 0.62, hyy - hw / 2 + hw * 0.62,
              max(1, int(scale * 0.55)), max(1, int(scale * 0.55)), skin_shadow)
        # pointing finger
        fx = hxx + math.cos(a2r) * 2.0 * scale
        fy = hyy + math.sin(a2r) * 2.0 * scale
        _pixel_line(c, hxx, hyy, fx, fy, max(1, int(scale * 0.8)), skin)
        if side == "r" and anim == "point":
            px = hxx + math.cos(a2r) * 11 * scale
            py = hyy + math.sin(a2r) * 11 * scale
            _pixel_line(c, hxx, hyy, px, py, max(1, int(scale * 0.7)),
                        (210, 180, 120), 240)
            _rect(c, px - scale, py - scale, 2 * scale, 2 * scale,
                  (255, 220, 120), 240)
            for i in range(3):
                sx = px + math.sin(t * 7 + i * 2) * 4 * scale
                sy = py - (3 + i * 3) * scale
                _rect(c, sx, sy, max(1, int(scale * 0.6)), max(1, int(scale * 0.6)),
                      (255, 220, 120), 150)
        elif side == "r" and anim == "show":
            _rect(c, hxx - 2 * scale, hyy - 5 * scale, 8 * scale, 11 * scale,
                  (12, 16, 22), 240)
            _rect(c, hxx - 1 * scale, hyy - 4 * scale, 6 * scale, 7 * scale,
                  (30, 60, 90), 240)
            _rect(c, hxx - 0.5 * scale, hyy + 1 * scale, 4 * scale, 1 * scale,
                  tuple(gfx.ACCENT), 200)

    def leg(hip, a1, a2):
        a1r = math.radians(a1)
        a2r = math.radians(a1 + a2)
        kx = hip[0] + math.cos(a1r) * 7.5
        ky = hip[1] + math.sin(a1r) * 7.5
        ax = kx + math.cos(a2r) * 7.5
        ay = ky + math.sin(a2r) * 7.5
        hx, hy = ox + hip[0] * scale, oy + hip[1] * scale
        kxx, kyy = ox + kx * scale, oy + ky * scale
        axx, ayy = ox + ax * scale, oy + ay * scale
        _pixel_line(c, hx, hy, kxx, kyy, 5.0 * scale, outline)
        _pixel_line(c, kxx, kyy, axx, ayy, 4.8 * scale, outline)
        _pixel_line(c, hx, hy, kxx, kyy, 4.2 * scale, pants)
        _pixel_line(c, kxx, kyy, axx, ayy, 4.0 * scale, pants)
        _pixel_line(c, hx, hy, kxx, kyy, 1.1 * scale,
                    gfx.blend(pants, (255, 255, 255), 0.12))
        # shoe follows the ankle
        sw, sh = 8.0 * scale, 3.6 * scale
        _rect(c, axx - 4.3 * scale, ayy - 1.0 * scale, sw + 1.8 * scale, sh + 1.4 * scale, outline)
        _rect(c, axx - 3.8 * scale, ayy - 0.7 * scale, sw, sh, shoes)
        _rect(c, axx - 2.6 * scale, ayy + 0.2 * scale, 4.0 * scale, 0.9 * scale,
              gfx.blend(shoes, (255, 255, 255), 0.18))

    if part == "legs":
        hip_l = (body_x + 3, 39)
        hip_r = (body_x + body_w - 3, 39)
        if anim == "walk":
            swing = math.sin(t * 7.2) * 24
            leg(hip_l, 88 + swing, max(0, -swing * 0.45))
            leg(hip_r, 88 - swing, max(0, swing * 0.45))
        else:
            loop, keys = LEG_KEYS.get(anim, LEG_KEYS["idle"])
            a_l, e_l, a_r, e_r = _kf(t, keys, loop)
            leg(hip_l, a_l, e_l)
            leg(hip_r, a_r, e_r)
        return

    sh_l = (body_x, 24)
    sh_r = (body_x + body_w, 24)
    if anim == "walk":
        swing = math.sin(t * 7.2) * 26
        a_l, e_l = 92 + swing, 8 + max(0, -swing) * 0.4
        a_r, e_r = 92 - swing, 8 + max(0, swing) * 0.4
    else:
        loop, left_keys, right_keys = ARM_KEYS.get(anim, ARM_KEYS["idle"])
        a_l, e_l = _kf(t, left_keys, loop)
        a_r, e_r = _kf(t, right_keys, loop)
        if anim in ("talk", "explain"):
            a_r -= env * 8.0
            e_r += env * 4.0
    arm(sh_l, a_l, e_l, side="l")
    arm(sh_r, a_r, e_r, side="r")


def _draw_image_sprite(c, image, x, y, max_w: float, max_h: float, sampling):
    iw = float(image.width())
    ih = float(image.height())
    if iw <= 0 or ih <= 0:
        return
    scale = min(max_w / iw, max_h / ih)
    w = iw * scale
    h = ih * scale
    # Keep the uploaded character centred and standing on the same baseline.
    dx = x + (max_w - w) / 2
    dy = y + (max_h - h)
    dst = skia.Rect.MakeXYWH(dx, dy, w, h)
    src = skia.Rect.MakeWH(image.width(), image.height())
    c.drawImageRect(image, src, dst, sampling, None)


def _count_value(value: str, k: float) -> str:
    """Animate numbers inside a card value from 0 to the target."""
    if k >= 0.999:
        return value
    import re

    def repl(match):
        raw = match.group(0)
        cleaned = raw.replace(" ", "").replace(",", ".")
        try:
            number = float(cleaned)
        except ValueError:
            return raw
        current = number * k
        if "." in cleaned:
            return f"{current:.1f}".replace(".", ",")
        return f"{int(round(current)):,}".replace(",", " ")

    return re.sub(r"\d+(?:[ \u00a0]\d+)*(?:[.,]\d+)?", repl, value)


def _wrap_text(text: str, style: str, size: int, max_w: float) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    cur: list[str] = []
    for word in words:
        test = " ".join(cur + [word])
        if cur and gfx.text_w(test, style, size, -1.0) > max_w:
            lines.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(" ".join(cur))
    return lines


def _encode_scene(renderer: PixelRenderer, scene_index: int, duration: float,
                  path: Path, fast: bool, progress=None, cancel=None) -> Path:
    total = max(1, int(round(duration * config.FPS)))
    if renderer.quality == "fast":
        preset, crf = "ultrafast", 24
        x264_params = ""
    elif renderer.quality == "ultra":
        preset, crf = "slow", 17
        x264_params = "aq-mode=3:aq-strength=1.15:deblock=-1,-1"
    else:
        preset, crf = "slow", 20
        x264_params = "aq-mode=3:aq-strength=1.05:deblock=-1,-1"
    cmd = [
        config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{renderer.out_w}x{renderer.out_h}",
        "-r", str(config.FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", preset,
        "-crf", str(crf), "-profile:v", "high", "-level", "4.2",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]
    if x264_params:
        cmd += ["-x264-params", x264_params]
    if renderer.out_w != config.W or renderer.out_h != config.H:
        cmd += ["-vf", f"scale={config.W}:{config.H}:flags=lanczos"]
    cmd.append(str(path))
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for frame in range(total):
            if cancel and cancel():
                break
            img = renderer.render_scene(scene_index, frame / config.FPS).makeImageSnapshot()
            proc.stdin.write(img.tobytes())
            if progress and frame % 30 == 0:
                progress(frame / max(1, total))
    finally:
        if proc.stdin:
            proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"FFmpeg завершился с кодом {code}")
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError("Не удалось собрать сцену")
    return path


def render_pixel_video(plan: dict, settings: dict, out_path: Path, audio_path: Path,
                       workdir: Path, progress=None, cancel=None,
                       scene_index: int | None = None,
                       reuse_clips: dict[int, Path] | None = None) -> dict:
    scenes = plan.get("scenes") or []
    if not scenes:
        raise RuntimeError("Нет сцен для пиксельного рендера")
    fast = settings.get("quality") == "fast"
    renderer = PixelRenderer(plan, settings, workdir)
    renderer.set_audio(audio_path)
    workdir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    reuse = reuse_clips or {}
    total_scenes = len(scenes)
    for i, scene in enumerate(scenes):
        duration = max(1.0, float(scene.get("end", 0)) - float(scene.get("start", 0)))
        clip = workdir / f"scene-{i + 1:02d}.mp4"
        if scene_index is not None and scene_index != i and i in reuse and Path(reuse[i]).exists():
            shutil.copyfile(reuse[i], clip)
            clips.append(clip)
            continue
        if scene_index is None and i in reuse and Path(reuse[i]).exists():
            shutil.copyfile(reuse[i], clip)
            clips.append(clip)
            continue
        if progress:
            progress(45 + int(40 * i / max(1, total_scenes)),
                     f"Пиксельная сцена {i + 1}/{total_scenes}")
        _encode_scene(
            renderer, i, duration, clip, fast,
            progress=lambda p, idx=i: progress(
                45 + int(40 * (idx + max(0.0, min(1.0, p))) / max(1, total_scenes)),
                f"Пиксельная сцена {idx + 1}/{total_scenes}",
            ) if progress else None,
            cancel=cancel,
        )
        clips.append(clip)
    if progress:
        progress(88, "Склеиваю сцены и накладываю звук")
    render._concat_and_mux(clips, audio_path, out_path, workdir, config.FFMPEG)
    if not out_path.exists() or out_path.stat().st_size < 50_000:
        raise RuntimeError("Пиксельное видео не создано")
    if progress:
        progress(98, "Финальный MP4 готов")
    return {"scene_clips": clips, "duration": plan.get("duration"), "scenes": len(scenes)}


def render_pixel_poster(plan: dict, settings: dict, workdir: Path, path: Path) -> None:
    try:
        renderer = PixelRenderer(plan, settings, workdir)
        scenes = plan.get("scenes") or []
        if not scenes:
            return
        duration = max(1.0, float(scenes[0].get("end", 1)) - float(scenes[0].get("start", 0)))
        renderer.preview_scene(0, min(1.2, max(0.3, duration * 0.3)), path)
    except Exception:
        pass
