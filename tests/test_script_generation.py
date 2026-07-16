from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.repository import (
    add_idea,
    get_latest_video_script,
    list_source_citations,
    save_video_script,
    start_job,
)
from tiktok_trivia_factory.script_generator import UnsupportedTopicError, generate_script


class ScriptGenerationTests(unittest.TestCase):
    def test_generate_world_cup_script_shape(self) -> None:
        generated = generate_script("10 trivia questions about the FIFA World Cup")
        payload = json.loads(generated.script_json)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["provider"], "local_seed")
        self.assertEqual(payload["topic"], "FIFA World Cup")
        self.assertEqual(len(payload["questions"]), 10)
        self.assertEqual(payload["questions"][0]["answer"], "Uruguay")
        self.assertEqual(payload["questions"][0]["answer_type"], "country")
        self.assertEqual(len(payload["questions"][0]["choices"]), 3)
        self.assertEqual(payload["questions"][0]["correct_choice_label"], "A")
        self.assertIn(
            {"label": "A", "text": "Uruguay", "is_correct": True},
            payload["questions"][0]["choices"],
        )
        self.assertIn(
            {"label": "B", "text": "South Korea and Japan", "is_correct": True},
            payload["questions"][4]["choices"],
        )
        self.assertEqual(
            _choice_texts(payload["questions"][4]),
            {"South Korea and Japan", "China and Russia", "USA and Canada"},
        )
        self.assertFalse(payload["metadata"]["needs_external_research"])
        self.assertEqual(generated.citations[0].source_type, "curated_seed")

    def test_distractors_match_answer_type(self) -> None:
        generated = generate_script("10 trivia questions about 6th grade science", question_count=2)
        payload = json.loads(generated.script_json)

        planet_question = payload["questions"][0]
        gas_question = payload["questions"][1]

        self.assertEqual(planet_question["answer_type"], "planet")
        self.assertEqual(len(_choice_texts(planet_question)), 3)
        self.assertIn("Mars", _choice_texts(planet_question))
        self.assertTrue(_choice_texts(planet_question).issubset({"Mars", "Venus", "Jupiter", "Mercury", "Saturn", "Neptune"}))
        self.assertEqual(gas_question["answer_type"], "gas")
        self.assertEqual(len(_choice_texts(gas_question)), 3)
        self.assertIn("Carbon dioxide", _choice_texts(gas_question))
        self.assertTrue(_choice_texts(gas_question).issubset({"Carbon dioxide", "Oxygen", "Nitrogen", "Hydrogen", "Helium", "Methane"}))

    def test_unsupported_topic_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedTopicError):
            generate_script("10 trivia questions about a topic not in the local seed bank")

    def test_generate_research_script_uses_wikimedia_for_nba_finals(self) -> None:
        generated = generate_script(
            "6 trivia questions about NBA Finals statistics",
            fetch_json=_fake_wikimedia_fetch,
        )
        payload = json.loads(generated.script_json)

        self.assertEqual(payload["provider"], "research_wikipedia")
        self.assertEqual(payload["generation_mode"], "free_research")
        self.assertEqual(payload["topic"], "NBA Finals")
        self.assertTrue(payload["metadata"]["needs_external_research"])
        self.assertIn("codex_web_search", payload["metadata"]["provider_chain"])
        self.assertIn("gemini_web_search", payload["metadata"]["provider_chain"])
        self.assertGreaterEqual(len(payload["questions"]), 5)
        self.assertIn("The Larry O'Brien Championship Trophy", _answers(payload))
        self.assertEqual(generated.citations[0].source_type, "wikimedia_api")

    def test_research_script_falls_back_to_open_trivia_db(self) -> None:
        generated = generate_script(
            "3 trivia questions about basketball",
            fetch_json=_fake_wikimedia_failure_then_opentdb,
        )
        payload = json.loads(generated.script_json)

        self.assertEqual(payload["provider"], "research_opentdb")
        self.assertEqual(payload["topic"], "Sports Trivia")
        self.assertEqual(len(payload["questions"]), 2)
        self.assertEqual(payload["questions"][0]["answer"], "Basketball")
        self.assertEqual(len(payload["questions"][0]["choices"]), 3)
        self.assertEqual(generated.citations[0].source_type, "opentdb_api")

    def test_save_script_and_citations_for_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            idea = add_idea(db_path, "10 trivia questions about 6th grade science")
            job = start_job(db_path, idea.id)
            generated = generate_script(idea.prompt)

            saved = save_video_script(
                db_path,
                job_id=job.id,
                script_json=generated.script_json,
                provider=generated.provider,
                confidence=generated.confidence,
                citations=generated.citations,
            )
            latest = get_latest_video_script(db_path, job.id)
            citations = list_source_citations(db_path, saved.id)

        self.assertIsNotNone(latest)
        self.assertEqual(latest.id, saved.id)
        self.assertEqual(latest.revision, 1)
        self.assertEqual(latest.provider, "local_seed")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].label, "curated_grade_science_seed_v1")

def _choice_texts(question: dict[str, object]) -> set[str]:
    choices = question["choices"]
    if not isinstance(choices, list):
        raise AssertionError("Expected choices list")
    return {str(choice["text"]) for choice in choices}


def _answers(payload: dict[str, object]) -> set[str]:
    questions = payload["questions"]
    if not isinstance(questions, list):
        raise AssertionError("Expected questions list")
    return {str(question["answer"]) for question in questions if isinstance(question, dict)}


def _fake_wikimedia_fetch(url: str) -> dict[str, object]:
    if "api/rest_v1/page/summary" in url:
        return {
            "extract": (
                "The NBA Finals is the annual championship series of the National Basketball Association (NBA)."
            )
        }
    if "w/api.php" in url:
        return {
            "query": {
                "pages": {
                    "1": {
                        "extract": (
                            "The series is contested between the Eastern and Western Conference champions. "
                            "It is a best-of-seven series. The winners receive the Larry O'Brien Championship Trophy. "
                            "The NBA Finals Most Valuable Player Award recognizes the top player. "
                            "The series was initially known as the BAA Finals."
                        )
                    }
                }
            }
        }
    raise AssertionError(f"Unexpected URL: {url}")


def _fake_wikimedia_failure_then_opentdb(url: str) -> dict[str, object]:
    if "wikipedia" in url:
        raise UnsupportedTopicError("simulated Wikimedia outage")
    if "opentdb.com" in url:
        return {
            "response_code": 0,
            "results": [
                {
                    "category": "Sports",
                    "type": "multiple",
                    "difficulty": "easy",
                    "question": "Which%20sport%20uses%20a%20jump%20ball%3F",
                    "correct_answer": "Basketball",
                    "incorrect_answers": ["Baseball", "Golf", "Tennis"],
                },
                {
                    "category": "Sports",
                    "type": "multiple",
                    "difficulty": "medium",
                    "question": "How%20many%20points%20is%20a%20free%20throw%20worth%3F",
                    "correct_answer": "One",
                    "incorrect_answers": ["Two", "Three", "Four"],
                },
            ],
        }
    raise AssertionError(f"Unexpected URL: {url}")


if __name__ == "__main__":
    unittest.main()
