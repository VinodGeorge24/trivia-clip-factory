from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import Settings, load_settings
from .database import initialize_database, probe_database
from .logging_config import configure_logging
from .models import (
    ApprovalEvent,
    DraftArtifact,
    Idea,
    ProductionJob,
    RenderManifest,
    RevisionEvent,
    SourceCitation,
    UploadAttempt,
    VideoScript,
)
from .paths import ensure_runtime_directories
from .repository import (
    ActiveJobExistsError,
    IdeaNotFoundError,
    NoActiveJobError,
    add_idea,
    cancel_active_job,
    get_active_job,
    get_idea,
    get_latest_draft_artifact,
    get_latest_render_manifest,
    get_latest_video_script,
    list_ideas,
    list_source_citations,
    save_draft_artifact,
    save_render_manifest,
    save_video_script,
    start_job,
)
from .render_manifest import ManifestError, build_render_manifest
from .renderer import RenderError, render_manifest_to_mp4
from .review import (
    ReviewError,
    ReviewSummary,
    approve_active_review,
    get_active_review_summary,
    reject_active_review,
    revise_active_review,
)
from .script_generator import UnsupportedTopicError, generate_script
from .telegram_adapter import handle_review_message
from .tiktok_api import (
    TikTokApiError,
    create_oauth_session,
    exchange_authorization_code,
    load_oauth_session,
    load_tiktok_credentials,
    load_tokens_if_present,
    refresh_access_token,
    run_oauth_callback_server,
    save_oauth_session,
    save_tokens,
    token_status_payload,
)
from .uploads import (
    UploadError,
    check_tiktok_upload_status,
    get_upload_status,
    mark_upload_failed,
    mark_upload_succeeded,
    prepare_upload_packet,
    send_approved_draft_to_tiktok,
    start_upload_handoff,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_logging(settings.log_level)

    if args.command == "status":
        return run_status(settings)
    if args.command == "db" and args.db_command == "init":
        return run_db_init(settings)
    if args.command == "ideas" and args.ideas_command == "add":
        return run_ideas_add(settings, args.prompt, args.source, args.notes)
    if args.command == "ideas" and args.ideas_command == "list":
        return run_ideas_list(settings, args.status)
    if args.command == "jobs" and args.jobs_command == "start":
        return run_jobs_start(settings, args.idea_id)
    if args.command == "jobs" and args.jobs_command == "active":
        return run_jobs_active(settings)
    if args.command == "jobs" and args.jobs_command == "cancel-active":
        return run_jobs_cancel_active(settings)
    if args.command == "scripts" and args.scripts_command == "generate":
        return run_scripts_generate(settings, args.count, args.duration_seconds)
    if args.command == "scripts" and args.scripts_command == "show":
        return run_scripts_show(settings, args.job_id)
    if args.command == "manifests" and args.manifests_command == "generate":
        return run_manifests_generate(settings, args.job_id)
    if args.command == "manifests" and args.manifests_command == "show":
        return run_manifests_show(settings, args.job_id)
    if args.command == "drafts" and args.drafts_command == "render":
        return run_drafts_render(settings, args.job_id, args.output, args.preview)
    if args.command == "drafts" and args.drafts_command == "show":
        return run_drafts_show(settings, args.job_id)
    if args.command == "reviews" and args.reviews_command == "show":
        return run_reviews_show(settings)
    if args.command == "reviews" and args.reviews_command == "approve":
        return run_reviews_approve(settings)
    if args.command == "reviews" and args.reviews_command == "reject":
        return run_reviews_reject(settings)
    if args.command == "reviews" and args.reviews_command == "revise":
        return run_reviews_revise(settings, args.requested_change, args.preview)
    if args.command == "uploads" and args.uploads_command == "status":
        return run_uploads_status(settings)
    if args.command == "uploads" and args.uploads_command == "next":
        return run_uploads_next(settings, args.job_id)
    if args.command == "uploads" and args.uploads_command == "prepare":
        return run_uploads_prepare(settings, args.job_id)
    if args.command == "uploads" and args.uploads_command == "send":
        return run_uploads_send(settings, args.job_id, args.dry_run)
    if args.command == "uploads" and args.uploads_command == "check":
        return run_uploads_check(settings, args.job_id)
    if args.command == "uploads" and args.uploads_command == "confirm":
        return run_uploads_confirm(settings, args.job_id, args.reference)
    if args.command == "uploads" and args.uploads_command == "fail":
        return run_uploads_fail(settings, args.job_id, args.error_message)
    if args.command == "tiktok" and args.tiktok_command == "auth-url":
        return run_tiktok_auth_url(settings)
    if args.command == "tiktok" and args.tiktok_command == "auth-listen":
        return run_tiktok_auth_listen(settings, args.no_browser, args.timeout_seconds)
    if args.command == "tiktok" and args.tiktok_command == "auth-exchange":
        return run_tiktok_auth_exchange(settings, args.code)
    if args.command == "tiktok" and args.tiktok_command == "auth-status":
        return run_tiktok_auth_status(settings)
    if args.command == "tiktok" and args.tiktok_command == "auth-refresh":
        return run_tiktok_auth_refresh(settings)
    if args.command == "telegram" and args.telegram_command == "handle":
        return run_telegram_handle(settings, args.message)
    if args.command == "smoke":
        return run_smoke(settings)

    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trivia-factory",
        description="Local worker for the TikTok Trivia Factory.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show local configuration and database status.")

    db_parser = subparsers.add_parser("db", help="Database commands.")
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser("init", help="Initialize the local SQLite database.")

    ideas_parser = subparsers.add_parser("ideas", help="Idea queue commands.")
    ideas_subparsers = ideas_parser.add_subparsers(dest="ideas_command")
    ideas_add_parser = ideas_subparsers.add_parser("add", help="Add an idea to the queue.")
    ideas_add_parser.add_argument("prompt", help="Idea prompt to save.")
    ideas_add_parser.add_argument("--source", default="cli", help="Idea source label.")
    ideas_add_parser.add_argument("--notes", default=None, help="Optional operator notes.")

    ideas_list_parser = ideas_subparsers.add_parser("list", help="List saved ideas.")
    ideas_list_parser.add_argument(
        "--status",
        choices=["queued", "active", "completed", "cancelled"],
        default=None,
        help="Filter ideas by status.",
    )

    jobs_parser = subparsers.add_parser("jobs", help="Production job commands.")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_start_parser = jobs_subparsers.add_parser("start", help="Start one active job for an idea.")
    jobs_start_parser.add_argument("idea_id", help="Idea ID to produce.")
    jobs_subparsers.add_parser("active", help="Show the current active job.")
    jobs_subparsers.add_parser("cancel-active", help="Cancel the current active job.")

    scripts_parser = subparsers.add_parser("scripts", help="Trivia script commands.")
    scripts_subparsers = scripts_parser.add_subparsers(dest="scripts_command")
    scripts_generate_parser = scripts_subparsers.add_parser(
        "generate",
        help="Generate a structured trivia script for the active job.",
    )
    scripts_generate_parser.add_argument("--count", type=int, default=None, help="Question count.")
    scripts_generate_parser.add_argument(
        "--duration-seconds",
        type=int,
        default=None,
        help="Target video duration in seconds.",
    )
    scripts_show_parser = scripts_subparsers.add_parser("show", help="Show the latest script.")
    scripts_show_parser.add_argument("--job-id", default=None, help="Job ID. Defaults to active job.")

    manifests_parser = subparsers.add_parser("manifests", help="Render manifest commands.")
    manifests_subparsers = manifests_parser.add_subparsers(dest="manifests_command")
    manifests_generate_parser = manifests_subparsers.add_parser(
        "generate",
        help="Generate a render manifest from the latest script.",
    )
    manifests_generate_parser.add_argument("--job-id", default=None, help="Job ID. Defaults to active job.")
    manifests_show_parser = manifests_subparsers.add_parser("show", help="Show the latest render manifest.")
    manifests_show_parser.add_argument("--job-id", default=None, help="Job ID. Defaults to active job.")

    drafts_parser = subparsers.add_parser("drafts", help="Draft artifact commands.")
    drafts_subparsers = drafts_parser.add_subparsers(dest="drafts_command")
    drafts_render_parser = drafts_subparsers.add_parser("render", help="Render an MP4 from the latest manifest.")
    drafts_render_parser.add_argument("--job-id", default=None, help="Job ID. Defaults to active job.")
    drafts_render_parser.add_argument("--output", default=None, help="Optional MP4 output path.")
    drafts_render_parser.add_argument(
        "--preview",
        action="store_true",
        help="Render at reduced FPS for faster local validation.",
    )
    drafts_show_parser = drafts_subparsers.add_parser("show", help="Show the latest MP4 draft artifact.")
    drafts_show_parser.add_argument("--job-id", default=None, help="Job ID. Defaults to active job.")

    reviews_parser = subparsers.add_parser("reviews", help="Review and approval commands.")
    reviews_subparsers = reviews_parser.add_subparsers(dest="reviews_command")
    reviews_subparsers.add_parser("show", help="Show the active draft review state.")
    reviews_subparsers.add_parser("approve", help="Approve the active MP4 draft.")
    reviews_subparsers.add_parser("reject", help="Reject the active MP4 draft.")
    reviews_revise_parser = reviews_subparsers.add_parser("revise", help="Request a manifest-level revision.")
    reviews_revise_parser.add_argument("requested_change", help="Revision request text.")
    reviews_revise_parser.add_argument("--preview", action="store_true", help="Render revised draft at reduced FPS.")

    uploads_parser = subparsers.add_parser("uploads", help="TikTok upload handoff commands.")
    uploads_subparsers = uploads_parser.add_subparsers(dest="uploads_command")
    uploads_subparsers.add_parser("status", help="Show approved drafts awaiting upload.")
    uploads_next_parser = uploads_subparsers.add_parser(
        "next",
        help="Start or show the next approved-draft upload handoff.",
    )
    uploads_next_parser.add_argument("--job-id", default=None, help="Optional job ID to hand off.")
    uploads_prepare_parser = uploads_subparsers.add_parser(
        "prepare",
        help="Write a TikTok inbox upload packet for the next approved draft.",
    )
    uploads_prepare_parser.add_argument("--job-id", default=None, help="Optional job ID to prepare.")
    uploads_send_parser = uploads_subparsers.add_parser(
        "send",
        help="Upload the next approved draft to TikTok inbox through the official API.",
    )
    uploads_send_parser.add_argument("--job-id", default=None, help="Optional job ID to upload.")
    uploads_send_parser.add_argument("--dry-run", action="store_true", help="Validate selection without API calls.")
    uploads_check_parser = uploads_subparsers.add_parser(
        "check",
        help="Fetch TikTok status for a previously sent official API upload.",
    )
    uploads_check_parser.add_argument("job_id", help="Job ID whose TikTok upload status should be checked.")
    uploads_confirm_parser = uploads_subparsers.add_parser(
        "confirm",
        help="Mark an upload handoff as successful.",
    )
    uploads_confirm_parser.add_argument("job_id", help="Job ID that was uploaded.")
    uploads_confirm_parser.add_argument("--reference", default=None, help="Optional TikTok/provider reference.")
    uploads_fail_parser = uploads_subparsers.add_parser(
        "fail",
        help="Mark an upload handoff as failed.",
    )
    uploads_fail_parser.add_argument("job_id", help="Job ID whose upload failed.")
    uploads_fail_parser.add_argument("error_message", help="Failure detail to store.")

    tiktok_parser = subparsers.add_parser("tiktok", help="TikTok API OAuth commands.")
    tiktok_subparsers = tiktok_parser.add_subparsers(dest="tiktok_command")
    tiktok_subparsers.add_parser("auth-url", help="Create a TikTok OAuth URL and save the local PKCE session.")
    tiktok_auth_listen_parser = tiktok_subparsers.add_parser(
        "auth-listen",
        help="Start the localhost OAuth callback server and save TikTok tokens.",
    )
    tiktok_auth_listen_parser.add_argument("--no-browser", action="store_true", help="Print URL only; do not open browser.")
    tiktok_auth_listen_parser.add_argument("--timeout-seconds", type=int, default=300, help="Callback wait timeout.")
    tiktok_auth_exchange_parser = tiktok_subparsers.add_parser(
        "auth-exchange",
        help="Exchange an authorization code from the saved TikTok OAuth session.",
    )
    tiktok_auth_exchange_parser.add_argument("code", help="Authorization code returned to the redirect URI.")
    tiktok_subparsers.add_parser("auth-status", help="Show redacted TikTok token/configuration status.")
    tiktok_subparsers.add_parser("auth-refresh", help="Refresh and save the TikTok access token.")

    telegram_parser = subparsers.add_parser("telegram", help="Telegram-shaped local command adapter.")
    telegram_subparsers = telegram_parser.add_subparsers(dest="telegram_command")
    telegram_handle_parser = telegram_subparsers.add_parser("handle", help="Handle one Telegram-like text message.")
    telegram_handle_parser.add_argument("message", help="Incoming Telegram message text.")

    subparsers.add_parser("smoke", help="Run a minimal local smoke check.")

    return parser


