"""Kokoro RU — free local Russian TTS on ONNX Runtime (CPU).

The model is a Russian port of Kokoro-82M by zaakirio:
https://huggingface.co/zaakirio/kokoro-ru

Weights are OpenRAIL, code is Apache-2.0. Three fixed voices come from
consented studio actors. The ONNX build needs no GPU and no API key.

The model card exposes speed control, but long sentences become unstable:
the duration predictor stretches some texts and compresses others. Splitting
each scene into sentences keeps the pacing even and adds natural pauses.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

from . import config

REPO = "zaakirio/kokoro-ru"
SAMPLE_RATE = 24000
GAP_SEC = 0.20

VOICES = {
    "kokoro-sveta": {
        "name": "Света", "gender": "female", "file": "sveta",
        "model": "base", "speed": 0.38,
    },
    "kokoro-masha": {
        "name": "Маша", "gender": "female", "file": "masha",
        "model": "base", "speed": 0.38,
    },
    "kokoro-dima": {
        "name": "Дима", "gender": "male", "file": "dima",
        "model": "dima", "speed": 0.62,
    },
}

_loaded = False
_g2p = None
_vocab: dict[str, int] = {}
_styles: dict[str, np.ndarray] = {}
_sessions: dict[str, object] = {}


def model_dir() -> Path:
    return Path(config.KOKORO_DIR)


def ensure_model() -> Path:
    """Download the ONNX model once, into an ASCII-safe local folder."""
    d = model_dir()
    ready = (
        (d / "onnx" / "model_quantized.onnx").exists()
        and (d / "onnx" / "model_dima_quantized.onnx").exists()
        and (d / "kokoro-config.json").exists()
        and (d / "espeak-data" / "ru_dict").exists()
        and (d / "ru_g2p.py").exists()
    )
    if not ready:
        try:
            from huggingface_hub import snapshot_download
        except Exception as exc:  # pragma: no cover - setup error path
            raise RuntimeError(
                "Kokoro RU: не установлен huggingface_hub. "
                "Выполни: pip install huggingface_hub"
            ) from exc
        d.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            REPO,
            local_dir=str(d),
            ignore_patterns=[
                "samples/*",
                "*.pth",
                "onnx/model.onnx",
                "onnx/model_fp16.onnx",
                "onnx/model_dima.onnx",
                "onnx/model_dima_fp16.onnx",
            ],
        )
    _fix_windows_encoding(d / "ru_g2p.py")
    return d


def _fix_windows_encoding(path: Path) -> None:
    """ru_g2p uses Path.read_text() without encoding; Windows defaults to cp1251."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    fixed = text.replace(".read_text()", ".read_text(encoding='utf-8')")
    if fixed != text:
        path.write_text(fixed, encoding="utf-8")


def _load() -> None:
    global _loaded, _g2p, _vocab
    if _loaded:
        return
    d = ensure_model()
    sys.path.insert(0, str(d))

    # Keep RUAccent's downloaded models inside the cached model folder.
    import ruaccent
    _base_accent = ruaccent.RUAccent

    class _CachedAccent(_base_accent):  # type: ignore[misc, valid-type]
        def load(self, *args, **kwargs):
            kwargs.setdefault("workdir", str(d / "ruaccent"))
            return super().load(*args, **kwargs)

    ruaccent.RUAccent = _CachedAccent

    from ru_g2p import RuG2P
    import onnxruntime as ort

    _vocab = json.loads((d / "kokoro-config.json").read_text(encoding="utf-8"))["vocab"]
    for voice, cfg in VOICES.items():
        _styles[voice] = np.fromfile(
            d / "voices" / f"{cfg['file']}.bin", dtype=np.float32
        ).reshape(510, 256)
    for name, path in (
        ("base", d / "onnx" / "model_quantized.onnx"),
        ("dima", d / "onnx" / "model_dima_quantized.onnx"),
    ):
        _sessions[name] = ort.InferenceSession(
            str(path), providers=["CPUExecutionProvider"]
        )
    _g2p = RuG2P()
    _loaded = True


_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_RE = re.compile(r"(?<=[,;:])\s+")


def _chunks(text: str) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return []
    out: list[str] = []
    for sentence in _SENTENCE_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence.split()) <= 16:
            out.append(sentence)
            continue
        current: list[str] = []
        for clause in _CLAUSE_RE.split(sentence):
            if current and len(current) + len(clause.split()) > 12:
                out.append(" ".join(current))
                current = []
            current.append(clause)
        if current:
            out.append(" ".join(current))
    return out


def _speed(voice: str, rate: int) -> float:
    base = VOICES.get(voice, VOICES["kokoro-sveta"])["speed"]
    # rate is the studio's -20..+30 % control; map it onto the model speed.
    return max(0.25, min(1.2, base * (1.0 - rate / 200.0)))


def synthesize(text: str, voice: str = "kokoro-sveta", rate: int = 0) -> tuple[np.ndarray, int]:
    """Return mono float32 audio at 24 kHz."""
    _load()
    cfg = VOICES.get(voice) or VOICES["kokoro-sveta"]
    speed = np.array([_speed(voice, int(rate))], dtype=np.float32)
    pieces: list[np.ndarray] = []
    gap = np.zeros(int(GAP_SEC * SAMPLE_RATE), dtype=np.float32)
    for chunk in _chunks(text):
        ipa, _oov = _g2p(chunk)
        ids = [_vocab[c] for c in ipa if c in _vocab]
        if not ids:
            continue
        row = _styles[voice][min(len(ipa) - 1, 509)][None]
        raw = _sessions[cfg["model"]].run(None, {
            "input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
            "style": row,
            "speed": speed,
        })[0]
        audio = np.asarray(raw, dtype=np.float32).reshape(-1)
        if pieces:
            pieces.append(gap)
        pieces.append(audio)
    if not pieces:
        raise RuntimeError("Kokoro RU не смог озвучить текст")
    out = np.concatenate(pieces)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out, SAMPLE_RATE
