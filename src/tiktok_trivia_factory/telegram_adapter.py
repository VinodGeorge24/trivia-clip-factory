from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import DraftArtifact, Idea
from .render_manifest import ManifestError, build_render_manifest
from .renderer import RenderError, render_manifest_to_mp4
from .repository import (
    ActiveJobExistsError,
    IdeaNotFoundError,
    NoActiveJobError,
    add_idea,
    cancel_active_job,
    clear_ideas,
    discard_active_job,
    get_active_job,
    get_idea,
    get_latest_draft_artifact,
    get_latest_render_manifest,
    list_ideas,
    save_draft_artifact,
    save_render_manifest,
    save_video_script,
    start_job,
)
from .review import (
    ReviewError,
    approve_active_review,
    get_active_review_summary,
    reject_active_review,
    revise_active_review,
)
from .script_generator import GeneratedScript, UnsupportedTopicError, generate_script
from .uploads import (
    UploadError,
    get_upload_status,
    mark_upload_failed,
    mark_upload_succeeded,
    prepare_upload_packet,
    start_upload_handoff,
)


@dataclass(frozen=True)
class TelegramReplyOption:
    label: str
    value: str


@dataclass(frozen=True)
class TelegramCommandResult:
    ok: bool
    message: str
    media_path: str | None = None
    media_type: str | None = None
    reply_options: list[TelegramReplyOption] | None = None


def handle_review_message(
    db_path: Path,
    artifacts_dir: Path,
    message: str,
    watermark_text: str = "Trivia Clip Factory",
    voiceover_provider: str = "none",
) -> TelegramCommandResult:
    text = message.strip()
    normalized = text.lower()
    try:
        if normalized in {"help", "/help", "commands"}:
            return TelegramCommandResult(ok=True, message=_help_message())
        if normalized in {"cancel", "no", "never mind", "nevermind"}:
            return TelegramCommandResult(ok=True, message="No changes made.")
        if normalized in {"status", "publish status"}:
            return _status(db_path)
        if normalized in {"uploads status", "upload status"}:
            return _uploads_status(db_path)
        if normalized in {"upload packet", "prepare upload", "prepare upload packet", "uploads prepare"}:
            return _upload_packet(db_path, artifacts_dir)
        if normalized in {"uploads next", "upload next", "upload approved", "upload approved draft"}:
            return _upload_next(db_path)
        upload_confirm = _upload_confirm_from_message(text)
        if upload_confirm is not None:
            job_id, reference = upload_confirm
            return _upload_confirm(db_path, job_id, reference)
        upload_failure = _upload_failure_from_message(text)
        if upload_failure is not None:
            job_id, error_message = upload_failure
            return _upload_fail(db_path, job_id, error_message)
        if normalized in {"ideas", "list ideas", "queue"}:
            return _list_ideas(db_path)
        if normalized.startswith("save idea "):
            return _save_idea(db_path, text[len("save idea ") :].strip())
        if normalized.startswith("add idea "):
            return _save_idea(db_path, text[len("add idea ") :].strip())
        if normalized.startswith("idea:"):
            return _save_idea(db_path, text[len("idea:") :].strip())
        if normalized == "produce next":
            return _produce(db_path, artifacts_dir, None, watermark_text, voiceover_provider)
        if normalized.startswith("produce "):
            return _produce(
                db_path,
                artifacts_dir,
                text[len("produce ") :].strip(),
                watermark_text,
                voiceover_provider,
            )
        if normalized in {"cancel active", "cancel job"}:
            return _cancel_active(db_path)
        if normalized in {"discard active", "discard job"}:
            return _confirmation_prompt(
                command="discard active",
                note="NOTE: You are getting rid of the oldest active task.",
                question="Confirm discard active?",
                yes_value="confirm discard active",
            )
        if normalized in {"confirm discard active", "confirm discard job"}:
            return _discard_active(db_path)
        if normalized in {"regenerate active", "regenerate draft"}:
            return _regenerate_active(db_path, artifacts_dir, watermark_text, voiceover_provider)
        clear_scope = _clear_scope_from_message(normalized)
        if clear_scope is not None:
            return _clear_confirmation_prompt(clear_scope)
        confirmed_clear_scope = _confirmed_clear_scope_from_message(normalized)
        if confirmed_clear_scope is not None:
            return _clear_ideas(db_path, confirmed_clear_scope)
        if normalized in {"show draft", "draft", "review"}:
            summary = get_active_review_summary(db_path)
            if summary.draft is None:
                return TelegramCommandResult(ok=True, message="No MP4 draft exists yet for the active job.")
            return TelegramCommandResult(
                ok=True,
                message=(
                    "Draft ready for review.\n"
                    f"Job: {summary.job.id}\n"
                    f"Draft: {summary.draft.path}\n"
                    "Reply with approve, reject, or revise CHANGE."
                ),
                media_path=summary.draft.path,
                media_type="video",
            )
        if normalized in {"approve", "approve draft", "approved"}:
            event = approve_active_review(db_path)
            return TelegramCommandResult(
                ok=True,
                message=f"Approved draft for job {event.job_id}. Publishing remains blocked until the upload phase.",
            )
        if normalized in {"reject", "reject draft", "rejected"}:
            event = reject_active_review(db_path)
            return TelegramCommandResult(ok=True, message=f"Rejected draft for job {event.job_id}.")
        if normalized.startswith("revise "):
            requested_change = text[len("revise ") :].strip()
            return _revise(db_path, artifacts_dir, requested_change, voiceover_provider)
        if normalized.startswith("request changes "):
            requested_change = text[len("request changes ") :].strip()
            return _revise(db_path, artifacts_dir, requested_change, voiceover_provider)
    except ReviewError as error:
        return TelegramCommandResult(ok=False, message=str(error))
    except UploadError as error:
        return TelegramCommandResult(ok=False, message=str(error))

    conversational_result = _handle_conversational_message(
        db_path=db_path,
        artifacts_dir=artifacts_dir,
        text=text,
        watermark_text=watermark_text,
        voiceover_provider=voiceover_provider,
    )
    if conversational_result is not None:
        return conversational_result

    clarification = _clarification_prompt(text)
    if clarification is not None:
        return clarification

    return _unknown_direction_response()


