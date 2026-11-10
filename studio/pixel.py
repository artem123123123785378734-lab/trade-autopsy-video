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
from pathlib import Path

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

VISUALS = ("room", "chart", "phone", "board", "terminal", "none")
ANIMATIONS = (
    "auto", "idle", "talk", "explain", "point", "surprise", "happy", "sad",
    "think", "scared", "show", "victory", "error",
)


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


def _draw_character(c, ox, oy, frame: int, ch: dict):
    skin = ch["skin"]
    hair = ch["hair"]
    shirt = ch["shirt"]
    pants = ch["pants"]
    shoes = ch["shoes"]
    accent = tuple(gfx.ACCENT)
    dark = (18, 22, 28)
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
        _rect(c, ox + 28, oy + 36, 9, 3, skin)
        _rect(c, ox + 35, oy + 32, 3, 6, skin)

    if walk:
        left = (frame - 4) in (0, 1)
        leg_l += 2 if left else 0
        leg_r -= 2 if left else 0
    _rect(c, ox + leg_l, oy + 42, 5 if slim else 6, 12, pants)
    _rect(c, ox + leg_r, oy + 42, 5 if slim else 6, 12, pants)
    _rect(c, ox + leg_l - 1, oy + 54, 7, 4, shoes)
    _rect(c, ox + leg_r - 1, oy + 54, 7, 4, shoes)

    # body
    _rect(c, ox + body_x, oy + 22, body_w, 20, shirt)
    _rect(c, ox + body_x, oy + 22, body_w, 3, gfx.blend(shirt, (255, 255, 255), 0.16))
    if style == "detailed":
        _rect(c, ox + body_x + 2, oy + 27, 1, 12, gfx.blend(shirt, (0, 0, 0), 0.22))

    # arms
    if point or show:
        dy = 3 if point_alt else 0
        _rect(c, ox + body_x + body_w - 2, oy + 21 + dy, 12, 4, shirt)
        _rect(c, ox + body_x + body_w + 8, oy + 20 + dy, 4, 4, skin)
        if show:
            lift = -3 if show_alt else 0
            _rect(c, ox + body_x + body_w + 10, oy + 18 + lift, 5, 5, (255, 198, 86))
            _rect(c, ox + body_x + body_w + 11, oy + 19 + lift, 3, 3, (255, 255, 220))
        _rect(c, ox + body_x - 6, oy + 26, 5, 11, shirt)
        _rect(c, ox + body_x - 6, oy + 36, 5, 4, skin)
    elif wave or happy or victory or scared:
        lift = 4 if wave_alt else 0
        _rect(c, ox + body_x + body_w - 2, oy + 12 + lift, 4, 13, shirt)
        _rect(c, ox + body_x + body_w - 1, oy + 6 + lift, 5, 7, skin)
        _rect(c, ox + body_x - 6, oy + 25, 5, 12, shirt)
        _rect(c, ox + body_x - 6, oy + 36, 5, 4, skin)
        left_up = (victory and not victory_alt) or happy_alt or scared_alt
        if left_up:
            _rect(c, ox + body_x - 6, oy + 12, 4, 13, shirt)
            _rect(c, ox + body_x - 7, oy + 6, 5, 7, skin)
        elif victory_alt:
            _rect(c, ox + body_x - 6, oy + 19, 4, 13, shirt)
            _rect(c, ox + body_x - 7, oy + 14, 5, 7, skin)
    elif think:
        hand_y = 6 if think_alt else 10
        _rect(c, ox + body_x + body_w - 2, oy + 16, 7, 4, shirt)
        _rect(c, ox + body_x + body_w + 3, oy + hand_y, 4, 8, skin)
        _rect(c, ox + body_x - 6, oy + 26, 5, 11, shirt)
        _rect(c, ox + body_x - 6, oy + 36, 5, 4, skin)
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
        _rect(c, ox + body_x - 6, oy + 24, 5, 12, shirt)
        _rect(c, ox + body_x + body_w + 1, oy + 24, 5, 12, shirt)
        _rect(c, ox + body_x - 6, oy + 34, 5, 4, skin)
        _rect(c, ox + body_x + body_w + 1, oy + 34, 5, 4, skin)

    # head
    head_x = 12 if not wide else 11
    head_y = 5
    head_w = 16 if not wide else 18
    _rect(c, ox + head_x, oy + head_y, head_w, 16, skin)
    _rect(c, ox + head_x - 1, oy + head_y + 13, head_w + 2, 3, skin)

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


