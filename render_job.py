"""Render one job inside GitHub Actions.

The Worker sends a base64 JSON payload via workflow_dispatch. This script
runs the same pipeline as the local studio, then copies the final files to
`out/` for the release step.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from studio import pipeline


def main(payload_path: str) -> None:
    data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    job_id = str(data["job_id"])
    title = str(data.get("title") or "Без названия")
    script = str(data.get("script") or "")
    settings = dict(data.get("settings") or {})
    # GitHub-hosted runners cannot reliably reach Microsoft's Edge endpoint.
    # Use the offline Piper voice bundled by the workflow.
    settings.update(provider="piper", voice="ru_RU-denis-medium", pitch=0,
                    quality="fast", auto_rate=True)
    settings.pop("eleven_key", None)
    settings.pop("custom_music", None)
    project_id = f"gh_{job_id}"
    render_id = "r1"

    info = pipeline.generate(
        project_id=project_id,
        title=title,
        script=script,
        settings=settings,
        render_id=render_id,
    )
    out = Path("out")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info["video"], out / "video.mp4")
    shutil.copy2(info["srt"], out / "subtitles.srt")
    if info.get("poster"):
        shutil.copy2(info["poster"], out / "poster.png")
    meta = {
        "job_id": job_id,
        "duration": info.get("duration"),
        "scenes": info.get("scenes"),
        "size": info.get("size"),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RENDER_OK", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python render_job.py payload.json")
    main(sys.argv[1])
