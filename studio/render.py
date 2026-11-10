"""Frame compositor + parallel FFmpeg renderer.

The canvas is Skia (software, no browser). Frames are split across worker
processes, each worker pipes raw BGRA frames into its own H.264 segment.
The segments are concatenated and the final audio master is muxed on top.
"""
from __future__ import annotations

import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from bisect import bisect_right
from pathlib import Path

import skia

from . import config, gfx, scenes
from .gfx import (BAD, CYAN, GREEN, HIGHLIGHT, MUTED, TEXT, WHITE, clamp, col,
                  dot, ease_out, fill_paint, line, orb, stroke_paint, text_w)

# ---------------------------------------------------------------- caption helpers
KEY_WORDS = {
    "TRADE", "AUTOPSY", "PREMIUM", "SMC", "R", "P&L", "EQUITY", "WINRATE",
    "TELEGRAM", "BOOSTY", "TIKTOK", "MP4", "AI", "API", "ЖУРНАЛ", "ТИЛЬТ",
    "БЕСПЛАТНО", "ГОД", "МЕСЯЦ", "ДЕПОЗИТ", "ПРОФИТ", "УБЫТОК", "РИСК",
}


def is_keyword(word: str) -> bool:
    raw = word.strip(".,!?;:—–-«»\"()")
    core = raw.upper()
    if not core:
        return False
    if any(ch.isdigit() for ch in core):
        return True
    if core in KEY_WORDS:
        return True
    if len(raw) >= 2 and raw.isupper() and raw.isalpha():
        return True
    return False


