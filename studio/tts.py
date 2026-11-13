"""Text-to-speech providers + word-level timing + subtitle grouping.

Providers
---------
edge        free Microsoft Edge voices, natural Russian, word boundaries
kokoro      free local Kokoro RU neural voices (ONNX, CPU, no key)
piper       fully offline Piper voices from _work/piper
elevenlabs  optional paid provider, requires the user's own API key

Every provider returns a WAV file and a list of word timings. If a provider
does not expose word boundaries we estimate them from the audio duration.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import subprocess
import urllib.request
import wave
from pathlib import Path

import edge_tts
import numpy as np

from . import config
from .analyzer import make_caption_groups, speech_text

TTS_CACHE = config.CACHE / "tts"
TTS_CACHE.mkdir(parents=True, exist_ok=True)
LEAD_PAD = 0.12
TAIL_PAD = 0.30


# ---------------------------------------------------------------- wav utils
def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("Ожидался 16-битный WAV")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path: Path, x: np.ndarray, sr: int = config.SR) -> None:
    x = np.clip(x, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767.0).astype(np.int16).tobytes())


def to_wav(src: Path, dst: Path) -> None:
    subprocess.run(
        [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-ac", "1", "-ar", str(config.SR), "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def trim_silence(x: np.ndarray, threshold: float = 0.004) -> tuple[np.ndarray, int]:
    idx = np.where(np.abs(x) > threshold)[0]
    if idx.size == 0:
        return x, 0
    start = max(0, int(idx[0]) - int(0.025 * config.SR))
    end = min(len(x), int(idx[-1]) + int(0.07 * config.SR))
    return x[start:end], start


# ---------------------------------------------------------------- edge
async def _edge_synth(text: str, voice: str, rate: int, pitch: int,
                      retries: int = 10) -> tuple[bytes, list]:
    last = None
    for attempt in range(retries):
        try:
            com = edge_tts.Communicate(
                text,
                voice,
                rate=f"{rate:+d}%",
                pitch=f"{pitch:+d}Hz",
                boundary="WordBoundary",
            )
            audio = bytearray()
            words: list[dict] = []
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
                elif chunk["type"] == "WordBoundary":
                    words.append({
                        "w": chunk["text"],
                        "t": chunk["offset"] / 1e7,
                        "d": chunk["duration"] / 1e7,
                    })
            if len(audio) < 2500:
                raise RuntimeError(f"слишком короткое аудио ({len(audio)} байт)")
            return bytes(audio), words
        except Exception as exc:  # network hiccups are common
            last = exc
            await asyncio.sleep(1.0 + attempt * 1.0)
    raise RuntimeError(
        f"Edge TTS не ответил после {retries} попыток: {type(last).__name__}: {last}. "
        "Проверь интернет или выбери локальный голос Piper."
    )


def synth_edge(text: str, voice: str, rate: int, pitch: int, key: str) -> dict:
    data, words = asyncio.run(_edge_synth(text, voice, rate, pitch))
    mp3 = TTS_CACHE / f"{key}.mp3"
    wav = TTS_CACHE / f"{key}.wav"
    raw = TTS_CACHE / f"{key}_raw.wav"
    mp3.write_bytes(data)
    to_wav(mp3, raw)
    x, _ = read_wav(raw)
    x, lead = trim_silence(x)
    write_wav(wav, x)
    for w in words:
        w["t"] = max(0.0, w["t"] - lead / config.SR)
    return {"wav": str(wav), "words": words, "dur": len(x) / config.SR,
            "provider": "edge"}


# ---------------------------------------------------------------- kokoro
def synth_kokoro(text: str, voice: str, rate: int, key: str) -> dict:
    """Free local Russian neural voice (Kokoro RU, ONNX Runtime)."""
    from . import kokoro

    audio, sr = kokoro.synthesize(text, voice, rate)
    raw = TTS_CACHE / f"{key}_24k.wav"
    wav = TTS_CACHE / f"{key}.wav"
    write_wav(raw, audio, sr)
    to_wav(raw, wav)
    x, _ = read_wav(wav)
    dur = len(x) / config.SR
    return {"wav": str(wav), "words": estimate_words(text, dur), "dur": dur,
            "provider": "kokoro"}


# ---------------------------------------------------------------- piper
def _piper_model(voice_id: str) -> Path | None:
    for v in config.PIPER_VOICES:
        if v["id"] == voice_id:
            p = config.PIPER_DIR / v["model"]
            if p.exists():
                return p
    return None


def synth_piper(text: str, voice: str, rate: int, key: str) -> dict:
    if not config.ensure_piper():
        raise RuntimeError(
            "Piper не найден. Проверь папку _work/piper или выбери Edge TTS."
        )
    model = _piper_model(voice)
    if not model:
        # Old projects may still point at Irina/Ruslan. Those datasets are not
        # cleared for the commercial studio, so fall back to a CC0 voice.
        for fallback in ("ru_RU-dmitri-medium", "ru_RU-denis-medium"):
            model = _piper_model(fallback)
            if model:
                voice = fallback
                break
    if not model:
        raise RuntimeError(f"Модель Piper для голоса {voice} не найдена.")
    wav = TTS_CACHE / f"{key}.wav"
    raw = TTS_CACHE / f"{key}_raw.wav"
    length_scale = max(0.7, min(1.5, 100.0 / max(50.0, 100.0 + rate)))
    cmd = [
        str(config.PIPER_EXE),
        "--model", str(model),
        "--output_file", str(raw),
        "--length_scale", f"{length_scale:.3f}",
    ]
    proc = subprocess.run(cmd, input=text.encode("utf-8"), capture_output=True,
                          cwd=str(config.PIPER_EXE.parent))
    if proc.returncode != 0 or not raw.exists():
        raise RuntimeError("Piper не смог озвучить текст: " + proc.stderr.decode("utf-8", "ignore")[:300])
    x, sr = read_wav(raw)
    if sr != config.SR:
        n = int(len(x) * config.SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    x, _ = trim_silence(x)
    write_wav(wav, x)
    dur = len(x) / config.SR
    return {"wav": str(wav), "words": estimate_words(text, dur), "dur": dur,
            "provider": "piper"}


# ---------------------------------------------------------------- elevenlabs
def synth_eleven(text: str, voice: str, rate: int, key: str, api_key: str) -> dict:
    if not api_key:
        raise RuntimeError(
            "Для ElevenLabs нужен API-ключ. Открой «API и ключи» и вставь свой ключ."
        )
    if not voice:
        raise RuntimeError("Укажи Voice ID ElevenLabs в настройках.")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("xi-api-key", api_key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "audio/mpeg")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
    except Exception as exc:
        raise RuntimeError(f"ElevenLabs вернул ошибку: {exc}") from exc
    mp3 = TTS_CACHE / f"{key}.mp3"
    wav = TTS_CACHE / f"{key}.wav"
    raw = TTS_CACHE / f"{key}_raw.wav"
    mp3.write_bytes(data)
    to_wav(mp3, raw)
    x, _ = read_wav(raw)
    x, _ = trim_silence(x)
    write_wav(wav, x)
    dur = len(x) / config.SR
    return {"wav": str(wav), "words": estimate_words(text, dur), "dur": dur,
            "provider": "elevenlabs"}


# ---------------------------------------------------------------- fallback timing
def estimate_words(text: str, dur: float) -> list[dict]:
    words = [w for w in re.findall(r"\S+", text) if w]
    if not words:
        return []
    weights = []
    for w in words:
        clean = re.sub(r"[^\wА-Яа-яЁё]", "", w, flags=re.UNICODE)
        weights.append(max(1.0, len(clean)) + (2.5 if w[-1:] in ".!?" else 1.0 if w[-1:] in ",;:" else 0.0))
    total = sum(weights)
    t = 0.0
    out = []
    for w, weight in zip(words, weights):
        d = dur * weight / total
        out.append({"w": w, "t": round(t, 3), "d": round(d, 3)})
        t += d
    return out


# ---------------------------------------------------------------- cache / dispatch
def _cache_key(text: str, settings: dict) -> str:
    raw = "|".join([
        settings.get("provider", "edge"),
        settings.get("voice", ""),
        str(settings.get("rate", 0)),
        str(settings.get("pitch", 0)),
        settings.get("eleven_key", "")[:6],
        text,
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def synth_once(text: str, settings: dict, force: bool = False) -> dict:
    provider = settings.get("provider", "edge")
    voice = settings.get("voice", "ru-RU-DmitryNeural")
    rate = int(settings.get("rate", 0))
    pitch = int(settings.get("pitch", 0))
    key = _cache_key(text, settings)
    wav = TTS_CACHE / f"{key}.wav"
    meta = TTS_CACHE / f"{key}.json"
    if not force and wav.exists() and meta.exists():
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            info["wav"] = str(wav)
            info["cached"] = True
            info["dur"] = wav_duration(wav)
            return info
        except Exception:
            pass
    if provider == "edge":
        info = synth_edge(text, voice, rate, pitch, key)
    elif provider == "kokoro":
        info = synth_kokoro(text, voice, rate, key)
    elif provider == "piper":
        info = synth_piper(text, voice, rate, key)
    elif provider == "elevenlabs":
        info = synth_eleven(text, voice, rate, key, settings.get("eleven_key", ""))
    else:
        raise RuntimeError(f"Неизвестный провайдер озвучки: {provider}")
    info["text"] = text
    info["cached"] = False
    meta.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


# ---------------------------------------------------------------- word alignment
def clean_word(token: str) -> str:
    core = token.strip()
    if not core:
        return core
    if core.isupper():
        return core
    letters = [c for c in core if c.isalpha()]
    if len(letters) > 1 and any(c.isupper() for c in letters[1:]):
        return core
    if core[0].isupper():
        return core[0].lower() + core[1:]
    return core


def align_words(text: str, words: list[dict]) -> list[dict]:
    """Match TTS tokens to the original spelling and punctuation."""
    tokens = text.split()
    norm = lambda s: re.sub(r"[^\w\-]", "", s, flags=re.UNICODE).lower()
    j = 0
    out = []
    for w in words:
        raw = w.get("w", "")
        nb = norm(raw)
        if not nb and raw.strip() in ("—", "–", "-"):
            if out:
                out[-1]["display"] = out[-1]["display"].rstrip(" —–-") + " —"
            continue
        match = None
        dash = False
        for k in range(j, min(j + 4, len(tokens))):
            nt = norm(tokens[k])
            if not nt and tokens[k] in ("—", "–"):
                dash = True
                continue
            if nt == nb or (nb and nt.startswith(nb)) or (nt and nb.startswith(nt)):
                match = k
                break
        if match is None:
            display = clean_word(w.get("w", ""))
            punct = ""
        else:
            tok = tokens[match]
            punct = tok[-1] if tok[-1] in ".,!?:;" else ""
            display = tok.rstrip(".,;:!?")
            j = match + 1
        if dash and out and not out[-1]["display"].rstrip().endswith("—"):
            out[-1]["display"] = out[-1]["display"] + " —"
        # Edge sometimes voices "P&L" as three tokens: P, &, L. The ampersand
        # is not a word and must not reach the subtitle line.
        if display.strip() in ("&", "and") and out and out[-1]["display"].upper().endswith("P&L"):
            continue
        out.append({
            "w": w.get("w", ""),
            "display": display,
            "punct": punct,
            "t": float(w.get("t", 0)),
            "d": float(w.get("d", 0.2)),
        })
    return out


def _phrase_times(groups: list[list[dict]]) -> list[dict]:
    out = []
    for i, group in enumerate(groups):
        text = " ".join(x.get("display") or x.get("w", "") for x in group)
        if not text:
            continue
        if group and group[0].get("display"):
            group[0]["display"] = group[0]["display"][0].upper() + group[0]["display"][1:]
        text = " ".join(x.get("display") or x.get("w", "") for x in group)
        text = text[0].upper() + text[1:]
        start = group[0]["t"]
        last_t = group[-1]["t"] + max(0.18, min(group[-1].get("d", 0.2), 0.7))
        if i + 1 < len(groups):
            nxt = groups[i + 1][0]["t"]
            end = max(start + 0.42, min(nxt - 0.02, last_t + 0.55))
        else:
            end = max(start + 0.5, min(start + 1.15, last_t + 0.2))
        out.append({
            "t0": round(start, 3),
            "t1": round(end, 3),
            "text": text,
            "words": group,
        })
    return out


def _needs_fallback(text: str, words: list[dict]) -> bool:
    """Detect a boundary stream that does not represent the written text."""
    if not words:
        return True
    toks = [t for t in text.split() if re.search(r"\w", t, re.UNICODE)]
    if not toks:
        return False
    norm = lambda s: re.sub(r"[^\w\-]", "", s, flags=re.UNICODE).lower()
    tts_norm = {norm(w.get("w", "")) for w in words}
    missing = sum(1 for t in toks if norm(t) and norm(t) not in tts_norm)
    if missing >= max(2, int(len(toks) * 0.18)):
        return True
    if len(words) > len(toks) * 1.55:
        return True
    if any(w.get("w", "").strip() == "&" for w in words):
        return True
    if re.search(r"\d", text) and any(re.search(r"\d", w.get("w", "")) for w in words):
        return True
    return False


def fmt_ts(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(phrases: list[dict], path: Path) -> None:
    lines = []
    for i, p in enumerate(phrases, 1):
        lines.append(f"{i}\n{fmt_ts(p['t0'])} --> {fmt_ts(p['t1'])}\n{p['text']}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- full timeline
def build_timeline(plan: dict, settings: dict, progress=None, cancel=None,
                   force: bool = False) -> dict:
    scenes = plan["scenes"]
    total = len(scenes)
    synths: list[dict] = []
    base: list[float] = []
    locked: list[bool] = []
    for i, scene in enumerate(scenes):
        if cancel and cancel():
            raise RuntimeError("Генерация отменена")
        if progress:
            progress(5 + int(28 * i / max(1, total)),
                     f"Озвучка сцены {i + 1}/{total}")
        spoken = speech_text(scene["text"])
        if scene.get("text", "").strip():
            info = synth_once(spoken, settings, force=force)
        else:
            info = {"wav": None, "words": [], "dur": 0.0, "cached": False,
                    "provider": settings.get("provider")}
        scene_dur = max(3.1, LEAD_PAD + info["dur"] + TAIL_PAD)
        try:
            override = float(scene.get("duration_override") or 0)
        except (TypeError, ValueError):
            override = 0
        if override > scene_dur:
            scene_dur = override
        synths.append(info)
        base.append(scene_dur)
        locked.append(override >= scene_dur > 0 and override > 0.001)

    # Short scripts must still reach the 45 s minimum. Instead of freezing on
    # a long outro, let each scene breathe after its line: the pacing stays
    # even, captions remain in sync, and the character keeps animating.
    minimum = 45.0
    holds = [0.0] * len(scenes)
    if scenes:
        missing = minimum - sum(base)
        free = [i for i in range(len(scenes)) if not locked[i]]
        step = 0.2
        while missing > 0.05:
            room = [i for i in free if holds[i] < 2.4 - 0.001]
            if not room:
                break
            for i in room:
                if missing <= 0.05:
                    break
                add = min(step, 2.4 - holds[i], missing)
                holds[i] += add
                missing -= add

    phrases: list[dict] = []
    cursor = 0.0
    for i, scene in enumerate(scenes):
        info = synths[i]
        lead = LEAD_PAD
        dur = info["dur"]
        scene_dur = base[i] + holds[i]
        scene["start"] = round(cursor, 3)
        scene["end"] = round(cursor + scene_dur, 3)
        scene["place"] = round(cursor + lead, 3)
        scene["audio"] = info["wav"]
        scene["dur"] = round(dur, 3)
        scene["rate_used"] = settings.get("rate", 0)
        scene["cached"] = info.get("cached", False)
        spoken = speech_text(scene["text"])
        tts_words = info.get("words", [])
        if spoken != scene["text"] or _needs_fallback(scene["text"], tts_words):
            # Edge occasionally merges numbers ("4 884") or drops words from
            # the boundary stream. The original text must win in the captions.
            aligned = align_words(scene["text"], estimate_words(scene["text"], dur))
        else:
            aligned = align_words(scene["text"], tts_words)
        if not aligned:
            aligned = align_words(scene["text"], estimate_words(scene["text"], dur))
        for w in aligned:
            w["t_abs"] = round(scene["place"] + w["t"], 3)
            w["t"] = w["t_abs"]
        groups = make_caption_groups({"words": aligned}, max_chars=30)
        for ph in _phrase_times(groups):
            ph["scene"] = scene["id"]
            phrases.append(ph)
        cursor += scene_dur

    duration = cursor
    # Keep the format inside 45-80 seconds wherever possible.
    if duration < minimum - 0.01:
        deficit = minimum - duration
        if deficit > 0.2:
            outro = {
                "index": len(scenes),
                "id": f"s{len(scenes) + 1:02d}",
                "kind": "outro",
                "text": "",
                "title": "TRADE AUTOPSY",
                "accent": "РАЗБОР, КОТОРЫЙ ВОЗВРАЩАЕТ ДЕНЬГИ",
                "kicker": "ЖУРНАЛ СДЕЛОК",
                "note": "ссылка в профиле",
                "badge": "",
                "bullets": [],
                "metric": None,
                "chart": None,
                "compare": None,
                "diagram": None,
                "rows": [],
                "est": 0.0,
                "start": round(cursor, 3),
                "end": round(cursor + min(12.0, max(2.6, deficit)), 3),
                "place": round(cursor, 3),
                "dur": 0.0,
                "audio": None,
                "cached": False,
            }
            scenes.append(outro)
            cursor = outro["end"]
            duration = cursor

    phrases.sort(key=lambda p: p["t0"])
    plan["duration"] = round(duration, 3)
    plan["phrases"] = phrases
    plan["rate"] = settings.get("rate", plan.get("rate", 0))
    return plan
