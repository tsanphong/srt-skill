"""Manual end-to-end smoke test. Output is written under ignored workspace/."""
from __future__ import annotations

import io
import math
import struct
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline import create_project, merge_project, render_scene, update_project


def sample_image() -> bytes:
    image = Image.new("RGB", (360, 640), "#F5EBD7")
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 120, 280, 320), outline="#222831", width=8)
    draw.line((110, 400, 250, 400), fill="#D67B35", width=12)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def sample_audio(seconds: float = 2.0, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = (struct.pack("<h", int(math.sin(i * 2 * math.pi * 220 / rate) * 900)) for i in range(int(seconds * rate)))
        out.writeframes(b"".join(frames))
    return buffer.getvalue()


def main() -> None:
    project = create_project("Smoke Test App", [("01.png", sample_image())], "Đây là cảnh kiểm tra.", ("voice.wav", sample_audio()), None)
    project = update_project(project["id"], {"settings": {"resolution": "720p", "channel_name": "Kênh thử"}})
    scene = render_scene(project["id"], 1, lambda p, m: print(f"scene {p:.0f}% {m}"))
    final = merge_project(project["id"], lambda p, m: print(f"merge {p:.0f}% {m}"))
    print(f"SCENE={scene}")
    print(f"FINAL={final}")


if __name__ == "__main__":
    main()
