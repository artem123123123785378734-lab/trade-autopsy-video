"""Skia drawing toolkit for the video generator.

The renderer runs in worker processes, so the active theme is a module-level
value initialised with :func:`set_theme` before any frame is drawn.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import skia

from . import config

# ------------------------------------------------------------------ theme
THEME: dict = {}
TYPEFACES: dict = {}
WHITE = (245, 248, 255)
BLUE = (58, 132, 255)
BLUE_L = (120, 180, 255)
CYAN = (40, 224, 255)
VIOLET = (168, 92, 250)
VIOLET_L = (205, 160, 255)
PINK = (255, 86, 190)
GREEN = (52, 225, 160)
AMBER = (255, 190, 92)
MUTED = (140, 158, 194)
CARD = (16, 22, 46)
ACCENT = BLUE
ACCENT2 = VIOLET
HIGHLIGHT = CYAN
TEXT = WHITE
BAD = (255, 92, 122)


def set_theme(style_id: str) -> dict:
    global THEME, TYPEFACES, WHITE, BLUE, BLUE_L, CYAN, VIOLET, VIOLET_L
    global PINK, GREEN, AMBER, MUTED, CARD, ACCENT, ACCENT2, HIGHLIGHT, TEXT, BAD
    THEME = dict(config.STYLES[style_id])
    THEME["id"] = style_id
    WHITE = tuple(THEME["text"])
    ACCENT = tuple(THEME["accent"])
    ACCENT2 = tuple(THEME["accent2"])
    HIGHLIGHT = tuple(THEME["highlight"])
    TEXT = tuple(THEME["text"])
    MUTED = tuple(THEME["muted"])
    CARD = tuple(THEME["card"])
    GREEN = tuple(THEME["good"])
    AMBER = tuple(THEME["warn"])
    BAD = tuple(THEME["bad"])
    BLUE, VIOLET = ACCENT, ACCENT2
    BLUE_L = blend(ACCENT, (255, 255, 255), 0.34)
    VIOLET_L = blend(ACCENT2, (255, 255, 255), 0.35)
    CYAN = HIGHLIGHT
    PINK = ACCENT2
    TYPEFACES.clear()
    return THEME


# ------------------------------------------------------------------ colour
def blend(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def col(rgb, a: int = 255) -> int:
    return skia.Color(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(max(0, min(255, a))))


# ------------------------------------------------------------------ easing
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = clamp(t)
    return t ** 3


def ease_in_out(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t, s=1.7):
    t = clamp(t) - 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def pulse(t, speed=2.0, lo=0.0, hi=1.0):
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(t * speed))


def appear(t, start, dur=0.35):
    return ease_out((t - start) / dur)


def spring(t, start, dur=0.45, s=1.9):
    return ease_out_back((t - start) / dur, s)


# ------------------------------------------------------------------ fonts
FONT_FILES = {
    "regular": config.FONTS / "Montserrat-Regular.ttf",
    "medium": config.FONTS / "Montserrat-Medium.ttf",
    "semibold": config.FONTS / "Montserrat-SemiBold.ttf",
    "bold": config.FONTS / "Montserrat-Bold.ttf",
    "extrabold": config.FONTS / "Montserrat-ExtraBold.ttf",
    "black": config.FONTS / "Montserrat-Black.ttf",
    "mono": config.FONTS / "JetBrainsMono-Medium.ttf",
    "monobold": config.FONTS / "JetBrainsMono-Bold.ttf",
    "monoreg": config.FONTS / "JetBrainsMono-Regular.ttf",
}


def _typeface(style: str):
    if style not in TYPEFACES:
        path = FONT_FILES.get(style) or FONT_FILES["bold"]
        TYPEFACES[style] = skia.Typeface.MakeFromFile(str(path))
    return TYPEFACES[style]


@lru_cache(maxsize=768)
def font(style: str, size: int) -> skia.Font:
    f = skia.Font(_typeface(style), int(size))
    f.setSubpixel(True)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f


@lru_cache(maxsize=30000)
def _char_w(style: str, size: int, ch: str) -> float:
    return font(style, size).measureText(ch)


@lru_cache(maxsize=80000)
def text_w(s: str, style="bold", size=64, tracking=0.0) -> float:
    if not s:
        return 0.0
    if tracking == 0:
        return font(style, size).measureText(s)
    return sum(_char_w(style, size, ch) for ch in s) + tracking * (len(s) - 1)


def draw_text(c, s: str, x: float, y: float, style="bold", size=64,
              color=WHITE, alpha=255, align="left", tracking=0.0, shader=None,
              glow=None, glow_a=90, glow_w=6, stroke_color=None, stroke_w=0.0,
              scale=1.0):
    """Draw one line of text. ``y`` is the baseline."""
    if not s or alpha <= 0:
        return 0.0
    p = skia.Paint(AntiAlias=True)
    if shader is not None:
        p.setShader(shader)
    else:
        p.setColor(col(color, alpha))
    if stroke_w and stroke_color:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke_w)
        p.setColor(col(stroke_color, alpha))
    total = text_w(s, style, size, tracking)
    if align == "center":
        x -= total / 2
    elif align == "right":
        x -= total

    f = font(style, size)
    if scale != 1.0:
        c.save()
        c.translate(x + total / 2, y)
        c.scale(scale, scale)
        c.translate(-(x + total / 2), -y)
    if glow:
        gp = skia.Paint(AntiAlias=True, Color=col(glow, glow_a))
        if tracking == 0:
            c.drawString(s, x, y, f, gp)
        else:
            _draw_tracked(c, s, x, y, style, size, tracking, gp)
    if tracking == 0:
        c.drawString(s, x, y, f, p)
    else:
        _draw_tracked(c, s, x, y, style, size, tracking, p)
    if scale != 1.0:
        c.restore()
    return total


def _draw_tracked(c, s, x, y, style, size, tracking, paint):
    f = font(style, size)
    cx = x
    for ch in s:
        c.drawString(ch, cx, y, f, paint)
        cx += _char_w(style, size, ch) + tracking


@lru_cache(maxsize=8000)
def _wrap_cached(s: str, max_w: float, style: str, size: int, tracking: float):
    words = s.split()
    lines, cur = [], ""
    for word in words:
        test = word if not cur else cur + " " + word
        if text_w(test, style, size, tracking) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return tuple(lines)


def wrap_text(s: str, max_w: float, style="semibold", size=56, tracking=0.0):
    return list(_wrap_cached(" ".join(str(s).split()), max_w, style, size, tracking))


def fit_size(text: str, style: str, max_w: float, start: int, min_size: int = 34,
             tracking: float = 0.0) -> int:
    for size in range(int(start), int(min_size) - 1, -2):
        if text_w(text, style, size, tracking) <= max_w:
            return size
    return int(min_size)


def fit_lines(text: str, style: str, max_w: float, start: int, min_size: int = 34,
              max_lines: int = 3, tracking: float = 0.0):
    for size in range(int(start), int(min_size) - 1, -2):
        longest = max((text_w(w, style, size, tracking) for w in str(text).split()),
                      default=0.0)
        if longest > max_w:
            continue
        lines = wrap_text(text, max_w, style, size, tracking)
        if len(lines) <= max_lines:
            return size, lines
    size = int(min_size)
    return size, wrap_text(text, max_w, style, size, tracking)


def draw_par(c, s, x, y, max_w, style="semibold", size=56, line_h=1.15,
             color=WHITE, alpha=255, align="left", tracking=0.0, shader=None,
             glow=None, glow_a=40, glow_w=8):
    lines = wrap_text(s, max_w, style, size, tracking)
    step = size * line_h
    for i, line in enumerate(lines):
        draw_text(c, line, x, y + i * step, style, size, color, alpha, align,
                  tracking, shader=shader, glow=glow, glow_a=glow_a, glow_w=glow_w)
    return len(lines) * step


# ------------------------------------------------------------------ paints
def fill_paint(color, alpha=255):
    p = skia.Paint(AntiAlias=True)
    p.setColor(col(color, alpha))
    return p


def stroke_paint(color, width=2, alpha=255):
    p = skia.Paint(AntiAlias=True)
    p.setColor(col(color, alpha))
    p.setStyle(skia.Paint.kStroke_Style)
    p.setStrokeWidth(width)
    p.setStrokeCap(skia.Paint.kRound_Cap)
    p.setStrokeJoin(skia.Paint.kRound_Join)
    return p


def rrect(c, x, y, w, h, r=28, fill=None, alpha=255, stroke=None, sw=1.5,
          sheen=False, grad=None):
    rect = skia.Rect.MakeXYWH(x, y, w, h)
    rr = skia.RRect.MakeRectXY(rect, r, r)
    if fill is not None:
        p = skia.Paint(AntiAlias=True)
        if grad:
            p.setShader(skia.GradientShader.MakeLinear(
                [skia.Point(x, y), skia.Point(x, y + h)],
                [col(grad[0], alpha), col(grad[1], alpha)],
            ))
        else:
            p.setColor(col(fill, 255 if alpha >= 200 else alpha))
        c.drawRRect(rr, p)
    if stroke is not None:
        c.drawRRect(rr, stroke_paint(stroke, sw, 255 if alpha >= 200 else alpha))
    if sheen:
        p = skia.Paint(AntiAlias=True)
        p.setColor(col(WHITE, 14))
        c.drawRRect(skia.RRect.MakeRectXY(
            skia.Rect.MakeXYWH(x + 1, y + 1, w - 2, max(2, h * 0.28)), r, r), p)


def glass(c, x, y, w, h, r=28, tint=None, alpha=225, border=None, border_a=60,
          sw=1.4):
    tint = tint or CARD
    border = border or ACCENT
    rrect(c, x, y, w, h, r, fill=tint, alpha=alpha, stroke=border, sw=sw)
    p = stroke_paint(WHITE, 1.2, 32)
    c.drawLine(x + r, y + 0.8, x + w - r, y + 0.8, p)


def glow_rrect(c, x, y, w, h, r=28, color=None, strength=1.0):
    color = color or ACCENT
    for width, a in ((28, 7), (15, 13), (7, 24), (3, 58)):
        c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r),
                    stroke_paint(color, width, int(a * strength)))


def line(c, x1, y1, x2, y2, color=None, width=2, alpha=255, cap=True):
    p = stroke_paint(color or ACCENT, width, alpha)
    if not cap:
        p.setStrokeCap(skia.Paint.kButt_Cap)
    c.drawLine(x1, y1, x2, y2, p)


def glow_line(c, x1, y1, x2, y2, color=None, width=2, alpha=220):
    color = color or ACCENT
    for w, a in ((width * 5, int(alpha * 0.07)), (width * 2.6, int(alpha * 0.13)),
                 (width, alpha)):
        line(c, x1, y1, x2, y2, color, w, a)


def dot(c, x, y, r, color=None, alpha=255):
    c.drawCircle(x, y, r, fill_paint(color or ACCENT, alpha))


def orb(c, x, y, r, color=None, alpha=120, rings: int = 4):
    color = color or ACCENT
    if r <= 0 or alpha <= 0:
        return
    p = skia.Paint(AntiAlias=True)
    p.setColor(col(color, 255))
    per = max(1, int(alpha / (rings * 0.72)))
    for i in range(rings):
        rr = r * (1 - i / rings * 0.86)
        p.setAlphaf(clamp(per / 255, 0, 1))
        c.drawCircle(x, y, rr, p)


def gradient_shader(x, y, w, c1=None, c2=None, vertical=False):
    c1 = c1 or ACCENT
    c2 = c2 or ACCENT2
    if vertical:
        pts = [skia.Point(x, y - w), skia.Point(x, y)]
    else:
        pts = [skia.Point(x, y), skia.Point(x + w, y)]
    return skia.GradientShader.MakeLinear(pts, [col(c1), col(blend(c1, (255, 255, 255), 0.35)), col(c2)])


# ------------------------------------------------------------------ components
def kicker(c, text, x, y, color=None, alpha=255, size=21, center=False, width=34):
    if not text or alpha <= 0:
        return
    color = color or ACCENT
    text = str(text).upper()
    tw = text_w(text, "mono", size, 3.0)
    if center:
        x = config.W / 2 - (width + 16 + tw) / 2
    line(c, x, y + 2, x + width, y + 2, color, 2, alpha)
    dot(c, x + 4, y + 2, 3.5, color, alpha)
    draw_text(c, text, x + width + 16, y + 9, "mono", size, color, alpha, tracking=3.0)


def chip(c, text, x, y, color=None, alpha=255, size=20, pad_x=18, pad_y=10):
    if not text or alpha <= 0:
        return 0
    color = color or ACCENT
    tw = text_w(text, "mono", size, 1.0)
    h = size + 2 * pad_y
    w = tw + 2 * pad_x
    rrect(c, x, y, w, h, h / 2, fill=color, alpha=max(8, int(28 * alpha / 255)),
          stroke=color, sw=1.2)
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), h / 2, h / 2),
                stroke_paint(color, 1.2, int(120 * alpha / 255)))
    draw_text(c, text, x + pad_x, y + h / 2 + size * 0.36, "mono", size, color,
              alpha, tracking=1.0)
    return w


def icon_check(c, x, y, s=26, color=None, alpha=255, width=3.0):
    color = color or GREEN
    p = skia.Path()
    p.moveTo(x, y + s * 0.55)
    p.lineTo(x + s * 0.36, y + s * 0.9)
    p.lineTo(x + s, y + s * 0.1)
    c.drawPath(p, stroke_paint(color, width, alpha))


def icon_cross(c, x, y, s=24, color=None, alpha=255, width=3.0):
    color = color or BAD
    p = stroke_paint(color, width, alpha)
    c.drawLine(x, y, x + s, y + s, p)
    c.drawLine(x + s, y, x, y + s, p)


def icon_arrow(c, x, y, s=20, color=None, alpha=255, width=2.6, angle=0):
    color = color or WHITE
    c.save()
    c.translate(x, y)
    c.rotate(angle)
    p = stroke_paint(color, width, alpha)
    c.drawLine(-s / 2, 0, s / 2, 0, p)
    c.drawLine(s / 2 - s * 0.28, -s * 0.28, s / 2, 0, p)
    c.drawLine(s / 2 - s * 0.28, s * 0.28, s / 2, 0, p)
    c.restore()


def icon_bolt(c, x, y, s=24, color=None, alpha=255):
    color = color or HIGHLIGHT
    p = skia.Path()
    p.moveTo(x + s * 0.55, y)
    p.lineTo(x + s * 0.12, y + s * 0.56)
    p.lineTo(x + s * 0.45, y + s * 0.56)
    p.lineTo(x + s * 0.34, y + s)
    p.lineTo(x + s * 0.9, y + s * 0.38)
    p.lineTo(x + s * 0.55, y + s * 0.38)
    p.close()
    c.drawPath(p, fill_paint(color, alpha))


def icon_warn(c, x, y, s=30, color=None, alpha=255):
    color = color or AMBER
    p = skia.Path()
    p.moveTo(x + s / 2, y)
    p.lineTo(x + s, y + s * 0.9)
    p.lineTo(x, y + s * 0.9)
    p.close()
    c.drawPath(p, fill_paint(color, alpha))
    draw_text(c, "!", x + s / 2, y + s * 0.8, "black", int(s * 0.55),
              (10, 12, 24), alpha, "center")


# ------------------------------------------------------------------ assets
def make_background(theme: dict | None = None) -> skia.Image:
    theme = theme or THEME
    stops = theme["bg"]
    surf = skia.Surface(config.W, config.H)
    c = surf.getCanvas()
    bands = 96
    hb = config.H / bands
    # four-stop vertical gradient, drawn as bands (fast software path)
    for i in range(bands):
        u = i / (bands - 1)
        if u < 1 / 3:
            f = u * 3
            cc = blend(stops[0], stops[1], f)
        elif u < 2 / 3:
            f = (u - 1 / 3) * 3
            cc = blend(stops[1], stops[2], f)
        else:
            f = (u - 2 / 3) * 3
            cc = blend(stops[2], stops[3], f)
        c.drawRect(skia.Rect.MakeXYWH(0, i * hb - 0.5, config.W, hb + 1),
                   fill_paint(cc, 255))

    # ambient glows
    for (gx, gy, gr, gc, gs) in ((880, 360, 320, theme["accent"], 0.30),
                                 (150, 1480, 300, theme["accent2"], 0.26)):
        p = skia.Paint(AntiAlias=True)
        rings = 34
        for k in range(rings):
            rr = gr * (1 - k / rings)
            f = gs * ((k + 1) / rings) ** 2.0
            p.setColor(col(blend(stops[1], gc, f), 255))
            c.drawCircle(gx, gy, rr, p)
    return surf.makeImageSnapshot()


def make_vignette() -> skia.Image:
    surf = skia.Surface(config.W, config.H)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    p = skia.Paint(AntiAlias=True)
    p.setShader(skia.GradientShader.MakeRadial(
        skia.Point(config.W / 2, config.H * 0.44), config.W * 0.98,
        [col((0, 0, 0), 0), col((0, 0, 0), 0), col((0, 0, 0), 195)],
        [0.0, 0.55, 1.0],
    ))
    c.drawRect(skia.Rect.MakeWH(config.W, config.H), p)
    return surf.makeImageSnapshot()


def make_grain(n=5, size=(540, 960), seed=7) -> list[skia.Image]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
        noise = rng.normal(128, 22, (size[1], size[0])).clip(0, 255).astype(np.uint8)
        arr[..., 0] = noise
        arr[..., 1] = noise
        arr[..., 2] = noise
        arr[..., 3] = 15
        out.append(skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType))
    return out


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return f"{int(round(value)):,}".replace(",", " ")
    return f"{value:,.1f}".replace(",", " ")


def fit_caption_size(text: str, max_w: float, start: int = 62, min_size: int = 40):
    for size in range(start, min_size - 1, -2):
        if text_w(text, "bold", size, -0.8) <= max_w:
            return size
    return min_size
