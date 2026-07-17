from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.render_manifest import build_render_manifest
from tiktok_trivia_factory.renderer import render_manifest_to_mp4
from tiktok_trivia_factory.repository import (
    add_idea,
    get_active_job,
    get_latest_video_script,
    get_latest_render_manifest,
    list_ideas,
    save_draft_artifact,
    save_render_manifest,
    save_video_script,
    start_job,
)
from tiktok_trivia_factory.review import (
    ReviewError,
    approve_active_review,
    get_active_review_summary,
    revise_active_review,
)
from tiktok_trivia_factory.script_generator import generate_script
from tiktok_trivia_factory.telegram_adapter import handle_review_message


class ReviewTests(unittest.TestCase):
    def test_approval_requires_existing_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
            start_job(db_path, idea.id)

            with self.assertRaises(ReviewError):
                approve_active_review(db_path)

    def test_approve_active_review_completes_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            event = approve_active_review(db_path)
            active = get_active_job(db_path)

        self.assertEqual(event.decision, "approved")
        self.assertIsNone(active)

    def test_revision_creates_new_manifest_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, job_id, original_manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            result = revise_active_review(
                db_path,
                artifacts_dir=Path(temp_dir) / "artifacts",
                requested_change='make it faster and change hook to "Lightning round!"',
                preview=True,
            )
            latest_manifest = get_latest_render_manifest(db_path, job_id)
            revised_draft_exists = Path(result.draft.path).exists()

        original_payload = json.loads(original_manifest.manifest_json)
        revised_payload = json.loads(result.manifest.manifest_json)
        self.assertEqual(result.manifest.revision, 2)
        self.assertEqual(latest_manifest.id, result.manifest.id)
        self.assertLess(revised_payload["video"]["duration_seconds"], original_payload["video"]["duration_seconds"])
        self.assertEqual(revised_payload["scenes"][0]["text"], "Lightning round!")
        self.assertTrue(revised_draft_exists)

    def test_telegram_adapter_show_and_approve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            show = handle_review_message(db_path, Path(temp_dir) / "artifacts", "show draft")
            approve = handle_review_message(db_path, Path(temp_dir) / "artifacts", "approve")
            show_media_exists = show.media_path is not None and Path(show.media_path).exists()

        self.assertTrue(show.ok)
        self.assertIn("Draft ready", show.message)
        self.assertNotIn("<change>", show.message)
        self.assertEqual(show.media_type, "video")
        self.assertIsNotNone(show.media_path)
        self.assertTrue(show_media_exists)
        self.assertTrue(approve.ok)
        self.assertIn("Approved draft", approve.message)

    def test_telegram_operator_saves_lists_and_produces_next_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"

            saved = handle_review_message(
                db_path,
                artifacts_dir,
                "save idea 10 trivia questions about FIFA World Cup",
            )
            listed = handle_review_message(db_path, artifacts_dir, "ideas")
            produced = handle_review_message(db_path, artifacts_dir, "produce next", watermark_text="@test")
            status = handle_review_message(db_path, artifacts_dir, "status")
            active = get_active_job(db_path)
            produced_media_exists = produced.media_path is not None and Path(produced.media_path).exists()

        self.assertTrue(saved.ok)
        self.assertIn("Saved idea", saved.message)
        self.assertTrue(listed.ok)
        self.assertIn("FIFA World Cup", listed.message)
        self.assertTrue(produced.ok)
        self.assertIn("Draft produced for review", produced.message)
        self.assertNotIn("<change>", produced.message)
        self.assertEqual(produced.media_type, "video")
        self.assertTrue(produced_media_exists)
        self.assertTrue(status.ok)
        self.assertIn("Active job", status.message)
        self.assertIsNotNone(active)

    def test_telegram_produce_next_uses_configured_trivia_bank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "state.sqlite3"
            artifacts_dir = base_dir / "artifacts"
            bank_path = base_dir / "trivia_bank.txt"
            bank_path.write_text(_sample_trivia_bank(), encoding="utf-8")

            saved = handle_review_message(
                db_path,
                artifacts_dir,
                "save idea 2 trivia questions about Minecraft mobs",
            )
            produced = handle_review_message(
                db_path,
                artifacts_dir,
                "produce next",
                trivia_bank_path=bank_path,
            )
            active = get_active_job(db_path)
            if active is None:
                raise AssertionError("Expected active job")
            script = get_latest_video_script(db_path, active.id)
            if script is None:
                raise AssertionError("Expected saved video script")
            payload = json.loads(script.script_json)

        self.assertTrue(saved.ok)
        self.assertTrue(produced.ok)
        self.assertEqual(script.provider, "local_trivia_bank")
        self.assertEqual(payload["topic"], "Minecraft Mobs")
        self.assertEqual(payload["questions"][0]["answer"], "Creeper")

    def test_telegram_approve_moves_used_trivia_bank_topic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "state.sqlite3"
            artifacts_dir = base_dir / "artifacts"
            bank_path = base_dir / "trivia_bank.txt"
            bank_path.write_text(_sample_trivia_bank(), encoding="utf-8")

            handle_review_message(
                db_path,
                artifacts_dir,
                "save idea 2 trivia questions about Minecraft mobs",
            )
            produced = handle_review_message(
                db_path,
                artifacts_dir,
                "produce next",
                trivia_bank_path=bank_path,
            )
            approved = handle_review_message(db_path, artifacts_dir, "approve")
            source_text = bank_path.read_text(encoding="utf-8")
            used_path = bank_path.parent / "used-trivia-bank.txt"
            used_text = used_path.read_text(encoding="utf-8")

        self.assertTrue(produced.ok)
        self.assertTrue(approved.ok)
        self.assertIn("Moved used bank topic", approved.message)
        self.assertNotIn("001. [Gaming - Minecraft Mobs]", source_text)
        self.assertIn("001. [Gaming - Minecraft Mobs]", used_text)
        self.assertIn("Which mob explodes when it gets close to the player?", used_text)

    def test_telegram_revision_returns_video_media_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            result = handle_review_message(
                db_path,
                Path(temp_dir) / "artifacts",
                "revise make it faster",
            )
            revised_media_exists = result.media_path is not None and Path(result.media_path).exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.media_type, "video")
        self.assertTrue(revised_media_exists)

    def test_telegram_operator_status_without_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            result = handle_review_message(db_path, Path(temp_dir) / "artifacts", "status")

        self.assertTrue(result.ok)
        self.assertIn("No active job", result.message)

    def test_telegram_produce_next_with_active_job_guides_operator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))
            add_idea(db_path, "10 trivia questions about 6th grade science")

            result = handle_review_message(db_path, Path(temp_dir) / "artifacts", "produce next")

        self.assertFalse(result.ok)
        self.assertIn("A production job is already active", result.message)
        self.assertIn("regenerate active", result.message)
        self.assertIn("discard active", result.message)

    def test_telegram_discard_active_requires_confirmation_and_unblocks_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))
            queued_idea = add_idea(db_path, "10 trivia questions about 6th grade science")
            artifacts_dir = Path(temp_dir) / "artifacts"

            prompt = handle_review_message(db_path, artifacts_dir, "discard active")
            still_blocked = handle_review_message(db_path, artifacts_dir, "produce next")
            discarded = handle_review_message(db_path, artifacts_dir, "confirm discard active")
            produced = handle_review_message(db_path, artifacts_dir, "produce next")
            active = get_active_job(db_path)
            produced_media_exists = produced.media_path is not None and Path(produced.media_path).exists()

        self.assertTrue(prompt.ok)
        self.assertIn("NOTE: You are getting rid of the oldest active task.", prompt.message)
        self.assertIn("Confirm discard active?", prompt.message)
        self.assertEqual(
            [(option.label, option.value) for option in prompt.reply_options or []],
            [("Yes", "confirm discard active"), ("No", "cancel")],
        )
        self.assertFalse(still_blocked.ok)
        self.assertTrue(discarded.ok)
        self.assertTrue(produced.ok)
        self.assertIn(queued_idea.prompt, produced.message)
        self.assertIsNotNone(active)
        self.assertEqual(active.idea_id, queued_idea.id)
        self.assertTrue(produced_media_exists)

    def test_telegram_regenerate_active_creates_new_media_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            result = handle_review_message(db_path, Path(temp_dir) / "artifacts", "regenerate active")
            latest_manifest = get_latest_render_manifest(db_path, job_id)
            media_exists = result.media_path is not None and Path(result.media_path).exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.media_type, "video")
        self.assertTrue(media_exists)
        self.assertIsNotNone(latest_manifest)
        self.assertEqual(latest_manifest.revision, 2)

    def test_telegram_clear_queued_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            add_idea(db_path, "10 trivia questions about FIFA World Cup")
            add_idea(db_path, "10 trivia questions about 6th grade science")

            prompt = handle_review_message(db_path, artifacts_dir, "clear queued")
            queued_before_confirm = list_ideas(db_path, status="queued")
            cleared = handle_review_message(db_path, artifacts_dir, "confirm clear queued")
            queued_after_confirm = list_ideas(db_path, status="queued")
            listed = handle_review_message(db_path, artifacts_dir, "ideas")

        self.assertTrue(prompt.ok)
        self.assertIn("Confirm clear queued?", prompt.message)
        self.assertEqual(
            [(option.label, option.value) for option in prompt.reply_options or []],
            [("Yes", "confirm clear queued"), ("No", "cancel")],
        )
        self.assertEqual(len(queued_before_confirm), 2)
        self.assertTrue(cleared.ok)
        self.assertEqual(queued_after_confirm, [])
        self.assertIn("No active or queued ideas", listed.message)

    def test_telegram_clear_active_confirmation_distinguishes_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            prompt = handle_review_message(db_path, Path(temp_dir) / "artifacts", "clear active")
            cancelled = handle_review_message(db_path, Path(temp_dir) / "artifacts", "no")

        self.assertTrue(prompt.ok)
        self.assertIn("NOTE: You are clearing ALL active tasks.", prompt.message)
        self.assertIn("Confirm clear active?", prompt.message)
        self.assertEqual(
            [(option.label, option.value) for option in prompt.reply_options or []],
            [("Yes", "confirm clear active"), ("No", "cancel")],
        )
        self.assertTrue(cancelled.ok)
        self.assertEqual(cancelled.message, "No changes made.")

    def test_telegram_conversation_can_show_status_and_save_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"

            result = handle_review_message(
                db_path,
                artifacts_dir,
                "Show me the status, and save this idea of having 15 questions about NBA Finals statistics.",
            )
            ideas = list_ideas(db_path, status="queued")

        self.assertTrue(result.ok)
        self.assertIn("No active job", result.message)
        self.assertIn("Saved idea", result.message)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].prompt, "15 trivia questions about NBA Finals statistics")

    def test_telegram_conversation_can_extract_long_form_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"

            result = handle_review_message(
                db_path,
                artifacts_dir,
                "I have some ideas for production. Maybe we can do a short-form video asking 10 questions about Led Zeppelin.",
            )
            ideas = list_ideas(db_path, status="queued")

        self.assertTrue(result.ok)
        self.assertIn("Saved idea", result.message)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].prompt, "10 trivia questions about Led Zeppelin")

    def test_telegram_conversation_can_list_ideas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            add_idea(db_path, "10 trivia questions about FIFA World Cup")

            result = handle_review_message(db_path, artifacts_dir, "Can you show me the ideas we have?")

        self.assertTrue(result.ok)
        self.assertIn("FIFA World Cup", result.message)

    def test_telegram_conversation_can_produce_next(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            add_idea(db_path, "10 trivia questions about FIFA World Cup")

            result = handle_review_message(db_path, artifacts_dir, "Please start the next queued video.")
            media_exists = result.media_path is not None and Path(result.media_path).exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.media_type, "video")
        self.assertTrue(media_exists)

    def test_telegram_produce_unsupported_topic_does_not_create_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            idea = add_idea(db_path, "15 trivia questions about ancient pottery glazing")

            result = handle_review_message(db_path, artifacts_dir, "Please start the next queued video.")
            active = get_active_job(db_path)
            queued = list_ideas(db_path, status="queued")

        self.assertFalse(result.ok)
        self.assertIn("No local seed pack or free research provider supports this topic yet", result.message)
        self.assertIsNone(active)
        self.assertEqual([item.id for item in queued], [idea.id])

    def test_telegram_conversation_can_prompt_to_discard_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            result = handle_review_message(db_path, Path(temp_dir) / "artifacts", "Can you get rid of the active draft?")

        self.assertTrue(result.ok)
        self.assertIn("Confirm discard active?", result.message)
        self.assertEqual(
            [(option.label, option.value) for option in result.reply_options or []],
            [("Yes", "confirm discard active"), ("No", "cancel")],
        )

    def test_telegram_conversation_clear_queued_ideas_keeps_queued_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            add_idea(db_path, "10 trivia questions about FIFA World Cup")

            result = handle_review_message(db_path, artifacts_dir, "Please clear the queued ideas.")

        self.assertTrue(result.ok)
        self.assertIn("Confirm clear queued?", result.message)
        self.assertEqual(
            [(option.label, option.value) for option in result.reply_options or []],
            [("Yes", "confirm clear queued"), ("No", "cancel")],
        )

    def test_telegram_conversation_can_revise_active_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, _job_id, _manifest, _draft = _create_reviewable_draft(Path(temp_dir))

            result = handle_review_message(db_path, Path(temp_dir) / "artifacts", "Please make it faster.")
            media_exists = result.media_path is not None and Path(result.media_path).exists()

        self.assertTrue(result.ok)
        self.assertIn("Revision rendered", result.message)
        self.assertEqual(result.media_type, "video")
        self.assertTrue(media_exists)

    def test_telegram_conversation_asks_for_nba_finals_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = handle_review_message(
                Path(temp_dir) / "state.sqlite3",
                Path(temp_dir) / "artifacts",
                "I want to do an NBA Finals trivia video.",
            )

        self.assertTrue(result.ok)
        self.assertIn("NBA Finals statistics trivia", result.message)
        self.assertEqual(
            [(option.label, option.value) for option in result.reply_options or []],
            [
                ("Stats trivia", "save idea 10 trivia questions about NBA Finals statistics"),
                ("Player trivia", "save idea 10 trivia questions about NBA Finals players"),
                ("Cancel", "cancel"),
            ],
        )

    def test_telegram_conversation_unknown_direction_returns_command_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = handle_review_message(
                Path(temp_dir) / "state.sqlite3",
                Path(temp_dir) / "artifacts",
                "Please handle that thing from before in the better way.",
            )

        self.assertFalse(result.ok)
        self.assertIn("Sorry, I was unable to get the directions", result.message)
        self.assertIn("save idea PROMPT", result.message)
        self.assertIn("produce next", result.message)