class Renderer:
    def __init__(self, plan: dict, settings: dict, fast: bool = False):
        self.plan = plan
        self.settings = settings
        self.quality = str(settings.get("quality") or ("fast" if fast else "quality"))
        if self.quality not in ("fast", "quality", "ultra"):
            self.quality = "quality"
        self.fast = self.quality == "fast"
        if self.quality == "fast":
            self.scale = 0.6667
            self.out_w, self.out_h = 720, 1280
        elif self.quality == "ultra":
            self.scale = 4 / 3
            self.out_w, self.out_h = 1440, 2560
        else:
            self.scale = 1.0
            self.out_w, self.out_h = config.W, config.H
        gfx.set_theme(settings.get("style", "tech_blue"))
        self.theme = gfx.THEME
        self.bg = gfx.make_background()
        self.vignette = gfx.make_vignette()
        # Full-size grain avoids a per-frame 2x scale in Skia software mode.
        self.grain = gfx.make_grain(4, (config.W, config.H)) if not self.fast else []
        self._surface = None
        self.segments = plan.get("scenes", [])
        self.phrases = plan.get("phrases", [])
        self.starts = [float(s.get("start", 0)) for s in self.segments]
        self.ends = [float(s.get("end", 0)) for s in self.segments]
        self.p_starts = [float(p.get("t0", 0)) for p in self.phrases]
        self.duration = float(plan.get("duration", 0))
        self.scene_starts = self.starts[1:] if len(self.starts) > 1 else []
        self.ctx = {
            "brand": settings.get("brand", "TRADE AUTOPSY"),
            "title": plan.get("title", ""),
            "cta_url": settings.get("cta_url", ""),
            "cta_label": settings.get("cta_label", "Открыть журнал"),
            "disclaimer": settings.get("disclaimer", ""),
            "settings": settings,
        }
        self._scrim = self._make_scrim()

    def _make_scrim(self):
        surf = skia.Surface(config.W, config.H)
        c = surf.getCanvas()
        c.clear(skia.ColorTRANSPARENT)
        p = skia.Paint(AntiAlias=True)
        p.setShader(skia.GradientShader.MakeLinear(
            [skia.Point(0, 1250), skia.Point(0, 1780)],
            [col((0, 0, 0), 0), col((2, 3, 8), 150), col((2, 3, 8), 215)],
            [0.0, 0.55, 1.0],
        ))
        c.drawRect(skia.Rect.MakeXYWH(0, 1250, config.W, 530), p)
        return surf.makeImageSnapshot()

    # ------------------------------------------------------------------ bg
    def draw_bg(self, c, t):
        c.drawImage(self.bg, 0, 0)
        # tech grid, slowly scrolling
        p = stroke_paint(gfx.ACCENT, 1, 11)
        p.setStrokeCap(skia.Paint.kButt_Cap)
        step = 72
        off = (t * 9) % step
        y = -step + off
        while y < config.H:
            c.drawLine(0, y, config.W, y, p)
            y += step
        x = -(off * 0.5)
        while x < config.W:
            c.drawLine(x, 0, x, config.H, p)
            x += step

        # floating sparks
        rng = random.Random(31)
        for i in range(38):
            speed = 7 + (i % 6) * 4
            px = (rng.random() * config.W + math.sin(t * 0.35 + i) * 16) % config.W
            py = (rng.random() * config.H - t * speed) % config.H
            r = 0.7 + (i % 5) * 0.7
            a = 30 + (i % 4) * 18
            dot(c, px, py, r, gfx.HIGHLIGHT if i % 3 else gfx.ACCENT2, a)
            if i % 19 == 0:
                orb(c, px, py, 14, gfx.ACCENT, 26, 3)

        # slow light streaks
        for i in range(2):
            sx = (t * (70 + i * 45) + i * 540) % (config.W + 500) - 250
            yy = 340 + i * 610
            p2 = skia.Paint(AntiAlias=True)
            p2.setShader(skia.GradientShader.MakeLinear(
                [skia.Point(sx - 240, yy), skia.Point(sx + 240, yy + 40)],
                [col(gfx.ACCENT, 0), col(gfx.ACCENT, 16), col(gfx.ACCENT2, 0)],
            ))
            c.drawRect(skia.Rect.MakeXYWH(sx - 240, yy, 480, 2), p2)

    def draw_cut_fx(self, c, t):
        for s in self.scene_starts:
            lt = t - s
            if 0 <= lt < 0.32:
                k = clamp(lt / 0.32)
                fade = (1 - k) ** 2
                # quick diagonal light wipe instead of a plain full-screen flash
                x = -config.W * 0.55 + k * config.W * 1.55
                path = skia.Path()
                path.moveTo(x, 0)
                path.lineTo(x + 250, 0)
                path.lineTo(x - 170, config.H)
                path.lineTo(x - 420, config.H)
                path.close()
                c.drawPath(path, fill_paint(gfx.ACCENT, int(58 * fade)))
                line(c, x + 250, 0, x - 170, config.H, gfx.HIGHLIGHT, 3,
                     int(165 * fade), cap=False)
                if lt < 0.12:
                    c.drawRect(skia.Rect.MakeWH(config.W, config.H),
                               fill_paint(gfx.TEXT, int(16 * (1 - lt / 0.12))))
                break

    def draw_grain(self, c, t):
        if not self.grain:
            return
        idx = int(t * config.FPS) % len(self.grain)
        p = skia.Paint(AntiAlias=False)
        p.setAlphaf(0.45)
        c.drawImage(self.grain[idx], 0, 0, skia.SamplingOptions(), p)

    # ------------------------------------------------------------------ HUD
    def draw_hud(self, c, t):
        # top safe area
        dot(c, 62, 74, 4, gfx.ACCENT, 235)
        gfx.draw_text(c, self.ctx["brand"].upper(), 80, 82, "mono", 18, TEXT, 210,
                      tracking=2.4)
        title = (self.ctx.get("title") or "").upper()
        if len(title) > 24:
            title = title[:21].rstrip() + "…"
        if title:
            gfx.draw_text(c, title, 322, 80, "mono", 14, MUTED, 150, tracking=2.0)
        gfx.draw_text(c, f"00:{int(t):02d}", config.W - 58, 82, "mono", 17, MUTED, 150,
                      "right", tracking=1.4)
        idx = 0
        for i, s in enumerate(self.starts):
            if t >= s:
                idx = i
        gfx.draw_text(c, f"{idx + 1:02d}/{len(self.segments):02d}", config.W - 58,
                      108, "mono", 12, MUTED, 105, "right", tracking=1.2)

        # corner ticks
        p = stroke_paint(WHITE, 1.2, 24)
        L = 26
        for (x, y, sx, sy) in ((34, 132, 1, 1), (config.W - 34, 132, -1, 1),
                               (34, 1310, 1, -1), (config.W - 34, 1310, -1, -1)):
            c.drawLine(x, y, x + L * sx, y, p)
            c.drawLine(x, y, x, y + L * sy, p)

        # bottom progress
        x0, x1, y = 66, config.W - 66, 1806
        c.drawLine(x0, y, x1, y, stroke_paint((90, 105, 145), 2, 45))
        prog = clamp(t / max(0.01, self.duration))
        p2 = skia.Paint(AntiAlias=True)
        p2.setShader(skia.GradientShader.MakeLinear(
            [skia.Point(x0, y), skia.Point(x1, y)],
            [col(gfx.ACCENT), col(gfx.ACCENT2)]))
        c.drawLine(x0, y, x0 + (x1 - x0) * prog, y, p2)
        if 0 < prog < 1:
            orb(c, x0 + (x1 - x0) * prog, y, 13, gfx.HIGHLIGHT, 80, 3)

    # ------------------------------------------------------------------ captions
    def _caption_layout(self, phrase):
        words = phrase.get("words") or []
        if not words:
            return 58, []
        max_w = 936
        fallback = (48, [])
        for size in range(72, 47, -2):
            lines: list[list[dict]] = []
            cur: list[dict] = []
            for w in words:
                txt = w.get("display") or w.get("w", "")
                test = " ".join([(x.get("display") or x.get("w", "")) for x in cur] + [txt])
                if cur and text_w(test, "bold", size, -0.8) > max_w:
                    lines.append(cur)
                    cur = []
                cur.append(w)
            if cur:
                lines.append(cur)
            fallback = (size, lines)
            if len(lines) > 2:
                continue
            if lines and len(lines[-1]) == 1 and len(lines[-2]) > 1 and size > 54:
                continue
            if all(text_w(" ".join((x.get("display") or x.get("w", "")) for x in ln),
                        "bold", size, -0.8) <= max_w for ln in lines):
                return size, lines
        return fallback

    def draw_subs(self, c, t):
        i = bisect_right(self.p_starts, t + 0.001) - 1
        if i < 0 or i >= len(self.phrases):
            return
        ph = self.phrases[i]
        t0, t1 = float(ph["t0"]), float(ph["t1"])
        if not (t0 - 0.02 <= t <= t1 + 0.10):
            return
        a_in = clamp((t - t0) / 0.10)
        a_out = clamp((t1 + 0.10 - t) / 0.10)
        alpha = int(255 * min(a_in, a_out))
        if alpha < 8:
            return

        c.drawImage(self._scrim, 0, 0)
        size, lines = self._caption_layout(ph)
        if not lines:
            return
        words = ph.get("words") or []
        word_index = {id(w): i for i, w in enumerate(words)}
        active = -1
        for k, w in enumerate(words):
            if float(w.get("t", 0)) - 0.02 <= t <= float(w.get("t", 0)) + max(0.16, float(w.get("d", 0.2))):
                active = k
                break

        line_h = size * 1.18
        base = 1508 - (len(lines) - 1) * line_h / 2
        rise = int((1 - ease_out(clamp((t - t0) / 0.16))) * 24)
        for li, line_words in enumerate(lines):
            texts = [w.get("display") or w.get("w", "") for w in line_words]
            total = text_w(" ".join(texts), "bold", size, -0.8)
            x = config.W / 2 - total / 2
            y = base + li * line_h - rise
            for w, txt in zip(line_words, texts):
                gi = word_index.get(id(w), 0)
                is_active = gi == active
                key = is_keyword(txt)
                reveal = clamp((t - t0 - gi * 0.018) / 0.11)
                color = gfx.HIGHLIGHT if is_active else (gfx.ACCENT if key else TEXT)
                a = alpha * reveal
                if active >= 0 and gi > active:
                    a *= 0.76
                a = int(a)
                ww = text_w(txt, "bold", size, -0.8)
                if is_active:
                    a = min(255, int(a * 1.08))
                gfx.draw_text(c, txt, x, y + 4, "bold", size, (0, 0, 0), int(a * 0.62),
                              tracking=-0.8)
                gfx.draw_text(c, txt, x, y, "bold", size, color, a, tracking=-0.8,
                              glow=(gfx.HIGHLIGHT if is_active else None), glow_a=72, glow_w=11,
                              scale=(1.055 if is_active else 1.0))
                if is_active:
                    line(c, x + 2, y + 11, x + ww - 2, y + 11, gfx.HIGHLIGHT, 3,
                         int(alpha * 0.85), cap=False)
                x += ww + text_w(" ", "bold", size, -0.8)

    # ------------------------------------------------------------------ frame
    def render(self, t):
        w, h = self.out_w, self.out_h
        if self._surface is None:
            self._surface = skia.Surface(w, h)
        surf = self._surface
        c = surf.getCanvas()
        c.resetMatrix()
        if self.scale != 1.0:
            c.scale(self.scale, self.scale)
        c.clear(col(gfx.THEME["bg"][0]))
        self.draw_bg(c, t)
        idx = 0
        for i, s in enumerate(self.starts):
            if t >= s:
                idx = i
        seg = self.segments[idx] if self.segments else {}
        fn = scenes.SCENES.get(seg.get("kind", "statement"), scenes.scene_statement)
        lt = t - float(seg.get("start", 0) or 0)
        c.save()
        if seg.get("kind") != "hook" and lt < 0.34:
            k = ease_out(clamp(lt / 0.34))
            sc = 1.028 - 0.028 * k
            c.translate(config.W / 2, 760)
            c.scale(sc, sc)
            c.translate(-config.W / 2, -760)
            c.translate(math.sin(lt * 96) * 3.5 * (1 - k),
                        math.cos(lt * 74) * 2.5 * (1 - k))
        try:
            fn(c, t, seg, self.ctx)
        except Exception:
            # A broken visual must never produce a black frame.
            gfx.draw_text(c, "SCENE ERROR", config.W / 2, 800, "bold", 42, BAD, 200,
                          "center")
        finally:
            c.restore()
        self.draw_cut_fx(c, t)
        c.drawImage(self.vignette, 0, 0)
        self.draw_subs(c, t)
        self.draw_hud(c, t)
        if not self.fast:
            self.draw_grain(c, t)
        return surf

    def preview(self, t: float, path: Path):
        surf = self.render(t)
        path.parent.mkdir(parents=True, exist_ok=True)
        surf.makeImageSnapshot().save(str(path), skia.kPNG)
        return path


