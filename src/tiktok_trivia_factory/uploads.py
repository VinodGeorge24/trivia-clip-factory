from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import DraftArtifact, Idea, ProductionJob, SourceCitation, UploadAttempt, VideoScript
from .repository import (
    get_latest_upload_attempt,
    get_latest_video_script,
    get_successful_upload_attempt,
    list_approved_jobs_with_drafts,
    list_source_citations,
    list_upload_attempts,
    save_upload_attempt,
)
from .tiktok_api import (
    TikTokApiError,
    ensure_access_token,
    fetch_publish_status,
    init_file_upload,
    load_tiktok_credentials,
    upload_video_file,
)


DEFAULT_UPLOAD_PROVIDER = "tiktok_inbox_manual"
UPLOAD_PACKET_PROVIDER = "tiktok_upload_packet"
TIKTOK_API_UPLOAD_PROVIDER = "tiktok_api_file_upload"
TIKTOK_TERMINAL_SUCCESS_STATUSES = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}
TIKTOK_TERMINAL_FAILURE_STATUSES = {"FAILED"}


class UploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadCandidate:
    job: ProductionJob
    idea: Idea
    draft: DraftArtifact
    latest_attempt: UploadAttempt | None


@dataclass(frozen=True)
class UploadHandoff:
    candidate: UploadCandidate
    attempt: UploadAttempt
    reused_existing_pending: bool


@dataclass(frozen=True)
class UploadPacket:
    candidate: UploadCandidate
    attempt: UploadAttempt
    packet_path: Path
    packet_json: dict[str, object]
    reused_existing_pending: bool


@dataclass(frozen=True)
class UploadStatus:
    candidates: list[UploadCandidate]
    recent_attempts: list[UploadAttempt]


@dataclass(frozen=True)
class TikTokSendResult:
    candidate: UploadCandidate
    attempt: UploadAttempt | None
    publish_id: str | None
    status: str
    dry_run: bool
    reused_existing_pending: bool
    message: str


@dataclass(frozen=True)
class TikTokCheckResult:
    attempt: UploadAttempt
    publish_id: str
    tiktok_status: str
    fail_reason: str | None
    local_attempt: UploadAttempt | None


def get_upload_status(db_path: Path) -> UploadStatus:
    return UploadStatus(
        candidates=list_upload_candidates(db_path),
        recent_attempts=list_upload_attempts(db_path),
    )


def list_upload_candidates(db_path: Path) -> list[UploadCandidate]:
    candidates: list[UploadCandidate] = []
    for job, idea, draft in list_approved_jobs_with_drafts(db_path):
        if get_successful_upload_attempt(db_path, job.id) is not None:
            continue
        candidates.append(
            UploadCandidate(
                job=job,
                idea=idea,
                draft=draft,
                latest_attempt=get_latest_upload_attempt(db_path, job.id),
            )
        )
    return candidates


def start_upload_handoff(
    db_path: Path,
    job_id: str | None = None,
    provider: str = DEFAULT_UPLOAD_PROVIDER,
) -> UploadHandoff:
    candidate = _select_upload_candidate(db_path, job_id)
    _require_draft_file(candidate)
    latest = candidate.latest_attempt
    if latest is not None and latest.status == "pending":
        return UploadHandoff(candidate=candidate, attempt=latest, reused_existing_pending=True)

    attempt = save_upload_attempt(
        db_path,
        job_id=candidate.job.id,
        provider=provider,
        status="pending",
    )
    return UploadHandoff(candidate=candidate, attempt=attempt, reused_existing_pending=False)


def prepare_upload_packet(
    db_path: Path,
    uploads_dir: Path,
    job_id: str | None = None,
) -> UploadPacket:
    candidate = _select_upload_candidate(db_path, job_id)
    _require_draft_file(candidate)

    packet_dir = uploads_dir / candidate.job.id
    packet_path = packet_dir / "upload_packet.json"
    script = get_latest_video_script(db_path, candidate.job.id)
    citations = [] if script is None else list_source_citations(db_path, script.id)
    packet_json = _build_upload_packet(candidate, script, citations)

    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet_json, indent=2, sort_keys=True), encoding="utf-8")

    latest = candidate.latest_attempt
    if (
        latest is not None
        and latest.status == "pending"
        and latest.provider == UPLOAD_PACKET_PROVIDER
        and latest.provider_reference == str(packet_path)
    ):
        return UploadPacket(
            candidate=candidate,
            attempt=latest,
            packet_path=packet_path,
            packet_json=packet_json,
            reused_existing_pending=True,
        )

    attempt = save_upload_attempt(
        db_path,
        job_id=candidate.job.id,
        provider=UPLOAD_PACKET_PROVIDER,
        status="pending",
        provider_reference=str(packet_path),
    )
    return UploadPacket(
        candidate=candidate,
        attempt=attempt,
        packet_path=packet_path,
        packet_json=packet_json,
        reused_existing_pending=False,
    )


