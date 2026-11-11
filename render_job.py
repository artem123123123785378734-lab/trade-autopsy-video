"""Render one job inside GitHub Actions.

The Worker sends a base64 JSON payload via workflow_dispatch. This script
runs the same pipeline as the local studio, then copies the final files to
`out/` for the release step.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from studio import pipeline, tts


def _reuse_clips(scenes: list, base_job_id: str | None, base_scene_count: int | None,
                 workdir: Path) -> dict[int, Path] | None:
    if not scenes or not base_job_id:
        return None
    # The base video may contain one auto-generated outro scene that is not
    # present in the editor payload. The release must at least contain clips
    # for every editable scene; missing indices fall back to a full render.
    if base_scene_count is not None and int(base_scene_count) < len(scenes):
        return None
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    reuse: dict[int, Path] = {}
    for i in range(len(scenes)):
        url = f"https://github.com/{repo}/releases/download/render-{base_job_id}/scene-{i + 1:02d}.mp4"
        path = workdir / f"reuse-{i + 1:02d}.mp4"
        try:
            with urllib.request.urlopen(url, timeout=90) as response, path.open("wb") as out:
                shutil.copyfileobj(response, out)
            if path.stat().st_size < 1000:
                return None
            reuse[i] = path
        except Exception:
            return None
    return reuse


def main(payload_path: str) -> None:
    data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    job_id = str(data["job_id"])
    title = str(data.get("title") or "Без названия")
    script = str(data.get("script") or "")
    settings = dict(data.get("settings") or {})
    scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else None
    mode = str(data.get("mode") or "full")
    scene_index = data.get("scene_index")
    base_job_id = data.get("base_job_id")
    base_scene_count = data.get("base_scene_count")
    # Prefer Microsoft Edge neural voices. They are free and much more natural
    # than Piper. If Microsoft is unreachable from the runner, fall back to the
    # bundled CC0 Piper voices automatically.
    edge_allowed = {"ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"}
    piper_allowed = {"ru_RU-dmitri-medium", "ru_RU-denis-medium"}
    provider = str(settings.get("provider") or "edge")
    if provider not in ("edge", "piper"):
        provider = "edge"
    voice = str(settings.get("voice") or "")
    quality = str(settings.get("quality") or "quality")
    if quality not in ("fast", "quality", "ultra"):
        quality = "quality"
    if provider == "edge":
        voice = voice if voice in edge_allowed else "ru-RU-DmitryNeural"
    else:
        voice = voice if voice in piper_allowed else "ru_RU-dmitri-medium"
    settings.update(provider=provider, voice=voice, pitch=0, quality=quality, auto_rate=True)
    settings.pop("eleven_key", None)
    settings.pop("custom_music", None)
    project_id = f"gh_{job_id}"
    render_id = "r1"

    workdir = Path("work") / job_id
    reuse = None
    if mode == "scene" and scenes and isinstance(scene_index, int):
        reuse = _reuse_clips(scenes, base_job_id, base_scene_count, workdir)

    if settings["provider"] == "edge":
        try:
            asyncio.run(tts._edge_synth("Проверка связи.", settings["voice"], 0, 0, retries=2))
        except Exception as exc:
            print("EDGE_PREFLIGHT_FALLBACK", type(exc).__name__, str(exc)[:200], flush=True)
            settings.update(provider="piper", voice="ru_RU-dmitri-medium", pitch=0)

    def run_render():
        return pipeline.generate(
            project_id=project_id,
            title=title,
            script=script,
            settings=settings,
            render_id=render_id,
            scenes_override=scenes,
            scene_index=scene_index if mode == "scene" and reuse is not None else None,
            reuse_clips=reuse,
        )

    provider_used = settings["provider"]
    voice_used = settings["voice"]
    try:
        info = run_render()
    except Exception as exc:
        if settings["provider"] != "edge":
            raise
        print("EDGE_TTS_FALLBACK", type(exc).__name__, str(exc)[:300], flush=True)
        settings.update(provider="piper", voice="ru_RU-dmitri-medium", pitch=0)
        provider_used = "piper"
        voice_used = "ru_RU-dmitri-medium"
        info = run_render()
    out = Path("out")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info["video"], out / "video.mp4")
    shutil.copy2(info["srt"], out / "subtitles.srt")
    if info.get("poster"):
        shutil.copy2(info["poster"], out / "poster.png")
    for i, clip in enumerate(info.get("scene_clips", [])):
        source = Path(clip)
        if source.exists():
            shutil.copy2(source, out / f"scene-{i + 1:02d}.mp4")
    meta = {
        "job_id": job_id,
        "duration": info.get("duration"),
        "scenes": info.get("scenes"),
        "size": info.get("size"),
        "format": info.get("format"),
        "voice": voice_used,
        "provider": provider_used,
        "quality": settings.get("quality"),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RENDER_OK", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python render_job.py payload.json")
    main(sys.argv[1])
