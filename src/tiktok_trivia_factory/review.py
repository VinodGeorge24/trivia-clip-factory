from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ApprovalEvent, DraftArtifact, ProductionJob, RenderManifest, RevisionEvent
from .renderer import render_manifest_to_mp4
from .repository import (
    get_active_job,
    get_latest_approval_event,
    get_latest_draft_artifact,
    get_latest_render_manifest,
    save_approval_event,
    save_draft_artifact,
    save_render_manifest,
    save_revision_event,
)


class ReviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReviewSummary:
    job: ProductionJob
    manifest: RenderManifest | None
    draft: DraftArtifact | None
    approval: ApprovalEvent | None


@dataclass(frozen=True)
class RevisionResult:
    event: RevisionEvent
    manifest: RenderManifest
    draft: DraftArtifact
    applied_changes: list[str]


def get_active_review_summary(db_path: Path) -> ReviewSummary:
    job = get_active_job(db_path)
    if job is None:
        raise ReviewError("No active production job")
    return get_review_summary(db_path, job.id)


def get_review_summary(db_path: Path, job_id: str) -> ReviewSummary:
    # A missing active job is acceptable when reviewing an already approved job
    job = get_active_job(db_path)
    if job is None or job.id != job_id:
        raise ReviewError("Review currently supports the active job only")
    return ReviewSummary(
        job=job,
        manifest=get_latest_render_manifest(db_path, job_id),
        draft=get_latest_draft_artifact(db_path, job_id),
        approval=get_latest_approval_event(db_path, job_id),
    )


def approve_active_review(db_path: Path) -> ApprovalEvent:
    summary = get_active_review_summary(db_path)
    if summary.draft is None:
        raise ReviewError("Cannot approve before an MP4 draft exists")
    return save_approval_event(db_path, summary.job.id, "approved")


def reject_active_review(db_path: Path) -> ApprovalEvent:
    summary = get_active_review_summary(db_path)
    return save_approval_event(db_path, summary.job.id, "rejected")


def revise_active_review(
    db_path: Path,
    artifacts_dir: Path,
    requested_change: str,
    preview: bool = True,
    voiceover_provider: str = "none",
) -> RevisionResult:
    summary = get_active_review_summary(db_path)
    if summary.manifest is None:
        raise ReviewError("Cannot revise before a render manifest exists")

    event = save_revision_event(db_path, summary.job.id, requested_change)
    manifest_payload = json.loads(summary.manifest.manifest_json)
    applied = _apply_manifest_revision(manifest_payload, requested_change)
    if not applied:
        raise ReviewError("Revision request was recorded but no supported manifest change was found")

    saved_manifest = save_render_manifest(
        db_path,
        job_id=summary.job.id,
        manifest_json=json.dumps(manifest_payload, indent=2, sort_keys=True),
        provider=summary.manifest.provider,
    )
    output_path = artifacts_dir / summary.job.id / f"draft_r{saved_manifest.revision:03d}.mp4"
    render_manifest_to_mp4(
        saved_manifest.manifest_json,
        output_path,
        preview=preview,
        voiceover_provider=voiceover_provider,
    )
    draft = save_draft_artifact(
        db_path,
        job_id=summary.job.id,
        revision=saved_manifest.revision,
        artifact_type="mp4",
        path=str(output_path),
    )
    return RevisionResult(event=event, manifest=saved_manifest, draft=draft, applied_changes=applied)


def _apply_manifest_revision(manifest: dict[str, object], requested_change: str) -> list[str]:
    text = requested_change.strip()
    normalized = text.lower()
    applied: list[str] = []

    if any(phrase in normalized for phrase in ("faster", "shorter", "shorten")):
        for scene in manifest.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            if scene.get("type") == "question":
                scene["duration_seconds"] = 3
                countdown = scene.get("countdown")
                if isinstance(countdown, dict):
                    countdown["duration_seconds"] = 3
                    countdown["starts_at"] = 3
                for cue in scene.get("sound_cues", []):
                    if isinstance(cue, dict) and cue.get("type") == "ticking":
                        cue["duration_seconds"] = 3
            elif scene.get("type") == "answer_reveal":
                scene["duration_seconds"] = 1.5
        _reflow_scene_start_times(manifest)
        applied.append("shortened question countdowns and answer linger")

    hook_match = re.search(r"(?:change|make|set)\s+(?:the\s+)?hook\s+(?:to|as)\s+(.+)", text, flags=re.IGNORECASE)
    if hook_match:
        hook_text = hook_match.group(1).strip().strip('"')
        for scene in manifest.get("scenes", []):
            if isinstance(scene, dict) and scene.get("type") == "hook":
                scene["text"] = hook_text
                scene["voiceover"] = hook_text
                applied.append("updated hook text")
                break

    background_match = re.search(r"(?:background|bg).*(blue|green|black|gold|yellow)", normalized)
    if background_match:
        color = background_match.group(1)
        color_map = {
            "blue": "#002060",
            "green": "#004225",
            "black": "#000000",
            "gold": "#6B5200",
            "yellow": "#6B5200",
        }
        style = manifest.setdefault("style", {})
        if isinstance(style, dict):
            background = style.setdefault("background", {})
            if isinstance(background, dict):
                background["color"] = color_map[color]
                applied.append(f"updated background color to {color}")

    return applied


def _reflow_scene_start_times(manifest: dict[str, object]) -> None:
    cursor = 0.0
    scenes = manifest.get("scenes", [])
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene["start_seconds"] = cursor
        cursor += float(scene.get("duration_seconds", 0))
    video = manifest.get("video")
    if isinstance(video, dict):
        video["duration_seconds"] = cursor