def _create_reviewable_draft(temp_dir: Path):
    db_path = temp_dir / "state.sqlite3"
    artifacts_dir = temp_dir / "artifacts"
    idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
    job = start_job(db_path, idea.id)
    generated_script = generate_script(idea.prompt, question_count=1, duration_seconds=10)
    script = save_video_script(
        db_path,
        job_id=job.id,
        script_json=generated_script.script_json,
        provider=generated_script.provider,
        confidence=generated_script.confidence,
        citations=generated_script.citations,
    )
    generated_manifest = build_render_manifest(script.script_json, watermark_text="@test")
    manifest = save_render_manifest(
        db_path,
        job_id=job.id,
        manifest_json=generated_manifest.manifest_json,
        provider=generated_manifest.provider,
    )
    output_path = artifacts_dir / job.id / f"draft_r{manifest.revision:03d}.mp4"
    render_manifest_to_mp4(manifest.manifest_json, output_path, preview=True)
    draft = save_draft_artifact(
        db_path,
        job_id=job.id,
        revision=manifest.revision,
        artifact_type="mp4",
        path=str(output_path),
    )
    summary = get_active_review_summary(db_path)
    if summary.draft is None:
        raise AssertionError("Expected reviewable draft")
    return db_path, job.id, manifest, draft


def _sample_trivia_bank() -> str:
    return """001. [Gaming - Minecraft Mobs]
Question:
Which mob explodes when it gets close to the player?
A. Zombie
B. Skeleton
C. Creeper
Answer: C. Creeper

Question:
Which mob drops blaze rods?
A. Ghast
B. Blaze
C. Enderman
Answer: B. Blaze

Question:
Which neutral mob becomes hostile if you look at it?
A. Enderman
B. Villager
C. Cow
Answer: A. Enderman
"""


if __name__ == "__main__":
    unittest.main()
