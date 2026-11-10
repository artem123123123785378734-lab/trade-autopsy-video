"""Animated scene library.

Every scene is a pure function of (canvas, absolute time, scene data).
Keeping them stateless makes parallel rendering and caching safe.
"""
from __future__ import annotations

import math

import skia

from . import config, gfx
from .gfx import (AMBER, BAD, CYAN, GREEN, HIGHLIGHT, MUTED, TEXT, WHITE,
                  appear, clamp, col, ease_in_out, ease_out, fill_paint, glass,
                  glow_line, glow_rrect, kicker, lerp, line, orb, pulse, rrect,
                  spring, stroke_paint, text_w)

M = 66
CX = config.W / 2
CONTENT_TOP = 250
CAPTION_TOP = 1350


# ---------------------------------------------------------------- primitives
def _fit_title(text, style, max_w, start, min_size=48, max_lines=3, tracking=-1.5):
    return gfx.fit_lines(text, style, max_w, start, min_size, max_lines, tracking)


def _title_shader(x, y, width):
    return gfx.gradient_shader(x, y, max(10, width), gfx.ACCENT, gfx.ACCENT2)


def draw_title_block(c, seg, y=360, size=88, max_lines=2, center=False,
                     max_w=930, style=None, show_kicker=True, kicker_y=None,
                     accent_size=52):
    """Kicker + big title + accent. Returns the y coordinate after the block."""
    u = seg.get("_u", 0)
    style = style or gfx.THEME.get("title_font", "black")
    if show_kicker:
        a = appear(u, 0.02, 0.35)
        if center:
            kicker(c, seg.get("kicker", ""), 0, kicker_y or (y - 105), gfx.ACCENT,
                   int(225 * a), 20, center=True)
        else:
            kicker(c, seg.get("kicker", ""), M, kicker_y or (y - 105), gfx.ACCENT,
                   int(225 * a), 20)
    title = seg.get("title", "")
    fsize, lines = _fit_title(title, style, max_w, size, int(size * 0.52), max_lines, -1.6)
    a1 = appear(u, 0.06, 0.45)
    step = fsize * 1.04
    for i, ln in enumerate(lines):
        aa = appear(u, 0.06 + i * 0.08, 0.42)
        rise = int((1 - aa) * 24)
        tw = text_w(ln, style, fsize, -1.6)
        x = (CX - tw / 2) if center else M
        sh = _title_shader(x, y + i * step, tw)
        gfx.draw_text(c, ln, x, y + i * step + rise, style, fsize, TEXT, int(255 * aa),
                      tracking=-1.6, shader=sh, glow=gfx.ACCENT, glow_a=38, glow_w=12,
                      scale=1.0 + 0.012 * (1 - aa))
    bottom = y + (len(lines) - 1) * step
    accent = seg.get("accent", "")
    if accent:
        a2 = appear(u, 0.34, 0.45)
        rise2 = int((1 - a2) * 18)
        asize = gfx.fit_size(accent, "extrabold", max_w, accent_size, 28, 0.4)
        ay = bottom + asize * 1.28
        if center:
            gfx.draw_text(c, accent, CX, ay + rise2, "extrabold", asize, TEXT, int(238 * a2),
                          "center", tracking=0.5)
        else:
            line(c, M, ay - asize * 0.72 + rise2, M + 5, ay + 6 + rise2,
                 gfx.ACCENT2, 5, int(210 * a2))
            gfx.draw_text(c, accent, M + 24, ay + rise2, "extrabold", asize, TEXT,
                          int(238 * a2), tracking=0.4)
        bottom = ay
    # animated underline under the whole block
    bar = ease_out(clamp((u - 0.30) / 0.55))
    if bar > 0:
        bx = (CX - 120) if center else M
        by = bottom + 34
        line(c, bx, by, bx + 240 * bar, by, gfx.ACCENT, 4, 170, cap=False)
        line(c, bx + 252 * bar, by, bx + 300 * bar, by, gfx.ACCENT2, 4, 150, cap=False)
    return bottom


def draw_note(c, text, y=1190, alpha=210, color=MUTED, center=False, width=None):
    if not text:
        return
    width = width or 900
    size = gfx.fit_size(text.upper(), "mono", width, 20, 13, 2.4)
    if center:
        gfx.draw_text(c, text.upper(), CX, y, "mono", size, color, alpha, "center",
                      tracking=2.4)
    else:
        gfx.draw_text(c, text.upper(), M, y, "mono", size, color, alpha, tracking=2.4)


def draw_badge(c, text, y=1000, alpha=230, center=True, color=None):
    if not text:
        return
    color = color or gfx.GREEN
    tw = text_w(text, "mono", 20, 1.0) + 38
    x = (CX - tw / 2) if center else M
    gfx.chip(c, text, x, y, color, alpha, 20)


def panel(c, x, y, w, h, r=32, tint=None, border=None, alpha=232):
    glass(c, x, y, w, h, r, tint=tint, alpha=alpha, border=border or gfx.ACCENT,
          border_a=52, sw=1.3)
    # tiny inner top highlight
    c.drawLine(x + r, y + 1.5, x + w - r, y + 1.5, stroke_paint(WHITE, 1, 22))


def chip_row(c, items, x, y, gap=12, alpha=220):
    cx = x
    for text, color in items:
        w = gfx.chip(c, text, cx, y, color, alpha, 16, 12, 7)
        cx += w + gap


def _count(u, value, delay=0.15, dur=0.85):
    k = ease_out(clamp((u - delay) / dur))
    return value * k