def _help_message() -> str:
    return (
        "TikTok Trivia commands:\n"
        "- status\n"
        "- save idea PROMPT\n"
        "- ideas\n"
        "- produce next\n"
        "- show draft\n"
        "- revise CHANGE\n"
        "- regenerate active\n"
        "- approve\n"
        "- reject\n"
        "- uploads status\n"
        "- upload packet\n"
        "- upload approved\n"
        "- discard active\n"
        "- clear ideas\n"
        "\nYou can also ask naturally, like show me status or save 15 NBA Finals trivia questions."
    )


def _handle_conversational_message(
    db_path: Path,
    artifacts_dir: Path,
    text: str,
    watermark_text: str,
    voiceover_provider: str,
) -> TelegramCommandResult | None:
    commands = _conversation_commands(text)
    if not commands:
        return None

    results: list[TelegramCommandResult] = []
    for command in commands:
        results.append(
            handle_review_message(
                db_path=db_path,
                artifacts_dir=artifacts_dir,
                message=command,
                watermark_text=watermark_text,
                voiceover_provider=voiceover_provider,
            )
        )
    return _combine_conversation_results(results)


def _combine_conversation_results(results: list[TelegramCommandResult]) -> TelegramCommandResult:
    ok = all(result.ok for result in results)
    media_path: str | None = None
    media_type: str | None = None
    reply_options: list[TelegramReplyOption] | None = None
    messages: list[str] = []
    for result in results:
        messages.append(result.message)
        if result.media_path is not None:
            media_path = result.media_path
            media_type = result.media_type
        if result.reply_options is not None:
            reply_options = result.reply_options

    return TelegramCommandResult(
        ok=ok,
        message="\n\n".join(messages),
        media_path=media_path,
        media_type=media_type,
        reply_options=reply_options,
    )


def _conversation_commands(text: str) -> list[str]:
    normalized = _normalize_text(text)
    matches: list[tuple[int, str]] = []

    for position, command in _simple_conversation_commands(normalized):
        matches.append((position, command))

    save_match = _extract_save_idea_command(text)
    if save_match is not None:
        matches.append(save_match)

    revision_match = _extract_revision_command(text, normalized)
    if revision_match is not None:
        matches.append(revision_match)

    ordered: list[str] = []
    seen: set[str] = set()
    for _position, command in sorted(matches, key=lambda item: item[0]):
        if command not in seen:
            ordered.append(command)
            seen.add(command)
    return ordered


