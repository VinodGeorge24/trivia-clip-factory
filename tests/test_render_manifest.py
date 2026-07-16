from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.render_manifest import build_render_manifest
from tiktok_trivia_factory.repository import (
    add_idea,
    get_latest_render_manifest,
    save_render_manifest,
    save_video_script,
    start_job,
)
from tiktok_trivia_factory.script_generator import generate_script


class RenderManifestTests(unittest.TestCase):
    def test_manifest_has_vertical_countdown_reveal_contract(self) -> None:
        script = generate_script("10 trivia questions about FIFA World Cup", question_count=2)
        generated = build_render_manifest(script.script_json)
        payload = json.loads(generated.manifest_json)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["provider"], "manifest_v1")
        self.assertEqual(payload["video"]["aspect_ratio"], "9:16")
        self.assertEqual(payload["video"]["width"], 1080)
        self.assertEqual(payload["video"]["height"], 1920)
        self.assertEqual(payload["format"]["selected"], "qa")
        self.assertIn("multiple_choice", payload["format"]["supported"])
        self.assertIn("guess_image", payload["format"]["future_supported"])
        self.assertEqual(payload["style"]["text_scale"], "large_mobile_readable")

        scenes = payload["scenes"]
        self.assertEqual([scene["type"] for scene in scenes], ["hook", "question", "answer_reveal", "question", "answer_reveal"])
        self.assertEqual(scenes[1]["countdown"]["duration_seconds"], 5)
        self.assertEqual(len(scenes[1]["choices"]), 3)
        self.assertEqual(scenes[1]["correct_choice_label"], "A")
        self.assertEqual(scenes[2]["question_text"], scenes[1]["text"])
        self.assertEqual(scenes[2]["choices"], scenes[1]["choices"])
        self.assertEqual(scenes[2]["correct_choice_label"], scenes[1]["correct_choice_label"])
        self.assertEqual(scenes[1]["sound_cues"][0]["type"], "ticking")
        self.assertTrue(scenes[1]["sound_cues"][0]["enabled"])
        self.assertEqual(scenes[2]["sound_cues"][0]["type"], "ding")
        self.assertTrue(scenes[2]["sound_cues"][0]["enabled"])
        self.assertTrue(scenes[2]["pacing"]["immediate_after_countdown"])
        self.assertIn("voiceover", scenes[1])
        self.assertTrue(payload["audio"]["background_music"]["enabled"])

    def test_save_and_retrieve_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about Led Zeppelin")
            job = start_job(db_path, idea.id)
            script = generate_script(idea.prompt, question_count=1)
            saved_script = save_video_script(
                db_path,
                job_id=job.id,
                script_json=script.script_json,
                provider=script.provider,
                confidence=script.confidence,
                citations=script.citations,
            )
            manifest = build_render_manifest(saved_script.script_json)

            saved = save_render_manifest(
                db_path,
                job_id=job.id,
                manifest_json=manifest.manifest_json,
                provider=manifest.provider,
            )
            latest = get_latest_render_manifest(db_path, job.id)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, saved.id)
        self.assertEqual(latest.revision, 1)
        self.assertEqual(latest.provider, "manifest_v1")


if __name__ == "__main__":
    unittest.main()
