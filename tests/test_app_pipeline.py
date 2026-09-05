import io
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import pipeline


def png_bytes(width=80, height=120):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "#F5EBD7").save(buf, format="PNG")
    return buf.getvalue()


def wav_bytes(seconds=2.0, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\0" * int(seconds * rate))
    return buf.getvalue()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp()) / "projects"
        self.patch = patch.object(pipeline, "WORKSPACE", self.temp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.temp.parent, ignore_errors=True)

    def test_natural_key_sorts_numbered_images(self):
        values = ["10.png", "2.png", "01.png"]
        self.assertEqual(sorted(values, key=pipeline.natural_key), ["01.png", "2.png", "10.png"])

    def test_create_project_sorts_and_aligns_to_voice(self):
        project = pipeline.create_project(
            "Bản thử",
            [("10.png", png_bytes()), ("2.png", png_bytes()), ("01.png", png_bytes())],
            "Mở đầu. Nội dung chính rất dài. Kết thúc.",
            ("voice.wav", wav_bytes(6.0)), None,
        )
        self.assertEqual([x["source_name"] for x in project["scenes"]], ["01.png", "2.png", "10.png"])
        self.assertAlmostEqual(sum(x["duration"] for x in project["scenes"]), 6.0, places=2)
        self.assertEqual(project["analysis"]["mode"], "voice")
        self.assertTrue((self.temp / project["id"] / "source" / "subtitles.srt").exists())

    def test_annotation_respects_duration_and_speed(self):
        project = pipeline.create_project("Nét vẽ", [("1.png", png_bytes())], "Một cảnh")
        project = pipeline.update_project(project["id"], {"scenes": [{"index": 1, "duration": 5, "speed": 2}]})
        annotation = pipeline._annotation(project, project["scenes"][0])
        data = pipeline.read_json(annotation)
        self.assertEqual(data["canvas"], {"width": 80, "height": 120})
        self.assertEqual(data["sceneDurationMs"], 5000)
        self.assertLess(data["elements"][0]["reveal"]["durationMs"], 3000)

    def test_render_setting_change_invalidates_scene(self):
        project = pipeline.create_project("Đổi nét", [("1.png", png_bytes())], "Một cảnh")
        project["scenes"][0].update({"rendered": True, "video": "scene-001.mp4", "status": "done"})
        pipeline.save_project(project)
        project = pipeline.update_project(project["id"], {"settings": {"ink_color": "#ff0000"}})
        self.assertFalse(project["scenes"][0]["rendered"])
        self.assertIsNone(project["scenes"][0]["video"])


if __name__ == "__main__":
    unittest.main()
