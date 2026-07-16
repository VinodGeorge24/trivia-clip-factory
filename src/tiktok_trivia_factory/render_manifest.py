from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


PROVIDER = "manifest_v1"
MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_FORMATS = ("qa", "multiple_choice", "true_false", "fill_in_blank", "guess_image")
MVP_FORMAT = "qa"
WIDTH = 1080
HEIGHT = 1920
QUESTION_SECONDS = 5
ANSWER_SECONDS = 2
HOOK_SECONDS = 3


class ManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedManifest:
    manifest_json: str
    provider: str


def build_render_manifest(script_json: str, watermark_text: str = "Trivia Clip Factory") -> GeneratedManifest:
    script = json.loads(script_json)
    questions = script.get("questions", [])
    if not questions:
        raise ManifestError("Script has no questions to render")

    scenes: list[dict[str, Any]] = [
        {
            "id": "hook",
            "type": "hook",
            "format": MVP_FORMAT,
            "start_seconds": 0,
            "duration_seconds": HOOK_SECONDS,
            "layout": "centered_title",
            "text": script.get("hook", "Trivia challenge. Keep score."),
            "voiceover": script.get("hook", ""),
            "pacing": {"purpose": "open_loop", "keep_moving": True},
        }
    ]

    cursor = HOOK_SECONDS
    for index, question in enumerate(questions, start=1):
        question_id = str(question["id"])
        question_scene = {
            "id": f"{question_id}_question",
            "type": "question",
            "format": MVP_FORMAT,
            "question_id": question_id,
            "start_seconds": cursor,
            "duration_seconds": QUESTION_SECONDS,
            "layout": "question_countdown",
            "text": question["question"],
            "choices": question.get("choices", []),
            "correct_choice_label": question.get("correct_choice_label"),
            "voiceover": question.get("voiceover", ""),
            "countdown": {
                "enabled": True,
                "duration_seconds": QUESTION_SECONDS,
                "style": "large_numeric",
                "starts_at": QUESTION_SECONDS,
                "ends_at": 1,
            },
            "sound_cues": [
                {
                    "id": f"{question_id}_tick",
                    "type": "ticking",
                    "enabled": True,
                    "start_offset_seconds": 0,
                    "duration_seconds": QUESTION_SECONDS,
                }
            ],
            "pacing": {
                "sequence": index,
                "phase": "guess",
                "viewer_task": "answer_before_reveal",
            },
        }
        scenes.append(question_scene)
        cursor += QUESTION_SECONDS

        answer_scene = {
            "id": f"{question_id}_answer",
            "type": "answer_reveal",
            "format": MVP_FORMAT,
            "question_id": question_id,
            "start_seconds": cursor,
            "duration_seconds": ANSWER_SECONDS,
            "layout": "answer_reveal",
            "question_text": question["question"],
            "text": question["answer"],
            "choices": question.get("choices", []),
            "correct_choice_label": question.get("correct_choice_label"),
            "secondary_text": question.get("explanation", ""),
            "voiceover": f"Answer: {question['answer']}. {question.get('explanation', '')}".strip(),
            "sound_cues": [
                {
                    "id": f"{question_id}_ding",
                    "type": "ding",
                    "enabled": True,
                    "start_offset_seconds": 0,
                    "duration_seconds": 1,
                }
            ],
            "pacing": {
                "sequence": index,
                "phase": "reveal",
                "immediate_after_countdown": True,
            },
        }
        scenes.append(answer_scene)
        cursor += ANSWER_SECONDS

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "provider": PROVIDER,
        "source_script": {
            "schema_version": script.get("schema_version"),
            "provider": script.get("provider"),
            "topic": script.get("topic"),
        },
        "video": {
            "orientation": "vertical",
            "aspect_ratio": "9:16",
            "width": WIDTH,
            "height": HEIGHT,
            "fps": 30,
            "duration_seconds": cursor,
        },
        "format": {
            "selected": MVP_FORMAT,
            "supported": list(SUPPORTED_FORMATS),
            "future_supported": ["multiple_choice", "true_false", "fill_in_blank", "guess_image"],
        },
        "style": {
            "watermark": {"text": watermark_text, "position": "bottom_center"},
            "text_scale": "large_mobile_readable",
            "question_text": {"max_lines": 5, "position": "upper_middle"},
            "answer_text": {"max_lines": 3, "position": "center"},
            "countdown": {"position": "lower_middle", "size": "extra_large"},
            "background": {"type": "solid_or_gradient", "safe_for_text": True},
        },
        "audio": {
            "background_music": {"enabled": True, "source": "procedural_game_show_loop", "volume": 0.1},
            "voiceover": {"enabled": True, "source": "scene_voiceover_text"},
            "countdown_tick": {"enabled": True, "source": "procedural_tick", "optional": True},
            "answer_ding": {"enabled": True, "source": "procedural_ding", "optional": True},
        },
        "scenes": scenes,
        "export": {
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "intended_platform": "tiktok",
        },
    }
    return GeneratedManifest(
        manifest_json=json.dumps(payload, indent=2, sort_keys=True),
        provider=PROVIDER,
    )
