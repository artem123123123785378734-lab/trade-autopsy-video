"""Local soundtrack: generated ambient music, SFX and the final voice mix.

No stock audio and no paid libraries. Everything is synthesised with numpy;
a user can also upload their own track, which is looped and ducked under voice.
"""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from . import config

RNG = np.random.default_rng(2026)


# ---------------------------------------------------------------- io
def read_wav_stereo(path: Path, sr: int = config.SR) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch, sw = w.getnchannels(), w.getsampwidth()
        data = w.readframes(w.getnframes())
        src_sr = w.getframerate()
    if sw != 2:
        raise ValueError("Ожидался 16-битный WAV")
    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 1:
        x = np.stack([x, x], axis=1)
    else:
        x = x.reshape(-1, ch)[:, :2]
        if x.shape[1] == 1:
            x = np.stack([x[:, 0], x[:, 0]], axis=1)
    if src_sr != sr:
        n = int(len(x) * sr / src_sr)
        idx = np.linspace(0, len(x) - 1, n)
        x = np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in range(2)], axis=1)
    return x.astype(np.float32)


def write_wav_stereo(path: Path, x: np.ndarray, sr: int = config.SR) -> None:
    x = np.clip(x, -1.0, 1.0)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    pcm = (x * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def load_custom_music(path: Path, duration: float) -> np.ndarray:
    tmp = path.with_suffix(".48k.wav")
    subprocess.run(
        [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-ac", "2", "-ar", str(config.SR), "-c:a", "pcm_s16le", str(tmp)],
        check=True,
    )
    x = read_wav_stereo(tmp)
    try:
        tmp.unlink()
    except OSError:
        pass
    n = int(duration * config.SR)
    if len(x) < n:
        reps = int(math.ceil(n / max(1, len(x))))
        x = np.tile(x, (reps, 1))
    x = x[:n].copy()
    fade = min(int(0.8 * config.SR), len(x) // 4)
    if fade:
        x[:fade] *= np.linspace(0, 1, fade)[:, None]
        x[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return x


# ---------------------------------------------------------------- synthesis helpers
def env_adsr(n: int, a=0.02, d=0.15, s=0.7, r=0.3) -> np.ndarray:
    a_n, d_n, r_n = int(a * config.SR), int(d * config.SR), int(r * config.SR)
    s_n = max(0, n - a_n - d_n - r_n)
    return np.concatenate([
        np.linspace(0, 1, max(1, a_n), endpoint=False),
        np.linspace(1, s, max(1, d_n), endpoint=False),
        np.full(s_n, s),
        np.linspace(s, 0, max(1, n - a_n - d_n - s_n)),
    ])[:n]


def add(buf: np.ndarray, start: float, sig: np.ndarray, gain=1.0, pan=0.0):
    i = int(start * config.SR)
    if i >= len(buf):
        return
    n = min(len(sig), len(buf) - i)
    if n <= 0:
        return
    l = math.sqrt(max(0.0, 0.5 - pan * 0.5)) * gain
    r = math.sqrt(max(0.0, 0.5 + pan * 0.5)) * gain
    if sig.ndim == 1:
        buf[i:i + n, 0] += sig[:n] * l
        buf[i:i + n, 1] += sig[:n] * r
    else:
        buf[i:i + n, 0] += sig[:n, 0] * l
        buf[i:i + n, 1] += sig[:n, 1] * r


def pad_note(freq: float, dur: float, amp=0.1) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    x = np.zeros(n)
    for det in (0.997, 1.0, 1.004):
        x += np.sin(2 * np.pi * freq * det * t)
        x += 0.18 * np.sin(2 * np.pi * freq * 2 * det * t)
        x += 0.08 * np.sin(2 * np.pi * freq * 3 * det * t)
    x /= 3.5
    e = env_adsr(n, 0.45, 0.25, 0.8, min(0.9, dur * 0.4))
    return x * e * amp


def pluck(freq: float, dur=0.4, amp=0.15) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    x = (np.sin(2 * np.pi * freq * t)
         + 0.45 * np.sin(2 * np.pi * freq * 2.01 * t)
         + 0.2 * np.sin(2 * np.pi * freq * 3.99 * t))
    return x * np.exp(-t * 7.0) * amp


def sub(freq: float, dur=0.6, amp=0.2) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    return np.sin(2 * np.pi * freq * t) * env_adsr(n, 0.01, 0.1, 0.8, 0.2) * amp


def kick(dur=0.32, amp=0.7) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    f = 46 + 105 * np.exp(-t * 34)
    body = np.sin(2 * np.pi * np.cumsum(f) / config.SR) * np.exp(-t * 9)
    click = RNG.normal(0, 0.2, n) * np.exp(-t * 130)
    return (body + click * 0.25) * amp


def hat(dur=0.06, amp=0.12) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    x = RNG.normal(0, 1, n)
    x = x - np.convolve(x, np.ones(5) / 5, mode="same")
    return x * np.exp(-t * 70) * amp


def clap(dur=0.22, amp=0.2) -> np.ndarray:
    n = int(dur * config.SR)
    t = np.arange(n) / config.SR
    x = RNG.normal(0, 1, n)
    x = x - np.convolve(x, np.ones(9) / 9, mode="same")
    return x * np.exp(-t * 26) * amp


def whoosh(dur=0.6, amp=0.25, up=True) -> np.ndarray:
    n = int(dur * config.SR)
    x = RNG.normal(0, 1, n)
    # simple spectral tilt via cumulative smoothing
    smooth = np.convolve(x, np.ones(7) / 7, mode="same")
    t = np.linspace(0, 1, n)
    mix = smooth * (1 - t if up else t) + x * (t if up else 1 - t)
    e = np.sin(np.pi * np.clip(t, 0, 1)) ** 2
    return mix * e * amp


def impact(amp=0.6) -> np.ndarray:
    n = int(1.0 * config.SR)
    t = np.arange(n) / config.SR
    boom = np.sin(2 * np.pi * (38 + 55 * np.exp(-t * 10)) * t) * np.exp(-t * 3.4)
    crack = RNG.normal(0, 1, n) * np.exp(-t * 50) * 0.25
    tail = np.convolve(RNG.normal(0, 0.4, n), np.ones(24) / 24, mode="same") * np.exp(-t * 2.4)
    return (boom + crack + tail) * amp


def pop(freq=760, amp=0.16) -> np.ndarray:
    n = int(0.12 * config.SR)
    t = np.arange(n) / config.SR
    return np.sin(2 * np.pi * freq * t) * np.exp(-t * 48) * amp


def chime(amp=0.2) -> np.ndarray:
    n = int(1.0 * config.SR)
    t = np.arange(n) / config.SR
    x = np.sin(2 * np.pi * 1318.5 * t) * 0.6 + np.sin(2 * np.pi * 1975.5 * t) * 0.4
    return x * np.exp(-t * 4.2) * amp


# ---------------------------------------------------------------- music
def build_music(duration: float, preset: str, seed: int = 7) -> np.ndarray:
    if preset == "none":
        return np.zeros((int(duration * config.SR), 2), dtype=np.float32)
    rng = np.random.default_rng(seed)
    bpm = {"tech": 88.0, "ambient": 68.0, "drive": 104.0}.get(preset, 88.0)
    beat = 60.0 / bpm
    bar = beat * 4
    n = int((duration + 0.8) * config.SR)
    out = np.zeros((n, 2), dtype=np.float32)
    roots = [110.0, 87.31, 130.81, 98.0]  # Am F C G
    minors = [True, False, False, False]
    bars = int(math.ceil((duration + 0.8) / bar)) + 1

    for b in range(bars):
        t0 = b * bar
        root = roots[b % 4]
        minor = minors[b % 4]
        third = 3 if minor else 4
        chord = [root, root * 2 ** (third / 12), root * 2 ** (7 / 12), root * 2]
        for f in chord:
            note = pad_note(f * 2 if preset != "ambient" else f * 1.5, bar + 0.4, 0.055)
            add(out, t0, note, 1.0, pan=rng.uniform(-0.15, 0.15))
        if preset in ("tech", "drive"):
            for k in range(8):
                tt = t0 + k * beat / 2
                f = root / 2 * (2 if k in (3, 6) else 1)
                add(out, tt, sub(f, beat * 0.44, 0.12), 0.75)
        # arpeggio
        steps = 16 if preset != "ambient" else 8
        for k in range(steps):
            tt = t0 + k * (bar / steps)
            f = chord[(k // 2) % 4] * 4
            add(out, tt, pluck(f, 0.24 if preset != "ambient" else 0.5, 0.035),
                1.0, pan=(-0.3 if k % 4 in (0, 3) else 0.3))
        if preset == "drive":
            for k in range(4):
                add(out, t0 + k * beat, kick(0.3, 0.34), 0.8)
            for k in range(8):
                add(out, t0 + k * beat / 2 + beat / 4, hat(0.05, 0.06), 0.8, pan=0.2)
        elif preset == "tech":
            for k in (0, 2):
                add(out, t0 + k * beat, kick(0.3, 0.17), 0.65)
            for k in range(4):
                add(out, t0 + k * beat + beat / 2, hat(0.04, 0.035), 0.7, pan=-0.2)
        else:
            # ambient noise wash
            wash = rng.normal(0, 0.02, int(bar * config.SR)).astype(np.float32)
            wash = np.convolve(wash, np.ones(120) / 120, mode="same")
            add(out, t0, wash, 0.55, pan=0.0)

    # gentle filter and level
    out = np.tanh(out * 1.1) * 0.7
    # loop-safe fade at the end
    fade = min(int(0.8 * config.SR), n // 4)
    if fade:
        out[:fade] *= np.linspace(0, 1, fade)[:, None]
        out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out.astype(np.float32)


def build_sfx(plan: dict) -> np.ndarray:
    duration = float(plan["duration"])
    n = int((duration + 0.3) * config.SR)
    out = np.zeros((n, 2), dtype=np.float32)
    scenes = plan.get("scenes", [])
    for i, s in enumerate(scenes):
        st = float(s.get("start", 0))
        if i > 0:
            add(out, max(0, st - 0.28), whoosh(0.5, 0.20), 0.55, pan=0.0)
        add(out, st, impact(0.28 if i else 0.45), 0.65)
        kind = s.get("kind")
        if kind in ("stat", "dashboard", "bars") and s.get("metric"):
            add(out, st + 0.42, pop(820, 0.09), 0.5, pan=0.15)
        if kind == "cta":
            add(out, st + 0.5, chime(0.16), 0.7, pan=0.0)
    return out


# ---------------------------------------------------------------- mixing
def highpass_fft(x: np.ndarray, cutoff: float = 78.0) -> np.ndarray:
    if len(x) < 16:
        return x
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1.0 / config.SR)
    ramp = np.clip((freqs - cutoff * 0.55) / max(1.0, cutoff * 0.45), 0, 1)
    return np.fft.irfft(spec * ramp, n=len(x)).astype(np.float32)


def mix_project(plan: dict, settings: dict, out_path: Path, music_path: Path | None = None) -> dict:
    duration = float(plan["duration"])
    n = int((duration + 0.35) * config.SR)

    # -------- voice
    voice = np.zeros(n, dtype=np.float32)
    for s in plan.get("scenes", []):
        audio = s.get("audio")
        if not audio:
            continue
        x = read_wav_stereo(Path(audio))[:, 0]
        i = int(float(s.get("place", s.get("start", 0))) * config.SR)
        ln = min(len(x), n - i)
        if ln > 0:
            voice[i:i + ln] += x[:ln]
    voice = highpass_fft(voice, 82)
    peak = float(np.max(np.abs(voice))) or 1.0
    voice = np.tanh(voice / peak * 2.1) / np.tanh(2.1)
    voice *= 0.92

    # -------- music
    if settings.get("music", True):
        if music_path and music_path.exists():
            music = load_custom_music(music_path, duration + 0.3)
        else:
            music = build_music(duration + 0.3, settings.get("music_preset", "tech"),
                                seed=abs(hash(settings.get("style", ""))) % 10000 + 7)
        music = music[:n]
        if len(music) < n:
            music = np.pad(music, ((0, n - len(music)), (0, 0)))
    else:
        music = np.zeros((n, 2), dtype=np.float32)

    # -------- sfx
    if settings.get("sfx", True):
        sfx = build_sfx(plan)
        if len(sfx) < n:
            sfx = np.pad(sfx, ((0, n - len(sfx)), (0, 0)))
        sfx = sfx[:n]
    else:
        sfx = np.zeros((n, 2), dtype=np.float32)

    # -------- duck music under speech
    win = int(0.03 * config.SR)
    env = np.abs(voice)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    slow = int(0.20 * config.SR)
    env = np.convolve(env, np.ones(slow) / slow, mode="same")
    env = np.clip(env / 0.05, 0, 1)
    duck = (1.0 - 0.74 * env).astype(np.float32)

    gain = float(settings.get("music_gain", 0.22))
    gain = max(0.0, min(0.8, gain))
    music_gain = gain * (0.55 if settings.get("music_preset") == "drive" else 0.72)
    master = music * duck[:, None] * music_gain + sfx
    master[:, 0] += voice
    master[:, 1] += voice

    # soft limiter and fades
    master = np.tanh(master * 1.12) / np.tanh(1.12)
    fade_in = int(0.25 * config.SR)
    fade_out = int(0.45 * config.SR)
    if fade_in:
        master[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    if fade_out:
        master[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = float(np.max(np.abs(master))) or 1.0
    master = master / peak * 0.92
    write_wav_stereo(out_path, master)
    rms = 20 * math.log10(float(np.sqrt(np.mean(master ** 2))) + 1e-9)
    return {
        "path": str(out_path),
        "rms_db": round(rms, 2),
        "voice_peak": round(float(np.max(np.abs(voice))), 3),
        "duration": round(len(master) / config.SR, 3),
    }
