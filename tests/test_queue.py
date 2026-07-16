from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.repository import (
    ActiveJobExistsError,
    add_idea,
    cancel_active_job,
    clear_ideas,
    discard_active_job,
    get_active_job,
    get_idea,
    list_ideas,
    start_job,
)


class QueueTests(unittest.TestCase):
    def test_add_and_list_ideas_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            first = add_idea(db_path, "10 trivia questions about Led Zeppelin")
            second = add_idea(db_path, "10 trivia questions about FIFA World Cup")

            ideas = list_ideas(db_path)

        self.assertEqual([idea.id for idea in ideas], [first.id, second.id])
        self.assertEqual(ideas[0].status, "queued")
        self.assertEqual(ideas[1].prompt, "10 trivia questions about FIFA World Cup")

    def test_only_one_active_job_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            first = add_idea(db_path, "10 trivia questions about Led Zeppelin")
            second = add_idea(db_path, "10 trivia questions about FIFA World Cup")

            first_job = start_job(db_path, first.id)
            active = get_active_job(db_path)

            with self.assertRaises(ActiveJobExistsError):
                start_job(db_path, second.id)

        self.assertIsNotNone(active)
        self.assertEqual(active.id, first_job.id)

    def test_cancel_active_job_returns_idea_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about 6th grade science")
            start_job(db_path, idea.id)

            cancelled = cancel_active_job(db_path)
            active = get_active_job(db_path)
            queued = list_ideas(db_path, status="queued")

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(active)
        self.assertEqual([item.id for item in queued], [idea.id])

    def test_discard_active_job_does_not_requeue_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
            start_job(db_path, idea.id)

            discarded = discard_active_job(db_path)
            active = get_active_job(db_path)
            queued = list_ideas(db_path, status="queued")
            updated_idea = get_idea(db_path, idea.id)

        self.assertEqual(discarded.status, "cancelled")
        self.assertIsNone(active)
        self.assertEqual(queued, [])
        self.assertEqual(updated_idea.status, "cancelled")

    def test_clear_ideas_all_clears_active_and_queued_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            active_idea = add_idea(db_path, "10 trivia questions about FIFA World Cup")
            queued_idea = add_idea(db_path, "10 trivia questions about 6th grade science")
            start_job(db_path, active_idea.id)

            result = clear_ideas(db_path, "all")
            active = get_active_job(db_path)
            queued = list_ideas(db_path, status="queued")
            cancelled = list_ideas(db_path, status="cancelled")

        self.assertEqual(result.scope, "all")
        self.assertEqual(result.active_jobs_cancelled, 1)
        self.assertEqual(result.ideas_cleared, 2)
        self.assertIsNone(active)
        self.assertEqual(queued, [])
        self.assertEqual({idea.id for idea in cancelled}, {active_idea.id, queued_idea.id})


if __name__ == "__main__":
    unittest.main()
