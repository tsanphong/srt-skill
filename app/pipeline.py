from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Callable

import av
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace" / "projects"
RENDERER = ROOT / "scripts" / "render_stream_whiteboard.py"
HAND = ROOT / "assets" / "drawing-hand-clean.png"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}
RENDER_SLOTS = threading.BoundedSemaphore(2)
PROJECT_STATE_LOCK = threading.RLock()
ACTIVE_SCENES_LOCK = threading.Lock()
ACTIVE_SCENES: set[tuple[str, int]] = set()
SUBTITLE_FONTS = (
    "Microsoft JhengHei", "Microsoft JhengHei UI", "Microsoft YaHei",
    "Segoe UI", "Arial", "Tahoma",
)
SUBTITLE_DEFAULTS = {
    "subtitle_position": "top",
    "subtitle_color": "#FFFFFF",
    "subtitle_font": "Microsoft JhengHei",
    "subtitle_font_size": 54,
    "subtitle_max_chars": 16,
}
VIDEO_DEFAULTS = {
    "render_mode": "whiteboard",
    "transition": "dissolve",
    "transition_duration": 0.55,
}


def synchronized_state(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with PROJECT_STATE_LOCK:
            return fn(*args, **kwargs)
    return wrapped


def natural_key(value: str) -> list[object]:
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", value)]


def safe_slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9\-]+", "-", value.strip()).strip("-").lower()
    return value[:60] or "du-an"


def split_script(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;：:])\s*|\n+", text)
    return [re.sub(r"\s+", " ", part).strip() for part in parts if part.strip()]


def distribute_text(text: str, count: int) -> list[str]:
    if count <= 0:
        return []
    sentences = split_script(text)
    groups = ["" for _ in range(count)]
    if not sentences:
        return groups
    total = sum(max(1, len(s)) for s in sentences)
    targets = [(i + 1) * total / count for i in range(count)]
    current_group = 0
    cumulative = 0
    for sentence in sentences:
        if current_group < count - 1 and cumulative >= targets[current_group]:
            current_group += 1
        groups[current_group] += (" " if groups[current_group] else "") + sentence
        cumulative += max(1, len(sentence))
    return groups


def probe_duration(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None
    with av.open(str(path)) as container:
        if container.duration:
            return float(container.duration / av.time_base)
        durations = [float(s.duration * s.time_base) for s in container.streams if s.duration]
        return max(durations) if durations else None


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("Không tìm thấy FFmpeg. Hãy chạy prepare_env.py.") from exc


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,79}", project_id):
        raise ValueError("Mã dự án không hợp lệ")
    path = (WORKSPACE / project_id).resolve()
    if WORKSPACE.resolve() not in path.parents:
        raise ValueError("Đường dẫn dự án không hợp lệ")
    return path


def _normalize_subtitle_settings(settings: dict) -> dict:
    for key, value in SUBTITLE_DEFAULTS.items():
        settings.setdefault(key, value)
    if settings.get("subtitle_position") not in {"top", "bottom"}:
        settings["subtitle_position"] = SUBTITLE_DEFAULTS["subtitle_position"]
    color = str(settings.get("subtitle_color", "")).upper()
    settings["subtitle_color"] = color if re.fullmatch(r"#[0-9A-F]{6}", color) else SUBTITLE_DEFAULTS["subtitle_color"]
    if settings.get("subtitle_font") not in SUBTITLE_FONTS:
        settings["subtitle_font"] = SUBTITLE_DEFAULTS["subtitle_font"]
    try:
        settings["subtitle_font_size"] = round(max(20, min(120, float(settings["subtitle_font_size"]))))
    except (TypeError, ValueError):
        settings["subtitle_font_size"] = SUBTITLE_DEFAULTS["subtitle_font_size"]
    try:
        settings["subtitle_max_chars"] = round(max(8, min(40, float(settings["subtitle_max_chars"]))))
    except (TypeError, ValueError):
        settings["subtitle_max_chars"] = SUBTITLE_DEFAULTS["subtitle_max_chars"]
    return settings


def _normalize_video_settings(settings: dict) -> dict:
    for key, value in VIDEO_DEFAULTS.items():
        settings.setdefault(key, value)
    if settings.get("render_mode") not in {"whiteboard", "static"}:
        settings["render_mode"] = VIDEO_DEFAULTS["render_mode"]
    if settings.get("transition") not in {"none", "dissolve", "fadeblack", "slideleft"}:
        settings["transition"] = VIDEO_DEFAULTS["transition"]
    try:
        settings["transition_duration"] = round(
            max(0.15, min(1.5, float(settings["transition_duration"]))), 2
        )
    except (TypeError, ValueError):
        settings["transition_duration"] = VIDEO_DEFAULTS["transition_duration"]
    return settings


