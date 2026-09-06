import io
import shutil
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import pipeline


def png_bytes(width=80, height=120, color="#F5EBD7"):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
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
        self.assertEqual(project["settings"]["subtitle_position"], "top")

    def test_create_project_keeps_selected_video_mode_and_transition(self):
        project = pipeline.create_project(
            "Ảnh tĩnh", [("1.png", png_bytes())], "Một cảnh", None, None,
            "static", "slideleft", .7,
        )
        self.assertEqual(project["settings"]["render_mode"], "static")
        self.assertEqual(project["settings"]["transition"], "slideleft")
        self.assertEqual(project["settings"]["transition_duration"], .7)

    def test_subtitle_style_supports_position_color_font_and_size(self):
        project = pipeline.create_project("Phụ đề", [("1.png", png_bytes())], "Xin chào")
        project["scenes"][0].update({"start": 0.0, "end": 6.0})
        project = pipeline.update_project(project["id"], {"settings": {
            "subtitle_position": "bottom", "subtitle_color": "#12ABEF",
            "subtitle_font": "Arial", "subtitle_font_size": 72,
        }})
        ass = pipeline.make_ass(project, 1080, 1920).read_text(encoding="utf-8-sig")
        self.assertIn("Style: Subtitle,Arial,72,&H00EFAB12", ass)
        self.assertIn(",2,60,60,180,1", ass)

    def test_subtitles_are_split_and_timed_to_voice_activity(self):
        text = "一個孩子，不需要一位完美的媽媽。孩子真正需要的，是有人陪伴。"
        project = pipeline.create_project("Khớp voice", [("1.png", png_bytes())], text, ("voice.wav", wav_bytes(6)), None)
        project = pipeline.update_project(project["id"], {"settings": {"subtitle_max_chars": 10}})
        with patch.object(pipeline, "_speech_intervals", return_value=[(.4, 2.0), (2.5, 5.4)]):
            events = pipeline._subtitle_events(project, 1080, 1920)
            ass = pipeline.make_ass(project, 1080, 1920).read_text(encoding="utf-8-sig")
        self.assertGreater(len(events), 2)
        self.assertTrue(all(len(text) <= 10 for _, _, text in events))
        self.assertAlmostEqual(events[0][0], .4, places=2)
        self.assertAlmostEqual(events[-1][1], 5.4, places=2)
        self.assertEqual(ass.count("Dialogue: 0,"), len(events))

    def test_short_closing_punctuation_is_kept_without_duplicate_text(self):
        text = "請把這支影片傳給一位需要聽見這句話的媽媽： 「你已經做得夠好了。 」"
        chunks = pipeline._subtitle_chunks(text, 16)
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))
        self.assertEqual(len(chunks), len(set(chunks)))

    def test_old_project_gets_top_subtitle_defaults(self):
        project = pipeline.create_project("Mặc định phụ đề", [("1.png", png_bytes())], "Một cảnh")
        for key in pipeline.SUBTITLE_DEFAULTS:
            project["settings"].pop(key)
        pipeline.save_project(project)
        loaded = pipeline.load_project(project["id"])
        self.assertEqual(loaded["settings"]["subtitle_position"], "top")
        self.assertEqual(loaded["settings"]["subtitle_font"], "Microsoft JhengHei")

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

    def test_switching_to_static_mode_invalidates_rendered_scenes(self):
        project = pipeline.create_project("Đổi kiểu dựng", [("1.png", png_bytes())], "Một cảnh")
        project["scenes"][0].update({"rendered": True, "video": "scene-001.mp4", "status": "done"})
        pipeline.save_project(project)
        project = pipeline.update_project(project["id"], {"settings": {"render_mode": "static"}})
        self.assertFalse(project["scenes"][0]["rendered"])
        self.assertIsNone(project["scenes"][0]["video"])

    def test_transition_change_only_requires_remerge(self):
        project = pipeline.create_project("Đổi chuyển cảnh", [("1.png", png_bytes())], "Một cảnh")
        project["scenes"][0].update({"rendered": True, "video": "scene-001.mp4", "status": "done"})
        project["final_video"] = "old.mp4"
        pipeline.save_project(project)
        project = pipeline.update_project(project["id"], {"settings": {"transition": "fadeblack"}})
        self.assertTrue(project["scenes"][0]["rendered"])
        self.assertIsNone(project["final_video"])

    def test_visual_filter_uses_duration_preserving_xfade_offsets(self):
        project = pipeline.create_project(
            "Chuyển cảnh", [("1.png", png_bytes()), ("2.png", png_bytes())], "Một. Hai."
        )
        project = pipeline.update_project(project["id"], {"settings": {
            "transition": "dissolve", "transition_duration": .55,
        }, "scenes": [{"index": 1, "duration": 3}, {"index": 2, "duration": 4}]})
        filters, label = pipeline._visual_filter(project, 1080, 1920, 30)
        chain = ";".join(filters)
        self.assertEqual(label, "[visual]")
        self.assertIn("tpad=stop_mode=clone:stop_duration=0.550", chain)
        self.assertIn("xfade=transition=fade:duration=0.550:offset=3.000", chain)

    def test_static_scene_renderer_keeps_full_image_and_duration(self):
        project = pipeline.create_project(
            "Render tĩnh", [("1.png", png_bytes())], "Một cảnh", None, None, "static"
        )
        project = pipeline.update_project(project["id"], {"scenes": [{"index": 1, "duration": .8}]})
        output = pipeline.render_scene(project["id"], 1)
        self.assertTrue(output.exists())
        self.assertAlmostEqual(pipeline.probe_duration(output), .8, delta=.08)

    def test_static_scenes_merge_with_smooth_transition_at_voice_length(self):
        project = pipeline.create_project(
            "Ghép tĩnh", [("1.png", png_bytes(color="#CC5533")),
                          ("2.png", png_bytes(color="#3355CC"))],
            "Một. Hai.", None, None, "static", "dissolve", .3,
        )
        project = pipeline.update_project(project["id"], {
            "settings": {"resolution": "720p", "subtitles": False},
            "scenes": [{"index": 1, "duration": .8}, {"index": 2, "duration": .8}],
        })
        pipeline.render_scene(project["id"], 1)
        pipeline.render_scene(project["id"], 2)
        output = pipeline.merge_project(project["id"])
        self.assertTrue(output.exists())
        self.assertAlmostEqual(pipeline.probe_duration(output), 1.6, delta=.12)

    def test_manual_timing_mode_uses_requested_scene_duration(self):
        project = pipeline.create_project("Thủ công", [("1.png", png_bytes()), ("2.png", png_bytes())], "Một. Hai.", ("voice.wav", wav_bytes(9)), None)
        pipeline.update_project(project["id"], {"settings": {"timing_mode": "manual", "manual_scene_duration": 4.5}})
        project = pipeline.analyze_project(project["id"])
        self.assertEqual(project["analysis"]["mode"], "manual")
        self.assertAlmostEqual(project["analysis"]["total_duration"], 9.0)
        self.assertEqual([x["duration"] for x in project["scenes"]], [4.5, 4.5])

    def test_voice_can_be_added_after_project_creation(self):
        project = pipeline.create_project("Thêm voice", [("1.png", png_bytes())], "Một cảnh")
        self.assertIsNone(project["audio"]["voice"])
        project = pipeline.set_audio(project["id"], "voice", "new.wav", wav_bytes(3.25))
        self.assertEqual(project["audio"]["voice"], "voice.wav")
        self.assertAlmostEqual(project["analysis"]["voice_duration"], 3.25, places=2)
        self.assertAlmostEqual(project["scenes"][0]["duration"], 3.25, places=2)
        self.assertEqual(project["scenes"][0]["voice_start"], 0.0)
        self.assertAlmostEqual(project["scenes"][0]["voice_end"], 3.25, places=2)

    def test_scene_voice_trim_shortens_timeline_and_invalidates_only_that_scene(self):
        project = pipeline.create_project(
            "Cắt voice",
            [("1.png", png_bytes()), ("2.png", png_bytes())],
            "Một. Hai.", ("voice.wav", wav_bytes(6)), None,
        )
        for scene in project["scenes"]:
            scene.update({"rendered": True, "video": f"scene-{scene['index']:03d}.mp4", "status": "done"})
        pipeline.save_project(project)
        project = pipeline.update_project(project["id"], {
            "scenes": [{"index": 2, "voice_trim_end": .75}],
        })
        self.assertTrue(project["scenes"][0]["rendered"])
        self.assertFalse(project["scenes"][1]["rendered"])
        self.assertAlmostEqual(project["scenes"][1]["voice_trim_end"], .75)
        self.assertAlmostEqual(project["analysis"]["total_duration"], 5.25, places=2)
        self.assertIsNone(project["final_video"])

    def test_old_voice_project_gets_segment_boundaries_on_load(self):
        project = pipeline.create_project("Tương thích", [("1.png", png_bytes())], "Một", ("voice.wav", wav_bytes(2)), None)
        project["scenes"][0].pop("voice_start")
        project["scenes"][0].pop("voice_end")
        project["scenes"][0].pop("voice_trim_start")
        project["scenes"][0].pop("voice_trim_end")
        pipeline.save_project(project)
        project = pipeline.load_project(project["id"])
        self.assertEqual(project["scenes"][0]["voice_start"], 0.0)
        self.assertAlmostEqual(project["scenes"][0]["voice_end"], 2.0, places=2)

    def test_batch_render_resumes_after_completed_scenes(self):
        project = pipeline.create_project("Tiếp tục", [("1.png", png_bytes()), ("2.png", png_bytes())], "Một. Hai.")
        first = project["scenes"][0]
        first.update({"rendered": True, "video": "scene-001.mp4", "status": "done"})
        scene_file = self.temp / project["id"] / "scenes" / "scene-001.mp4"
        scene_file.write_bytes(b"ready")
        pipeline.save_project(project)
        with patch.object(pipeline, "render_scene") as render, patch.object(pipeline, "merge_project", return_value=Path("final.mp4")):
            result = pipeline.render_all(project["id"], lambda *_: None)
        self.assertEqual(result, Path("final.mp4"))
        self.assertEqual(render.call_count, 1)
        self.assertEqual(render.call_args.args[1], 2)

    def test_batch_render_runs_two_scenes_concurrently(self):
        project = pipeline.create_project(
            "Song song",
            [("1.png", png_bytes()), ("2.png", png_bytes()), ("3.png", png_bytes())],
            "Một. Hai. Ba.",
        )
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_render(project_id, scene_index, progress):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            progress(50, f"Đang dựng cảnh {scene_index}")
            time.sleep(.05)
            with lock:
                active -= 1
            return Path(f"scene-{scene_index:03d}.mp4")

        with patch.object(pipeline, "render_scene", side_effect=fake_render), \
                patch.object(pipeline, "merge_project", return_value=Path("final.mp4")):
            pipeline.render_all(project["id"], lambda *_: None)
        self.assertEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
