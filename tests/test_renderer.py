from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.renderer import render_manifest_to_mp4
from tiktok_trivia_factory.repository import (
    add_idea,
    get_latest_draft_artifact,
    save_draft_artifact,
    start_job,
)


class RendererTests(unittest.TestCase):
    def test_render_manifest_to_mp4_creates_file(self) -> None:
        manifest = {
            "video": {"width": 1080, "height": 1920, "fps": 12},
            "source_script": {"topic": "Test Trivia"},
            "scenes": [
                {
                    "id": "hook",
                    "type": "hook",
                    "format": "qa",
                    "duration_seconds": 0.5,
                    "text": "Test hook",
                    "voiceover": "Test hook",
                    "pacing": {"purpose": "open_loop"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "draft.mp4"
            rendered = render_manifest_to_mp4(json.dumps(manifest), output_path, preview=True)
            header = rendered.read_bytes()[:32]

        self.assertGreater(rendered.stat().st_size if rendered.exists() else len(header), 0)
        self.assertIn(b"ftyp", header)

    def test_save_and_get_latest_draft_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
            job = start_job(db_path, idea.id)
            saved = save_draft_artifact(
                db_path,
                job_id=job.id,
                revision=1,
                artifact_type="mp4",
                path=str(Path(temp_dir) / "draft.mp4"),
            )
            latest = get_latest_draft_artifact(db_path, job.id)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, saved.id)
        self.assertEqual(latest.artifact_type, "mp4")


if __name__ == "__main__":
    unittest.main()
