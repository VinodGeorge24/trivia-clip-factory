from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.repository import (
    add_idea,
    get_successful_upload_attempt,
    save_draft_artifact,
    save_video_script,
    start_job,
)
from tiktok_trivia_factory.review import approve_active_review
from tiktok_trivia_factory.script_generator import generate_script
from tiktok_trivia_factory.telegram_adapter import handle_review_message
from tiktok_trivia_factory.uploads import (
    TIKTOK_API_UPLOAD_PROVIDER,
    UPLOAD_PACKET_PROVIDER,
    UploadError,
    get_upload_status,
    mark_upload_failed,
    mark_upload_succeeded,
    prepare_upload_packet,
    send_approved_draft_to_tiktok,
    start_upload_handoff,
)


class UploadTests(unittest.TestCase):
    def test_unapproved_draft_is_not_awaiting_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            _job_id = _create_draft_job(db_path, Path(temp_dir), approved=False)

            status = get_upload_status(db_path)

        self.assertEqual(status.candidates, [])

    def test_approved_draft_handoff_is_pending_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True)

            first = start_upload_handoff(db_path)
            second = start_upload_handoff(db_path)

        self.assertEqual(first.candidate.job.id, job_id)
        self.assertEqual(first.attempt.status, "pending")
        self.assertFalse(first.reused_existing_pending)
        self.assertEqual(second.attempt.id, first.attempt.id)
        self.assertTrue(second.reused_existing_pending)

    def test_successful_upload_removes_candidate_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True)
            start_upload_handoff(db_path)

            first = mark_upload_succeeded(db_path, job_id, provider_reference="tiktok-draft-1")
            second = mark_upload_succeeded(db_path, job_id, provider_reference="ignored")
            status = get_upload_status(db_path)
            successful = get_successful_upload_attempt(db_path, job_id)

        self.assertEqual(first.status, "succeeded")
        self.assertEqual(first.provider_reference, "tiktok-draft-1")
        self.assertEqual(second.id, first.id)
        self.assertEqual(successful.id, first.id)
        self.assertEqual(status.candidates, [])

    def test_failed_upload_keeps_candidate_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True)
            start_upload_handoff(db_path)

            failed = mark_upload_failed(db_path, job_id, "browser session expired")
            status = get_upload_status(db_path)

        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_message, "browser session expired")
        self.assertEqual([candidate.job.id for candidate in status.candidates], [job_id])
        self.assertEqual(status.candidates[0].latest_attempt.id, failed.id)

    def test_start_handoff_rejects_unknown_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"

            with self.assertRaises(UploadError):
                start_upload_handoff(db_path, job_id="job_000000000000")

    def test_start_handoff_rejects_missing_draft_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            _create_draft_job(db_path, Path(temp_dir), approved=True)
            (Path(temp_dir) / "draft.mp4").unlink()

            with self.assertRaisesRegex(UploadError, "Approved draft file is missing"):
                start_upload_handoff(db_path)

    def test_prepare_upload_packet_writes_metadata_and_pending_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            uploads_dir = Path(temp_dir) / "uploads"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True, with_script=True)

            packet = prepare_upload_packet(db_path, uploads_dir)
            second_packet = prepare_upload_packet(db_path, uploads_dir)
            persisted = json.loads(packet.packet_path.read_text(encoding="utf-8"))

        self.assertEqual(packet.candidate.job.id, job_id)
        self.assertEqual(packet.attempt.provider, UPLOAD_PACKET_PROVIDER)
        self.assertEqual(packet.attempt.status, "pending")
        self.assertEqual(packet.attempt.provider_reference, str(packet.packet_path))
        self.assertFalse(packet.reused_existing_pending)
        self.assertEqual(second_packet.attempt.id, packet.attempt.id)
        self.assertTrue(second_packet.reused_existing_pending)
        self.assertEqual(persisted["mode"], "tiktok_inbox_upload_packet")
        self.assertFalse(persisted["public_auto_post"])
        self.assertEqual(persisted["job"]["id"], job_id)
        self.assertEqual(persisted["script"]["topic"], "FIFA World Cup")
        self.assertIn("#worldcup", persisted["script"]["hashtags"])
        self.assertEqual(persisted["tiktok_upload"]["required_scope"], "video.upload")
        self.assertTrue(persisted["tiktok_upload"]["live_upload_implemented"])
        self.assertEqual(persisted["tiktok_upload"]["live_upload_provider"], TIKTOK_API_UPLOAD_PROVIDER)
        self.assertNotIn("token", json.dumps(persisted).lower())
        self.assertNotIn("cookie", json.dumps(persisted).lower())

    def test_tiktok_send_dry_run_selects_approved_draft_without_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True)

            result = send_approved_draft_to_tiktok(db_path, Path(temp_dir), dry_run=True)
            status = get_upload_status(db_path)

        self.assertEqual(result.candidate.job.id, job_id)
        self.assertEqual(result.status, "dry_run")
        self.assertIsNone(result.attempt)
        self.assertEqual(status.recent_attempts, [])

    def test_telegram_upload_status_handoff_and_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True)

            status = handle_review_message(db_path, artifacts_dir, "uploads status")
            handoff = handle_review_message(db_path, artifacts_dir, "upload approved")
            confirmed = handle_review_message(db_path, artifacts_dir, f"upload succeeded {job_id} draft-url-1")
            after = handle_review_message(db_path, artifacts_dir, "uploads status")

        self.assertTrue(status.ok)
        self.assertIn(job_id, status.message)
        self.assertTrue(handoff.ok)
        self.assertEqual(handoff.media_type, "video")
        self.assertIsNotNone(handoff.media_path)
        self.assertIn("Upload handoff", handoff.message)
        self.assertTrue(confirmed.ok)
        self.assertIn("Marked upload succeeded", confirmed.message)
        self.assertTrue(after.ok)
        self.assertIn("No approved drafts are awaiting upload", after.message)

    def test_telegram_upload_packet_returns_media_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=True, with_script=True)

            result = handle_review_message(db_path, artifacts_dir, "upload packet")
            packet_path = Path(temp_dir) / "uploads" / job_id / "upload_packet.json"
            media_exists = result.media_path is not None and Path(result.media_path).exists()
            packet_exists = packet_path.exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.media_type, "video")
        self.assertIsNotNone(result.media_path)
        self.assertTrue(media_exists)
        self.assertIn("Upload packet prepared", result.message)
        self.assertIn(str(packet_path), result.message)
        self.assertTrue(packet_exists)

    def test_send_draft_phrase_does_not_create_upload_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            artifacts_dir = Path(temp_dir) / "artifacts"
            _create_draft_job(db_path, Path(temp_dir), approved=True)

            result = handle_review_message(db_path, artifacts_dir, "Can you send me the draft?")
            status = get_upload_status(db_path)

        self.assertFalse(result.ok)
        self.assertIn("No active production job", result.message)
        self.assertEqual(status.recent_attempts, [])

    def test_latest_draft_candidate_uses_one_row_when_revision_duplicates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            job_id = _create_draft_job(db_path, Path(temp_dir), approved=False)
            second_draft_path = Path(temp_dir) / "draft-2.mp4"
            second_draft_path.write_bytes(b"newer duplicate revision")
            save_draft_artifact(
                db_path,
                job_id=job_id,
                revision=1,
                artifact_type="mp4",
                path=str(second_draft_path),
            )
            approve_active_review(db_path)

            status = get_upload_status(db_path)

        self.assertEqual(len(status.candidates), 1)
        self.assertEqual(status.candidates[0].draft.path, str(second_draft_path))


def _create_draft_job(db_path: Path, temp_dir: Path, approved: bool, with_script: bool = False) -> str:
    idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
    job = start_job(db_path, idea.id)
    if with_script:
        generated = generate_script(idea.prompt)
        save_video_script(
            db_path,
            job_id=job.id,
            script_json=generated.script_json,
            provider=generated.provider,
            confidence=generated.confidence,
            citations=generated.citations,
        )
    draft_path = temp_dir / "draft.mp4"
    draft_path.write_bytes(b"fake mp4 placeholder for upload tests")
    save_draft_artifact(
        db_path,
        job_id=job.id,
        revision=1,
        artifact_type="mp4",
        path=str(draft_path),
    )
    if approved:
        approve_active_review(db_path)
    return job.id


if __name__ == "__main__":
    unittest.main()
