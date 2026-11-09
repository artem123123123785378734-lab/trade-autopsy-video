"""End-to-end generation pipeline: script -> plan -> voice -> mix -> MP4."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import analyzer, audio, config, render, tts


def _poster(plan: dict, settings: dict, path: Path) -> None:
    try:
        r = render.Renderer(plan, settings, fast=False)
        scenes = plan.get("scenes") or []
        t = float(scenes[0].get("start", 0)) + min(1.3, max(0.5, float(scenes[0].get("end", 3)) * 0.3))
        r.preview(t, path)
    except Exception:
        # Poster is a nicety; never fail a render because of it.
        pass


def generate(project_id: str, title: str, script: str, settings: dict,
             render_id: str, progress=None, cancel=None, force_tts: bool = False) -> dict:
    t_start = time.time()
    workdir = config.PROJECTS / project_id / "renders" / render_id
    workdir.mkdir(parents=True, exist_ok=True)

    def report(pct: int, message: str):
        if progress:
            progress(max(0, min(100, int(pct))), message)

    report(2, "Разбираю сценарий на сцены")
    plan = analyzer.make_plan(title, script, settings)
    if not plan["scenes"]:
        raise RuntimeError("Не удалось разбить сценарий на сцены")

    effective = dict(config.DEFAULT_SETTINGS)
    effective.update(settings or {})
    effective["rate"] = int(plan["rate"])
    # A safe URL for the CTA card.
    effective["cta_url"] = str(effective.get("cta_url") or "").replace("https://", "").replace("http://", "").strip().rstrip("/")

    custom_music = None
    if effective.get("custom_music"):
        name = Path(str(effective["custom_music"])).name
        p = config.UPLOADS / name
        if p.exists():
            custom_music = p

    report(5, f"Сцен: {len(plan['scenes'])}. Синтезирую озвучку")
    plan = tts.build_timeline(plan, effective, progress=report, cancel=cancel,
                              force=force_tts)

    report(34, "Собираю музыку и микширую звук")
    master = workdir / "master.wav"
    audio.mix_project(plan, effective, master, music_path=custom_music)

    report(42, "Сохраняю сценарий и субтитры")
    srt = workdir / "subtitles.srt"
    tts.write_srt(plan.get("phrases", []), srt)
    (workdir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (workdir / "voiceover.txt").write_text(
        "\n\n".join(s.get("text", "") for s in plan.get("scenes", []) if s.get("text")),
        encoding="utf-8")
    _poster(plan, effective, workdir / "poster.png")

    video = workdir / "video.mp4"
    report(45, "Рендерю видео")
    render.render_video(plan, effective, video, master, progress=report, cancel=cancel,
                        fast=effective.get("quality") == "fast")

    if not video.exists() or video.stat().st_size < 100_000:
        raise RuntimeError("Видео не создано или получилось пустым")

    report(100, "Готово")
    info = {
        "render_id": render_id,
        "project_id": project_id,
        "video": str(video),
        "srt": str(srt),
        "poster": str(workdir / "poster.png") if (workdir / "poster.png").exists() else None,
        "duration": plan.get("duration"),
        "scenes": len(plan.get("scenes", [])),
        "words": len([w for p in plan.get("phrases", []) for w in p.get("words", [])]),
        "rate": plan.get("rate"),
        "size": video.stat().st_size,
        "elapsed": round(time.time() - t_start, 1),
        "plan": plan,
        "audio": str(master),
    }
    return info


def clean_render(project_id: str, render_id: str) -> None:
    workdir = config.PROJECTS / project_id / "renders" / render_id
    shutil.rmtree(workdir, ignore_errors=True)