def send_approved_draft_to_tiktok(
    db_path: Path,
    data_dir: Path,
    job_id: str | None = None,
    dry_run: bool = False,
) -> TikTokSendResult:
    candidate = _select_upload_candidate(db_path, job_id)
    _require_draft_file(candidate)

    latest = candidate.latest_attempt
    if latest is not None and latest.status == "pending" and latest.provider == TIKTOK_API_UPLOAD_PROVIDER:
        return TikTokSendResult(
            candidate=candidate,
            attempt=latest,
            publish_id=latest.provider_reference,
            status="pending",
            dry_run=dry_run,
            reused_existing_pending=True,
            message="Existing pending TikTok API upload found. Run `uploads check JOB_ID` before retrying.",
        )

    if dry_run:
        return TikTokSendResult(
            candidate=candidate,
            attempt=None,
            publish_id=None,
            status="dry_run",
            dry_run=True,
            reused_existing_pending=False,
            message="Dry run only. No TikTok API request was made.",
        )

    draft_path = Path(candidate.draft.path)
    try:
        credentials = load_tiktok_credentials()
        token_set = ensure_access_token(credentials, data_dir)
        initialized = init_file_upload(token_set.access_token, draft_path)
        attempt = save_upload_attempt(
            db_path,
            job_id=candidate.job.id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="pending",
            provider_reference=initialized.publish_id,
        )
        upload_video_file(initialized.upload_url, draft_path)
        status = fetch_publish_status(token_set.access_token, initialized.publish_id)
    except TikTokApiError as error:
        failure_attempt = save_upload_attempt(
            db_path,
            job_id=candidate.job.id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="failed",
            error_message=str(error),
        )
        return TikTokSendResult(
            candidate=candidate,
            attempt=failure_attempt,
            publish_id=None,
            status="failed",
            dry_run=False,
            reused_existing_pending=False,
            message=str(error),
        )

    if status.status in TIKTOK_TERMINAL_FAILURE_STATUSES:
        failed = save_upload_attempt(
            db_path,
            job_id=candidate.job.id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="failed",
            provider_reference=initialized.publish_id,
            error_message=status.fail_reason or "TikTok upload failed",
        )
        return TikTokSendResult(
            candidate=candidate,
            attempt=failed,
            publish_id=initialized.publish_id,
            status=status.status,
            dry_run=False,
            reused_existing_pending=False,
            message=status.fail_reason or "TikTok upload failed",
        )

    if status.status in TIKTOK_TERMINAL_SUCCESS_STATUSES:
        succeeded = save_upload_attempt(
            db_path,
            job_id=candidate.job.id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="succeeded",
            provider_reference=initialized.publish_id,
        )
        return TikTokSendResult(
            candidate=candidate,
            attempt=succeeded,
            publish_id=initialized.publish_id,
            status=status.status,
            dry_run=False,
            reused_existing_pending=False,
            message="TikTok accepted the upload. Finish review/posting from the TikTok inbox.",
        )

    return TikTokSendResult(
        candidate=candidate,
        attempt=attempt,
        publish_id=initialized.publish_id,
        status=status.status or "pending",
        dry_run=False,
        reused_existing_pending=False,
        message="TikTok upload is still processing. Run `uploads check JOB_ID`.",
    )


def check_tiktok_upload_status(db_path: Path, data_dir: Path, job_id: str) -> TikTokCheckResult:
    latest = get_latest_upload_attempt(db_path, job_id)
    if latest is None or latest.provider != TIKTOK_API_UPLOAD_PROVIDER or latest.provider_reference is None:
        raise UploadError(f"No TikTok API upload attempt with a publish_id exists for job: {job_id}")

    try:
        credentials = load_tiktok_credentials()
        token_set = ensure_access_token(credentials, data_dir)
        status = fetch_publish_status(token_set.access_token, latest.provider_reference)
    except TikTokApiError as error:
        raise UploadError(str(error)) from error

    local_attempt: UploadAttempt | None = None
    if latest.status == "pending" and status.status in TIKTOK_TERMINAL_SUCCESS_STATUSES:
        local_attempt = save_upload_attempt(
            db_path,
            job_id=job_id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="succeeded",
            provider_reference=latest.provider_reference,
        )
    elif latest.status == "pending" and status.status in TIKTOK_TERMINAL_FAILURE_STATUSES:
        local_attempt = save_upload_attempt(
            db_path,
            job_id=job_id,
            provider=TIKTOK_API_UPLOAD_PROVIDER,
            status="failed",
            provider_reference=latest.provider_reference,
            error_message=status.fail_reason or "TikTok upload failed",
        )

    return TikTokCheckResult(
        attempt=latest,
        publish_id=latest.provider_reference,
        tiktok_status=status.status,
        fail_reason=status.fail_reason,
        local_attempt=local_attempt,
    )