def load_project(project_id: str) -> dict:
    with PROJECT_STATE_LOCK:
        project = read_json(project_path(project_id) / "project.json")
        _normalize_subtitle_settings(project.setdefault("settings", {}))
        _normalize_video_settings(project["settings"])
        if project.get("audio", {}).get("voice") and project.get("analysis", {}).get("mode") == "voice":
            voice_cursor = 0.0
            for scene in project.get("scenes", []):
                trim_start = float(scene.get("voice_trim_start") or 0.0)
                trim_end = float(scene.get("voice_trim_end") or 0.0)
                scene["voice_trim_start"], scene["voice_trim_end"] = trim_start, trim_end
                source_duration = float(scene.get("duration", 0)) + trim_start + trim_end
                if scene.get("voice_start") is None or scene.get("voice_end") is None:
                    scene["voice_start"] = round(voice_cursor, 3)
                    scene["voice_end"] = round(voice_cursor + source_duration, 3)
                voice_cursor = float(scene["voice_end"])
        return project


def save_project(project: dict) -> dict:
    with PROJECT_STATE_LOCK:
        project["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = project_path(project["id"]) / "project.json"
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        write_json(temporary, project)
        temporary.replace(path)
    return project


def list_projects() -> list[dict]:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    projects = []
    for config in WORKSPACE.glob("*/project.json"):
        try:
            projects.append(read_json(config))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(projects, key=lambda p: p.get("updated_at", ""), reverse=True)


def _unique_id(name: str) -> str:
    base = safe_slug(name)
    candidate = base
    index = 2
    while (WORKSPACE / candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


@synchronized_state
def create_project(name: str, images: list[tuple[str, bytes]], script: str = "",
                   voice: tuple[str, bytes] | None = None,
                   music: tuple[str, bytes] | None = None,
                   render_mode: str = "whiteboard", transition: str = "dissolve",
                   transition_duration: float = 0.55) -> dict:
    valid_images = [(n, b) for n, b in images if Path(n).suffix.lower() in IMAGE_EXTENSIONS and b]
    if not valid_images:
        raise ValueError("Cần ít nhất một ảnh hợp lệ")
    project_id = _unique_id(name)
    root = project_path(project_id)
    for rel in ("source/images", "source/audio", "scenes", "outputs", "logs"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    valid_images.sort(key=lambda item: natural_key(item[0].replace("\\", "/")))
    scenes = []
    for index, (original, data) in enumerate(valid_images, 1):
        suffix = Path(original).suffix.lower()
        filename = f"scene-{index:03d}{suffix}"
        (root / "source" / "images" / filename).write_bytes(data)
        scenes.append({
            "index": index, "source_name": original.replace("\\", "/"), "image": filename,
            "text": "", "duration": 6.0, "speed": 1.0, "status": "ready",
            "rendered": False, "video": None,
        })
    audio = {"voice": None, "music": None}
    for key, value in (("voice", voice), ("music", music)):
        if value and Path(value[0]).suffix.lower() in AUDIO_EXTENSIONS:
            filename = f"{key}{Path(value[0]).suffix.lower()}"
            (root / "source" / "audio" / filename).write_bytes(value[1])
            audio[key] = filename
    now = datetime.now().isoformat(timespec="seconds")
    project = {
        "id": project_id, "name": name.strip() or "Dự án mới", "created_at": now, "updated_at": now,
        "script": script.strip(), "audio": audio, "scenes": scenes,
        "settings": {
            "aspect": "9:16", "fps": 30, "resolution": "1080p", "ink_color": "#222831",
            "ink_path": "grid", "color_fill": "contour-wipe", "voice_volume": 1.0,
            "music_volume": 0.18, "subtitles": True, "channel_name": "",
            **SUBTITLE_DEFAULTS,
            **VIDEO_DEFAULTS,
            "timing_mode": "voice", "manual_scene_duration": 6.0,
        },
        "analysis": {}, "final_video": None,
    }
    project["settings"].update({
        "render_mode": render_mode,
        "transition": transition,
        "transition_duration": transition_duration,
    })
    _normalize_video_settings(project["settings"])
    save_project(project)
    analyze_project(project_id)
    return load_project(project_id)


def _audio_file(project: dict, kind: str) -> Path | None:
    name = project.get("audio", {}).get(kind)
    return project_path(project["id"]) / "source" / "audio" / name if name else None


@synchronized_state
def set_audio(project_id: str, kind: str, filename: str, data: bytes) -> dict:
    if kind not in {"voice", "music"}:
        raise ValueError("Loại âm thanh không hợp lệ")
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS or not data:
        raise ValueError("File âm thanh không hợp lệ")
    project = load_project(project_id)
    root = project_path(project_id)
    saved_name = f"{kind}{suffix}"
    (root / "source" / "audio" / saved_name).write_bytes(data)
    project["audio"][kind] = saved_name
    project["final_video"] = None
    if kind == "voice":
        for scene in project["scenes"]:
            scene["voice_trim_start"] = 0.0
            scene["voice_trim_end"] = 0.0
    save_project(project)
    if kind == "voice":
        return analyze_project(project_id)
    return load_project(project_id)


@synchronized_state
def analyze_project(project_id: str) -> dict:
    project = load_project(project_id)
    count = len(project["scenes"])
    settings = project.get("settings", {})
    detected_voice_duration = probe_duration(_audio_file(project, "voice"))
    use_voice = settings.get("timing_mode", "voice") == "voice" and detected_voice_duration
    voice_duration = detected_voice_duration if use_voice else None
    chunks = distribute_text(project.get("script", ""), count)
    weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
    manual_duration = max(.8, min(600, float(settings.get("manual_scene_duration", 6.0))))
    total = voice_duration or manual_duration * count
    if use_voice:
        weight_total = sum(weights) or count
        raw = [max(2.0, total * w / weight_total) for w in weights]
        scale = total / sum(raw) if raw else 1
        durations = [round(value * scale, 3) for value in raw]
        if durations:
            durations[-1] = round(max(0.5, total - sum(durations[:-1])), 3)
    else:
        durations = [round(manual_duration, 3)] * count
    cursor = 0.0
    voice_cursor = 0.0
    for scene, text, source_duration in zip(project["scenes"], chunks, durations):
        if use_voice:
            voice_start = round(voice_cursor, 3)
            voice_end = round(voice_cursor + source_duration, 3)
            voice_cursor += source_duration
            trim_start = max(0.0, float(scene.get("voice_trim_start", 0)))
            trim_start = min(trim_start, max(0.0, source_duration - .5))
            trim_end = max(0.0, float(scene.get("voice_trim_end", 0)))
            trim_end = min(trim_end, max(0.0, source_duration - trim_start - .5))
            duration = round(source_duration - trim_start - trim_end, 3)
        else:
            voice_start = voice_end = None
            trim_start = trim_end = 0.0
            duration = source_duration
        changed = scene.get("text") != text or abs(float(scene.get("duration", 0)) - duration) > .001
        scene["text"] = text
        scene["duration"] = duration
        scene["voice_start"] = voice_start
        scene["voice_end"] = voice_end
        scene["voice_trim_start"] = round(trim_start, 3)
        scene["voice_trim_end"] = round(trim_end, 3)
        scene["start"] = round(cursor, 3)
        scene["end"] = round(cursor + duration, 3)
        cursor += duration
        if changed:
            scene.update({"rendered": False, "status": "ready", "video": None})
    project["analysis"] = {
        "voice_duration": round(detected_voice_duration, 3) if detected_voice_duration else None,
        "total_duration": round(cursor, 3), "mode": "voice" if use_voice else "manual",
    }
    generate_subtitles(project)
    return save_project(project)


@synchronized_state
def update_project(project_id: str, payload: dict) -> dict:
    project = load_project(project_id)
    project_changed = False
    if "script" in payload:
        script = str(payload["script"])
        project_changed = project_changed or script != project.get("script")
        project["script"] = script
    settings = payload.get("settings", {})
    allowed = {"aspect", "fps", "resolution", "ink_color", "ink_path", "color_fill",
               "voice_volume", "music_volume", "subtitles", "channel_name",
               "subtitle_position", "subtitle_color", "subtitle_font", "subtitle_font_size", "subtitle_max_chars",
               "timing_mode", "manual_scene_duration", "render_mode", "transition", "transition_duration"}
    old_settings = dict(project["settings"])
    for key in allowed:
        if key in settings:
            project["settings"][key] = settings[key]
    _normalize_subtitle_settings(project["settings"])
    _normalize_video_settings(project["settings"])
    project_changed = project_changed or old_settings != project["settings"]
    render_settings_changed = any(old_settings.get(key) != project["settings"].get(key)
                                  for key in ("fps", "ink_color", "ink_path", "color_fill", "render_mode"))
    scene_updates = {int(x["index"]): x for x in payload.get("scenes", []) if "index" in x}
    voice_linked = project["settings"].get("timing_mode", "voice") == "voice" and project.get("audio", {}).get("voice")
    cursor = 0.0
    for scene in project["scenes"]:
        update = scene_updates.get(scene["index"], {})
        changed = render_settings_changed
        if voice_linked and scene.get("voice_start") is not None and scene.get("voice_end") is not None:
            source_duration = max(.5, float(scene["voice_end"]) - float(scene["voice_start"]))
            trim_start = max(0.0, float(update.get("voice_trim_start", scene.get("voice_trim_start", 0))))
            trim_start = min(trim_start, max(0.0, source_duration - .5))
            trim_end = max(0.0, float(update.get("voice_trim_end", scene.get("voice_trim_end", 0))))
            trim_end = min(trim_end, max(0.0, source_duration - trim_start - .5))
            duration = round(source_duration - trim_start - trim_end, 3)
            changed = changed or duration != scene.get("duration")
            changed = changed or round(trim_start, 3) != scene.get("voice_trim_start", 0)
            changed = changed or round(trim_end, 3) != scene.get("voice_trim_end", 0)
            scene["voice_trim_start"], scene["voice_trim_end"] = round(trim_start, 3), round(trim_end, 3)
            scene["duration"] = duration
        elif "duration" in update:
            value = round(max(0.8, min(600, float(update["duration"]))), 3)
            changed = changed or value != scene.get("duration")
            scene["duration"] = value
        if "speed" in update:
            value = round(max(0.25, min(4, float(update["speed"]))), 2)
            changed = changed or value != scene.get("speed")
            scene["speed"] = value
        if "text" in update:
            value = str(update["text"])
            changed = changed or value != scene.get("text")
            scene["text"] = value
        scene["start"], scene["end"] = round(cursor, 3), round(cursor + scene["duration"], 3)
        cursor += scene["duration"]
        if changed:
            scene.update({"rendered": False, "status": "ready", "video": None})
            project_changed = True
    project["analysis"]["total_duration"] = round(cursor, 3)
    if project_changed:
        project["final_video"] = None
    generate_subtitles(project)
    return save_project(project)


def _srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02},{millis % 1000:03}"


def generate_subtitles(project: dict) -> None:
    root = project_path(project["id"])
    entries = []
    for scene in project["scenes"]:
        text = scene.get("text", "").strip()
        if text:
            entries.append(f"{len(entries)+1}\n{_srt_time(scene['start'])} --> {_srt_time(scene['end'])}\n{text}")
    (root / "source" / "subtitles.srt").write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")


def _annotation(project: dict, scene: dict) -> Path:
    root = project_path(project["id"])
    image_path = root / "source" / "images" / scene["image"]
    with Image.open(image_path) as image:
        width, height = image.size
    duration_ms = max(800, round(scene["duration"] * 1000))
    draw_ms = min(duration_ms - 500, max(300, round((duration_ms - 800) / scene.get("speed", 1.0))))
    ann = {
        "sceneId": f"scene-{scene['index']:03d}", "canvas": {"width": width, "height": height},
        "storyBasis": scene.get("text", ""), "sceneDurationMs": duration_ms,
        "elements": [{
            "id": "full-scene", "label": "Toàn cảnh", "sequence": 1,
            "narrativeRole": "Minh họa nội dung cảnh", "subtitle": scene.get("text", ""),
            "type": "scene", "region": {"x": 0, "y": 0, "width": width, "height": height},
            "reveal": {"direction": "top_to_bottom", "startMs": 0, "durationMs": draw_ms,
                       "maskPaddingPx": 0, "protectedRegions": []},
            "handPath": {"start": [width // 2, 0], "end": [width // 2, height], "easing": "easeInOut"},
        }],
    }
    path = root / "scenes" / f"scene-{scene['index']:03d}.annotation.json"
    write_json(path, ann)
    return path


def _scene_signature(project: dict, scene: dict) -> tuple:
    settings = project.get("settings", {})
    return (
        scene.get("text"), float(scene.get("duration", 0)), float(scene.get("speed", 1)),
        settings.get("fps"), settings.get("ink_color"), settings.get("ink_path"),
        settings.get("color_fill"), settings.get("render_mode"),
    )


def render_scene(project_id: str, scene_index: int, progress: Callable[[float, str], None] | None = None) -> Path:
    active_key = (project_id, scene_index)
    with ACTIVE_SCENES_LOCK:
        if active_key in ACTIVE_SCENES:
            raise RuntimeError(f"Cảnh {scene_index} đang được dựng")
        ACTIVE_SCENES.add(active_key)
    try:
        return _render_scene(project_id, scene_index, progress)
    finally:
        with ACTIVE_SCENES_LOCK:
            ACTIVE_SCENES.discard(active_key)


def _render_static_scene(image: Path, output: Path, duration: float, fps: int,
                         log_path: Path, progress: Callable[[float, str], None] | None,
                         scene_index: int) -> None:
    """Turn one source image into a duration-accurate video clip without draw animation."""
    command = [
        ffmpeg_exe(), "-hide_banner", "-y", "-loop", "1", "-framerate", str(fps),
        "-i", str(image), "-t", f"{duration:.3f}",
        "-vf", (
            "scale=1080:1080:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2:flags=lanczos,setsar=1,format=yuv420p"
        ),
        "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", str(output),
    ]
    if progress:
        progress(8, f"Đang tạo cảnh ảnh tĩnh {scene_index}")
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError(f"Dựng cảnh {scene_index} thất bại. Xem {log_path.name}")
    if progress:
        progress(96, f"Đã tạo cảnh ảnh tĩnh {scene_index}")


def _render_scene(project_id: str, scene_index: int, progress: Callable[[float, str], None] | None = None) -> Path:
    project = load_project(project_id)
    scene = next((x for x in project["scenes"] if x["index"] == scene_index), None)
    if not scene:
        raise ValueError("Không tìm thấy cảnh")
    signature = _scene_signature(project, scene)
    root = project_path(project_id)
    image = root / "source" / "images" / scene["image"]
    output = root / "scenes" / f"scene-{scene_index:03d}.mp4"
    settings = project["settings"]
    log_path = root / "logs" / f"scene-{scene_index:03d}.log"
    if progress:
        progress(1, f"Cảnh {scene_index} đang chờ lượt")
    with RENDER_SLOTS:
        if progress:
            progress(3, f"Đang chuẩn bị cảnh {scene_index}")
        if settings.get("render_mode") == "static":
            _render_static_scene(image, output, float(scene["duration"]), int(settings.get("fps", 30)),
                                 log_path, progress, scene_index)
        else:
            annotation = _annotation(project, scene)
            command = [sys.executable, "-X", "utf8", str(RENDERER), str(image), str(annotation), str(output), str(HAND),
                       "--total-ms", str(round(scene["duration"] * 1000)), "--fps", str(settings.get("fps", 30)),
                       "--cap-long-edge", "1080", "--ink-path", settings.get("ink_path", "grid"),
                       "--color-fill", settings.get("color_fill", "contour-wipe"), "--ink-color", settings.get("ink_color", "#222831")]
            output_lines: list[str] = []
            proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            assert proc.stdout is not None
            for line in proc.stdout:
                output_lines.append(line)
                match = re.search(r"PROGRESS=(\d+(?:\.\d+)?)", line)
                if match and progress:
                    value = max(3.0, min(99.0, float(match.group(1))))
                    progress(value, f"Đang dựng cảnh {scene_index} · {round(value)}%")
            proc.wait()
            log_path.write_text("".join(output_lines), encoding="utf-8")
            if proc.returncode:
                raise RuntimeError(f"Dựng cảnh {scene_index} thất bại. Xem {log_path.name}")
    with PROJECT_STATE_LOCK:
        project = load_project(project_id)
        scene = next(x for x in project["scenes"] if x["index"] == scene_index)
        if _scene_signature(project, scene) != signature:
            scene.update({"rendered": False, "status": "ready", "video": None})
            save_project(project)
            raise RuntimeError(f"Cảnh {scene_index} đã được chỉnh sửa trong lúc dựng. Hãy dựng lại cảnh này.")
        scene.update({"rendered": True, "status": "done", "video": output.name})
        save_project(project)
    if progress:
        progress(100, f"Đã dựng cảnh {scene_index}")
    return output


def _escape_ass(text: str) -> str:
    return text.replace("\\", "／").replace("{", "（").replace("}", "）").replace("\n", "\\N")


def _ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000:01}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def _ass_color(value: str) -> str:
    color = value.lstrip("#")
    red, green, blue = color[0:2], color[2:4], color[4:6]
    return f"&H00{blue}{green}{red}"


def _split_long_subtitle(value: str, max_chars: int) -> list[str]:
    value = value.strip()
    if len(value) <= max_chars:
        return [value] if value else []
    if " " not in value:
        return [value[i:i + max_chars] for i in range(0, len(value), max_chars)]
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _subtitle_chunks(text: str, max_chars: int) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    clauses = re.findall(r"[^，,。！？!?；;：:、]+[，,。！？!?；;：:、]?", text)
    chunks: list[str] = []
    current = ""
    joiner = "" if re.search(r"[\u3400-\u9fff]", text) else " "
    for clause in clauses:
        for piece in _split_long_subtitle(clause.strip(), max_chars):
            candidate = f"{current}{joiner}{piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    for index in range(1, len(chunks)):
        closing = re.match(r"^[」』”’]+", chunks[index])
        if closing:
            chunks[index - 1] += closing.group(0)
            chunks[index] = chunks[index][len(closing.group(0)):].lstrip()
    chunks = [chunk for chunk in chunks if chunk]
    if len(chunks) > 1 and len(chunks[-1]) <= 3 and len(chunks[-2]) + len(chunks[-1]) <= max_chars + 2:
        tail = chunks.pop()
        chunks[-1] += tail
    return chunks


def _boolean_runs(mask: np.ndarray, value: bool) -> list[tuple[int, int]]:
    selected = (mask == value).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.r_[0, selected, 0]))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


def _speech_intervals(path: Path, sample_rate: int = 16000) -> list[tuple[float, float]]:
    """Return voiced ranges using a fast local energy detector; no cloud/API is used."""
    try:
        chunks: list[np.ndarray] = []
        with av.open(str(path)) as container:
            if not container.streams.audio:
                return []
            resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
            for frame in container.decode(audio=0):
                converted = resampler.resample(frame)
                converted = converted if isinstance(converted, list) else [converted]
                chunks.extend(item.to_ndarray().reshape(-1).astype(np.float32) for item in converted)
        if not chunks:
            return []
        samples = np.concatenate(chunks)
        frame_samples = round(sample_rate * .02)
        count = len(samples) // frame_samples
        if count < 1:
            return []
        rms = np.sqrt(np.mean(samples[:count * frame_samples].reshape(count, frame_samples) ** 2, axis=1))
        threshold = max(120.0, float(np.percentile(rms, 15)) * 2.2, float(np.percentile(rms, 90)) * .045)
        active = rms >= threshold
        for start, end in _boolean_runs(active, False):
            if start > 0 and end < len(active) and end - start <= 3:
                active[start:end] = True
        for start, end in _boolean_runs(active, True):
            if end - start < 3:
                active[start:end] = False
        return [(start * .02, end * .02) for start, end in _boolean_runs(active, True)]
    except (av.error.FFmpegError, OSError, ValueError):
        return []


def _time_at_voice_fraction(intervals: list[tuple[float, float]], fraction: float) -> float:
    total = sum(end - start for start, end in intervals)
    target = max(0.0, min(1.0, fraction)) * total
    for start, end in intervals:
        duration = end - start
        if target <= duration:
            return start + target
        target -= duration
    return intervals[-1][1]


def _subtitle_events(project: dict, width: int, height: int) -> list[tuple[float, float, str]]:
    settings = project["settings"]
    _normalize_subtitle_settings(settings)
    scale = height / 1920
    logical_width = width / scale
    fit_chars = max(8, int((logical_width - 120) / max(20, settings["subtitle_font_size"])))
    max_chars = min(settings["subtitle_max_chars"], fit_chars)
    voice = _audio_file(project, "voice")
    activity = _speech_intervals(voice) if voice else []
    events: list[tuple[float, float, str]] = []
    for scene in project["scenes"]:
        chunks = _subtitle_chunks(scene.get("text", ""), max_chars)
        if not chunks:
            continue
        scene_start, scene_end = float(scene["start"]), float(scene["end"])
        source_start = float(scene.get("voice_start") if scene.get("voice_start") is not None else scene_start)
        source_start += float(scene.get("voice_trim_start", 0))
        source_end = float(scene.get("voice_end") if scene.get("voice_end") is not None else scene_end)
        source_end -= float(scene.get("voice_trim_end", 0))
        voiced = [(max(start, source_start), min(end, source_end)) for start, end in activity
                  if min(end, source_end) - max(start, source_start) >= .02]
        weights = [max(1, len(re.sub(r"[\s，,。！？!?；;：:、]", "", chunk))) for chunk in chunks]
        weight_total = sum(weights)
        fractions = [0.0]
        for weight in weights:
            fractions.append(fractions[-1] + weight / weight_total)
        if voiced:
            desired = [_time_at_voice_fraction(voiced, value) for value in fractions[1:-1]]
            gaps = [(voiced[index][1], voiced[index + 1][0]) for index in range(len(voiced) - 1)
                    if voiced[index + 1][0] - voiced[index][1] >= .10]
            cuts: list[tuple[float, float]] = []
            last_gap = -1
            for target in desired:
                candidates = [(index, gap) for index, gap in enumerate(gaps) if index > last_gap]
                nearest = min(candidates, key=lambda item: abs(sum(item[1]) / 2 - target)) if candidates else None
                if nearest and abs(sum(nearest[1]) / 2 - target) <= .70:
                    last_gap, cut = nearest
                    cuts.append(cut)
                else:
                    cuts.append((target, target))
            source_starts = [voiced[0][0], *[cut[1] for cut in cuts]]
            source_ends = [cut[0] for cut in cuts] + [voiced[-1][1]]
            starts = [scene_start + value - source_start for value in source_starts]
            ends = [scene_start + value - source_start for value in source_ends]
        else:
            boundaries = [scene_start + (scene_end - scene_start) * value for value in fractions]
            starts, ends = boundaries[:-1], boundaries[1:]
        starts[0] = max(scene_start, starts[0])
        ends[-1] = min(scene_end, ends[-1])
        for index, chunk in enumerate(chunks):
            start, end = starts[index], ends[index]
            if end - start >= .08:
                events.append((start, end, chunk))
    return events


def make_ass(project: dict, width: int, height: int) -> Path | None:
    settings = project["settings"]
    _normalize_subtitle_settings(settings)
    if not settings.get("subtitles") and not settings.get("channel_name", "").strip():
        return None
    scale = height / 1920
    font_size = max(12, round(settings["subtitle_font_size"] * scale))
    font_name = settings["subtitle_font"]
    primary_color = _ass_color(settings["subtitle_color"])
    subtitle_top = settings["subtitle_position"] == "top"
    subtitle_alignment = 8 if subtitle_top else 2
    subtitle_margin = round((140 if subtitle_top else 180) * scale)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Subtitle,{font_name},{font_size},{primary_color},&H000000FF,&H96000000,&H96000000,-1,0,0,0,100,100,0,0,3,1,0,{subtitle_alignment},60,60,{subtitle_margin},1",
        f"Style: Channel,Arial,{round(28*scale)},&HAAFFFFFF,&H000000FF,&H50000000,&H50000000,0,0,0,0,100,100,0,0,1,1,0,9,35,35,35,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if settings.get("subtitles"):
        for start, end, text in _subtitle_events(project, width, height):
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Subtitle,,0,0,0,,{_escape_ass(text)}")
    channel = settings.get("channel_name", "").strip()
    if channel:
        lines.append(f"Dialogue: 1,0:00:00.00,{_ass_time(project['analysis']['total_duration'])},Channel,,0,0,0,,{_escape_ass(channel)}")
    path = project_path(project["id"]) / "source" / "subtitles.ass"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def _output_size(settings: dict) -> tuple[int, int]:
    hd = settings.get("resolution", "1080p") == "1080p"
    if settings.get("aspect") == "16:9":
        return (1920, 1080) if hd else (1280, 720)
    return (1080, 1920) if hd else (720, 1280)


def _visual_filter(project: dict, width: int, height: int, fps: int) -> tuple[list[str], str]:
    """Build a duration-preserving scene chain with an optional smooth transition."""
    scenes = project["scenes"]
    filters: list[str] = []
    for index, scene in enumerate(scenes):
        duration = max(.1, float(scene["duration"]))
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=#F6F1E3,setsar=1,"
            f"fps={fps},settb=1/{fps},trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[base{index}]"
        )
    if len(scenes) == 1:
        filters.append("[base0]null[visual]")
        return filters, "[visual]"

    transition = project["settings"].get("transition", "dissolve")
    if transition == "none":
        filters.append("".join(f"[base{i}]" for i in range(len(scenes))) +
                       f"concat=n={len(scenes)}:v=1:a=0[visual]")
        return filters, "[visual]"

    requested = float(project["settings"].get("transition_duration", .55))
    shortest = min(float(scene["duration"]) for scene in scenes)
    duration = max(.1, min(requested, shortest * .45))
    effect = {"dissolve": "fade", "fadeblack": "fadeblack", "slideleft": "slideleft"}.get(transition, "fade")
    for index in range(len(scenes)):
        if index < len(scenes) - 1:
            filters.append(f"[base{index}]tpad=stop_mode=clone:stop_duration={duration:.3f},fps={fps}[v{index}]")
        else:
            filters.append(f"[base{index}]fps={fps}[v{index}]")
    previous = "v0"
    offset = float(scenes[0]["duration"])
    for index in range(1, len(scenes)):
        output = "visual" if index == len(scenes) - 1 else f"mix{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition={effect}:duration={duration:.3f}:"
            f"offset={offset:.3f}[{output}]"
        )
        previous = output
        offset += float(scenes[index]["duration"])
    return filters, "[visual]"


