"""AI Video Factory — Enhanced Web Dashboard (localhost controller).

Run:  python web_app.py
Open: http://localhost:5000

New Features:
- Batch queue (add multiple jobs, runs sequentially)
- Preset system (save/load settings per niche)
- Script editor (edit generated script before render)
- Video player (watch output in-browser)
- Thumbnail A/B viewer (see all variants)
- Progress steps (Research → Plan → Script → Thumbnail → Render → Done)
- Settings panel (default keys, output folder, hardware prefs)
- Job queue sidebar (running + pending + history)
- Browser notifications when job completes
"""
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_video_factory.composer import compose_short_from_video
from ai_video_factory.director import VideoDirector
from ai_video_factory.factory import create_package
from ai_video_factory.nle_export import export_edl

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
app.config["OUTPUT_FOLDER"] = "output"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

jobs = {}
job_queue = queue.Queue()
queue_running = False
queue_lock = threading.Lock()

PRESETS_FILE = os.path.join(os.path.dirname(__file__), "dashboard_presets.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "dashboard_settings.json")


def load_presets():
    if os.path.exists(PRESETS_FILE):
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_presets(presets):
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {
        "default_target_seconds": 45,
        "default_workflow": "director",
        "default_skip_qc": False,
        "default_use_groq": False,
        "output_folder": "output",
        "groq_key": "",
        "model_key": "",
        "elevenlabs_key": "",
    }


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


class JobLogger:
    def __init__(self):
        self.logs = queue.Queue()
        self.done = False
        self.step = "waiting"

    def info(self, msg):
        self.logs.put({"time": datetime.now().strftime("%H:%M:%S"), "level": "INFO", "msg": msg})

    def warning(self, msg):
        self.logs.put({"time": datetime.now().strftime("%H:%M:%S"), "level": "WARN", "msg": msg})

    def error(self, msg):
        self.logs.put({"time": datetime.now().strftime("%H:%M:%S"), "level": "ERROR", "msg": msg})

    def step_update(self, step_name):
        self.step = step_name
        self.info(f"→ {step_name}")

    def finish(self):
        self.done = True


def queue_worker():
    global queue_running
    while True:
        job_id = job_queue.get()
        if job_id is None:
            break
        with queue_lock:
            queue_running = True
        if job_id in jobs:
            jobs[job_id]["status"] = "running"
            _execute_job(job_id)
        with queue_lock:
            queue_running = False
        job_queue.task_done()


def _execute_job(job_id):
    job = jobs[job_id]
    logger = job["logger"]
    params = job["params"]
    pkg_dir = None

    try:
        logger.step_update("Research")
        time.sleep(0.5)

        if params["workflow"] == "director":
            logger.step_update("Director Pipeline")
            director = VideoDirector(out_root=app.config["OUTPUT_FOLDER"], model_key=params.get("model_key"))
            pkg_dir = director.produce(
                params["topic"],
                raw_video=params.get("raw_video"),
                use_groq=params.get("use_groq", False),
                groq_key=params.get("groq_key"),
                target_seconds=params.get("target_seconds", 45),
                skip_qc=params.get("skip_qc", False),
            )
        else:
            logger.step_update("Legacy Pipeline")
            pkg_dir = create_package(
                params["topic"],
                out_root=app.config["OUTPUT_FOLDER"],
                thumbnail_subject=params.get("thumbnail_subject"),
                use_groq=params.get("use_groq", False),
                groq_api_key=params.get("groq_key"),
                target_total_seconds=params.get("target_seconds", 45),
            )

            if params.get("raw_video") and pkg_dir:
                logger.step_update("Auto-Edit")
                compose_short_from_video(
                    params["raw_video"],
                    pkg_dir,
                    review=not params.get("skip_qc", False),
                    auto_fix=True,
                    model_key=params.get("model_key"),
                    skip_qc=params.get("skip_qc", False),
                )

        if params.get("elevenlabs_key") and pkg_dir:
            logger.step_update("Voiceover")
            try:
                from ai_video_factory.tts import generate_high_quality_voiceover

                script_path = os.path.join(pkg_dir, "script.txt")
                if os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as f:
                        text = f.read()
                    vo_out = os.path.join(pkg_dir, "voice_hq.mp3")
                    generate_high_quality_voiceover(text, vo_out, params["elevenlabs_key"])
                    logger.info(f"HQ VO: {vo_out}")
            except Exception as e:
                logger.warning(f"VO failed: {e}")

        logger.step_update("Complete")
        job["status"] = "done"
        job["pkg_dir"] = pkg_dir
        logger.info("Job complete!")

    except Exception as e:
        logger.error(f"Job failed: {e}")
        job["status"] = "error"
        job["error"] = str(e)

    finally:
        logger.finish()


threading.Thread(target=queue_worker, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        new_settings = request.get_json() or {}
        current = load_settings()
        current.update(new_settings)
        save_settings(current)
        return jsonify(current)
    return jsonify(load_settings())


@app.route("/api/presets", methods=["GET", "POST", "DELETE"])
def presets():
    if request.method == "POST":
        data = request.get_json() or {}
        name = data.get("name")
        if not name:
            return jsonify({"error": "Name required"}), 400
        all_presets = load_presets()
        all_presets[name] = data.get("config", {})
        save_presets(all_presets)
        return jsonify({"ok": True})
    if request.method == "DELETE":
        name = request.args.get("name")
        all_presets = load_presets()
        if name in all_presets:
            del all_presets[name]
            save_presets(all_presets)
        return jsonify({"ok": True})
    return jsonify(load_presets())


@app.route("/api/packages")
def list_packages():
    output_dir = app.config["OUTPUT_FOLDER"]
    packages = []
    if os.path.exists(output_dir):
        for name in sorted(os.listdir(output_dir), reverse=True):
            pkg_path = os.path.join(output_dir, name)
            if not os.path.isdir(pkg_path):
                continue

            thumb = None
            for t in ["thumbnail.png", "thumbnail_vertical.png"]:
                candidate = os.path.join(pkg_path, t)
                if os.path.exists(candidate):
                    thumb = f"/api/package/{name}/file/{t}"
                    break

            thumbnails = []
            thumbs_dir = os.path.join(pkg_path, "thumbnails")
            if os.path.exists(thumbs_dir):
                for f in sorted(os.listdir(thumbs_dir)):
                    if f.lower().endswith((".png", ".jpg", ".jpeg")):
                        thumbnails.append(f"/api/package/{name}/file/thumbnails/{f}")

            script_preview = ""
            script_path = os.path.join(pkg_path, "script.txt")
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8") as f:
                    script_preview = f.read()[:200]

            has_video = any(
                os.path.exists(os.path.join(pkg_path, v))
                for v in ["final_short.mp4", "final_with_music.mp4", "final_short_vo.mp4"]
            )

            packages.append(
                {
                    "name": name,
                    "created": datetime.fromtimestamp(os.path.getctime(pkg_path)).strftime("%Y-%m-%d %H:%M"),
                    "thumbnail": thumb,
                    "thumbnails": thumbnails,
                    "script_preview": script_preview,
                    "has_video": has_video,
                }
            )
    return jsonify(packages)


@app.route("/api/package/<name>/file/<path:filename>")
def package_file(name, filename):
    pkg_dir = os.path.join(app.config["OUTPUT_FOLDER"], name)
    return send_from_directory(pkg_dir, filename)


@app.route("/api/package/<name>/files")
def package_files(name):
    pkg_dir = os.path.join(app.config["OUTPUT_FOLDER"], name)
    files = []
    if os.path.exists(pkg_dir):
        for root, _, filenames in os.walk(pkg_dir):
            for f in filenames:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, pkg_dir)
                files.append({"path": rel, "size": os.path.getsize(full)})
    return jsonify(files)


@app.route("/api/package/<name>/script", methods=["GET", "POST"])
def package_script(name):
    script_path = os.path.join(app.config["OUTPUT_FOLDER"], name, "script.txt")
    if request.method == "POST":
        payload = request.get_json() or {}
        new_text = payload.get("script", "")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return jsonify({"ok": True})
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            return jsonify({"script": f.read()})
    return jsonify({"script": ""})


@app.route("/api/jobs")
def list_jobs():
    data = {}
    for job_id, job in jobs.items():
        data[job_id] = {
            "id": job_id,
            "topic": job["topic"],
            "status": job["status"],
            "step": job["logger"].step if hasattr(job["logger"], "step") else "waiting",
            "pkg_dir": job.get("pkg_dir"),
            "error": job.get("error"),
        }
    return jsonify(data)


@app.route("/api/jobs/<job_id>/logs")
def job_logs(job_id):
    def stream():
        if job_id not in jobs:
            yield f"data: {json.dumps({'time': '', 'level': 'ERROR', 'msg': 'Job not found'})}\n\n"
            return

        logger = jobs[job_id]["logger"]
        while not logger.done or not logger.logs.empty():
            try:
                log = logger.logs.get(timeout=1)
                yield f"data: {json.dumps(log)}\n\n"
            except queue.Empty:
                if logger.done:
                    break
                continue

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/jobs/<job_id>/status")
def job_status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    job = jobs[job_id]
    return jsonify(
        {
            "status": job["status"],
            "step": job["logger"].step,
            "pkg_dir": job.get("pkg_dir"),
            "error": job.get("error"),
        }
    )


@app.route("/api/run", methods=["POST"]) 
def run_job():
    topic = request.form.get("topic", "").strip()
    if not topic or len(topic) < 2:
        return jsonify({"error": "Topic must be at least 2 characters"}), 400

    raw_video_path = None
    if "raw_video" in request.files:
        video = request.files["raw_video"]
        if video.filename:
            safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{video.filename}"
            raw_video_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
            video.save(raw_video_path)

    settings = load_settings()
    job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(jobs)}"
    params = {
        "topic": topic,
        "raw_video": raw_video_path,
        "target_seconds": float(request.form.get("target_seconds", settings.get("default_target_seconds", 45))),
        "workflow": request.form.get("workflow", settings.get("default_workflow", "director")),
        "use_groq": request.form.get("use_groq") == "on",
        "groq_key": request.form.get("groq_key", "").strip() or settings.get("groq_key", "") or os.environ.get("GROQ_API_KEY", ""),
        "model_key": request.form.get("model_key", "").strip() or settings.get("model_key", "") or os.environ.get("OPENAI_API_KEY", ""),
        "skip_qc": request.form.get("skip_qc") == "on",
        "elevenlabs_key": request.form.get("elevenlabs_key", "").strip() or settings.get("elevenlabs_key", ""),
        "thumbnail_subject": request.form.get("thumbnail_subject", "").strip() or None,
    }

    jobs[job_id] = {
        "id": job_id,
        "topic": topic,
        "status": "queued",
        "logger": JobLogger(),
        "pkg_dir": None,
        "error": None,
        "params": params,
    }

    job_queue.put(job_id)
    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/queue/status")
def queue_status():
    with queue_lock:
        running = queue_running
    pending = [job_id for job_id, job in jobs.items() if job["status"] == "queued"]
    return jsonify({"running": running, "pending": len(pending), "pending_ids": pending})


if __name__ == "__main__":
    print("=" * 50)
    print("AI VIDEO FACTORY — Enhanced Web Dashboard")
    print("Open: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