def build_sprite_sheet(character: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    surf = skia.Surface(FRAME_W * SHEET_FRAMES, FRAME_H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    for frame in range(SHEET_FRAMES):
        _draw_character(c, frame * FRAME_W, 0, frame, character)
    surf.makeImageSnapshot().save(str(path), skia.kPNG)
    return path


def _default_visual(kind: str) -> str:
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
            self.sheet_path = build_sprite_sheet(self.character, workdir / "character.png")
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
        self.starts = [float(s.get("start", 0)) for s in plan.get("scenes", [])]
        self.duration = float(plan.get("duration", 0) or 0)
        self._caption = render.Renderer(
            {"title": plan.get("title", ""), "scenes": [], "phrases": [], "duration": 1},
            settings, fast=False,
        )
        self._caption._scrim = self._caption._make_scrim()

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

    def _draw_world(self, c, scene, t):
        bg, card, accent, accent2, highlight, good, bad, text, muted = self._palette()
        visual = scene.get("pixel_visual")
        if not visual or visual == "auto":
            visual = self.settings.get("pixel_background") or _default_visual(scene.get("kind", "statement"))
        if visual not in VISUALS:
            visual = _default_visual(scene.get("kind", "statement"))

        _rect(c, 0, 0, SW, SH, bg)
        # sky / wall bands
        for i in range(6):
            shade = gfx.blend(bg, accent, 0.06 + i * 0.012)
            _rect(c, 0, i * 70, SW, 72, shade)
        _rect(c, 0, 340, SW, 140, gfx.blend(bg, (0, 0, 0), 0.25))
        _rect(c, 0, 338, SW, 3, accent)
        # textured studio floor: subtle bands + pixel specks instead of a flat void
        for i in range(8):
            y = 346 + i * 17
            _rect(c, 0, y, SW, 1, gfx.blend(bg, accent, 0.10 + i * 0.012), 95)
        for i in range(18):
            x = (i * 37 + 11) % SW
            y = 348 + (i * 29) % 126
            _pixel(c, x, y, accent2 if i % 3 else highlight, 70)
        # slow floating pixels make the dark background feel alive
        for i in range(12):
            x = (i * 41 + int(t * 6)) % SW
            y = (i * 53 + int(t * 2)) % 190
            _pixel(c, x, y, highlight if i % 3 else accent2, 55)

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
            _rect(c, 52, 70, 168, 172, gfx.blend(card, (0, 0, 0), 0.06))
            _rect(c, 58, 76, 156, 160, gfx.blend(bg, accent, 0.12))
            for i in range(5):
                _rect(c, 60, 86 + i * 28, 152, 1, gfx.blend(muted, bg, 0.55))
            for i in range(14):
                x = 66 + i * 10
                pulse = 0.5 + 0.5 * math.sin(t * 1.8 + i * 0.55)
                h = 12 + int(((i * 13) % 48) * (0.94 + 0.06 * pulse))
                _rect(c, x, 220 - h, 6, h, accent if i % 3 else accent2)
                _rect(c, x, 220 - h, 6, 2, highlight)
            _rect(c, 200, 80, 12, 12, good, 180)
            _rect(c, 216, 84, 22, 3, muted)
        elif visual == "board":
            _rect(c, 42, 66, 178, 164, (238, 241, 235))
            _rect(c, 46, 70, 170, 156, (214, 221, 213))
            _rect(c, 56, 84, 80, 5, accent)
            for i in range(4):
                _rect(c, 56, 102 + i * 22, 6, 6, good if i != 3 else bad)
                _rect(c, 68, 103 + i * 22, 112 - (i * 8), 3, (40, 52, 48))
                _rect(c, 68, 109 + i * 22, 70, 2, (100, 112, 105))
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

        # character
        character_on = scene.get("character")
        if character_on is False or self.settings.get("pixel_character") is False:
            return
        anim = scene.get("pixel_animation") or "auto"
        if anim == "auto":
            anim = auto_animation(scene.get("text", ""), scene.get("kind", ""))
        if anim not in ANIMATIONS:
            anim = "talk" if scene.get("text") else "idle"
        scene_start = float(scene.get("start", 0) or 0)
        scene_end = float(scene.get("end", scene_start + 1) or scene_start + 1)
        speech_start = max(0.0, float(scene.get("place", scene_start) or scene_start) - scene_start)
        speech_dur = float(scene.get("dur", 0) or 0)
        speech_end = speech_start + speech_dur if speech_dur > 0 else scene_end - scene_start
        talking = bool(scene.get("text")) and speech_start - 0.06 <= t <= speech_end + 0.12
        intensity = str(self.settings.get("pixel_animation_intensity") or "medium")
        speed = {"low": 4.0, "medium": 7.0, "high": 11.0}.get(intensity, 7.0)
        frame = self._frame(anim, t * (speed / 7.0))
        position = scene.get("character_position") or self.settings.get("pixel_position") or "auto"
        if position == "auto":
            position = "center"
        size = scene.get("character_size") or self.settings.get("pixel_size") or "medium"
        size_scale = {"small": 1.8, "medium": 2.4, "large": 2.9}.get(size, 2.4)
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
        if anim == "walk":
            x += math.sin(t * speed * 0.3) * 8
        elif anim in ("talk", "idle", "explain", "think") or talking:
            x += math.sin(t * speed * 0.34) * (2.0 if talking else 1.2)
        bob_speed = 0.82 if talking else 0.55
        bob = math.sin(t * speed * bob_speed) * (3.2 if talking else (2.6 if intensity == "high" else 1.4))
        # Keep the feet on the same baseline regardless of height/size.
        y = 328 - FRAME_H * scale + bob
        # floor highlight makes the character read as the main subject
        _rect(c, x - 5, y + FRAME_H * scale - 2, char_w + 10, 3,
              gfx.blend(bg, accent, 0.45), 150)
        _rect(c, x + 4, y + FRAME_H * scale - 2, max(6.0, char_w - 8), 3, (0, 0, 0), 110)
        if self.custom_image is not None:
            _draw_image_sprite(c, self.custom_image, x, y, char_w, FRAME_H * scale, self.nearest)
        else:
            _draw_sprite(c, self.sheet, x, y, frame, self.nearest, scale)
        if talking and self.custom_image is None:
            _draw_talk_overlay(c, x, y, scale, self.character, t)

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
    def _draw_title(self, c, scene, t):
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
        if kicker:
            gfx.draw_text(c, kicker.upper(), 52, 196, "mono", 15, accent_rgb,
                          int(230 * a_kick), tracking=2.0)
        y = 248
        for line in title_lines:
            yy = y + rise_title
            gfx.draw_text(c, line, 52, yy, title_font, size, (0, 0, 0),
                          int(150 * a_title), tracking=-1.0)
            gfx.draw_text(c, line, 49, yy - 3, title_font, size, text_rgb,
                          int(255 * a_title), tracking=-1.0)
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
        gfx.draw_text(c, str(self.settings.get("brand", "TRADE AUTOPSY")).upper(),
                      52, 82, "mono", 19, tuple(gfx.TEXT), 220, tracking=2.4)
        gfx.draw_text(c, f"{scene_index + 1:02d}/{len(self.starts):02d}",
                      config.W - 52, 82, "mono", 17, tuple(gfx.MUTED), 180,
                      "right", tracking=1.4)
        # progress
        x0, x1, y = 52, config.W - 52, 1848
        p = skia.Paint(AntiAlias=True)
        p.setColor(gfx.col((80, 90, 105), 90))
        c.drawRect(skia.Rect.MakeXYWH(x0, y, x1 - x0, 3), p)
        prog = max(0.0, min(1.0, t / max(0.01, self.duration)))
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
            self._draw_world(low, scene, t)
        except Exception:
            _rect(low, 0, 0, SW, SH, (8, 8, 11))
            _rect(low, 20, 200, 230, 80, tuple(gfx.ACCENT))
        full = self.full.getCanvas()
        full.resetMatrix()
        full.clear(gfx.col((8, 8, 11)))
        full.drawImageRect(
            self.low.makeImageSnapshot(),
            skia.Rect.MakeWH(SW, SH),
            skia.Rect.MakeWH(self.out_w, self.out_h),
            self.nearest,
            None,
        )
        if self.text_scale != 1.0:
            full.save()
            full.scale(self.text_scale, self.text_scale)
        try:
            self._draw_title(full, scene, t)
        except Exception:
            pass
        try:
            self._draw_captions(full, scene, t)
        except Exception:
            pass
        self._draw_hud(full, scene_index, t)
        if self.text_scale != 1.0:
            full.restore()
        # short fade avoids a hard black cut between pixel scenes
        if t < 0.20:
            _rect(full, 0, 0, self.out_w, self.out_h, (0, 0, 0),
                  int(210 * (1 - t / 0.20)))
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
            return
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


def _draw_sprite(c, sheet, x, y, frame: int, sampling, scale: float = 1.0):
    src = skia.Rect.MakeXYWH(frame * FRAME_W, 0, FRAME_W, FRAME_H)
    dst = skia.Rect.MakeXYWH(float(x), float(y), FRAME_W * scale, FRAME_H * scale)
    c.drawImageRect(sheet, src, dst, sampling, None)


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
        preset, crf = "ultrafast", 23
        x264_params = ""
    elif renderer.quality == "ultra":
        preset, crf = "slow", 15
        x264_params = "aq-mode=3:aq-strength=1.15:deblock=-1,-1"
    else:
        preset, crf = "medium", 16
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
