from __future__ import annotations

import json
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from tiktok_trivia_factory.audio import SAMPLE_RATE, write_procedural_audio


class AudioTests(unittest.TestCase):
    def test_write_procedural_audio_creates_non_silent_wav(self) -> None:
        manifest = {
            "video": {"duration_seconds": 2},
            "audio": {
                "background_music": {"enabled": True},
                "countdown_tick": {"enabled": True},
                "answer_ding": {"enabled": True},
            },
            "scenes": [
                {
                    "start_seconds": 0,
                    "duration_seconds": 1,
                    "sound_cues": [
                        {"type": "ticking", "enabled": True, "start_offset_seconds": 0, "duration_seconds": 1},
                        {"type": "ding", "enabled": True, "start_offset_seconds": 1, "duration_seconds": 1},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = write_procedural_audio(json.dumps(manifest), Path(temp_dir) / "audio.wav")
            with wave.open(str(output_path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                audio_bytes = wav_file.readframes(frame_count)

        self.assertGreater(frame_count, 0)
        self.assertNotEqual(set(audio_bytes), {0})

    def test_write_procedural_audio_can_mix_scene_voiceover(self) -> None:
        manifest = {
            "video": {"duration_seconds": 1},
            "audio": {"background_music": {"enabled": False}},
            "scenes": [
                {
                    "id": "hook",
                    "start_seconds": 0,
                    "duration_seconds": 1,
                    "voiceover": "Hello trivia fans.",
                    "sound_cues": [],
                }
            ],
        }

        def fake_synthesizer(text: str, output_path: Path) -> Path:
            self.assertEqual(text, "Hello trivia fans.")
            samples = array("h", [16000] * int(0.2 * SAMPLE_RATE))
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(samples.tobytes())
            return output_path

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = write_procedural_audio(
                json.dumps(manifest),
                Path(temp_dir) / "audio.wav",
                voiceover_provider="windows_sapi",
                synthesize_voiceover=fake_synthesizer,
            )
            with wave.open(str(output_path), "rb") as wav_file:
                audio_bytes = wav_file.readframes(wav_file.getnframes())

        self.assertNotEqual(set(audio_bytes), {0})


if __name__ == "__main__":
    unittest.main()
