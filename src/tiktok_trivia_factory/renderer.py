from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from textwrap import wrap
from typing import Any

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

from .audio import write_procedural_audio


RENDERER_NAME = "pillow_ffmpeg_v1"
PREVIEW_FPS = 12
FULL_FPS = 30
BACKGROUND = "#002060"
GOLD = "#FFCC00"
WHITE = "#FFFFFF"
BLACK = "#000000"
GREEN = "#00AA33"


class RenderError(RuntimeError):
    pass


def render_manifest_to_mp4(
    manifest_json: str,
    output_path: Path,
    preview: bool = False,
    voiceover_provider: str = "none",
) -> Path:
    manifest = json.loads(manifest_json)
    video = manifest["video"]
    width = int(video["width"])
    height = int(video["height"])
    fps = PREVIEW_FPS if preview else int(video.get("fps", FULL_FPS))
    scenes = manifest.get("scenes", [])
    if not scenes:
        raise RenderError("Manifest has no scenes")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        audio_path = write_procedural_audio(
            manifest_json,
            Path(temp_dir) / "audio.wav",
            voiceover_provider=voiceover_provider,
            voiceover_dir=Path(temp_dir) / "voiceover",
        )
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        command = [
            ffmpeg_exe,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-i",
            str(audio_path),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None
        try:
            for scene in scenes:
                frame_count = max(1, round(float(scene["duration_seconds"]) * fps))
                for frame_index in range(frame_count):
                    elapsed = frame_index / fps
                    frame = _draw_scene(scene, manifest, width, height, elapsed)
                    process.stdin.write(frame.tobytes())
        except BrokenPipeError as error:
            raise RenderError("FFmpeg stopped accepting frames") from error
        finally:
            process.stdin.close()

        stdout, stderr = process.communicate()
    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        stdout_text = stdout.decode("utf-8", errors="replace")
        raise RenderError(f"FFmpeg failed with code {process.returncode}: {stderr_text or stdout_text}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RenderError(f"Renderer did not create a non-empty MP4: {output_path}")
    return output_path


def _draw_scene(
    scene: dict[str, Any],
    manifest: dict[str, Any],
    width: int,
    height: int,
    elapsed: float,
) -> Image.Image:
    background = manifest.get("style", {}).get("background", {})
    background_color = background.get("color", BACKGROUND) if isinstance(background, dict) else BACKGROUND
    image = Image.new("RGB", (width, height), background_color)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    scene_type = scene["type"]

    _draw_header(draw, width, scene)
    if scene_type == "hook":
        _draw_center_card(draw, width, height, scene["text"], fonts["title"], GOLD)
    elif scene_type == "question":
        _draw_question(draw, width, scene["text"], fonts)
        _draw_visual_hook(draw, width, scene, manifest, fonts)
        _draw_countdown(draw, width, scene, elapsed, fonts)
        _draw_options(draw, width, scene, fonts, reveal=False)
    elif scene_type == "answer_reveal":
        _draw_question(draw, width, scene.get("question_text", ""), fonts)
        _draw_visual_hook(draw, width, scene, manifest, fonts)
        _draw_options(draw, width, scene, fonts, reveal=True)
    else:
        _draw_center_card(draw, width, height, scene.get("text", scene_type), fonts["title"], WHITE)

    watermark_text = manifest.get("style", {}).get("watermark", {}).get("text", "Trivia Clip Factory")
    _draw_watermark(draw, width, height, fonts, watermark_text)
    return image


def _fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    return {
        "title": _font(72),
        "question": _font(54),
        "option": _font(48),
        "option_small": _font(40),
        "option_tiny": _font(32),
        "countdown": _font(120),
        "small": _font(34),
    }


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_header(draw: ImageDraw.ImageDraw, width: int, scene: dict[str, Any]) -> None:
    sequence = scene.get("pacing", {}).get("sequence")
    label = str(sequence if sequence is not None else "GO")
    draw.ellipse((465, 100, 615, 250), fill=BLACK, outline=WHITE, width=5)
    draw.text((540, 175), label, fill=WHITE, font=_font(58), anchor="mm")


def _draw_question(draw: ImageDraw.ImageDraw, width: int, text: str, fonts: dict[str, Any]) -> None:
    box = (60, 280, width - 60, 500)
    draw.rounded_rectangle(box, radius=18, fill=(0, 0, 0, 130), outline=GOLD, width=6)
    _draw_wrapped_center(draw, text.upper(), box, fonts["question"], WHITE, max_chars=28)


def _draw_visual_hook(
    draw: ImageDraw.ImageDraw,
    width: int,
    scene: dict[str, Any],
    manifest: dict[str, Any],
    fonts: dict[str, Any],
) -> None:
    box = (90, 530, width - 90, 1100)
    draw.rounded_rectangle(box, radius=15, fill=(255, 255, 255, 32), outline=(255, 255, 255, 110), width=3)
    topic = manifest.get("source_script", {}).get("topic", "Trivia")
    scene_label = "THINK FAST" if scene["type"] == "question" else "ANSWER"
    draw.text((width // 2, 725), topic.upper(), fill=GOLD, font=fonts["title"], anchor="mm")
    draw.text((width // 2, 845), scene_label, fill=WHITE, font=fonts["question"], anchor="mm")


def _draw_countdown(draw: ImageDraw.ImageDraw, width: int, scene: dict[str, Any], elapsed: float, fonts: dict[str, Any]) -> None:
    countdown = scene.get("countdown", {})
    if not countdown.get("enabled"):
        return
    remaining = max(1, int(countdown["duration_seconds"] - elapsed))
    draw.ellipse((430, 930, 650, 1150), fill=BLACK, outline=GOLD, width=8)
    draw.text((540, 1040), str(remaining), fill=GOLD, font=fonts["countdown"], anchor="mm")


def _draw_options(draw: ImageDraw.ImageDraw, width: int, scene: dict[str, Any], fonts: dict[str, Any], reveal: bool) -> None:
    choices = _normalized_choices(scene)
    correct_label = scene.get("correct_choice_label")
    for index, y in enumerate((1150, 1300, 1450)):
        choice = choices[index]
        is_correct = reveal and choice["label"] == correct_label
        box = (90, y, width - 90, y + 110)
        fill = GREEN if is_correct else WHITE
        text_fill = WHITE if is_correct else BLACK
        draw.rounded_rectangle(box, radius=16, fill=fill)
        draw.text((130, y + 55), str(choice["label"]), fill=text_fill, font=fonts["option"], anchor="lm")
        _draw_option_text(draw, str(choice["text"]), (190, y + 12, width - 120, y + 98), fonts, text_fill)


def _normalized_choices(scene: dict[str, Any]) -> list[dict[str, str]]:
    raw_choices = scene.get("choices", [])
    if isinstance(raw_choices, list) and len(raw_choices) >= 3:
        choices = []
        for fallback_label, choice in zip(("A", "B", "C"), raw_choices[:3], strict=True):
            if isinstance(choice, dict):
                choices.append(
                    {
                        "label": str(choice.get("label", fallback_label)),
                        "text": str(choice.get("text", "")),
                    }
                )
            else:
                choices.append({"label": fallback_label, "text": str(choice)})
        return choices
    return [
        {"label": "A", "text": "Option A"},
        {"label": "B", "text": str(scene.get("text", "Answer"))},
        {"label": "C", "text": "Option C"},
    ]


def _draw_option_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    fonts: dict[str, Any],
    fill: str,
) -> None:
    if len(text) <= 24:
        font = fonts["option"]
        max_chars = 24
    elif len(text) <= 42:
        font = fonts["option_small"]
        max_chars = 30
    else:
        font = fonts["option_tiny"]
        max_chars = 34
    _draw_wrapped_center(draw, text, box, font, fill, max_chars=max_chars)


def _draw_center_card(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
) -> None:
    box = (90, 520, width - 90, height - 520)
    draw.rounded_rectangle(box, radius=24, fill=(0, 0, 0, 125), outline=GOLD, width=6)
    _draw_wrapped_center(draw, text.upper(), box, font, fill, max_chars=18)


def _draw_watermark(draw: ImageDraw.ImageDraw, width: int, height: int, fonts: dict[str, Any], text: str) -> None:
    draw.text((width // 2, height - 105), text, fill=(255, 255, 255, 135), font=fonts["small"], anchor="mm")


def _draw_wrapped_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    max_chars: int,
) -> None:
    lines = wrap(text, width=max_chars) or [text]
    line_height = font.size + 8 if hasattr(font, "size") else 24
    total_height = line_height * len(lines)
    y = box[1] + ((box[3] - box[1] - total_height) / 2)
    x = (box[0] + box[2]) / 2
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font, anchor="ma")
        y += line_height