def _simple_conversation_commands(normalized: str) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    _append_match(candidates, normalized, r"\b(?:show|send|tell|give|what is|what's).{0,40}\bstatus\b", "status")
    _append_match(candidates, normalized, r"\b(?:how|what).{0,40}\b(?:jobs?|workflow|production).{0,20}\b(?:doing|looking|status)\b", "status")
    _append_match(candidates, normalized, r"\bwhere are we(?: at)?\b", "status")
    _append_match(candidates, normalized, r"\b(?:show|list|view|see|what are|what's).{0,40}\b(?:ideas|queue)\b", "ideas")
    _append_match(candidates, normalized, r"\b(?:produce|start|make|create|render|generate).{0,50}\b(?:next|queued|draft|video)\b", "produce next")
    _append_match(candidates, normalized, r"\b(?:show|send|view|watch).{0,30}\b(?:draft|preview|video)\b", "show draft")
    _append_match(candidates, normalized, r"\b(?:regenerate|redo|rebuild|rerender|re-render).{0,40}\b(?:active|current|draft|video|job)\b", "regenerate active")
    _append_match(candidates, normalized, r"\b(?:approve|approved|accept|looks good|good to go)\b", "approve")
    _append_match(candidates, normalized, r"\b(?:reject|rejected|decline|not good)\b", "reject")
    _append_match(candidates, normalized, r"\b(?:prepare|create|build|generate).{0,40}\bupload.{0,30}\b(?:packet|metadata|json)\b", "upload packet")
    _append_match(candidates, normalized, r"\bupload.{0,40}\b(?:approved|next|tiktok|draft)\b", "upload approved")
    _append_match(candidates, normalized, r"\b(?:discard|get rid of).{0,40}\b(?:active|current|draft|job|task)\b", "discard active")

    clear_match = re.search(r"\b(?:clear|delete|remove).{0,30}?\b(active|queued|queue|all|ideas)\b", normalized)
    if clear_match:
        scope = clear_match.group(1)
        if scope == "queue":
            scope = "queued"
        elif scope == "ideas":
            scope = "all"
        candidates.append((clear_match.start(), f"clear {scope}"))

    return candidates


def _append_match(candidates: list[tuple[int, str]], normalized: str, pattern: str, command: str) -> None:
    match = re.search(pattern, normalized)
    if match:
        candidates.append((match.start(), command))


