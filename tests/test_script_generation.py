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
from tiktok_trivia_factory.trivia_bank import consume_bank_topic, find_matching_bank_topic


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
            trivia_bank_path=Path("__missing_trivia_bank__"),
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
            trivia_bank_path=Path("__missing_trivia_bank__"),
        )
        payload = json.loads(generated.script_json)

        self.assertEqual(payload["provider"], "research_opentdb")
        self.assertEqual(payload["topic"], "Sports Trivia")
        self.assertEqual(len(payload["questions"]), 2)
        self.assertEqual(payload["questions"][0]["answer"], "Basketball")
        self.assertEqual(len(payload["questions"][0]["choices"]), 3)
        self.assertEqual(generated.citations[0].source_type, "opentdb_api")

    def test_generate_script_uses_matching_trivia_bank_topic_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bank_path = Path(temp_dir) / "trivia_bank.txt"
            bank_path.write_text(_sample_trivia_bank(), encoding="utf-8")

            generated = generate_script(
                "2 trivia questions about Minecraft mobs",
                trivia_bank_path=bank_path,
            )
            payload = json.loads(generated.script_json)

        self.assertEqual(payload["provider"], "local_trivia_bank")
        self.assertEqual(payload["generation_mode"], "local_trivia_bank")
        self.assertEqual(payload["topic"], "Minecraft Mobs")
        self.assertEqual(payload["questions"][0]["question"], "Which mob explodes when it gets close to the player?")
        self.assertEqual(payload["questions"][0]["answer"], "Creeper")
        self.assertEqual(payload["questions"][1]["correct_choice_label"], "B")
        self.assertEqual(generated.citations[0].source_type, "local_trivia_bank")

    def test_consumed_trivia_bank_topic_moves_to_used_file_and_stops_matching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bank_path = Path(temp_dir) / "trivia_bank.txt"
            bank_path.write_text(_sample_trivia_bank(), encoding="utf-8")
            topic = find_matching_bank_topic("Minecraft mobs trivia", bank_path)
            if topic is None:
                raise AssertionError("Expected matching bank topic")

            consumed = consume_bank_topic(topic, job_id="job_test123456", prompt="Minecraft mobs trivia")
            source_text = bank_path.read_text(encoding="utf-8")
            used_text = consumed.used_path.read_text(encoding="utf-8")
            rematch = find_matching_bank_topic("Minecraft mobs trivia", bank_path)

        self.assertNotIn("001. [Gaming - Minecraft Mobs]", source_text)
        self.assertIn("001. [Gaming - Minecraft Mobs]", used_text)
        self.assertIn("# Job: job_test123456", used_text)
        self.assertIn("Which mob explodes when it gets close to the player?", used_text)
        self.assertIsNone(rematch)

    def test_trivia_bank_matching_rejects_wrong_era_after_topic_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bank_path = Path(temp_dir) / "trivia_bank.txt"
            bank_path.write_text(_sample_era_bank(), encoding="utf-8")
            topic = find_matching_bank_topic("NFL Super Bowl Winners 2010s trivia", bank_path)
            if topic is None:
                raise AssertionError("Expected matching 2010s bank topic")

            consume_bank_topic(topic, job_id="job_test123456", prompt="NFL Super Bowl Winners 2010s trivia")
            rematch = find_matching_bank_topic("NFL Super Bowl Winners 2010s trivia", bank_path)

        self.assertEqual(topic.heading, "085. [Sports - NFL Super Bowl Winners (2010s)]")
        self.assertIsNone(rematch)

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


def _sample_era_bank() -> str:
    return """084. [Sports - NFL Super Bowl Winners (2000s)]
Question:
Which team won Super Bowl XLIII?
A. Pittsburgh Steelers
B. New York Giants
C. Indianapolis Colts
Answer: A. Pittsburgh Steelers

Question:
Which Giants receiver caught the helmet catch?
A. David Tyree
B. Plaxico Burress
C. Amani Toomer
Answer: A. David Tyree

085. [Sports - NFL Super Bowl Winners (2010s)]
Question:
Which team beat the Seahawks after Malcolm Butler's goal-line interception?
A. New England Patriots
B. Denver Broncos
C. Atlanta Falcons
Answer: A. New England Patriots

Question:
Which Saints quarterback was named MVP of Super Bowl XLIV?
A. Drew Brees
B. Peyton Manning
C. Reggie Bush
Answer: A. Drew Brees
"""


if __name__ == "__main__":
    unittest.main()
