"""Flask application: local web UI + JSON API + background render jobs."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename

from . import analyzer, config, pipeline, storage, tts

KEYS_FILE = config.DATA / "keys.json"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "").lower() in ("1", "true", "yes", "on")
MAX_ACTIVE = 1 if PUBLIC_MODE else 2
MAX_SCRIPT = 6000
RATE_LOCK = threading.Lock()
RATE: dict[str, list[float]] = {}


def _owner() -> str | None:
    if not PUBLIC_MODE:
        return None
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def _client_ip() -> str:
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "unknown")


def _rate_ok(ip: str, bucket: str = "gen") -> bool:
    now = time.time()
    key = f"{bucket}:{ip}"
    with RATE_LOCK:
        arr = [t for t in RATE.get(key, []) if now - t < 3600]
        if len(arr) >= 3:
            RATE[key] = arr
            return False
        arr.append(now)
        RATE[key] = arr
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_keys() -> dict:
    if KEYS_FILE.exists():
        try:
            return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_keys(data: dict) -> None:
    KEYS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _bool(v, default=False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return default


def sanitize_settings(raw: dict | None) -> dict:
    raw = raw or {}
    s = dict(config.DEFAULT_SETTINGS)
    for k in s:
        if k in raw:
            s[k] = raw[k]
    # provider / voice
    if PUBLIC_MODE and s.get("provider") == "elevenlabs":
        s["provider"] = "edge"
    if s.get("provider") not in {p["id"] for p in config.PROVIDERS}:
        s["provider"] = "edge"
    valid_voices = {v["id"]: v for v in config.EDGE_VOICES + config.PIPER_VOICES}
    if s.get("provider") == "edge":
        if s.get("voice") not in {v["id"] for v in config.EDGE_VOICES}:
            s["voice"] = config.EDGE_VOICES[0]["id"]
        s["pitch"] = int(max(-20, min(20, int(s.get("pitch", 0) or 0))))
    elif s.get("provider") == "piper":
        if s.get("voice") not in {v["id"] for v in config.PIPER_VOICES}:
            s["voice"] = config.PIPER_VOICES[0]["id"]
        s["pitch"] = 0
    else:
        s["voice"] = str(s.get("eleven_voice") or s.get("voice") or "")[:80]
        s["pitch"] = 0
    s["rate"] = int(max(-20, min(30, int(s.get("rate", 0) or 0))))
    s["auto_rate"] = _bool(s.get("auto_rate", True), True)
    s["music"] = _bool(s.get("music", True), True)
    s["sfx"] = _bool(s.get("sfx", True), True)
    try:
        s["music_gain"] = float(max(0.0, min(0.6, float(s.get("music_gain", 0.22)))))
    except Exception:
        s["music_gain"] = 0.22
    if s.get("music_preset") not in {m["id"] for m in config.MUSIC_PRESETS}:
        s["music_preset"] = "tech"
    if s.get("duration") not in {d["id"] for d in config.DURATIONS}:
        s["duration"] = "60"
    if s.get("style") not in config.STYLES:
        s["style"] = "tech_blue"
    if s.get("quality") not in ("fast", "quality"):
        s["quality"] = "quality"
    if PUBLIC_MODE:
        # Free CPU Space: 1080p full-quality render would take too long.
        # Fast still writes a 1080x1920 H.264 file at the end.
        s["quality"] = "fast"
    s["brand"] = str(s.get("brand") or "TRADE AUTOPSY")[:40]
    s["cta_url"] = str(s.get("cta_url") or "")[:120]
    s["cta_label"] = str(s.get("cta_label") or "Открыть журнал")[:40]
    s["disclaimer"] = str(s.get("disclaimer") or "")[:90]
    cm = s.get("custom_music")
    s["custom_music"] = Path(str(cm)).name if cm else None
    if s["custom_music"] and not (config.UPLOADS / s["custom_music"]).exists():
        s["custom_music"] = None
    # Never trust a key coming from the browser.
    s.pop("eleven_key", None)
    return s


def _project_payload(p: dict) -> dict:
    return {
        "id": p["id"],
        "title": p["title"],
        "script": p["script"],
        "settings": p["settings"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "renders": p.get("renders", 0),
    }


def _render_payload(r: dict) -> dict:
    pid, rid = r["project_id"], r["id"]
    video = r.get("video_path")
    srt = r.get("srt_path")
    poster = r.get("poster_path")
    return {
        "id": rid,
        "project_id": pid,
        "status": r.get("status"),
        "stage": r.get("stage"),
        "progress": r.get("progress", 0),
        "duration": r.get("duration"),
        "size": r.get("size"),
        "error": r.get("error"),
        "created_at": r.get("created_at"),
        "video_url": f"/media/{video}" if video else None,
        "srt_url": f"/media/{srt}" if srt else None,
        "poster_url": f"/media/{poster}" if poster else None,
    }


def _job_public(job: dict) -> dict:
    with JOBS_LOCK:
        d = dict(job)
    d.pop("cancel_event", None)
    d.pop("log", None)
    d.pop("owner", None)
    return d


def _active_count() -> int:
    with JOBS_LOCK:
        return sum(1 for j in JOBS.values() if j["status"] in ("queued", "running"))


def _prune_renders(pid: str, keep: int = 2) -> None:
    try:
        rows = storage.list_renders(pid)
        for r in rows[keep:]:
            if r.get("status") in ("done", "failed", "cancelled"):
                storage.delete_render(r["id"])
    except Exception:
        pass


def _run_job(job_id: str, pid: str, title: str, script: str, settings: dict,
             render_id: str, force_tts: bool):
    job = JOBS[job_id]

    def progress(pct, message):
        with JOBS_LOCK:
            job["progress"] = pct
            job["stage"] = message
            job["message"] = message
            job["log"].append(f"[{time.strftime('%H:%M:%S')}] {message}")
            job["log"] = job["log"][-40:]
        storage.update_render(render_id, progress=pct, stage=message)

    with JOBS_LOCK:
        job["status"] = "running"
        job["started"] = _now()
    storage.update_render(render_id, status="running", stage="Старт", progress=1)

    used_fallback = False
    try:
        try:
            info = pipeline.generate(
                project_id=pid,
                title=title,
                script=script,
                settings=settings,
                render_id=render_id,
                progress=progress,
                cancel=lambda: job["cancel_event"].is_set(),
                force_tts=force_tts,
            )
        except Exception as exc:
            # Edge sometimes returns "No audio" for minutes. A local Piper
            # voice is a better outcome than a failed render.
            can_fallback = (
                settings.get("provider") == "edge"
                and "Edge TTS" in str(exc)
                and config.ensure_piper()
                and not job["cancel_event"].is_set()
            )
            if not can_fallback:
                raise
            used_fallback = True
            with JOBS_LOCK:
                job["stage"] = "Edge недоступен — перехожу на локальный Piper"
                job["message"] = job["stage"]
            fallback = dict(settings)
            fallback.update(provider="piper", voice="ru_RU-denis-medium", pitch=0)
            info = pipeline.generate(
                project_id=pid,
                title=title,
                script=script,
                settings=fallback,
                render_id=render_id,
                progress=progress,
                cancel=lambda: job["cancel_event"].is_set(),
                force_tts=force_tts,
            )
        rel_video = Path(info["video"]).relative_to(config.DATA).as_posix()
        rel_srt = Path(info["srt"]).relative_to(config.DATA).as_posix()
        rel_poster = None
        if info.get("poster"):
            rel_poster = Path(info["poster"]).relative_to(config.DATA).as_posix()
        storage.update_render(
            render_id, status="done", progress=100, stage="Готово",
            video_path=rel_video, srt_path=rel_srt, poster_path=rel_poster,
            duration=info.get("duration"), size=info.get("size"), error=None,
        )
        summary = {
            "render_id": render_id,
            "project_id": pid,
            "duration": info.get("duration"),
            "scenes": info.get("scenes"),
            "size": info.get("size"),
            "elapsed": info.get("elapsed"),
            "video_url": f"/media/{rel_video}",
            "srt_url": f"/media/{rel_srt}",
            "poster_url": f"/media/{rel_poster}" if rel_poster else None,
            "warning": ("Edge TTS был недоступен — озвучил локальным Piper"
                        if used_fallback else None),
        }
        with JOBS_LOCK:
            job["status"] = "done"
            job["progress"] = 100
            job["stage"] = "Готово"
            job["message"] = "Видео готово"
            job["result"] = summary
            job["ended"] = _now()
    except Exception as exc:
        cancelled = job["cancel_event"].is_set() or "отменена" in str(exc).lower()
        msg = "Генерация отменена" if cancelled else str(exc)
        storage.update_render(render_id, status="cancelled" if cancelled else "failed",
                              stage="Отменено" if cancelled else "Ошибка", error=msg)
        with JOBS_LOCK:
            job["status"] = "cancelled" if cancelled else "failed"
            job["stage"] = "Отменено" if cancelled else "Ошибка"
            job["message"] = msg
            job["error"] = msg
            job["ended"] = _now()
            job["log"].append(f"[{time.strftime('%H:%M:%S')}] ERROR: {msg}")
    if PUBLIC_MODE:
        _prune_renders(pid, keep=2)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(config.WEB), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    storage.init_db()
    if not PUBLIC_MODE:
        storage.ensure_demo()
    try:
        config.ensure_piper()
    except Exception:
        pass

    @app.get("/")
    def index():
        return send_from_directory(str(config.WEB), "index.html")

    @app.get("/fonts/<path:name>")
    def fonts(name):
        return send_from_directory(str(config.FONTS), name)

    @app.get("/api/health")
    def health():
        return jsonify({
            "ok": True,
            "ffmpeg": Path(config.FFMPEG).exists() or bool(os.popen("where ffmpeg").read().strip()),
            "skia": True,
            "fonts": all(p.exists() for p in [
                config.FONTS / "Montserrat-Black.ttf",
                config.FONTS / "JetBrainsMono-Medium.ttf",
            ]),
            "piper": config.PIPER_EXE.exists(),
            "edge": True,
            "cpus": os.cpu_count() or 1,
        })

    @app.get("/api/bootstrap")
    def bootstrap():
        owner = _owner()
        keys = load_keys()
        piper_ok = config.PIPER_EXE.exists() and any(
            (config.PIPER_DIR / v["model"]).exists() for v in config.PIPER_VOICES
        )
        voices = list(config.EDGE_VOICES)
        if piper_ok:
            voices += config.PIPER_VOICES
        providers = [p for p in config.PROVIDERS
                     if not (PUBLIC_MODE and (
                         p["id"] == "elevenlabs" or (p["id"] == "piper" and not piper_ok)
                     ))]
        defaults = {**config.DEFAULT_SETTINGS, "eleven_key": ""}
        if PUBLIC_MODE:
            defaults["quality"] = "fast"
        if PUBLIC_MODE and owner is not None and not storage.list_projects(owner):
            storage.create_project(config.DEFAULT_TITLE, config.DEFAULT_SCRIPT, defaults, owner)
        projects = storage.list_projects(owner)
        return jsonify({
            "voices": voices,
            "providers": providers,
            "styles": [{"id": k, **{kk: vv for kk, vv in v.items() if kk in ("name", "desc")}}
                       for k, v in config.STYLES.items()],
            "music_presets": config.MUSIC_PRESETS,
            "durations": config.DURATIONS,
            "defaults": defaults,
            "projects": [_project_payload(p) for p in projects],
            "health": {
                "ffmpeg": Path(config.FFMPEG).exists(),
                "piper": piper_ok,
                "fonts": (config.FONTS / "Montserrat-Black.ttf").exists(),
            },
            "keys": {
                "eleven_configured": bool(keys.get("eleven_key")) and not PUBLIC_MODE,
                "eleven_voice": keys.get("eleven_voice", "") if not PUBLIC_MODE else "",
            },
            "public_mode": PUBLIC_MODE,
            "max_script": MAX_SCRIPT if PUBLIC_MODE else 20000,
        })

    @app.get("/api/projects")
    def projects_list():
        return jsonify([_project_payload(p) for p in storage.list_projects(_owner())])

    @app.post("/api/projects")
    def project_create():
        body = request.get_json(silent=True) or {}
        s = sanitize_settings(body.get("settings"))
        p = storage.create_project(
            str(body.get("title") or "Новый ролик")[:120],
            str(body.get("script") or "")[:MAX_SCRIPT],
            s,
            _owner() or "",
        )
        return jsonify(_project_payload(p)), 201

    @app.get("/api/projects/<pid>")
    def project_get(pid):
        p = storage.get_project(pid, _owner())
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        return jsonify(_project_payload(p))

    @app.put("/api/projects/<pid>")
    def project_update(pid):
        body = request.get_json(silent=True) or {}
        if "script" in body and len(str(body.get("script") or "")) > MAX_SCRIPT:
            return jsonify({"error": f"Слишком длинный сценарий. Максимум {MAX_SCRIPT} символов."}), 400
        s = sanitize_settings(body.get("settings")) if "settings" in body else None
        p = storage.update_project(pid, body.get("title"), body.get("script"), s, _owner())
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        return jsonify(_project_payload(p))

    @app.delete("/api/projects/<pid>")
    def project_delete(pid):
        if not storage.get_project(pid, _owner()):
            return jsonify({"error": "Проект не найден"}), 404
        if any(j["project_id"] == pid and j["status"] in ("queued", "running")
               for j in JOBS.values()):
            return jsonify({"error": "Сначала дождись завершения рендера"}), 409
        storage.delete_project(pid, _owner())
        return jsonify({"ok": True})

    @app.post("/api/projects/<pid>/plan")
    def project_plan(pid):
        p = storage.get_project(pid, _owner())
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        body = request.get_json(silent=True) or {}
        title = body.get("title", p["title"])
        script = body.get("script", p["script"])
        if len(script) > MAX_SCRIPT:
            return jsonify({"error": f"Слишком длинный сценарий. Максимум {MAX_SCRIPT} символов."}), 400
        s = sanitize_settings(body.get("settings", p["settings"]))
        try:
            plan = analyzer.make_plan(title, script, s)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        scenes = []
        for sc in plan["scenes"]:
            scenes.append({
                "index": sc["index"],
                "kind": sc["kind"],
                "label": config.TYPE_LABELS.get(sc["kind"], sc["kind"]),
                "title": sc["title"],
                "accent": sc["accent"],
                "kicker": sc["kicker"],
                "text": sc["text"],
                "est": sc["est"],
                "bullets": sc["bullets"],
            })
        return jsonify({
            "title": plan["title"],
            "rate": plan["rate"],
            "est_total": plan["est_total"],
            "scenes": scenes,
        })

    @app.post("/api/projects/<pid>/generate")
    def project_generate(pid):
        owner = _owner()
        p = storage.get_project(pid, owner)
        if not p:
            return jsonify({"error": "Проект не найден"}), 404
        if _active_count() >= MAX_ACTIVE:
            return jsonify({"error": "Сейчас уже идёт рендер. Попробуй через несколько минут."}), 429
        if PUBLIC_MODE and not _rate_ok(_client_ip()):
            return jsonify({"error": "Слишком много запусков. Лимит — 3 ролика в час."}), 429
        body = request.get_json(silent=True) or {}
        title = str(body.get("title", p["title"]))[:120]
        script = str(body.get("script", p["script"]))
        if not script.strip():
            return jsonify({"error": "Сценарий пустой"}), 400
        if len(script) > MAX_SCRIPT:
            return jsonify({"error": f"Слишком длинный сценарий. Максимум {MAX_SCRIPT} символов."}), 400
        s = sanitize_settings(body.get("settings", p["settings"]))
        if s["provider"] == "piper" and not config.PIPER_EXE.exists():
            return jsonify({"error": "Piper не найден. Выбери Edge TTS или проверь _work/piper."}), 400
        if s["provider"] == "elevenlabs":
            keys = load_keys()
            if not keys.get("eleven_key"):
                return jsonify({"error": "Для ElevenLabs добавь API-ключ в разделе «API и ключи»."}), 400
            s["eleven_key"] = keys["eleven_key"]
            s["eleven_voice"] = str(s.get("eleven_voice") or keys.get("eleven_voice") or "")
            if not s["eleven_voice"]:
                return jsonify({"error": "Укажи Voice ID ElevenLabs."}), 400
        storage.update_project(pid, title, script, {k: v for k, v in s.items() if k != "eleven_key"},
                               owner)
        r = storage.create_render(pid, {k: v for k, v in s.items() if k != "eleven_key"})
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "owner": owner or "",
            "project_id": pid,
            "render_id": r["id"],
            "status": "queued",
            "stage": "В очереди",
            "message": "В очереди",
            "progress": 0,
            "error": None,
            "result": None,
            "created": _now(),
            "started": None,
            "ended": None,
            "cancel_event": threading.Event(),
            "log": [],
        }
        with JOBS_LOCK:
            JOBS[job_id] = job
        t = threading.Thread(target=_run_job, args=(
            job_id, pid, title, script, s, r["id"], bool(body.get("force_tts"))),
            daemon=True)
        t.start()
        return jsonify({"job_id": job_id, "render_id": r["id"]}), 202

    @app.get("/api/jobs/<job_id>")
    def job_get(job_id):
        job = JOBS.get(job_id)
        if not job or (PUBLIC_MODE and job.get("owner") not in (None, _owner())):
            return jsonify({"error": "Задача не найдена"}), 404
        return jsonify(_job_public(job))

    @app.post("/api/jobs/<job_id>/cancel")
    def job_cancel(job_id):
        job = JOBS.get(job_id)
        if not job or (PUBLIC_MODE and job.get("owner") not in (None, _owner())):
            return jsonify({"error": "Задача не найдена"}), 404
        job["cancel_event"].set()
        with JOBS_LOCK:
            job["stage"] = "Отмена…"
            job["message"] = "Отмена…"
        return jsonify({"ok": True})

    @app.get("/api/projects/<pid>/renders")
    def renders_list(pid):
        if not storage.get_project(pid, _owner()):
            return jsonify({"error": "Проект не найден"}), 404
        return jsonify([_render_payload(r) for r in storage.list_renders(pid)])

    @app.delete("/api/renders/<rid>")
    def render_delete(rid):
        r = storage.get_render(rid)
        if not r or not storage.get_project(r["project_id"], _owner()):
            return jsonify({"error": "Рендер не найден"}), 404
        if any(j["render_id"] == rid and j["status"] in ("queued", "running")
               for j in JOBS.values()):
            return jsonify({"error": "Этот рендер ещё идёт"}), 409
        storage.delete_render(rid)
        return jsonify({"ok": True})

    @app.post("/api/voice-preview")
    def voice_preview():
        if PUBLIC_MODE and not _rate_ok(_client_ip(), "tts"):
            return jsonify({"error": "Слишком много запросов. Попробуй позже."}), 429
        body = request.get_json(silent=True) or {}
        text = str(body.get("text") or "Проверка голоса. Так будет звучать твой ролик.")[:220]
        text = analyzer.speech_text(text)
        s = sanitize_settings(body.get("settings"))
        if s["provider"] == "elevenlabs":
            keys = load_keys()
            if not keys.get("eleven_key"):
                return jsonify({"error": "Добавь ключ ElevenLabs в разделе «API и ключи»."}), 400
            s["eleven_key"] = keys["eleven_key"]
            s["eleven_voice"] = str(s.get("eleven_voice") or keys.get("eleven_voice") or "")
        try:
            info = tts.synth_once(text, s, force=bool(body.get("force")))
            rel = Path(info["wav"]).relative_to(config.DATA).as_posix()
            return jsonify({"url": f"/media/{rel}", "duration": round(info["dur"], 2),
                            "provider": info.get("provider")})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @app.post("/api/upload/music")
    def upload_music():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Файл не выбран"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
            return jsonify({"error": "Поддерживаются MP3, WAV, M4A, AAC, OGG, FLAC"}), 400
        name = uuid.uuid4().hex[:10] + ext
        f.save(config.UPLOADS / name)
        return jsonify({"name": name, "original": f.filename})

    @app.get("/api/keys")
    def keys_get():
        if PUBLIC_MODE:
            return jsonify({"eleven_configured": False, "eleven_voice": "", "eleven_key_masked": ""})
        k = load_keys()
        return jsonify({
            "eleven_configured": bool(k.get("eleven_key")),
            "eleven_voice": k.get("eleven_voice", ""),
            "eleven_key_masked": ("•" * 8 + k.get("eleven_key", "")[-4:]) if k.get("eleven_key") else "",
        })

    @app.post("/api/keys")
    def keys_set():
        if PUBLIC_MODE:
            return jsonify({"error": "В онлайн-версии ключи не сохраняются на сервере."}), 403
        body = request.get_json(silent=True) or {}
        k = load_keys()
        if "eleven_key" in body:
            k["eleven_key"] = str(body.get("eleven_key") or "").strip()
        if "eleven_voice" in body:
            k["eleven_voice"] = str(body.get("eleven_voice") or "").strip()
        save_keys(k)
        return jsonify({"ok": True, "eleven_configured": bool(k.get("eleven_key"))})

    @app.get("/media/<path:rel>")
    def media(rel):
        parts = Path(rel).parts
        if not parts or parts[0] not in ("projects", "cache", "uploads") or ".." in parts:
            return jsonify({"error": "forbidden"}), 403
        if PUBLIC_MODE and parts[0] == "projects" and len(parts) > 1:
            if not storage.get_project(parts[1], _owner()):
                return jsonify({"error": "not found"}), 404
        return send_from_directory(str(config.DATA), rel, conditional=True)

    return app