def _extract_save_idea_command(text: str) -> tuple[int, str] | None:
    patterns = (
        r"\b(?:save|add|queue|remember)\s+(?:this\s+)?(?:idea|video idea|content idea)(?:\s+(?:of|for|about|as|:))?\s+(?P<prompt>.+)",
        r"\b(?:save|add|queue|remember)\s+(?P<prompt>\d+\s+.+)",
        r"\b(?:i have|i've got|got|have)\s+(?:an?\s+)?(?:idea|video idea|content idea).{0,80}?\b(?P<prompt>\d+\s+(?:trivia\s+)?questions?\s+(?:about|on)\s+.+)",
        r"\b(?:maybe\s+)?(?:we|you)\s+can\s+(?:do|make|create|produce).{0,60}?\b(?P<prompt>\d+\s+(?:trivia\s+)?questions?\s+(?:about|on)\s+.+)",
        r"\b(?:short-form\s+)?video\s+(?:asking|with|about).{0,40}?\b(?P<prompt>\d+\s+(?:trivia\s+)?questions?\s+(?:about|on)\s+.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            prompt = _normalize_idea_prompt(match.group("prompt"))
            if prompt:
                return match.start(), f"save idea {prompt}"
    return None


def _normalize_idea_prompt(prompt: str) -> str:
    clean = prompt.strip().strip(" .!?")
    clean = re.split(
        r"\b(?:and then|then|and)\s+(?:produce|start|show|list|clear|discard|regenerate|approve|reject)\b",
        clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip().strip(" .!?")
    clean = re.sub(r"^(?:having|to do|doing|make|making|a video about|an idea for)\s+", "", clean, flags=re.IGNORECASE)

    question_topic = re.fullmatch(
        r"(?P<count>\d+)\s+(?:trivia\s+)?questions?\s+(?:about|on)\s+(?P<topic>.+)",
        clean,
        flags=re.IGNORECASE,
    )
    if question_topic:
        return f"{question_topic.group('count')} trivia questions about {question_topic.group('topic').strip()}"

    topic_trivia = re.fullmatch(
        r"(?P<count>\d+)\s+(?P<topic>.+?)\s+trivia\s+questions?",
        clean,
        flags=re.IGNORECASE,
    )
    if topic_trivia:
        return f"{topic_trivia.group('count')} trivia questions about {topic_trivia.group('topic').strip()}"

    topic_questions = re.fullmatch(
        r"(?P<count>\d+)\s+(?P<topic>.+?)\s+questions?",
        clean,
        flags=re.IGNORECASE,
    )
    if topic_questions:
        return f"{topic_questions.group('count')} trivia questions about {topic_questions.group('topic').strip()}"

    return clean


def _extract_revision_command(text: str, normalized: str) -> tuple[int, str] | None:
    match = re.search(
        r"\b(?:make it faster|make this faster|make it shorter|shorten it|change hook\b.+|change background\b.+)",
        normalized,
    )
    if match is None:
        return None
    requested_change = text[match.start() :].strip().strip(" .!?")
    return match.start(), f"revise {requested_change}"


def _upload_confirm_from_message(text: str) -> tuple[str, str | None] | None:
    match = re.fullmatch(
        r"(?:confirm upload|upload succeeded|uploaded)\s+(?P<job_id>job_[a-f0-9]{12})(?:\s+(?P<reference>.+))?",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    reference = match.group("reference")
    return match.group("job_id"), None if reference is None else reference.strip()


def _upload_failure_from_message(text: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"(?:upload failed|failed upload)\s+(?P<job_id>job_[a-f0-9]{12})\s+(?P<error>.+)",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group("job_id"), match.group("error").strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _clarification_prompt(text: str) -> TelegramCommandResult | None:
    normalized = _normalize_text(text)
    if "nba finals" not in normalized:
        return None
    if not any(keyword in normalized for keyword in ("trivia", "question", "video", "idea", "content")):
        return None

    return TelegramCommandResult(
        ok=True,
        message=(
            "I heard an NBA Finals trivia idea, but I need one detail before saving it.\n\n"
            "Do you want NBA Finals statistics trivia or NBA Finals player trivia?"
        ),
        reply_options=[
            TelegramReplyOption(label="Stats trivia", value="save idea 10 trivia questions about NBA Finals statistics"),
            TelegramReplyOption(label="Player trivia", value="save idea 10 trivia questions about NBA Finals players"),
            TelegramReplyOption(label="Cancel", value="cancel"),
        ],
    )


def _unknown_direction_response() -> TelegramCommandResult:
    return TelegramCommandResult(
        ok=False,
        message=(
            "Sorry, I was unable to get the directions. Please try again in clearer natural language, "
            "or use one of these command formats:\n\n"
            "1. status\n"
            "2. ideas\n"
            "3. save idea PROMPT\n"
            "4. produce next\n"
            "5. show draft\n"
            "6. revise CHANGE\n"
            "7. regenerate active\n"
            "8. approve\n"
            "9. reject\n"
            "10. uploads status\n"
            "11. upload packet\n"
            "12. upload approved\n"
            "13. discard active\n"
            "14. clear active\n"
            "15. clear queued\n\n"
            "Examples:\n"
            "- save idea 10 trivia questions about FIFA World Cup\n"
            "- show me the status and save this idea of having 15 questions about NBA Finals statistics\n"
            "- please start the next queued video"
        ),
    )


def _status(db_path: Path) -> TelegramCommandResult:
    active = get_active_job(db_path)
    queued = list_ideas(db_path, status="queued")
    upload_status = get_upload_status(db_path)
    upload_summary = f"Approved awaiting upload: {len(upload_status.candidates)}."
    if active is None:
        return TelegramCommandResult(
            ok=True,
            message=f"No active job. Queued ideas: {len(queued)}. {upload_summary}",
        )

    draft = get_latest_draft_artifact(db_path, active.id)
    manifest = get_latest_render_manifest(db_path, active.id)
    return TelegramCommandResult(
        ok=True,
        message=(
            f"Active job: {active.id}\n"
            f"Idea: {active.idea_id}\n"
            f"Manifest: {'ready' if manifest else 'missing'}\n"
            f"Draft: {draft.path if draft else 'missing'}\n"
            f"Queued ideas: {len(queued)}\n"
            f"{upload_summary}"
        ),
    )


def _uploads_status(db_path: Path) -> TelegramCommandResult:
    status = get_upload_status(db_path)
    if not status.candidates:
        recent = status.recent_attempts[0] if status.recent_attempts else None
        suffix = "" if recent is None else f" Last upload attempt: {recent.status} for {recent.job_id}."
        return TelegramCommandResult(ok=True, message=f"No approved drafts are awaiting upload.{suffix}")

    lines = ["Approved drafts awaiting TikTok upload:"]
    for candidate in status.candidates[:10]:
        latest = candidate.latest_attempt.status if candidate.latest_attempt is not None else "none"
        lines.append(f"- {candidate.job.id}: {candidate.idea.prompt} (latest upload: {latest})")
    if len(status.candidates) > 10:
        lines.append(f"...and {len(status.candidates) - 10} more.")
    lines.append("Reply upload approved to hand off the oldest approved draft.")
    return TelegramCommandResult(ok=True, message="\n".join(lines))


def _upload_packet(db_path: Path, artifacts_dir: Path) -> TelegramCommandResult:
    packet = prepare_upload_packet(db_path, uploads_dir=artifacts_dir.parent / "uploads")
    draft_path = packet.candidate.draft.path
    reused = "Existing upload packet reused." if packet.reused_existing_pending else "Upload packet prepared."
    return TelegramCommandResult(
        ok=True,
        message=(
            f"{reused}\n"
            f"Job: {packet.candidate.job.id}\n"
            f"Idea: {packet.candidate.idea.prompt}\n"
            f"Packet: {packet.packet_path}\n"
            f"Draft: {draft_path}\n"
            "Use the packet for the TikTok inbox upload runner, then reply "
            f"upload succeeded {packet.candidate.job.id} REFERENCE or "
            f"upload failed {packet.candidate.job.id} REASON."
        ),
        media_path=draft_path,
        media_type="video",
    )


def _upload_next(db_path: Path) -> TelegramCommandResult:
    handoff = start_upload_handoff(db_path)
    draft_path = handoff.candidate.draft.path
    reused = "Existing pending upload handoff." if handoff.reused_existing_pending else "Upload handoff started."
    return TelegramCommandResult(
        ok=True,
        message=(
            f"{reused}\n"
            f"Job: {handoff.candidate.job.id}\n"
            f"Idea: {handoff.candidate.idea.prompt}\n"
            f"Draft: {draft_path}\n"
            "Upload this MP4 to TikTok inbox/drafts, then reply "
            f"upload succeeded {handoff.candidate.job.id} REFERENCE or "
            f"upload failed {handoff.candidate.job.id} REASON."
        ),
        media_path=draft_path,
        media_type="video",
    )


def _upload_confirm(db_path: Path, job_id: str, reference: str | None) -> TelegramCommandResult:
    attempt = mark_upload_succeeded(db_path, job_id=job_id, provider_reference=reference)
    reference_text = "" if attempt.provider_reference is None else f" Reference: {attempt.provider_reference}."
    return TelegramCommandResult(
        ok=True,
        message=f"Marked upload succeeded for job {attempt.job_id}.{reference_text}",
    )


def _upload_fail(db_path: Path, job_id: str, error_message: str) -> TelegramCommandResult:
    attempt = mark_upload_failed(db_path, job_id=job_id, error_message=error_message)
    return TelegramCommandResult(
        ok=True,
        message=f"Marked upload failed for job {attempt.job_id}: {attempt.error_message}",
    )


def _save_idea(db_path: Path, prompt: str) -> TelegramCommandResult:
    if not prompt:
        return TelegramCommandResult(ok=False, message="Tell me the idea after save idea.")
    try:
        idea = add_idea(db_path, prompt, source="telegram")
    except ValueError as error:
        return TelegramCommandResult(ok=False, message=str(error))
    return TelegramCommandResult(ok=True, message=f"Saved idea {idea.id}: {idea.prompt}")


def _list_ideas(db_path: Path) -> TelegramCommandResult:
    ideas = list_ideas(db_path)
    actionable = [idea for idea in ideas if idea.status in {"active", "queued"}]
    hidden_count = len(ideas) - len(actionable)
    if not actionable:
        message = "No active or queued ideas."
        if hidden_count:
            message += f" Hidden completed or cancelled ideas: {hidden_count}."
        return TelegramCommandResult(ok=True, message=message)

    lines = ["Saved ideas:"]
    for idea in actionable[:10]:
        lines.append(f"- {idea.id} [{idea.status}] {idea.prompt}")
    if len(actionable) > 10:
        lines.append(f"...and {len(actionable) - 10} more active or queued ideas.")
    if hidden_count:
        lines.append(f"Hidden completed or cancelled ideas: {hidden_count}.")
    return TelegramCommandResult(ok=True, message="\n".join(lines))


def _produce(
    db_path: Path,
    artifacts_dir: Path,
    idea_id: str | None,
    watermark_text: str,
    voiceover_provider: str,
) -> TelegramCommandResult:
    try:
        active = get_active_job(db_path)
        if active is not None:
            return TelegramCommandResult(
                ok=False,
                message=(
                    "A production job is already active.\n"
                    f"Job: {active.id}\n"
                    f"Idea: {active.idea_id}\n"
                    "Reply show draft, approve, revise CHANGE, regenerate active, discard active, or cancel active."
                ),
            )

        selected_idea = _select_idea(db_path, idea_id)
        if selected_idea is None:
            return TelegramCommandResult(ok=False, message="No queued ideas are available to produce.")

        generated = generate_script(selected_idea.prompt)
        job = start_job(db_path, selected_idea.id)
        draft = _render_new_draft_for_job(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            job_id=job.id,
            prompt=selected_idea.prompt,
            watermark_text=watermark_text,
            voiceover_provider=voiceover_provider,
            generated_script=generated,
        )
    except (
        ActiveJobExistsError,
        IdeaNotFoundError,
        UnsupportedTopicError,
        ManifestError,
        RenderError,
    ) as error:
        return TelegramCommandResult(ok=False, message=str(error))

    return TelegramCommandResult(
        ok=True,
        message=(
            "Draft produced for review.\n"
            f"Job: {job.id}\n"
            f"Idea: {selected_idea.prompt}\n"
            f"Draft: {draft.path}\n"
            "Reply approve, reject, or revise CHANGE."
        ),
        media_path=draft.path,
        media_type="video",
    )


def _select_idea(db_path: Path, idea_id: str | None) -> Idea | None:
    if idea_id:
        return get_idea(db_path, idea_id)
    queued = list_ideas(db_path, status="queued")
    return queued[0] if queued else None


def _cancel_active(db_path: Path) -> TelegramCommandResult:
    try:
        job = cancel_active_job(db_path)
    except NoActiveJobError as error:
        return TelegramCommandResult(ok=False, message=str(error))
    return TelegramCommandResult(ok=True, message=f"Cancelled active job {job.id} and returned its idea to the queue.")


def _discard_active(db_path: Path) -> TelegramCommandResult:
    try:
        job = discard_active_job(db_path)
    except NoActiveJobError as error:
        return TelegramCommandResult(ok=False, message=str(error))
    return TelegramCommandResult(ok=True, message=f"Discarded active job {job.id}. Its idea was not requeued.")


def _clear_ideas(db_path: Path, scope: str) -> TelegramCommandResult:
    result = clear_ideas(db_path, scope)
    return TelegramCommandResult(
        ok=True,
        message=(
            f"Cleared {result.ideas_cleared} {result.scope} idea(s). "
            f"Cancelled active jobs: {result.active_jobs_cancelled}."
        ),
    )


def _confirmation_prompt(
    command: str,
    note: str,
    question: str,
    yes_value: str,
) -> TelegramCommandResult:
    return TelegramCommandResult(
        ok=True,
        message=f"{command}\n\n{note}\n\n{question}",
        reply_options=[
            TelegramReplyOption(label="Yes", value=yes_value),
            TelegramReplyOption(label="No", value="cancel"),
        ],
    )


def _clear_confirmation_prompt(scope: str) -> TelegramCommandResult:
    if scope == "active":
        return _confirmation_prompt(
            command="clear active",
            note="NOTE: You are clearing ALL active tasks.",
            question="Confirm clear active?",
            yes_value="confirm clear active",
        )
    return _confirmation_prompt(
        command=f"clear {scope}",
        note=f"NOTE: You are clearing ALL {scope} ideas.",
        question=f"Confirm clear {scope}?",
        yes_value=f"confirm clear {scope}",
    )


def _regenerate_active(
    db_path: Path,
    artifacts_dir: Path,
    watermark_text: str,
    voiceover_provider: str,
) -> TelegramCommandResult:
    try:
        active = get_active_job(db_path)
        if active is None:
            raise NoActiveJobError("No active production job")
        idea = get_idea(db_path, active.idea_id)
        draft = _render_new_draft_for_job(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            job_id=active.id,
            prompt=idea.prompt,
            watermark_text=watermark_text,
            voiceover_provider=voiceover_provider,
        )
    except (
        NoActiveJobError,
        IdeaNotFoundError,
        UnsupportedTopicError,
        ManifestError,
        RenderError,
    ) as error:
        return TelegramCommandResult(ok=False, message=str(error))

    return TelegramCommandResult(
        ok=True,
        message=(
            "Active draft regenerated with the latest script and render rules.\n"
            f"Job: {active.id}\n"
            f"Draft: {draft.path}\n"
            "Reply approve, reject, or revise CHANGE."
        ),
        media_path=draft.path,
        media_type="video",
    )


def _revise(
    db_path: Path,
    artifacts_dir: Path,
    requested_change: str,
    voiceover_provider: str,
) -> TelegramCommandResult:
    if not requested_change:
        return TelegramCommandResult(ok=False, message="Tell me what to revise after revise.")
    try:
        result = revise_active_review(
            db_path,
            artifacts_dir=artifacts_dir,
            requested_change=requested_change,
            preview=True,
            voiceover_provider=voiceover_provider,
        )
        return TelegramCommandResult(
            ok=True,
            message=(
                "Revision rendered.\n"
                f"Applied: {', '.join(result.applied_changes)}\n"
                f"Draft: {result.draft.path}"
            ),
            media_path=result.draft.path,
            media_type="video",
        )
    except ReviewError as error:
        return TelegramCommandResult(ok=False, message=str(error))


def _render_new_draft_for_job(
    db_path: Path,
    artifacts_dir: Path,
    job_id: str,
    prompt: str,
    watermark_text: str,
    voiceover_provider: str = "none",
    generated_script: GeneratedScript | None = None,
) -> DraftArtifact:
    generated = generated_script or generate_script(prompt)
    script = save_video_script(
        db_path,
        job_id=job_id,
        script_json=generated.script_json,
        provider=generated.provider,
        confidence=generated.confidence,
        citations=generated.citations,
    )
    generated_manifest = build_render_manifest(script.script_json, watermark_text=watermark_text)
    manifest = save_render_manifest(
        db_path,
        job_id=job_id,
        manifest_json=generated_manifest.manifest_json,
        provider=generated_manifest.provider,
    )
    output_path = artifacts_dir / job_id / f"draft_r{manifest.revision:03d}.mp4"
    render_manifest_to_mp4(
        manifest.manifest_json,
        output_path,
        preview=True,
        voiceover_provider=voiceover_provider,
    )
    return save_draft_artifact(
        db_path,
        job_id=job_id,
        revision=manifest.revision,
        artifact_type="mp4",
        path=str(output_path),
    )


def _clear_scope_from_message(normalized: str) -> str | None:
    match normalized:
        case "clear ideas":
            return "all"
        case "clear active" | "clear ideas active":
            return "active"
        case "clear queued" | "clear queue" | "clear ideas queued":
            return "queued"
        case "clear all" | "clear ideas all":
            return "all"
        case _:
            return None


def _confirmed_clear_scope_from_message(normalized: str) -> str | None:
    match normalized:
        case "confirm clear active" | "confirm clear ideas active":
            return "active"
        case "confirm clear queued" | "confirm clear queue" | "confirm clear ideas queued":
            return "queued"
        case "confirm clear all" | "confirm clear ideas" | "confirm clear ideas all":
            return "all"
        case _:
            return None