# ================================================================ scenes
def scene_hook(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    zoom = 1.06 - 0.05 * ease_out(u / 1.2)
    c.save()
    c.translate(CX, 780)
    c.scale(zoom, zoom)
    c.translate(-CX, -780)

    # opening rings
    for i in range(2):
        if u < 1.0:
            rr = 100 + 800 * ease_out(u / (0.9 + i * 0.15))
            c.drawCircle(CX, 760, rr, stroke_paint(gfx.ACCENT if i == 0 else gfx.ACCENT2,
                                                   2.5, int((90 - i * 30) * (1 - u / 1.2))))
    orb(c, CX, 720, 470, gfx.ACCENT, 22, 5)
    orb(c, CX, 720, 330, gfx.ACCENT2, 14, 4)

    a0 = appear(u, 0.02, 0.35)
    kicker(c, seg.get("kicker", "РАЗБОР"), 0, 352, gfx.ACCENT, int(230 * a0), 21, center=True)
    draw_title_block(c, seg, y=560, size=126, max_lines=3, center=True,
                     max_w=930, show_kicker=False, accent_size=66)
    draw_note(c, seg.get("note", ""), 1085, int(200 * appear(u, 0.75, 0.5)), center=True,
              width=860)
    draw_badge(c, seg.get("badge", ""), 1130, int(230 * appear(u, 0.95, 0.5)))

    # corner ticks
    p = stroke_paint(WHITE, 1.4, 26)
    for (x, y, sx, sy) in ((38, 250, 1, 1), (config.W - 38, 250, -1, 1),
                           (38, 1240, 1, -1), (config.W - 38, 1240, -1, -1)):
        c.drawLine(x, y, x + 30 * sx, y, p)
        c.drawLine(x, y, x, y + 30 * sy, p)
    c.restore()


def scene_statement(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    c.save()
    zoom = 1.015 + 0.015 * ease_in_out(clamp(u / 5))
    c.translate(CX, 760)
    c.scale(zoom, zoom)
    c.translate(-CX, -760)

    # faint index number
    idx = str(seg.get("index", 0) + 1).zfill(2)
    gfx.draw_text(c, idx, config.W - 54, 660, "black", 360, gfx.ACCENT, 12, "right",
                  tracking=-12)
    a = appear(u, 0.02, 0.35)
    line(c, 54, 360, 54, 1180, gfx.ACCENT, 2, int(60 * a), cap=False)
    line(c, 54, 360, 54, 520, gfx.ACCENT2, 5, int(180 * a), cap=False)

    bottom = draw_title_block(c, seg, y=430, size=92, max_lines=3, max_w=890)
    note = seg.get("note", "")
    if note:
        aa = appear(u, 0.7, 0.45)
        ny = 1080
        panel(c, M, ny, config.W - 2 * M, 100, 24, alpha=222)
        gfx.dot(c, M + 34, ny + 50, 5, gfx.GREEN, int(230 * aa))
        gfx.draw_text(c, note, M + 58, ny + 59, "semibold", 32, TEXT, int(235 * aa),
                      tracking=0.2)
    draw_note(c, seg.get("badge", ""), 1240, int(170 * appear(u, 1.0, 0.4)), center=False)
    c.restore()


def scene_checklist(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    bottom = draw_title_block(c, seg, y=380, size=80, max_lines=2, max_w=930,
                              accent_size=42)
    bullets = seg.get("bullets") or []
    if not bullets:
        bullets = [seg.get("title", ""), seg.get("accent", "")]
    bullets = [b for b in bullets if b][:3]
    n = len(bullets)
    top = max(640, bottom + 90)
    avail = 1190 - top
    gap = 22
    h = min(168, (avail - gap * (n - 1)) / max(1, n))
    bad_tone = seg.get("tone") == "bad"
    icon_color = BAD if bad_tone else gfx.GREEN
    for i, b in enumerate(bullets):
        aa = spring(u, 0.32 + i * 0.20, 0.48)
        if aa <= 0:
            continue
        y = top + i * (h + gap)
        dx = int((1 - aa) * 55)
        x = M + dx
        panel(c, x, y, config.W - 2 * M, h, 26, alpha=int(235 * aa))
        # number
        orb(c, x + 56, y + h / 2, 42, icon_color, int(38 * aa))
        gfx.dot(c, x + 56, y + h / 2, 31, (12, 16, 30), int(240 * aa))
        gfx.draw_text(c, f"0{i + 1}", x + 56, y + h / 2 + 8, "mono", 20,
                      icon_color, int(240 * aa), "center", tracking=1)
        # icon
        if bad_tone:
            gfx.icon_cross(c, x + config.W - 2 * M - 70, y + h / 2 - 13, 26, BAD,
                           int(220 * aa), 3)
        else:
            gfx.icon_check(c, x + config.W - 2 * M - 70, y + h / 2 - 13, 26, GREEN,
                           int(220 * aa), 3)
        lines = gfx.wrap_text(b, config.W - 2 * M - 190, "semibold", 33, 0.1)[:2]
        ty = y + h / 2 - (len(lines) - 1) * 20 + 11
        for k, ln in enumerate(lines):
            gfx.draw_text(c, ln, x + 106, ty + k * 41, "semibold", 33, TEXT,
                          int(238 * aa), tracking=0.1)
    draw_note(c, seg.get("note", ""), 1260, int(190 * appear(u, 1.1, 0.4)))


def scene_stat(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    metric = seg.get("metric") or {}
    value = float(metric.get("value", 0))
    prefix = metric.get("prefix", "")
    suffix = metric.get("suffix", "")
    label = metric.get("label", "") or ""

    kicker(c, seg.get("kicker", "ЦИФРЫ"), 0, 330, gfx.ACCENT, 230, 20, center=True)
    a0 = appear(u, 0.05, 0.4)
    if label:
        gfx.draw_text(c, label.upper(), CX, 455, "semibold", 34, MUTED, int(230 * a0),
                      "center", tracking=1.6)

    # gauge
    if u > 0.05:
        sweep = 260 * ease_out(clamp((u - 0.05) / 1.1))
        rect = skia.Rect.MakeXYWH(CX - 280, 520, 560, 560)
        c.drawArc(rect, -230, sweep, False, stroke_paint(gfx.ACCENT, 10, 150))
        c.drawArc(rect, -230, 260, False, stroke_paint(gfx.ACCENT, 2, 26))
        for k in range(28):
            ang = math.radians(-230 + k * 260 / 27)
            r1, r2 = 292, 306
            x1, y1 = CX + math.cos(ang) * r1, 800 + math.sin(ang) * r1
            x2, y2 = CX + math.cos(ang) * r2, 800 + math.sin(ang) * r2
            line(c, x1, y1, x2, y2, gfx.ACCENT, 2, 60 if k % 4 else 110, cap=False)

    current = _count(u, value, 0.12, 0.95)
    display = gfx.fmt_num(current)
    if prefix:
        display = prefix + display
    if suffix:
        display = display + " " + suffix
    size = 300 if len(display) <= 5 else 240 if len(display) <= 8 else 186
    tw = text_w(display, "black", size, -4)
    if tw > 930:
        size = int(size * 930 / tw)
        tw = text_w(display, "black", size, -4)
    aa = appear(u, 0.1, 0.4)
    sh = _title_shader(CX - tw / 2, 880, tw)
    gfx.draw_text(c, display, CX, 880, "black", size, TEXT, int(255 * aa), "center",
                  tracking=-4, shader=sh, glow=gfx.ACCENT, glow_a=55, glow_w=18)

    # supporting bullets
    bullets = (seg.get("bullets") or [])[:2]
    y = 1020
    for i, b in enumerate(bullets):
        ab = appear(u, 0.65 + i * 0.16, 0.4)
        gfx.dot(c, M + 20, y + i * 62, 5, gfx.ACCENT2, int(200 * ab))
        gfx.draw_text(c, b, M + 42, y + i * 62 + 8, "semibold", 30, TEXT,
                      int(228 * ab), tracking=0.2)
    draw_note(c, seg.get("note", ""), 1240, int(190 * appear(u, 1.0, 0.4)), center=False)


def _chart_geom(seg, x, y, w, h):
    chart = seg.get("chart") or {}
    candles = chart.get("candles", [])
    if not candles:
        return None
    lo, hi = chart["lo"], chart["hi"]
    span = max(1e-6, hi - lo)
    pad_x, pad_top, pad_bot = 24, 34, 32
    inner_w = w - pad_x * 2
    inner_h = h - pad_top - pad_bot

    def px(i):
        return x + pad_x + (i + 0.5) * inner_w / len(candles)

    def py(v):
        return y + pad_top + (hi - v) / span * inner_h

    return px, py, inner_w, inner_h


def scene_chart(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    bottom = draw_title_block(c, seg, y=355, size=68, max_lines=1, max_w=940,
                              accent_size=34)
    chart = seg.get("chart") or {}
    x, y, w, h = M, 500, config.W - 2 * M, 760
    panel(c, x, y, w, h, 30, alpha=240)

    # header
    gfx.draw_text(c, chart.get("symbol", "EURUSD"), x + 30, y + 54, "monobold", 30,
                  TEXT, 240, tracking=0.5)
    gfx.chip(c, chart.get("timeframe", "M15"), x + 30 + text_w(chart.get("symbol", ""), "monobold", 30, 0.5) + 20,
             y + 28, gfx.ACCENT, 220, 16, 12, 7)
    price = chart.get("price", 1.08)
    change = chart.get("change", 0)
    gfx.draw_text(c, f"{price:.5f}", x + w - 30, y + 48, "monobold", 34,
                  GREEN if change >= 0 else BAD, 245, "right", tracking=0.4)
    ch = f"{change:+.2f}%"
    gfx.draw_text(c, ch, x + w - 30, y + 82, "mono", 19, GREEN if change >= 0 else BAD,
                  200, "right")
    gfx.draw_text(c, "ПРИМЕР СДЕЛКИ", x + w - 30, y + 112, "mono", 14, MUTED, 150,
                  "right", tracking=1.6)

    geom = _chart_geom(seg, x + 12, y + 120, w - 24, h - 150)
    if not geom:
        return
    px, py, inner_w, inner_h = geom
    # grid
    for k in range(5):
        yy = y + 150 + k * (h - 190) / 4
        line(c, x + 26, yy, x + w - 26, yy, gfx.ACCENT, 1, 18, cap=False)
    for k in range(7):
        xx = x + 26 + k * (w - 52) / 6
        line(c, xx, y + 140, xx, y + h - 40, gfx.ACCENT, 1, 10, cap=False)

    candles = chart.get("candles", [])
    progress = clamp((u - 0.15) / 2.1)
    visible = int(len(candles) * progress + 0.999)
    cw = max(4.0, (w - 52) / len(candles) * 0.58)
    for i, cd in enumerate(candles[:visible]):
        alpha = int(245 * clamp((progress * len(candles) - i) / 2.5))
        if alpha <= 0:
            continue
        up = cd["c"] >= cd["o"]
        color = GREEN if up else BAD
        cx = px(i)
        line(c, cx, py(cd["h"]), cx, py(cd["l"]), color, 2, int(alpha * 0.75), cap=False)
        top, bot = py(max(cd["o"], cd["c"])), py(min(cd["o"], cd["c"]))
        rect = skia.Rect.MakeXYWH(cx - cw / 2, top, cw, max(3.0, bot - top))
        c.drawRect(rect, fill_paint(color, alpha))

    # levels
    def level(value, color, label, delay):
        if u < delay:
            return
        yy = py(value)
        p = stroke_paint(color, 2, 190)
        p.setPathEffect(skia.DashPathEffect.Make([9, 7], 0))
        c.drawLine(x + 26, yy, x + w - 120, yy, p)
        gfx.chip(c, label, x + w - 108, yy - 16, color, 235, 14, 9, 5)

    level(chart.get("entry", 0), WHITE, "ВХОД", 1.0)
    level(chart.get("stop", 0), BAD, "СТОП", 1.15)
    level(chart.get("target", 0), GREEN, "ТЕЙК", 1.3)

    # footer stats
    ay = appear(u, 1.35, 0.4)
    line(c, x + 30, y + h - 46, x + w - 30, y + h - 46, gfx.ACCENT, 1, int(35 * ay), cap=False)
    gfx.draw_text(c, "РИСК 1%", x + 30, y + h - 22, "mono", 16, MUTED, int(190 * ay),
                  tracking=1.4)
    gfx.draw_text(c, "R:R 1 : 2.5", x + 170, y + h - 22, "mono", 16,
                  gfx.ACCENT, int(200 * ay), tracking=1.4)
    gfx.draw_text(c, "БЕЗ СИГНАЛОВ · ТОЛЬКО ТВОИ ДАННЫЕ", x + w - 30, y + h - 22,
                  "mono", 14, MUTED, int(160 * ay), "right", tracking=1.1)
    draw_note(c, seg.get("note", ""), 1305, int(180 * ay))


def scene_dashboard(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    draw_title_block(c, seg, y=355, size=68, max_lines=1, max_w=950, accent_size=32)
    x, y, w, h = M, 500, config.W - 2 * M, 790
    panel(c, x, y, w, h, 30, alpha=242)

    # window chrome
    for i, cc in enumerate(((255, 96, 96), (255, 196, 86), (110, 231, 168))):
        gfx.dot(c, x + 30 + i * 24, y + 28, 7, cc, 220)
    gfx.draw_text(c, "TRADE AUTOPSY — ЖУРНАЛ", x + 116, y + 35, "mono", 17, MUTED,
                  210, tracking=1.4)
    gfx.chip(c, "ПРИМЕР", x + w - 104, y + 14, gfx.ACCENT, 210, 13, 10, 5)

    # summary tiles
    tiles = [("58%", "WINRATE"), ("1.9", "PROFIT FACTOR"), ("+0.42R", "СРЕДНИЙ R")]
    tw = (w - 60 - 24) / 3
    for i, (val, lab) in enumerate(tiles):
        tx = x + 30 + i * (tw + 12)
        ty = y + 66
        rrect(c, tx, ty, tw, 132, 18, fill=(255, 255, 255), alpha=10,
              stroke=gfx.ACCENT, sw=1.0)
        # count-up for numeric values
        if i == 0:
            v = f"{_count(u, 58, 0.35):.0f}%"
        elif i == 1:
            v = f"{_count(u, 1.9, 0.45, 0.8):.1f}"
        else:
            v = f"+{_count(u, 0.42, 0.55, 0.9):.2f}R"
        gfx.draw_text(c, v, tx + 20, ty + 64, "black", 40, TEXT, 245, tracking=-1)
        gfx.draw_text(c, lab, tx + 20, ty + 104, "mono", 13, MUTED, 190, tracking=1.2)

    # table header
    hy = y + 238
    gfx.draw_text(c, "ДАТА", x + 30, hy, "mono", 13, MUTED, 160, tracking=1.2)
    gfx.draw_text(c, "ИНСТРУМЕНТ", x + 120, hy, "mono", 13, MUTED, 160, tracking=1.2)
    gfx.draw_text(c, "СЕТАП", x + 390, hy, "mono", 13, MUTED, 160, tracking=1.2)
    gfx.draw_text(c, "R", x + w - 170, hy, "mono", 13, MUTED, 160, "right", tracking=1.2)
    gfx.draw_text(c, "P&L", x + w - 30, hy, "mono", 13, MUTED, 160, "right", tracking=1.2)
    line(c, x + 30, hy + 18, x + w - 30, hy + 18, gfx.ACCENT, 1, 35, cap=False)

    rows = seg.get("rows") or []
    for i, row in enumerate(rows[:4]):
        aa = spring(u, 0.55 + i * 0.14, 0.45)
        if aa <= 0:
            continue
        ry = y + 290 + i * 102
        selected = i == 0
        if selected:
            rrect(c, x + 22, ry - 26, w - 44, 86, 16, fill=gfx.ACCENT, alpha=18,
                  stroke=gfx.ACCENT, sw=1.5)
        else:
            line(c, x + 30, ry + 58, x + w - 30, ry + 58, gfx.ACCENT, 1, 20, cap=False)
        date, pair, setup, rr, pnl = row
        gfx.draw_text(c, date, x + 30, ry + 20, "mono", 19, MUTED, int(220 * aa), tracking=0.4)
        gfx.draw_text(c, pair, x + 120, ry + 24, "monobold", 24, TEXT, int(240 * aa), tracking=0.4)
        gfx.draw_text(c, setup, x + 390, ry + 22, "mono", 17, MUTED, int(205 * aa), tracking=0.2)
        up = rr.startswith("+")
        gfx.draw_text(c, rr, x + w - 170, ry + 24, "monobold", 22, GREEN if up else BAD,
                      int(240 * aa), "right", tracking=0.3)
        gfx.draw_text(c, pnl, x + w - 30, ry + 24, "monobold", 22, GREEN if up else BAD,
                      int(240 * aa), "right", tracking=0.3)

    a = appear(u, 1.2, 0.5)
    gfx.draw_text(c, "P&L · СЕТАП · РИСК · ЭМОЦИИ", x + 30, y + h - 22, "mono", 14,
                  MUTED, int(180 * a), tracking=1.3)
    gfx.draw_text(c, "ИСТОРИЯ НЕ ОБРЕЗАЕТСЯ", x + w - 30, y + h - 22, "mono", 14,
                  gfx.ACCENT, int(180 * a), "right", tracking=1.3)


def scene_terminal(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    draw_title_block(c, seg, y=355, size=68, max_lines=1, max_w=950, accent_size=32)
    x, y, w, h = M, 500, config.W - 2 * M, 780
    panel(c, x, y, w, h, 30, alpha=244)

    # header
    gfx.draw_text(c, "BTCUSDT", x + 30, y + 46, "monobold", 30, TEXT, 245, tracking=0.5)
    gfx.chip(c, "PERP", x + 178, y + 22, gfx.ACCENT, 220, 14, 10, 6)
    gfx.chip(c, "LONG 0.40", x + 250, y + 22, GREEN, 220, 14, 10, 6)
    price = 64820 + math.sin(u * 2.2) * 18 + math.sin(u * 5.1) * 6
    gfx.draw_text(c, f"{price:,.0f}".replace(",", " "), x + w - 30, y + 46, "monobold", 34,
                  GREEN, 245, "right", tracking=0.3)
    gfx.draw_text(c, "+0.42%", x + w - 30, y + 76, "mono", 15, GREEN, 190, "right")

    # order book
    bx, bw = x + 26, 470
    by = y + 110
    gfx.draw_text(c, "СТАКАН", bx, by, "mono", 13, MUTED, 180, tracking=1.6)
    gfx.draw_text(c, "ЦЕНА", bx + bw - 130, by, "mono", 12, MUTED, 150, "right", tracking=1.1)
    gfx.draw_text(c, "ОБЪЁМ", bx + bw, by, "mono", 12, MUTED, 150, "right", tracking=1.1)
    asks = [(64960 + i * 8, 0.8 + i * 0.21) for i in range(4, 0, -1)]
    bids = [(64952 - i * 8, 0.9 + i * 0.24) for i in range(0, 4)]
    row_h = 42
    yy = by + 24
    for i, (pr, sz) in enumerate(asks):
        aa = appear(u, 0.2 + i * 0.05, 0.3)
        rrect(c, bx, yy - 24, bw * min(1, sz / 2.2), row_h - 6, 5, fill=BAD, alpha=int(26 * aa))
        gfx.draw_text(c, f"{pr:.0f}", bx + 8, yy, "mono", 19, BAD, int(220 * aa))
        gfx.draw_text(c, f"{sz:.2f}", bx + bw, yy, "mono", 19, MUTED, int(220 * aa), "right")
        yy += row_h
    # spread
    line(c, bx, yy + 2, bx + bw, yy + 2, gfx.ACCENT, 1, 45, cap=False)
    gfx.draw_text(c, "SPREAD 0.8", bx + bw / 2, yy + 24, "mono", 13, MUTED, 170, "center",
                  tracking=1.2)
    yy += 34
    for i, (pr, sz) in enumerate(bids):
        aa = appear(u, 0.35 + i * 0.05, 0.3)
        rrect(c, bx, yy - 24, bw * min(1, sz / 2.2), row_h - 6, 5, fill=GREEN, alpha=int(26 * aa))
        gfx.draw_text(c, f"{pr:.0f}", bx + 8, yy, "mono", 19, GREEN, int(220 * aa))
        gfx.draw_text(c, f"{sz:.2f}", bx + bw, yy, "mono", 19, MUTED, int(220 * aa), "right")
        yy += row_h

    # position card
    px, pw = x + 530, w - 560
    py = y + 110
    rrect(c, px, py, pw, 210, 20, fill=(255, 255, 255), alpha=10, stroke=gfx.ACCENT, sw=1.0)
    gfx.draw_text(c, "ОТКРЫТАЯ ПОЗИЦИЯ", px + 20, py + 32, "mono", 13, MUTED, 190, tracking=1.3)
    gfx.draw_text(c, "LONG", px + 20, py + 76, "black", 42, GREEN, 245, tracking=-1)
    gfx.draw_text(c, "0.40 BTC", px + 20, py + 108, "mono", 16, MUTED, 200, tracking=0.6)
    pnl = 328 + 46 * math.sin(u * 1.7)
    gfx.draw_text(c, f"+${pnl:,.0f}".replace(",", " "), px + pw - 20, py + 76, "black", 40,
                  GREEN, 245, "right", tracking=-1)
    gfx.draw_text(c, "P&L", px + pw - 20, py + 108, "mono", 13, MUTED, 180, "right", tracking=1.3)
    gfx.draw_text(c, "ВХОД 64 510", px + 20, py + 160, "mono", 15, TEXT, 200, tracking=0.4)
    gfx.draw_text(c, "R:R 1 : 3.1", px + pw - 20, py + 160, "mono", 15, gfx.ACCENT, 210,
                  "right", tracking=0.4)

    # risk bar
    ry = py + 250
    gfx.draw_text(c, "РИСК 0.8% / ЛИМИТ 1.0%", px, ry, "mono", 14, MUTED, 200, tracking=1.1)
    rrect(c, px, ry + 16, pw, 14, 7, fill=(255, 255, 255), alpha=18)
    rrect(c, px, ry + 16, pw * 0.8 * ease_out(clamp((u - 0.5) / 0.8)), 14, 7,
          fill=gfx.GREEN, alpha=235)
    gfx.draw_text(c, "ЛИМИТЫ ПОД КОНТРОЛЕМ", px, ry + 72, "mono", 14, GREEN, 190,
                  tracking=1.1)
    gfx.draw_text(c, "ПРОП-РЕЖИМ", px + pw, ry + 72, "mono", 14, gfx.ACCENT, 200, "right",
                  tracking=1.1)

    # buttons
    by2 = y + h - 74
    rrect(c, px, by2, pw * 0.48, 52, 14, fill=gfx.ACCENT, alpha=230)
    gfx.draw_text(c, "ЗАКРЫТЬ", px + pw * 0.24, by2 + 34, "monobold", 18, (8, 10, 16), 245,
                  "center", tracking=0.8)
    rrect(c, px + pw * 0.52, by2, pw * 0.48, 52, 14, fill=(255, 255, 255), alpha=12,
          stroke=gfx.ACCENT, sw=1.2)
    gfx.draw_text(c, "ЗАЩИТИТЬ", px + pw * 0.76, by2 + 34, "monobold", 18, TEXT, 235,
                  "center", tracking=0.8)
    draw_note(c, seg.get("note", ""), 1320, int(170 * appear(u, 1.0, 0.4)))


def scene_diagram(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    bottom = draw_title_block(c, seg, y=380, size=76, max_lines=2, max_w=930,
                              accent_size=40)
    diagram = seg.get("diagram") or {}
    nodes = diagram.get("nodes") or ["СДЕЛКА", "ЖУРНАЛ", "РАЗБОР", "РЕШЕНИЕ"]
    nodes = nodes[:4]
    center = diagram.get("center", "СИСТЕМА")
    cx, cy = CX, 880
    positions = [(cx, cy - 240), (cx + 300, cy), (cx, cy + 240), (cx - 300, cy)]
    labels_pos = [(cx, cy - 180), (cx + 300, cy + 70), (cx, cy + 300), (cx - 300, cy + 70)]

    # connections + pulses
    for i, (nx, ny) in enumerate(positions):
        aa = appear(u, 0.2 + i * 0.12, 0.45)
        if aa <= 0:
            continue
        glow_line(c, cx, cy, nx, ny, gfx.ACCENT, 2, int(150 * aa))
        ph = (u * 0.45 + i * 0.25) % 1.0
        px = lerp(cx, nx, ph)
        py = lerp(cy, ny, ph)
        orb(c, px, py, 18, gfx.HIGHLIGHT, int(90 * (1 - abs(ph - 0.5) * 1.2)), 3)

    # central node
    a0 = appear(u, 0.1, 0.45)
    orb(c, cx, cy, 190, gfx.ACCENT, int(30 * a0), 5)
    gfx.dot(c, cx, cy, 132, (13, 18, 36), int(250 * a0))
    c.drawCircle(cx, cy, 132, stroke_paint(gfx.ACCENT, 2, int(200 * a0)))
    lines = gfx.wrap_text(center, 210, "monobold", 25, 1.0)[:2]
    for k, ln in enumerate(lines):
        gfx.draw_text(c, ln, cx, cy - (len(lines) - 1) * 16 + k * 34 + 9, "monobold",
                      25, TEXT, int(245 * a0), "center", tracking=1.0)

    for i, ((nx, ny), (lx, ly)) in enumerate(zip(positions, labels_pos)):
        aa = spring(u, 0.35 + i * 0.14, 0.45)
        if aa <= 0:
            continue
        orb(c, nx, ny, 78, gfx.ACCENT2 if i % 2 else gfx.ACCENT, int(45 * aa), 4)
        gfx.dot(c, nx, ny, 52, (12, 16, 32), int(245 * aa))
        c.drawCircle(nx, ny, 52, stroke_paint(gfx.ACCENT2 if i % 2 else gfx.ACCENT, 2,
                                              int(220 * aa)))
        gfx.draw_text(c, f"0{i + 1}", nx, ny + 7, "mono", 19,
                      gfx.ACCENT2 if i % 2 else gfx.ACCENT, int(235 * aa), "center", tracking=1)
        label = nodes[i]
        lsize = gfx.fit_size(label.upper(), "monobold", 250, 24, 15, 1.4)
        gfx.draw_text(c, label.upper(), lx, ly, "monobold", lsize, TEXT, int(235 * aa),
                      "center", tracking=1.4)

    draw_note(c, seg.get("note", ""), 1260, int(180 * appear(u, 1.0, 0.4)), center=True)


def scene_compare(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    draw_title_block(c, seg, y=380, size=74, max_lines=2, max_w=930, accent_size=38)
    cmp = seg.get("compare") or analyzer_compare()
    y, h = 610, 560
    gap = 24
    w = (config.W - 2 * M - gap) / 2
    sides = [
        (M, cmp["left"], cmp["left_items"], BAD, "cross", 0.18),
        (M + w + gap, cmp["right"], cmp["right_items"], gfx.GREEN, "check", 0.42),
    ]
    for x, title, items, color, icon, delay in sides:
        aa = spring(u, delay, 0.55)
        if aa <= 0:
            continue
        dy = int((1 - aa) * 40)
        panel(c, x, y + dy, w, h, 28, tint=(14, 18, 34) if color == BAD else (12, 24, 22),
              alpha=int(235 * aa))
        rrect(c, x, y + dy, w, 8, 4, fill=color, alpha=int(220 * aa))
        gfx.draw_text(c, title.upper(), x + 24, y + dy + 58, "black", 26, color,
                      int(240 * aa), tracking=0.4)
        for k, item in enumerate(items[:3]):
            iy = y + dy + 126 + k * 130
            icon_x = x + 24
            if icon == "cross":
                gfx.icon_cross(c, icon_x, iy - 18, 18, color, int(220 * aa), 2.6)
            else:
                gfx.icon_check(c, icon_x, iy - 22, 20, color, int(220 * aa), 2.8)
            lines = gfx.wrap_text(item, w - 88, "semibold", 27, 0.1)[:2]
            for j, ln in enumerate(lines):
                gfx.draw_text(c, ln, x + 62, iy + j * 35, "semibold", 27, TEXT,
                              int(225 * aa), tracking=0.1)
        # bottom marker
        gfx.draw_text(c, "ТАК СЕЙЧАС" if icon == "cross" else "ТАК МОЖНО",
                      x + 24, y + dy + h - 28, "mono", 14, color, int(170 * aa), tracking=1.4)

    # vs circle
    av = spring(u, 0.55, 0.5)
    if av > 0:
        gfx.dot(c, CX, y + h / 2, 52, (10, 13, 26), int(250 * av))
        c.drawCircle(CX, y + h / 2, 52, stroke_paint(gfx.ACCENT, 2, int(220 * av)))
        gfx.draw_text(c, "VS", CX, y + h / 2 + 9, "monobold", 22, gfx.ACCENT,
                      int(240 * av), "center", tracking=1)
    draw_note(c, seg.get("note", ""), 1250, int(180 * appear(u, 1.1, 0.4)), center=True)


def analyzer_compare():
    return {
        "left": "БЕЗ ЖУРНАЛА",
        "right": "С ЖУРНАЛОМ",
        "left_items": ["Сделки в голове", "Ошибки повторяются", "Нет цифр"],
        "right_items": ["Вся история в одном месте", "Видно, что съедает депозит", "Решения по данным"],
    }


def scene_notification(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    draw_title_block(c, seg, y=380, size=74, max_lines=2, max_w=930, accent_size=38)

    # phone
    x, y, w, h = 302, 590, 476, 610
    aa = appear(u, 0.1, 0.5)
    rrect(c, x, y, w, h, 48, fill=(8, 10, 20), alpha=int(245 * aa),
          stroke=gfx.ACCENT, sw=2)
    rrect(c, x + 10, y + 10, w - 20, h - 20, 40, fill=(13, 17, 32), alpha=int(240 * aa))
    # notch
    rrect(c, x + w / 2 - 58, y + 18, 116, 20, 10, fill=(4, 5, 10), alpha=int(240 * aa))
    gfx.draw_text(c, "9:41", x + 34, y + 62, "monobold", 18, TEXT, int(220 * aa))
    gfx.draw_text(c, "● ● ●", x + w - 34, y + 62, "mono", 12, TEXT, int(180 * aa), "right")

    # notification 1
    def notif(ny, title, body, delay, tint):
        a = spring(u, delay, 0.5)
        if a <= 0:
            return
        dy = int((1 - a) * -60)
        rrect(c, x + 18, ny + dy, w - 36, 136, 22, fill=(24, 28, 46), alpha=int(248 * a),
              stroke=tint, sw=1.2)
        rrect(c, x + 34, ny + dy + 20, 46, 46, 13, fill=tint, alpha=int(235 * a))
        gfx.draw_text(c, "TA", x + 57, ny + dy + 51, "monobold", 16, (8, 10, 16),
                      int(240 * a), "center", tracking=0)
        gfx.draw_text(c, "TRADE AUTOPSY", x + 92, ny + dy + 34, "monobold", 14, TEXT,
                      int(230 * a), tracking=0.6)
        gfx.draw_text(c, "сейчас", x + w - 34, ny + dy + 34, "mono", 12, MUTED,
                      int(180 * a), "right")
        gfx.draw_text(c, title, x + 92, ny + dy + 58, "semibold", 16, TEXT, int(235 * a))
        lines = gfx.wrap_text(body, w - 130, "regular", 14, 0)[:2]
        for k, ln in enumerate(lines):
            gfx.draw_text(c, ln, x + 92, ny + dy + 82 + k * 18, "regular", 14, MUTED,
                          int(210 * a))

    notif(y + 100, seg.get("title", "Недельный отчёт готов"),
          seg.get("accent", "") or seg.get("note", "") or "Разбор твоих сделок внутри.", 0.45,
          gfx.ACCENT)
    notif(y + 252, "Тильт-детектор", "2 убытка подряд. Пора сделать паузу.", 1.05,
          gfx.AMBER)
    notif(y + 404, "Проп-режим", "Лимит риска 0.8% из 1.0%. Всё под контролем.", 1.55,
          gfx.GREEN)

    draw_note(c, seg.get("note", ""), 1275, int(180 * appear(u, 1.2, 0.4)), center=True)


def scene_bars(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    draw_title_block(c, seg, y=380, size=74, max_lines=2, max_w=920, accent_size=38)
    x, y, w, h = M, 600, config.W - 2 * M, 570
    panel(c, x, y, w, h, 30, alpha=238)
    gfx.chip(c, "ПРИМЕР РАЗБОРА", x + w - 190, y + 22, gfx.ACCENT, 210, 13, 11, 5)
    rows = seg.get("rows") or []
    maxv = max([r[1] for r in rows] or [1])
    for i, (label, value) in enumerate(rows[:4]):
        aa = appear(u, 0.25 + i * 0.14, 0.5)
        if aa <= 0:
            continue
        ry = y + 96 + i * 112
        gfx.draw_text(c, label, x + 28, ry + 8, "semibold", 25, TEXT, int(230 * aa))
        bx, bw = x + 270, w - 380
        rrect(c, bx, ry - 12, bw, 26, 13, fill=(255, 255, 255), alpha=14)
        prog = ease_out(clamp((u - 0.35 - i * 0.14) / 0.8))
        rrect(c, bx, ry - 12, max(8, bw * value / maxv * prog), 26, 13,
              fill=gfx.ACCENT if i % 2 == 0 else gfx.ACCENT2, alpha=235)
        gfx.draw_text(c, f"{value:.0f}%", x + w - 28, ry + 8, "monobold", 25,
                      gfx.ACCENT, int(225 * aa), "right")
    draw_note(c, seg.get("note", ""), 1250, int(170 * appear(u, 1.0, 0.4)))


def scene_timeline(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    bottom = draw_title_block(c, seg, y=380, size=78, max_lines=2, max_w=930, accent_size=38)
    steps = (seg.get("bullets") or [])[:3]
    if not steps:
        steps = ["Первый шаг", "Второй шаг", "Третий шаг"]
    x_line = 120
    y0 = max(660, bottom + 100)
    gap = 180
    line(c, x_line, y0 - 30, x_line, y0 + gap * (len(steps) - 1) + 30, gfx.ACCENT, 2, 55, cap=False)
    for i, text in enumerate(steps):
        aa = spring(u, 0.35 + i * 0.2, 0.5)
        if aa <= 0:
            continue
        cy = y0 + i * gap
        color = [gfx.GREEN, gfx.ACCENT, gfx.ACCENT2][i % 3]
        orb(c, x_line, cy, 54, color, int(40 * aa), 4)
        gfx.dot(c, x_line, cy, 36, (11, 16, 32), int(250 * aa))
        c.drawCircle(x_line, cy, 36, stroke_paint(color, 2, int(220 * aa)))
        gfx.draw_text(c, f"0{i + 1}", x_line, cy + 8, "mono", 19, color,
                      int(240 * aa), "center", tracking=1)
        panel(c, 190, cy - 62, config.W - 190 - M, 124, 22, alpha=int(238 * aa))
        lines = gfx.wrap_text(text, config.W - 190 - M - 44, "semibold", 30, 0.1)[:2]
        for k, ln in enumerate(lines):
            gfx.draw_text(c, ln, 218, cy - (len(lines) - 1) * 19 + k * 38 + 10,
                          "semibold", 30, TEXT, int(238 * aa), tracking=0.1)
    draw_note(c, seg.get("note", ""), 1260, int(170 * appear(u, 1.1, 0.4)))


def scene_quote(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    kicker(c, seg.get("kicker", "ПРАВИЛО"), 0, 330, gfx.ACCENT, 225, 20, center=True)
    aa = appear(u, 0.08, 0.5)
    gfx.draw_text(c, "“", CX, 520, "black", 260, gfx.ACCENT, int(60 * aa), "center")
    text = seg.get("title", "")
    size, lines = _fit_title(text, "bold", 900, 78, 46, 4, -1.0)
    y = 700
    for i, ln in enumerate(lines):
        a = appear(u, 0.15 + i * 0.12, 0.45)
        gfx.draw_text(c, ln, CX, y + i * size * 1.08, "bold", size, TEXT, int(245 * a),
                      "center", tracking=-1.0)
    accent = seg.get("accent", "")
    if accent:
        a = appear(u, 0.7, 0.45)
        gfx.draw_text(c, "— " + accent.upper(), CX, y + len(lines) * size * 1.08 + 70,
                      "mono", 20, MUTED, int(210 * a), "center", tracking=2.0)
    draw_note(c, seg.get("note", ""), 1250, int(170 * appear(u, 1.0, 0.4)), center=True)


def scene_cta(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    # pulsing rings
    for i in range(3):
        ph = (u * 0.30 + i / 3) % 1.0
        rr = 200 + 340 * ph
        c.drawCircle(CX, 880, rr, stroke_paint(gfx.ACCENT if i % 2 else gfx.ACCENT2,
                                               2, int(42 * (1 - ph))))
    orb(c, CX, 820, 420, gfx.ACCENT, 18, 5)

    a0 = appear(u, 0.02, 0.35)
    kicker(c, seg.get("kicker", "НАЧНИ СЕЙЧАС"), 0, 390, gfx.ACCENT, int(230 * a0),
           21, center=True)
    block_bottom = draw_title_block(c, seg, y=590, size=118, max_lines=3, center=True,
                                    max_w=920, show_kicker=False, accent_size=56)
    # button
    label = ctx.get("cta_label") or "Открыть журнал"
    ab = spring(u, 0.55, 0.55)
    by = max(930, min(1010, block_bottom + 72))
    if ab > 0:
        bw = text_w(label, "bold", 38, 0.4) + 150
        bh = 104
        bx = CX - bw / 2
        glow_rrect(c, bx, by, bw, bh, bh / 2, gfx.ACCENT, 0.9 * ab)
        rrect(c, bx, by, bw, bh, bh / 2, fill=gfx.ACCENT, alpha=int(245 * ab))
        gfx.draw_text(c, label, bx + 54, by + bh / 2 + 13, "bold", 38, (8, 10, 16),
                      int(245 * ab), tracking=0.4)
        gfx.icon_arrow(c, bx + bw - 56, by + bh / 2, 26, (8, 10, 16), int(235 * ab))
        # subtle shine
        rrect(c, bx + 2, by + 2, bw - 4, bh * 0.36, bh * 0.18, fill=(255, 255, 255), alpha=int(20 * ab))

    url = ctx.get("cta_url") or ""
    if url:
        a = appear(u, 0.9, 0.45)
        gfx.draw_text(c, url, CX, by + 158, "mono", 20, TEXT, int(215 * a), "center",
                      tracking=1.0)
    offer = seg.get("note", "") or "7 дней бесплатно · без карты"
    ao = appear(u, 1.05, 0.45)
    draw_badge(c, offer.upper(), by + 208, int(220 * ao), True, gfx.GREEN)
    disc = ctx.get("disclaimer") or ""
    if disc:
        ad = appear(u, 1.2, 0.5)
        gfx.draw_text(c, disc.upper(), CX, by + 288, "mono", 12, MUTED, int(150 * ad),
                      "center", tracking=1.4)
    draw_badge(c, seg.get("badge", ""), 520, int(200 * appear(u, 0.75, 0.4)))


def scene_outro(c, t, seg, ctx):
    u = t - seg["start"]
    seg["_u"] = u
    # grid + rings
    for k in range(5):
        rr = 120 + k * 90 + math.sin(u * 0.8 + k) * 12
        c.drawCircle(CX, 780, rr, stroke_paint(gfx.ACCENT, 1, 18))
    brand = ctx.get("brand", "TRADE AUTOPSY")
    aa = appear(u, 0.05, 0.5)
    parts = brand.split()
    first = parts[0] if parts else "TRADE"
    rest = " ".join(parts[1:]) if len(parts) > 1 else ""
    size = 78
    w1 = text_w(first, "black", size, -2)
    w2 = text_w(rest, "black", size, -2) if rest else 0
    total = w1 + w2 + (12 if rest else 0)
    x = CX - total / 2
    gfx.draw_text(c, first, x, 720, "black", size, TEXT, int(245 * aa), tracking=-2)
    if rest:
        gfx.draw_text(c, rest, x + w1 + 12, 720, "black", size, gfx.ACCENT, int(245 * aa),
                      tracking=-2, glow=gfx.ACCENT, glow_a=40, glow_w=12)
    gfx.draw_text(c, "ЖУРНАЛ, КОТОРЫЙ ПОКАЗЫВАЕТ ГДЕ ТЫ ТЕРЯЕШЬ",
                  CX, 790, "semibold", 22, MUTED, int(210 * appear(u, 0.4, 0.5)),
                  "center", tracking=1.2)
    url = ctx.get("cta_url") or ""
    if url:
        gfx.draw_text(c, url, CX, 900, "mono", 22, TEXT, int(220 * appear(u, 0.7, 0.5)),
                      "center", tracking=1.0)


SCENES = {
    "hook": scene_hook,
    "statement": scene_statement,
    "checklist": scene_checklist,
    "stat": scene_stat,
    "chart": scene_chart,
    "dashboard": scene_dashboard,
    "terminal": scene_terminal,
    "diagram": scene_diagram,
    "compare": scene_compare,
    "notification": scene_notification,
    "bars": scene_bars,
    "timeline": scene_timeline,
    "quote": scene_quote,
    "cta": scene_cta,
    "outro": scene_outro,
}
