from __future__ import annotations

import json
import math
import platform
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any, Callable


SAMPLE_RATE = 44_100
MAX_INT16 = 32767
VoiceoverSynthesizer = Callable[[str, Path], Path]


class AudioRenderError(RuntimeError):
    pass


def write_procedural_audio(
    manifest_json: str,
    output_path: Path,
    voiceover_provider: str = "none",
    voiceover_dir: Path | None = None,
    synthesize_voiceover: VoiceoverSynthesizer | None = None,
) -> Path:
    manifest = json.loads(manifest_json)
    duration = float(manifest.get("video", {}).get("duration_seconds") or _duration_from_scenes(manifest.get("scenes", [])))
    total_samples = max(1, int(duration * SAMPLE_RATE))
    samples = [0.0] * total_samples

    audio_config = manifest.get("audio", {})
    if audio_config.get("background_music", {}).get("enabled", True):
        _mix_background(samples)

    for scene in manifest.get("scenes", []):
        scene_start = float(scene.get("start_seconds", 0))
        for cue in scene.get("sound_cues", []):
            if not cue.get("enabled", False):
                continue
            cue_start = scene_start + float(cue.get("start_offset_seconds", 0))
            cue_type = cue.get("type")
            if cue_type == "ticking":
                _mix_tick_loop(samples, cue_start, float(cue.get("duration_seconds", 5)))
            elif cue_type == "ding":
                _mix_ding(samples, cue_start)

    _mix_voiceovers(
        samples=samples,
        scenes=manifest.get("scenes", []),
        provider=voiceover_provider,
        voiceover_dir=voiceover_dir or output_path.parent / "voiceover",
        synthesize_voiceover=synthesize_voiceover,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array("h", (_clamp_to_int16(value) for value in samples))
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return output_path


def _mix_background(samples: list[float]) -> None:
    notes = (261.63, 329.63, 392.00, 523.25)
    note_length = int(0.35 * SAMPLE_RATE)
    for index in range(len(samples)):
        note = notes[(index // note_length) % len(notes)]
        envelope = 0.5 + 0.5 * math.sin(2 * math.pi * (index % note_length) / note_length)
        samples[index] += 0.035 * envelope * math.sin(2 * math.pi * note * index / SAMPLE_RATE)


def _mix_tick_loop(samples: list[float], start_seconds: float, duration_seconds: float) -> None:
    tick_count = max(1, int(duration_seconds))
    for offset in range(tick_count):
        _mix_click(samples, start_seconds + offset, frequency=1200.0, amplitude=0.35)


def _mix_click(samples: list[float], start_seconds: float, frequency: float, amplitude: float) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    length = int(0.08 * SAMPLE_RATE)
    for i in range(length):
        target = start + i
        if 0 <= target < len(samples):
            decay = 1.0 - (i / length)
            samples[target] += amplitude * decay * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE)


def _mix_ding(samples: list[float], start_seconds: float) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    length = int(0.75 * SAMPLE_RATE)
    for i in range(length):
        target = start + i
        if 0 <= target < len(samples):
            decay = math.exp(-4 * i / length)
            tone = (
                0.45 * math.sin(2 * math.pi * 880.0 * i / SAMPLE_RATE)
                + 0.25 * math.sin(2 * math.pi * 1320.0 * i / SAMPLE_RATE)
            )
            samples[target] += decay * tone


def _mix_voiceovers(
    samples: list[float],
    scenes: list[dict[str, Any]],
    provider: str,
    voiceover_dir: Path,
    synthesize_voiceover: VoiceoverSynthesizer | None,
) -> None:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "none":
        return
    if normalized_provider != "windows_sapi":
        raise AudioRenderError(f"Unsupported voiceover provider: {provider}")

    synthesize = synthesize_voiceover or _synthesize_windows_sapi
    voiceover_dir.mkdir(parents=True, exist_ok=True)
    for index, scene in enumerate(scenes):
        text = str(scene.get("voiceover", "")).strip()
        if not text:
            continue
        voice_path = voiceover_dir / f"{index:03d}_{scene.get('id', 'scene')}.wav"
        synthesize(text, voice_path)
        voice_samples = _read_pcm16_mono_wav(voice_path)
        _mix_samples_at(samples, voice_samples, float(scene.get("start_seconds", 0)), volume=0.85)


def _synthesize_windows_sapi(text: str, output_path: Path) -> Path:
    if platform.system() != "Windows":
        raise AudioRenderError("windows_sapi voiceover provider is only available on Windows")

    script = r"""
param([string]$Text, [string]$OutputPath)
Add-Type -AssemblyName System.Speech
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
  44100,
  [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
  [System.Speech.AudioFormat.AudioChannel]::Mono
)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 1
$synth.Volume = 100
$synth.SetOutputToWaveFile($OutputPath, $format)
$synth.Speak($Text)
$synth.Dispose()
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ps1", delete=False) as script_file:
        script_file.write(script)
        script_path = Path(script_file.name)
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                text,
                str(output_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "PowerShell speech synthesis failed"
        raise AudioRenderError(detail)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AudioRenderError(f"Voiceover provider did not create audio: {output_path}")
    return output_path


def _read_pcm16_mono_wav(path: Path) -> list[float]:
    with wave.open(str(path), "rb") as wav_file:
        channel_count = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        frames = wav_file.readframes(frame_count)

    if sample_width != 2:
        raise AudioRenderError(f"Unsupported voiceover sample width: {sample_width}")
    if frame_rate != SAMPLE_RATE:
        raise AudioRenderError(f"Unsupported voiceover sample rate: {frame_rate}")
    if channel_count < 1:
        raise AudioRenderError("Voiceover WAV has no channels")

    pcm = array("h")
    pcm.frombytes(frames)
    if channel_count == 1:
        return [sample / MAX_INT16 for sample in pcm]

    mixed: list[float] = []
    for index in range(0, len(pcm), channel_count):
        frame = pcm[index : index + channel_count]
        mixed.append(sum(frame) / (len(frame) * MAX_INT16))
    return mixed


def _mix_samples_at(samples: list[float], overlay: list[float], start_seconds: float, volume: float) -> None:
    start = int(start_seconds * SAMPLE_RATE)
    for index, value in enumerate(overlay):
        target = start + index
        if 0 <= target < len(samples):
            samples[target] += value * volume


def _clamp_to_int16(value: float) -> int:
    return int(max(-1.0, min(1.0, value)) * MAX_INT16)


def _duration_from_scenes(scenes: list[dict[str, Any]]) -> float:
    duration = 0.0
    for scene in scenes:
        end_time = float(scene.get("start_seconds", duration)) + float(scene.get("duration_seconds", 0))
        duration = max(duration, end_time)
    return max(0.1, duration)