def run_status(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    active = get_active_job(settings.db_path)
    queued = list_ideas(settings.db_path, status="queued")
    upload_status = get_upload_status(settings.db_path)
    payload = {
        "app": "tiktok-trivia-factory",
        "version": __version__,
        "data_dir": str(settings.data_dir),
        "db_path": str(settings.db_path),
        "db_exists": settings.db_path.exists(),
        "log_level": settings.log_level,
        "active_job": None if active is None else active.id,
        "queued_ideas": len(queued),
        "approved_awaiting_upload": len(upload_status.candidates),
    }
    print(json.dumps(payload, indent=2))
    return 0


def run_db_init(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    initialize_database(settings.db_path)
    print(f"initialized database: {settings.db_path}")
    return 0


def run_smoke(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    initialize_database(settings.db_path)
    probe_database(settings.db_path)
    print("smoke ok")
    return 0


def run_ideas_add(settings: Settings, prompt: str, source: str, notes: str | None) -> int:
    ensure_runtime_directories(settings)
    idea = add_idea(settings.db_path, prompt=prompt, source=source, notes=notes)
    print(json.dumps({"saved": _idea_payload(idea)}, indent=2))
    return 0


def run_ideas_list(settings: Settings, status: str | None) -> int:
    ensure_runtime_directories(settings)
    ideas = list_ideas(settings.db_path, status=status)
    print(json.dumps({"ideas": [_idea_payload(idea) for idea in ideas]}, indent=2))
    return 0


def run_jobs_start(settings: Settings, idea_id: str) -> int:
    ensure_runtime_directories(settings)
    try:
        job = start_job(settings.db_path, idea_id=idea_id)
    except IdeaNotFoundError as error:
        print(str(error))
        return 1
    except ActiveJobExistsError as error:
        print(str(error))
        return 1

    print(json.dumps({"started": _job_payload(job)}, indent=2))
    return 0


def run_jobs_active(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    job = get_active_job(settings.db_path)
    print(json.dumps({"active_job": None if job is None else _job_payload(job)}, indent=2))
    return 0


def run_jobs_cancel_active(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        job = cancel_active_job(settings.db_path)
    except NoActiveJobError as error:
        print(str(error))
        return 1

    print(json.dumps({"cancelled": _job_payload(job)}, indent=2))
    return 0


def run_scripts_generate(
    settings: Settings,
    count: int | None,
    duration_seconds: int | None,
) -> int:
    ensure_runtime_directories(settings)
    active_job = get_active_job(settings.db_path)
    if active_job is None:
        print("No active production job")
        return 1

    idea = get_idea(settings.db_path, active_job.idea_id)
    try:
        generated = generate_script(
            idea.prompt,
            question_count=count,
            duration_seconds=duration_seconds,
            trivia_bank_path=settings.trivia_bank_path,
        )
    except UnsupportedTopicError as error:
        print(str(error))
        return 1

    script = save_video_script(
        settings.db_path,
        job_id=active_job.id,
        script_json=generated.script_json,
        provider=generated.provider,
        confidence=generated.confidence,
        citations=generated.citations,
    )
    citations = list_source_citations(settings.db_path, script.id)
    print(json.dumps(_script_response_payload(script, citations), indent=2))
    return 0


def run_scripts_show(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    selected_job_id = job_id
    if selected_job_id is None:
        active_job = get_active_job(settings.db_path)
        if active_job is None:
            print("No active production job")
            return 1
        selected_job_id = active_job.id

    script = get_latest_video_script(settings.db_path, selected_job_id)
    if script is None:
        print(f"No script found for job: {selected_job_id}")
        return 1

    citations = list_source_citations(settings.db_path, script.id)
    print(json.dumps(_script_response_payload(script, citations), indent=2))
    return 0


def run_manifests_generate(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    selected_job_id = _resolve_job_id(settings, job_id)
    if selected_job_id is None:
        print("No active production job")
        return 1

    script = get_latest_video_script(settings.db_path, selected_job_id)
    if script is None:
        print(f"No script found for job: {selected_job_id}")
        return 1

    try:
        generated = build_render_manifest(script.script_json, watermark_text=settings.watermark_text)
    except ManifestError as error:
        print(str(error))
        return 1

    manifest = save_render_manifest(
        settings.db_path,
        job_id=selected_job_id,
        manifest_json=generated.manifest_json,
        provider=generated.provider,
    )
    print(json.dumps(_manifest_response_payload(manifest), indent=2))
    return 0


def run_manifests_show(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    selected_job_id = _resolve_job_id(settings, job_id)
    if selected_job_id is None:
        print("No active production job")
        return 1

    manifest = get_latest_render_manifest(settings.db_path, selected_job_id)
    if manifest is None:
        print(f"No render manifest found for job: {selected_job_id}")
        return 1

    print(json.dumps(_manifest_response_payload(manifest), indent=2))
    return 0


def run_drafts_render(
    settings: Settings,
    job_id: str | None,
    output: str | None,
    preview: bool,
) -> int:
    ensure_runtime_directories(settings)
    selected_job_id = _resolve_job_id(settings, job_id)
    if selected_job_id is None:
        print("No active production job")
        return 1

    manifest = get_latest_render_manifest(settings.db_path, selected_job_id)
    if manifest is None:
        print(f"No render manifest found for job: {selected_job_id}")
        return 1

    output_path = _draft_output_path(settings, selected_job_id, manifest.revision, output)
    try:
        render_manifest_to_mp4(
            manifest.manifest_json,
            output_path,
            preview=preview,
            voiceover_provider=settings.voiceover_provider,
        )
    except RenderError as error:
        print(str(error))
        return 1

    artifact = save_draft_artifact(
        settings.db_path,
        job_id=selected_job_id,
        revision=manifest.revision,
        artifact_type="mp4",
        path=str(output_path),
    )
    print(json.dumps({"draft": _draft_payload(artifact)}, indent=2))
    return 0


def run_drafts_show(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    selected_job_id = _resolve_job_id(settings, job_id)
    if selected_job_id is None:
        print("No active production job")
        return 1

    artifact = get_latest_draft_artifact(settings.db_path, selected_job_id)
    if artifact is None:
        print(f"No MP4 draft found for job: {selected_job_id}")
        return 1

    print(json.dumps({"draft": _draft_payload(artifact)}, indent=2))
    return 0


def run_reviews_show(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        summary = get_active_review_summary(settings.db_path)
    except ReviewError as error:
        print(str(error))
        return 1
    print(json.dumps({"review": _review_summary_payload(summary)}, indent=2))
    return 0


def run_reviews_approve(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        event = approve_active_review(settings.db_path)
    except ReviewError as error:
        print(str(error))
        return 1
    print(json.dumps({"approval": _approval_payload(event)}, indent=2))
    return 0


def run_reviews_reject(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        event = reject_active_review(settings.db_path)
    except ReviewError as error:
        print(str(error))
        return 1
    print(json.dumps({"approval": _approval_payload(event)}, indent=2))
    return 0


def run_reviews_revise(settings: Settings, requested_change: str, preview: bool) -> int:
    ensure_runtime_directories(settings)
    try:
        result = revise_active_review(
            settings.db_path,
            artifacts_dir=settings.artifacts_dir,
            requested_change=requested_change,
            preview=preview,
            voiceover_provider=settings.voiceover_provider,
        )
    except ReviewError as error:
        print(str(error))
        return 1
    print(
        json.dumps(
            {
                "revision": {
                    "event": _revision_payload(result.event),
                    "manifest": _manifest_payload(result.manifest),
                    "draft": _draft_payload(result.draft),
                    "applied_changes": result.applied_changes,
                }
            },
            indent=2,
        )
    )
    return 0


def run_uploads_status(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    status = get_upload_status(settings.db_path)
    print(
        json.dumps(
            {
                "upload_status": {
                    "awaiting_upload": [_upload_candidate_payload(candidate) for candidate in status.candidates],
                    "recent_attempts": [_upload_attempt_payload(attempt) for attempt in status.recent_attempts],
                }
            },
            indent=2,
        )
    )
    return 0


def run_uploads_next(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    try:
        handoff = start_upload_handoff(settings.db_path, job_id=job_id)
    except UploadError as error:
        print(str(error))
        return 1

    print(
        json.dumps(
            {
                "upload_handoff": {
                    "attempt": _upload_attempt_payload(handoff.attempt),
                    "candidate": _upload_candidate_payload(handoff.candidate),
                    "reused_existing_pending": handoff.reused_existing_pending,
                    "operator_instruction": (
                        "Upload the MP4 to TikTok inbox/drafts, then run uploads confirm JOB_ID "
                        "or uploads fail JOB_ID ERROR_MESSAGE."
                    ),
                }
            },
            indent=2,
        )
    )
    return 0


def run_uploads_prepare(settings: Settings, job_id: str | None) -> int:
    ensure_runtime_directories(settings)
    try:
        packet = prepare_upload_packet(settings.db_path, uploads_dir=settings.data_dir / "uploads", job_id=job_id)
    except UploadError as error:
        print(str(error))
        return 1

    print(
        json.dumps(
            {
                "upload_packet": {
                    "attempt": _upload_attempt_payload(packet.attempt),
                    "candidate": _upload_candidate_payload(packet.candidate),
                    "packet_path": str(packet.packet_path),
                    "packet": packet.packet_json,
                    "reused_existing_pending": packet.reused_existing_pending,
                    "operator_instruction": (
                        "Use the upload packet plus MP4 path for the TikTok inbox upload runner. "
                        "After TikTok accepts it, run uploads confirm JOB_ID --reference REFERENCE."
                    ),
                }
            },
            indent=2,
        )
    )
    return 0


def run_uploads_send(settings: Settings, job_id: str | None, dry_run: bool) -> int:
    ensure_runtime_directories(settings)
    try:
        result = send_approved_draft_to_tiktok(
            settings.db_path,
            data_dir=settings.data_dir,
            job_id=job_id,
            dry_run=dry_run,
        )
    except UploadError as error:
        print(str(error))
        return 1

    print(
        json.dumps(
            {
                "tiktok_upload": {
                    "candidate": _upload_candidate_payload(result.candidate),
                    "attempt": None if result.attempt is None else _upload_attempt_payload(result.attempt),
                    "publish_id": result.publish_id,
                    "status": result.status,
                    "dry_run": result.dry_run,
                    "reused_existing_pending": result.reused_existing_pending,
                    "message": result.message,
                    "operator_instruction": (
                        "If TikTok accepted the upload, open TikTok notifications/inbox to finish editing/posting. "
                        "Run uploads check JOB_ID while the upload is pending."
                    ),
                }
            },
            indent=2,
        )
    )
    return 0 if result.status != "failed" else 1


def run_uploads_check(settings: Settings, job_id: str) -> int:
    ensure_runtime_directories(settings)
    try:
        result = check_tiktok_upload_status(settings.db_path, settings.data_dir, job_id)
    except UploadError as error:
        print(str(error))
        return 1

    print(
        json.dumps(
            {
                "tiktok_upload_status": {
                    "job_id": job_id,
                    "publish_id": result.publish_id,
                    "tiktok_status": result.tiktok_status,
                    "fail_reason": result.fail_reason,
                    "previous_attempt": _upload_attempt_payload(result.attempt),
                    "recorded_local_attempt": None
                    if result.local_attempt is None
                    else _upload_attempt_payload(result.local_attempt),
                }
            },
            indent=2,
        )
    )
    return 0


def run_uploads_confirm(settings: Settings, job_id: str, reference: str | None) -> int:
    ensure_runtime_directories(settings)
    try:
        attempt = mark_upload_succeeded(settings.db_path, job_id=job_id, provider_reference=reference)
    except UploadError as error:
        print(str(error))
        return 1
    print(json.dumps({"upload_attempt": _upload_attempt_payload(attempt)}, indent=2))
    return 0


def run_uploads_fail(settings: Settings, job_id: str, error_message: str) -> int:
    ensure_runtime_directories(settings)
    try:
        attempt = mark_upload_failed(settings.db_path, job_id=job_id, error_message=error_message)
    except UploadError as error:
        print(str(error))
        return 1
    print(json.dumps({"upload_attempt": _upload_attempt_payload(attempt)}, indent=2))
    return 0


def run_tiktok_auth_url(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        credentials = load_tiktok_credentials()
        session = create_oauth_session(credentials)
        session_path = save_oauth_session(settings.data_dir, session)
    except TikTokApiError as error:
        print(str(error))
        return 1

    print(
        json.dumps(
            {
                "tiktok_oauth": {
                    "authorization_url": session.auth_url,
                    "redirect_uri": session.redirect_uri,
                    "scopes": session.scopes,
                    "session_path": str(session_path),
                    "operator_instruction": (
                        "Open authorization_url, approve the sandbox app, then run "
                        "`tiktok auth-exchange CODE` with the code from the redirect URL."
                    ),
                }
            },
            indent=2,
        )
    )
    return 0


def run_tiktok_auth_listen(settings: Settings, no_browser: bool, timeout_seconds: int) -> int:
    ensure_runtime_directories(settings)
    try:
        credentials = load_tiktok_credentials()
        token_set = run_oauth_callback_server(
            credentials,
            settings.data_dir,
            open_browser=not no_browser,
            timeout_seconds=timeout_seconds,
        )
    except TikTokApiError as error:
        print(str(error))
        return 1

    print(json.dumps({"tiktok_auth": token_status_payload(credentials, token_set)}, indent=2))
    return 0


def run_tiktok_auth_exchange(settings: Settings, code: str) -> int:
    ensure_runtime_directories(settings)
    try:
        credentials = load_tiktok_credentials()
        session = load_oauth_session(settings.data_dir)
        token_set = exchange_authorization_code(credentials, code, session)
        save_tokens(settings.data_dir, token_set)
    except TikTokApiError as error:
        print(str(error))
        return 1

    print(json.dumps({"tiktok_auth": token_status_payload(credentials, token_set)}, indent=2))
    return 0


def run_tiktok_auth_status(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        credentials = load_tiktok_credentials()
    except TikTokApiError as error:
        print(json.dumps({"tiktok_auth": {"configured": False, "error": str(error)}}, indent=2))
        return 1

    print(
        json.dumps(
            {"tiktok_auth": token_status_payload(credentials, load_tokens_if_present(settings.data_dir))},
            indent=2,
        )
    )
    return 0


def run_tiktok_auth_refresh(settings: Settings) -> int:
    ensure_runtime_directories(settings)
    try:
        credentials = load_tiktok_credentials()
        token_set = load_tokens_if_present(settings.data_dir)
        if token_set is None:
            raise TikTokApiError("No TikTok token file found. Run OAuth authorization first.")
        refreshed = refresh_access_token(credentials, token_set)
        save_tokens(settings.data_dir, refreshed)
    except TikTokApiError as error:
        print(str(error))
        return 1

    print(json.dumps({"tiktok_auth": token_status_payload(credentials, refreshed)}, indent=2))
    return 0


def run_telegram_handle(settings: Settings, message: str) -> int:
    ensure_runtime_directories(settings)
    result = handle_review_message(
        settings.db_path,
        settings.artifacts_dir,
        message,
        watermark_text=settings.watermark_text,
        voiceover_provider=settings.voiceover_provider,
        trivia_bank_path=settings.trivia_bank_path,
    )
    payload = {"ok": result.ok, "message": result.message}
    if result.media_path is not None:
        payload["media_path"] = result.media_path
    if result.media_type is not None:
        payload["media_type"] = result.media_type
    if result.reply_options is not None:
        payload["reply_options"] = [
            {"label": option.label, "value": option.value}
            for option in result.reply_options
        ]
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


def _idea_payload(idea: Idea) -> dict[str, str | None]:
    return {
        "id": idea.id,
        "prompt": idea.prompt,
        "source": idea.source,
        "status": idea.status,
        "notes": idea.notes,
        "created_at": idea.created_at,
        "updated_at": idea.updated_at,
    }


def _job_payload(job: ProductionJob) -> dict[str, str | None]:
    return {
        "id": job.id,
        "idea_id": job.idea_id,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


def _script_response_payload(script: VideoScript, citations: list[SourceCitation]) -> dict[str, object]:
    return {
        "script": {
            "id": script.id,
            "job_id": script.job_id,
            "revision": script.revision,
            "provider": script.provider,
            "confidence": script.confidence,
            "created_at": script.created_at,
            "content": json.loads(script.script_json),
        },
        "citations": [
            {
                "id": citation.id,
                "label": citation.label,
                "source_type": citation.source_type,
                "reference": citation.reference,
                "confidence": citation.confidence,
            }
            for citation in citations
        ],
    }


def _manifest_response_payload(manifest: RenderManifest) -> dict[str, object]:
    return {
        "manifest": _manifest_payload(manifest)
    }


def _manifest_payload(manifest: RenderManifest) -> dict[str, object]:
    return {
        "id": manifest.id,
        "job_id": manifest.job_id,
        "revision": manifest.revision,
        "provider": manifest.provider,
        "created_at": manifest.created_at,
        "content": json.loads(manifest.manifest_json),
    }


def _draft_payload(artifact: DraftArtifact) -> dict[str, str | int]:
    return {
        "id": artifact.id,
        "job_id": artifact.job_id,
        "revision": artifact.revision,
        "artifact_type": artifact.artifact_type,
        "path": artifact.path,
        "created_at": artifact.created_at,
    }


def _approval_payload(event: ApprovalEvent) -> dict[str, str]:
    return {
        "id": event.id,
        "job_id": event.job_id,
        "decision": event.decision,
        "created_at": event.created_at,
    }


def _upload_attempt_payload(attempt: UploadAttempt) -> dict[str, str | None]:
    return {
        "id": attempt.id,
        "job_id": attempt.job_id,
        "provider": attempt.provider,
        "status": attempt.status,
        "provider_reference": attempt.provider_reference,
        "error_message": attempt.error_message,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
    }


def _upload_candidate_payload(candidate: object) -> dict[str, object]:
    return {
        "job": _job_payload(candidate.job),
        "idea": _idea_payload(candidate.idea),
        "draft": _draft_payload(candidate.draft),
        "latest_attempt": None
        if candidate.latest_attempt is None
        else _upload_attempt_payload(candidate.latest_attempt),
    }


def _revision_payload(event: RevisionEvent) -> dict[str, str]:
    return {
        "id": event.id,
        "job_id": event.job_id,
        "requested_change": event.requested_change,
        "created_at": event.created_at,
    }


def _review_summary_payload(summary: ReviewSummary) -> dict[str, object]:
    return {
        "job": _job_payload(summary.job),
        "manifest": None if summary.manifest is None else _manifest_payload(summary.manifest),
        "draft": None if summary.draft is None else _draft_payload(summary.draft),
        "approval": None if summary.approval is None else _approval_payload(summary.approval),
    }


def _resolve_job_id(settings: Settings, job_id: str | None) -> str | None:
    if job_id is not None:
        return job_id
    active_job = get_active_job(settings.db_path)
    if active_job is None:
        return None
    return active_job.id


def _draft_output_path(
    settings: Settings,
    job_id: str,
    revision: int,
    output: str | None,
) -> Path:
    if output is not None:
        return Path(output).expanduser().resolve()
    return settings.artifacts_dir / job_id / f"draft_r{revision:03d}.mp4"