def mark_upload_succeeded(
    db_path: Path,
    job_id: str,
    provider_reference: str | None = None,
    provider: str = DEFAULT_UPLOAD_PROVIDER,
) -> UploadAttempt:
    existing = get_successful_upload_attempt(db_path, job_id)
    if existing is not None:
        return existing

    _require_upload_candidate_or_pending_attempt(db_path, job_id)
    return save_upload_attempt(
        db_path,
        job_id=job_id,
        provider=provider,
        status="succeeded",
        provider_reference=provider_reference,
    )


def mark_upload_failed(
    db_path: Path,
    job_id: str,
    error_message: str,
    provider: str = DEFAULT_UPLOAD_PROVIDER,
) -> UploadAttempt:
    message = error_message.strip()
    if not message:
        raise UploadError("Upload failure needs an error message")

    _require_upload_candidate_or_pending_attempt(db_path, job_id)
    return save_upload_attempt(
        db_path,
        job_id=job_id,
        provider=provider,
        status="failed",
        error_message=message,
    )


def _require_upload_candidate_or_pending_attempt(db_path: Path, job_id: str) -> None:
    for candidate in list_upload_candidates(db_path):
        if candidate.job.id == job_id:
            return
    latest = get_latest_upload_attempt(db_path, job_id)
    if latest is not None and latest.status == "pending":
        return
    raise UploadError(f"No upload handoff exists for job: {job_id}")


def _select_upload_candidate(db_path: Path, job_id: str | None) -> UploadCandidate:
    candidates = list_upload_candidates(db_path)
    if job_id is not None:
        candidates = [candidate for candidate in candidates if candidate.job.id == job_id]
        if not candidates:
            if get_successful_upload_attempt(db_path, job_id) is not None:
                raise UploadError(f"Job already has a successful upload attempt: {job_id}")
            raise UploadError(f"No approved MP4 draft is awaiting upload for job: {job_id}")
    if not candidates:
        raise UploadError("No approved MP4 drafts are awaiting upload")
    return candidates[0]


def _require_draft_file(candidate: UploadCandidate) -> None:
    if not Path(candidate.draft.path).is_file():
        raise UploadError(f"Approved draft file is missing: {candidate.draft.path}")


def _build_upload_packet(
    candidate: UploadCandidate,
    script: VideoScript | None,
    citations: list[SourceCitation],
) -> dict[str, object]:
    script_payload = _script_payload(script)
    return {
        "schema_version": 1,
        "mode": "tiktok_inbox_upload_packet",
        "provider": UPLOAD_PACKET_PROVIDER,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "public_auto_post": False,
        "job": {
            "id": candidate.job.id,
            "status": candidate.job.status,
            "completed_at": candidate.job.completed_at,
        },
        "idea": {
            "id": candidate.idea.id,
            "prompt": candidate.idea.prompt,
            "source": candidate.idea.source,
        },
        "draft": {
            "id": candidate.draft.id,
            "path": candidate.draft.path,
            "artifact_type": candidate.draft.artifact_type,
            "revision": candidate.draft.revision,
        },
        "script": _script_summary(script, script_payload),
        "citations": [
            {
                "label": citation.label,
                "source_type": citation.source_type,
                "reference": citation.reference,
                "confidence": citation.confidence,
            }
            for citation in citations
        ],
        "tiktok_upload": {
            "target_surface": "TikTok Content Posting API Upload API inbox/draft flow",
            "required_scope": "video.upload",
            "requires_registered_app": True,
            "requires_user_oauth": True,
            "live_upload_implemented": True,
            "live_upload_provider": TIKTOK_API_UPLOAD_PROVIDER,
            "operator_must_finish_in_tiktok": True,
        },
        "operator_steps": [
            "Run uploads send --job-id JOB_ID to upload the MP4 to the TikTok inbox through the official API.",
            "Upload only to TikTok inbox/drafts unless the operator explicitly enables Direct Post later.",
            "After TikTok accepts the upload, record upload succeeded JOB_ID REFERENCE.",
            "If upload fails, record upload failed JOB_ID REASON.",
        ],
    }


def _script_payload(script: VideoScript | None) -> dict[str, object] | None:
    if script is None:
        return None
    try:
        payload = json.loads(script.script_json)
    except json.JSONDecodeError as error:
        raise UploadError(f"Latest script JSON is invalid for job: {script.job_id}") from error
    if not isinstance(payload, dict):
        raise UploadError(f"Latest script JSON must be an object for job: {script.job_id}")
    return payload


def _script_summary(
    script: VideoScript | None,
    payload: dict[str, object] | None,
) -> dict[str, object] | None:
    if script is None or payload is None:
        return None
    hashtags = payload.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = []
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": script.id,
        "revision": script.revision,
        "provider": script.provider,
        "confidence": script.confidence,
        "topic": payload.get("topic"),
        "prompt": payload.get("prompt"),
        "caption": payload.get("caption"),
        "hashtags": [str(value) for value in hashtags],
        "question_count": metadata.get("question_count"),
        "needs_external_research": metadata.get("needs_external_research"),
    }