def merge_project(project_id: str, progress: Callable[[float, str], None] | None = None) -> Path:
    project = load_project(project_id)
    root = project_path(project_id)
    videos = [root / "scenes" / s["video"] if s.get("rendered") and s.get("video")
              else root / "scenes" / f"missing-scene-{s['index']:03d}.mp4" for s in project["scenes"]]
    missing = [str(p.name) for p in videos if not p.exists()]
    if missing:
        raise ValueError("Chưa dựng: " + ", ".join(missing))
    width, height = _output_size(project["settings"])
    fps = int(project["settings"].get("fps", 30))
    ffmpeg = ffmpeg_exe()
    visual = root / "outputs" / "visual.mp4"
    args = []
    for video in videos:
        args += ["-i", str(video)]
    filters, visual_label = _visual_filter(project, width, height, fps)
    command = [ffmpeg, "-hide_banner", "-y", *args, "-filter_complex", ";".join(filters), "-map", visual_label,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(visual)]
    if progress:
        progress(10, "Đang chuẩn hóa và ghép hình")
    proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (root / "logs" / "merge-visual.log").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode:
        detail = " | ".join(proc.stderr.strip().splitlines()[-12:]) if proc.stderr.strip() else "FFmpeg không trả về chi tiết"
        raise RuntimeError(f"Ghép hình thất bại: {detail}")

    project = load_project(project_id)
    total = float(project["analysis"]["total_duration"])
    ass = make_ass(project, width, height)
    voice, music = _audio_file(project, "voice"), _audio_file(project, "music")
    final = root / "outputs" / f"{project_id}-final.mp4"
    inputs = ["-i", str(visual)]
    audio_filters = []
    audio_labels = []
    next_index = 1
    if voice:
        inputs += ["-i", str(voice)]
        segments = []
        for scene in project["scenes"]:
            if scene.get("voice_start") is None or scene.get("voice_end") is None:
                segments = []
                break
            start = float(scene["voice_start"]) + float(scene.get("voice_trim_start", 0))
            end = float(scene["voice_end"]) - float(scene.get("voice_trim_end", 0))
            if end - start < .05:
                segments = []
                break
            segments.append((start, end))
        if not any(float(scene.get("voice_trim_start", 0)) > 0 or float(scene.get("voice_trim_end", 0)) > 0
                   for scene in project["scenes"]):
            segments = []
        volume = float(project["settings"].get("voice_volume", 1.0))
        if len(segments) > 1:
            sources = "".join(f"[voice-src-{i}]" for i in range(len(segments)))
            audio_filters.append(f"[{next_index}:a]asplit={len(segments)}{sources}")
            labels = []
            for i, (start, end) in enumerate(segments):
                label = f"voice-part-{i}"
                audio_filters.append(
                    f"[voice-src-{i}]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[{label}]"
                )
                labels.append(f"[{label}]")
            audio_filters.append(
                "".join(labels) + f"concat=n={len(labels)}:v=0:a=1,volume={volume},apad=whole_dur={total}[voice]"
            )
        elif len(segments) == 1:
            start, end = segments[0]
            audio_filters.append(
                f"[{next_index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"volume={volume},apad=whole_dur={total}[voice]"
            )
        else:
            audio_filters.append(f"[{next_index}:a]volume={volume},apad=whole_dur={total}[voice]")
        audio_labels.append("[voice]")
        next_index += 1
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        fade_start = max(0, total - 2.5)
        audio_filters.append(f"[{next_index}:a]volume={float(project['settings'].get('music_volume',.18))},atrim=0:{total},afade=t=out:st={fade_start}:d={min(2.5,total)}[music]")
        audio_labels.append("[music]")
    video_filter = "[0:v]" + ("ass=source/subtitles.ass" if ass else "null") + "[video]"
    complex_filters = [video_filter, *audio_filters]
    if len(audio_labels) > 1:
        complex_filters.append("".join(audio_labels) + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0,alimiter=limit=0.95,atrim=0:{total}[audio]")
    elif len(audio_labels) == 1:
        complex_filters.append(audio_labels[0] + f"atrim=0:{total}[audio]")
    else:
        complex_filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total}[audio]")
    command = [ffmpeg, "-hide_banner", "-y", *inputs, "-filter_complex", ";".join(complex_filters),
               "-map", "[video]", "-map", "[audio]", "-t", str(total), "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(final)]
    if progress:
        progress(65, "Đang trộn âm thanh, phụ đề và tên kênh")
    proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (root / "logs" / "final.log").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError("Xuất MP4 thất bại. Xem logs/final.log")
    with PROJECT_STATE_LOCK:
        project = load_project(project_id)
        project["final_video"] = final.name
        save_project(project)
    if progress:
        progress(100, "Đã xuất MP4 hoàn chỉnh")
    return final


class JobManager:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="whiteboard")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, project_id: str, kind: str, fn: Callable) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[job_id] = {"id": job_id, "project_id": project_id, "kind": kind,
                                 "state": "queued", "progress": 0, "message": "Đang chờ", "error": None}

        def update(progress: float, message: str, details: dict | None = None) -> None:
            with self.lock:
                values = {"state": "running", "progress": round(progress, 1), "message": message}
                if details is not None:
                    values["details"] = details
                self.jobs[job_id].update(values)

        def run() -> None:
            try:
                update(1, "Đang bắt đầu")
                result = fn(update)
                with self.lock:
                    self.jobs[job_id].update({"state": "done", "progress": 100, "message": "Hoàn tất", "result": str(result)})
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id].update({"state": "error", "message": "Có lỗi", "error": str(exc)})
        self.executor.submit(run)
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return dict(self.jobs[job_id]) if job_id in self.jobs else None


JOBS = JobManager()


def render_all(project_id: str, progress: Callable[..., None]) -> Path:
    project = load_project(project_id)
    root = project_path(project_id)
    pending = [scene for scene in project["scenes"]
               if not scene.get("rendered") or not scene.get("video")
               or not (root / "scenes" / scene["video"]).exists()]
    total = len(pending)
    scene_values = {scene["index"]: 0.0 for scene in pending}
    progress_lock = threading.Lock()

    def run_one(scene: dict) -> Path:
        index = scene["index"]

        def scene_progress(value: float, message: str) -> None:
            with progress_lock:
                scene_values[index] = value
                overall = sum(scene_values.values()) / max(1, total) * .88
                progress(overall, message, {
                    "scene_index": index,
                    "scene_progress": {str(key): round(current, 1) for key, current in scene_values.items()},
                })

        return render_scene(project_id, index, scene_progress)

    if pending:
        with ThreadPoolExecutor(max_workers=min(2, total), thread_name_prefix="scene") as executor:
            futures = [executor.submit(run_one, scene) for scene in pending]
            for future in as_completed(futures):
                future.result()
    progress(90, "Đang ghép video hoàn chỉnh")
    return merge_project(project_id, lambda value, message: progress(90 + value * .1, message))
