from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, request, send_file

from .pipeline import (JOBS, WORKSPACE, analyze_project, create_project, list_projects,
                       load_project, merge_project, project_path, render_all, render_scene,
                       set_audio, update_project)

ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__, static_folder=str(ROOT / "app" / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024
app.json.ensure_ascii = False


@app.get("/")
def index():
    return send_file(ROOT / "app" / "static" / "index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "workspace": str(WORKSPACE)})


@app.get("/api/projects")
def projects_index():
    return jsonify(list_projects())


@app.post("/api/projects")
def projects_create():
    images = [(item.filename or "image.png", item.read()) for item in request.files.getlist("images")]
    script = request.form.get("script", "")
    script_file = request.files.get("script_file")
    if script_file and script_file.filename:
        script = script_file.read().decode("utf-8-sig", errors="replace")
    voice_file = request.files.get("voice")
    music_file = request.files.get("music")
    voice = (voice_file.filename, voice_file.read()) if voice_file and voice_file.filename else None
    music = (music_file.filename, music_file.read()) if music_file and music_file.filename else None
    try:
        project = create_project(request.form.get("name", "Dự án mới"), images, script, voice, music)
        return jsonify(project), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/projects/<project_id>")
def projects_show(project_id: str):
    try:
        return jsonify(load_project(project_id))
    except (ValueError, OSError):
        return jsonify({"error": "Không tìm thấy dự án"}), 404


@app.patch("/api/projects/<project_id>")
def projects_update(project_id: str):
    try:
        return jsonify(update_project(project_id, request.get_json(force=True) or {}))
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<project_id>/analyze")
def projects_analyze(project_id: str):
    try:
        return jsonify(analyze_project(project_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<project_id>/audio/<kind>")
def projects_audio(project_id: str, kind: str):
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Chưa chọn file âm thanh"}), 400
    try:
        return jsonify(set_audio(project_id, kind, upload.filename, upload.read()))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<project_id>/render/scenes/<int:scene_index>")
def scenes_render(project_id: str, scene_index: int):
    try:
        load_project(project_id)
        job = JOBS.submit(project_id, "scene", lambda update: render_scene(
            project_id, scene_index,
            lambda value, message: update(value, message, {
                "scene_index": scene_index, "scene_progress": {str(scene_index): round(value, 1)},
            }),
        ))
        return jsonify({"job_id": job}), 202
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<project_id>/render/all")
def projects_render_all(project_id: str):
    try:
        load_project(project_id)
        job = JOBS.submit(project_id, "all", lambda update: render_all(project_id, update))
        return jsonify({"job_id": job}), 202
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/projects/<project_id>/merge")
def projects_merge(project_id: str):
    try:
        load_project(project_id)
        job = JOBS.submit(project_id, "merge", lambda update: merge_project(project_id, update))
        return jsonify({"job_id": job}), 202
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/jobs/<job_id>")
def jobs_show(job_id: str):
    job = JOBS.get(job_id)
    return jsonify(job) if job else (jsonify({"error": "Không tìm thấy tác vụ"}), 404)


@app.get("/api/projects/<project_id>/images/<int:scene_index>")
def images_show(project_id: str, scene_index: int):
    project = load_project(project_id)
    scene = next((s for s in project["scenes"] if s["index"] == scene_index), None)
    if not scene:
        return jsonify({"error": "Không tìm thấy ảnh"}), 404
    return send_file(project_path(project_id) / "source" / "images" / scene["image"])


@app.get("/api/projects/<project_id>/scenes/<int:scene_index>/video")
def scenes_video(project_id: str, scene_index: int):
    path = project_path(project_id) / "scenes" / f"scene-{scene_index:03d}.mp4"
    return send_file(path, mimetype="video/mp4", conditional=True) if path.exists() else (jsonify({"error": "Cảnh chưa được dựng"}), 404)


@app.get("/api/projects/<project_id>/download")
def final_download(project_id: str):
    project = load_project(project_id)
    if not project.get("final_video"):
        return jsonify({"error": "Chưa có video hoàn chỉnh"}), 404
    path = project_path(project_id) / "outputs" / project["final_video"]
    return send_file(path, mimetype="video/mp4", as_attachment=True, download_name=path.name)


def existing_studio_url(host: str, port: int) -> str | None:
    url = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("ok") and Path(payload.get("workspace", "")).resolve() == WORKSPACE.resolve():
            return url
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="SRT Whiteboard Studio chạy local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    running_url = existing_studio_url(args.host, args.port)
    if running_url:
        print(f"SRT Whiteboard Studio đang chạy: {running_url}")
        if not args.no_browser:
            webbrowser.open(running_url)
        return
    if not args.no_browser:
        Timer(1.2, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    print(f"SRT Whiteboard Studio: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