# ---------------------------------------------------------------- worker
def _worker(args: dict):
    try:
        start, end = args["start"], args["end"]
        renderer = Renderer(args["plan"], args["settings"], fast=args["fast"])
        rw, rh = renderer.out_w, renderer.out_h
        out = Path(args["path"])
        cmd = [
            args["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{rw}x{rh}",
            "-r", str(config.FPS), "-i", "-",
            "-an", "-c:v", "libx264",
            "-preset", args["preset"], "-crf", str(args["crf"]),
            "-profile:v", "high", "-level", "4.2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
        if args.get("x264_params"):
            cmd += ["-x264-params", args["x264_params"]]
        if rw != config.W or rh != config.H:
            cmd += ["-vf", f"scale={config.W}:{config.H}:flags=lanczos"]
        cmd.append(str(out))
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for frame in range(start, end):
                if args["cancel"].is_set():
                    break
                t = frame / config.FPS
                img = renderer.render(t).makeImageSnapshot()
                proc.stdin.write(img.tobytes())
                with args["counter"].get_lock():
                    args["counter"].value += 1
        finally:
            if proc.stdin:
                proc.stdin.close()
            code = proc.wait()
        if code != 0 and not args["cancel"].is_set():
            raise RuntimeError(f"FFmpeg завершился с кодом {code}")
    except Exception:
        try:
            args["errors"].put(traceback.format_exc())
        except Exception:
            pass
        raise


# ---------------------------------------------------------------- helpers
def _visual_key(plan: dict, settings: dict, quality: str) -> str:
    payload = {
        "title": plan.get("title"),
        "duration": plan.get("duration"),
        "scenes": [
            {k: s.get(k) for k in (
                "kind", "text", "title", "accent", "kicker", "note", "badge",
                "bullets", "metric", "chart", "compare", "diagram", "rows",
                "start", "end", "place")}
            for s in plan.get("scenes", [])
        ],
        "phrases": plan.get("phrases", []),
        "style": settings.get("style"),
        "brand": settings.get("brand"),
        "cta_url": settings.get("cta_url"),
        "cta_label": settings.get("cta_label"),
        "disclaimer": settings.get("disclaimer"),
        "quality": quality,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def _concat_and_mux(parts: list[Path], audio: Path, out_path: Path, workdir: Path,
                    ffmpeg: str):
    list_path = workdir / "concat.txt"
    list_path.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
    )
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.2:LRA=9",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------- public
def render_video(plan: dict, settings: dict, out_path: Path, audio_path: Path,
                 progress=None, cancel=None, fast: bool = False) -> Path:
    total_frames = int(round(float(plan["duration"]) * config.FPS))
    if total_frames <= 0:
        raise RuntimeError("Пустая длительность видео")

    quality = str(settings.get("quality") or ("fast" if fast else "quality"))
    if quality not in ("fast", "quality", "ultra"):
        quality = "quality"
    fast = quality == "fast"
    key = _visual_key(plan, settings, quality)
    cache_dir = config.CACHE / "renders"
    cache_dir.mkdir(parents=True, exist_ok=True)
    silent = cache_dir / f"visual_{key}.mp4"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if silent.exists():
        if progress:
            progress(92, "Видео не изменилось — берём готовый рендер из кэша")
        _concat_and_mux([silent], audio_path, out_path, cache_dir, config.FFMPEG)
        if progress:
            progress(98, "Финальный MP4 готов")
        return out_path

    worker_cap = int(os.environ.get("MAX_WORKERS", "5") or 5)
    workers = max(1, min(worker_cap, 5, (os.cpu_count() or 4), max(1, total_frames // 150)))
    workdir = cache_dir / f"work_{key}"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    ctx = mp.get_context("spawn")
    counter = ctx.Value("i", 0)
    cancel_event = ctx.Event()
    errors = ctx.Queue()
    chunk = math.ceil(total_frames / workers)
    procs = []
    parts = []
    if quality == "fast":
        preset, crf = "ultrafast", 24
        x264_params = ""
    elif quality == "ultra":
        preset, crf = "slow", 15
        x264_params = "aq-mode=3:aq-strength=1.15:deblock=-1,-1"
    else:
        preset, crf = "medium", 16
        x264_params = "aq-mode=3:aq-strength=1.05:deblock=-1,-1"
    if progress:
        progress(44, f"Рендер {quality}: {workers} потоков, {total_frames} кадров")

    for wi in range(workers):
        start = wi * chunk
        end = min(total_frames, (wi + 1) * chunk)
        if start >= end:
            break
        part = workdir / f"part_{wi:02d}.mp4"
        parts.append(part)
        args = {
            "plan": plan,
            "settings": settings,
            "fast": fast,
            "start": start,
            "end": end,
            "path": str(part),
            "ffmpeg": config.FFMPEG,
            "preset": preset,
            "crf": crf,
            "x264_params": x264_params,
            "counter": counter,
            "cancel": cancel_event,
            "errors": errors,
        }
        p = ctx.Process(target=_worker, args=(args,), daemon=True)
        p.start()
        procs.append(p)

    interrupted = False
    while any(p.is_alive() for p in procs):
        if cancel and cancel():
            cancel_event.set()
            interrupted = True
        done = counter.value
        if progress:
            pct = min(99, int(100 * done / max(1, total_frames)))
            progress(45 + int(46 * done / max(1, total_frames)),
                     f"Рендер кадров: {done}/{total_frames} ({pct}%)")
        time.sleep(0.45)
    for p in procs:
        p.join()

    err_text = ""
    while True:
        try:
            err_text = errors.get_nowait()
        except Exception:
            break
    if interrupted:
        shutil.rmtree(workdir, ignore_errors=True)
        raise RuntimeError("Генерация отменена")
    if err_text:
        raise RuntimeError("Ошибка рендера: " + err_text.strip().splitlines()[-1])
    for p in procs:
        if p.exitcode not in (0, None):
            raise RuntimeError(f"Процесс рендера завершился с кодом {p.exitcode}")
    if not parts or not all(p.exists() and p.stat().st_size > 1000 for p in parts):
        raise RuntimeError("FFmpeg не создал видеофайлы. Проверь установку FFmpeg.")

    if progress:
        progress(93, "Сборка сцен и наложение звука")
    _concat_and_mux(parts, audio_path, out_path, workdir, config.FFMPEG)
    # Keep the silent master for repeat muxing without re-rendering.
    try:
        shutil.copyfile(out_path, silent)
    except OSError:
        pass
    shutil.rmtree(workdir, ignore_errors=True)
    if progress:
        progress(98, "Финальный MP4 готов")
    return out_path
