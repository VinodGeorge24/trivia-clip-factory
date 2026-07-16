from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .database import initialize_database
from .models import (
    ApprovalEvent,
    DraftArtifact,
    Idea,
    ProductionJob,
    RenderManifest,
    RevisionEvent,
    SourceCitation,
    SourceCitationDraft,
    UploadAttempt,
    VideoScript,
)


class ActiveJobExistsError(RuntimeError):
    pass


class IdeaNotFoundError(RuntimeError):
    pass


class NoActiveJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClearIdeasResult:
    scope: str
    active_jobs_cancelled: int
    ideas_cleared: int


def add_idea(db_path: Path, prompt: str, source: str = "cli", notes: str | None = None) -> Idea:
    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("Idea prompt cannot be empty")

    idea_id = f"idea_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO ideas (id, prompt, source, notes)
            VALUES (?, ?, ?, ?)
            """,
            (idea_id, clean_prompt, source, notes),
        )
        connection.commit()
        return _get_idea(connection, idea_id)


def list_ideas(db_path: Path, status: str | None = None) -> list[Idea]:
    with _connect(db_path) as connection:
        if status is None:
            rows = connection.execute(
                """
                SELECT id, prompt, source, status, notes, created_at, updated_at
                FROM ideas
                ORDER BY created_at ASC, rowid ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, prompt, source, status, notes, created_at, updated_at
                FROM ideas
                WHERE status = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (status,),
            ).fetchall()
    return [_idea_from_row(row) for row in rows]


def start_job(db_path: Path, idea_id: str) -> ProductionJob:
    job_id = f"job_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        idea = connection.execute(
            "SELECT id, status FROM ideas WHERE id = ?",
            (idea_id,),
        ).fetchone()
        if idea is None:
            raise IdeaNotFoundError(f"Idea not found: {idea_id}")

        try:
            connection.execute(
                """
                INSERT INTO production_jobs (id, idea_id, status)
                VALUES (?, ?, 'active')
                """,
                (job_id, idea_id),
            )
        except sqlite3.IntegrityError as error:
            if "idx_one_active_production_job" in str(error) or "UNIQUE" in str(error):
                raise ActiveJobExistsError("A production job is already active") from error
            raise

        connection.execute(
            """
            UPDATE ideas
            SET status = 'active', updated_at = datetime('now')
            WHERE id = ?
            """,
            (idea_id,),
        )
        connection.commit()
        return _get_job(connection, job_id)


def get_active_job(db_path: Path) -> ProductionJob | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, idea_id, status, created_at, updated_at, completed_at
            FROM production_jobs
            WHERE status = 'active'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return None if row is None else _job_from_row(row)


def cancel_active_job(db_path: Path) -> ProductionJob:
    with _connect(db_path) as connection:
        active = connection.execute(
            """
            SELECT id, idea_id, status, created_at, updated_at, completed_at
            FROM production_jobs
            WHERE status = 'active'
            LIMIT 1
            """
        ).fetchone()
        if active is None:
            raise NoActiveJobError("No active production job")

        job = _job_from_row(active)
        connection.execute(
            """
            UPDATE production_jobs
            SET status = 'cancelled', updated_at = datetime('now'), completed_at = datetime('now')
            WHERE id = ?
            """,
            (job.id,),
        )
        connection.execute(
            """
            UPDATE ideas
            SET status = 'queued', updated_at = datetime('now')
            WHERE id = ?
            """,
            (job.idea_id,),
        )
        connection.commit()
        return _get_job(connection, job.id)


def discard_active_job(db_path: Path) -> ProductionJob:
    with _connect(db_path) as connection:
        active = connection.execute(
            """
            SELECT id, idea_id, status, created_at, updated_at, completed_at
            FROM production_jobs
            WHERE status = 'active'
            LIMIT 1
            """
        ).fetchone()
        if active is None:
            raise NoActiveJobError("No active production job")

        job = _job_from_row(active)
        connection.execute(
            """
            UPDATE production_jobs
            SET status = 'cancelled', updated_at = datetime('now'), completed_at = datetime('now')
            WHERE id = ?
            """,
            (job.id,),
        )
        connection.execute(
            """
            UPDATE ideas
            SET status = 'cancelled', updated_at = datetime('now')
            WHERE id = ?
            """,
            (job.idea_id,),
        )
        connection.commit()
        return _get_job(connection, job.id)


def clear_ideas(db_path: Path, scope: str) -> ClearIdeasResult:
    if scope not in {"active", "queued", "all"}:
        raise ValueError(f"Unsupported clear scope: {scope}")

    target_statuses = ("active", "queued") if scope == "all" else (scope,)
    with _connect(db_path) as connection:
        active_jobs_cancelled = 0
        if scope in {"active", "all"}:
            cursor = connection.execute(
                """
                UPDATE production_jobs
                SET status = 'cancelled', updated_at = datetime('now'), completed_at = datetime('now')
                WHERE status = 'active'
                """
            )
            active_jobs_cancelled = cursor.rowcount

        placeholders = ", ".join("?" for _ in target_statuses)
        cursor = connection.execute(
            f"""
            UPDATE ideas
            SET status = 'cancelled', updated_at = datetime('now')
            WHERE status IN ({placeholders})
            """,
            target_statuses,
        )
        ideas_cleared = cursor.rowcount
        connection.commit()

    return ClearIdeasResult(
        scope=scope,
        active_jobs_cancelled=active_jobs_cancelled,
        ideas_cleared=ideas_cleared,
    )


def get_idea(db_path: Path, idea_id: str) -> Idea:
    with _connect(db_path) as connection:
        return _get_idea(connection, idea_id)


def save_video_script(
    db_path: Path,
    job_id: str,
    script_json: str,
    provider: str,
    confidence: float,
    citations: list[SourceCitationDraft],
) -> VideoScript:
    script_id = f"script_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        revision = _next_script_revision(connection, job_id)
        connection.execute(
            """
            INSERT INTO video_scripts (id, job_id, revision, script_json, provider, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (script_id, job_id, revision, script_json, provider, confidence),
        )
        for citation in citations:
            connection.execute(
                """
                INSERT INTO source_citations
                    (id, script_id, label, source_type, reference, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cite_{uuid4().hex[:12]}",
                    script_id,
                    citation.label,
                    citation.source_type,
                    citation.reference,
                    citation.confidence,
                ),
            )
        connection.commit()
        return _get_video_script(connection, script_id)


def get_latest_video_script(db_path: Path, job_id: str) -> VideoScript | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, revision, script_json, provider, confidence, created_at
            FROM video_scripts
            WHERE job_id = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _video_script_from_row(row)


def list_source_citations(db_path: Path, script_id: str) -> list[SourceCitation]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, script_id, label, source_type, reference, confidence, created_at
            FROM source_citations
            WHERE script_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (script_id,),
        ).fetchall()
    return [_source_citation_from_row(row) for row in rows]


def save_render_manifest(
    db_path: Path,
    job_id: str,
    manifest_json: str,
    provider: str,
) -> RenderManifest:
    manifest_id = f"manifest_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        revision = _next_manifest_revision(connection, job_id)
        connection.execute(
            """
            INSERT INTO render_manifests (id, job_id, revision, manifest_json, provider)
            VALUES (?, ?, ?, ?, ?)
            """,
            (manifest_id, job_id, revision, manifest_json, provider),
        )
        connection.commit()
        return _get_render_manifest(connection, manifest_id)


def get_latest_render_manifest(db_path: Path, job_id: str) -> RenderManifest | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, revision, manifest_json, provider, created_at
            FROM render_manifests
            WHERE job_id = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _render_manifest_from_row(row)


def save_draft_artifact(
    db_path: Path,
    job_id: str,
    revision: int,
    artifact_type: str,
    path: str,
) -> DraftArtifact:
    artifact_id = f"draft_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO draft_artifacts (id, job_id, revision, artifact_type, path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (artifact_id, job_id, revision, artifact_type, path),
        )
        connection.commit()
        return _get_draft_artifact(connection, artifact_id)


def get_latest_draft_artifact(db_path: Path, job_id: str) -> DraftArtifact | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, revision, artifact_type, path, created_at
            FROM draft_artifacts
            WHERE job_id = ? AND artifact_type = 'mp4'
            ORDER BY revision DESC, created_at DESC, rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _draft_artifact_from_row(row)


def save_revision_event(db_path: Path, job_id: str, requested_change: str) -> RevisionEvent:
    event_id = f"rev_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO revision_events (id, job_id, requested_change)
            VALUES (?, ?, ?)
            """,
            (event_id, job_id, requested_change),
        )
        connection.commit()
        return _get_revision_event(connection, event_id)


def save_approval_event(db_path: Path, job_id: str, decision: str) -> ApprovalEvent:
    if decision not in {"approved", "rejected"}:
        raise ValueError(f"Unsupported approval decision: {decision}")

    event_id = f"approval_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        job = _get_job(connection, job_id)
        connection.execute(
            """
            INSERT INTO approval_events (id, job_id, decision)
            VALUES (?, ?, ?)
            """,
            (event_id, job_id, decision),
        )
        if decision == "approved":
            connection.execute(
                """
                UPDATE production_jobs
                SET status = 'completed', updated_at = datetime('now'), completed_at = datetime('now')
                WHERE id = ?
                """,
                (job_id,),
            )
            connection.execute(
                """
                UPDATE ideas
                SET status = 'completed', updated_at = datetime('now')
                WHERE id = ?
                """,
                (job.idea_id,),
            )
        else:
            connection.execute(
                """
                UPDATE production_jobs
                SET status = 'cancelled', updated_at = datetime('now'), completed_at = datetime('now')
                WHERE id = ?
                """,
                (job_id,),
            )
            connection.execute(
                """
                UPDATE ideas
                SET status = 'queued', updated_at = datetime('now')
                WHERE id = ?
                """,
                (job.idea_id,),
            )
        connection.commit()
        return _get_approval_event(connection, event_id)


def get_latest_approval_event(db_path: Path, job_id: str) -> ApprovalEvent | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, decision, created_at
            FROM approval_events
            WHERE job_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _approval_event_from_row(row)


def save_upload_attempt(
    db_path: Path,
    job_id: str,
    provider: str,
    status: str,
    provider_reference: str | None = None,
    error_message: str | None = None,
) -> UploadAttempt:
    if status not in {"pending", "succeeded", "failed"}:
        raise ValueError(f"Unsupported upload status: {status}")

    attempt_id = f"upload_{uuid4().hex[:12]}"
    with _connect(db_path) as connection:
        _get_job(connection, job_id)
        connection.execute(
            """
            INSERT INTO upload_attempts
                (id, job_id, provider, status, provider_reference, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (attempt_id, job_id, provider, status, provider_reference, error_message),
        )
        connection.commit()
        return _get_upload_attempt(connection, attempt_id)


def get_latest_upload_attempt(db_path: Path, job_id: str) -> UploadAttempt | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, provider, status, provider_reference, error_message, created_at, updated_at
            FROM upload_attempts
            WHERE job_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _upload_attempt_from_row(row)


def get_successful_upload_attempt(db_path: Path, job_id: str) -> UploadAttempt | None:
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, job_id, provider, status, provider_reference, error_message, created_at, updated_at
            FROM upload_attempts
            WHERE job_id = ? AND status = 'succeeded'
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    return None if row is None else _upload_attempt_from_row(row)


def list_upload_attempts(db_path: Path, limit: int = 20) -> list[UploadAttempt]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, job_id, provider, status, provider_reference, error_message, created_at, updated_at
            FROM upload_attempts
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_upload_attempt_from_row(row) for row in rows]


def list_approved_jobs_with_drafts(db_path: Path) -> list[tuple[ProductionJob, Idea, DraftArtifact]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                j.id, j.idea_id, j.status, j.created_at, j.updated_at, j.completed_at,
                i.id, i.prompt, i.source, i.status, i.notes, i.created_at, i.updated_at,
                d.id, d.job_id, d.revision, d.artifact_type, d.path, d.created_at
            FROM production_jobs j
            JOIN ideas i ON i.id = j.idea_id
            JOIN approval_events a ON a.job_id = j.id AND a.decision = 'approved'
            JOIN draft_artifacts d ON d.job_id = j.id AND d.artifact_type = 'mp4'
            WHERE j.status = 'completed'
              AND a.rowid = (
                SELECT MAX(a2.rowid)
                FROM approval_events a2
                WHERE a2.job_id = j.id
              )
              AND d.rowid = (
                SELECT d2.rowid
                FROM draft_artifacts d2
                WHERE d2.job_id = j.id AND d2.artifact_type = 'mp4'
                ORDER BY d2.revision DESC, d2.created_at DESC, d2.rowid DESC
                LIMIT 1
              )
            ORDER BY j.completed_at ASC, j.rowid ASC
            """
        ).fetchall()

    result: list[tuple[ProductionJob, Idea, DraftArtifact]] = []
    for row in rows:
        result.append(
            (
                _job_from_row(row[0:6]),
                _idea_from_row(row[6:13]),
                _draft_artifact_from_row(row[13:19]),
            )
        )
    return result


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    initialize_database(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
    finally:
        connection.close()


def _get_idea(connection: sqlite3.Connection, idea_id: str) -> Idea:
    row = connection.execute(
        """
        SELECT id, prompt, source, status, notes, created_at, updated_at
        FROM ideas
        WHERE id = ?
        """,
        (idea_id,),
    ).fetchone()
    if row is None:
        raise IdeaNotFoundError(f"Idea not found: {idea_id}")
    return _idea_from_row(row)


def _get_job(connection: sqlite3.Connection, job_id: str) -> ProductionJob:
    row = connection.execute(
        """
        SELECT id, idea_id, status, created_at, updated_at, completed_at
        FROM production_jobs
        WHERE id = ?
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Production job not found: {job_id}")
    return _job_from_row(row)


def _get_video_script(connection: sqlite3.Connection, script_id: str) -> VideoScript:
    row = connection.execute(
        """
        SELECT id, job_id, revision, script_json, provider, confidence, created_at
        FROM video_scripts
        WHERE id = ?
        """,
        (script_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Video script not found: {script_id}")
    return _video_script_from_row(row)


def _get_render_manifest(connection: sqlite3.Connection, manifest_id: str) -> RenderManifest:
    row = connection.execute(
        """
        SELECT id, job_id, revision, manifest_json, provider, created_at
        FROM render_manifests
        WHERE id = ?
        """,
        (manifest_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Render manifest not found: {manifest_id}")
    return _render_manifest_from_row(row)


def _get_draft_artifact(connection: sqlite3.Connection, artifact_id: str) -> DraftArtifact:
    row = connection.execute(
        """
        SELECT id, job_id, revision, artifact_type, path, created_at
        FROM draft_artifacts
        WHERE id = ?
        """,
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Draft artifact not found: {artifact_id}")
    return _draft_artifact_from_row(row)


def _get_revision_event(connection: sqlite3.Connection, event_id: str) -> RevisionEvent:
    row = connection.execute(
        """
        SELECT id, job_id, requested_change, created_at
        FROM revision_events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Revision event not found: {event_id}")
    return _revision_event_from_row(row)


def _get_approval_event(connection: sqlite3.Connection, event_id: str) -> ApprovalEvent:
    row = connection.execute(
        """
        SELECT id, job_id, decision, created_at
        FROM approval_events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Approval event not found: {event_id}")
    return _approval_event_from_row(row)


def _get_upload_attempt(connection: sqlite3.Connection, attempt_id: str) -> UploadAttempt:
    row = connection.execute(
        """
        SELECT id, job_id, provider, status, provider_reference, error_message, created_at, updated_at
        FROM upload_attempts
        WHERE id = ?
        """,
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Upload attempt not found: {attempt_id}")
    return _upload_attempt_from_row(row)


def _next_script_revision(connection: sqlite3.Connection, job_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(revision), 0) + 1 FROM video_scripts WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return 1
    return int(row[0])


def _next_manifest_revision(connection: sqlite3.Connection, job_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(revision), 0) + 1 FROM render_manifests WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return 1
    return int(row[0])


def _idea_from_row(row: tuple[str, str, str, str, str | None, str, str]) -> Idea:
    return Idea(
        id=row[0],
        prompt=row[1],
        source=row[2],
        status=row[3],
        notes=row[4],
        created_at=row[5],
        updated_at=row[6],
    )


def _job_from_row(row: tuple[str, str, str, str, str, str | None]) -> ProductionJob:
    return ProductionJob(
        id=row[0],
        idea_id=row[1],
        status=row[2],
        created_at=row[3],
        updated_at=row[4],
        completed_at=row[5],
    )


def _video_script_from_row(row: tuple[str, str, int, str, str, float, str]) -> VideoScript:
    return VideoScript(
        id=row[0],
        job_id=row[1],
        revision=row[2],
        script_json=row[3],
        provider=row[4],
        confidence=row[5],
        created_at=row[6],
    )


def _render_manifest_from_row(row: tuple[str, str, int, str, str, str]) -> RenderManifest:
    return RenderManifest(
        id=row[0],
        job_id=row[1],
        revision=row[2],
        manifest_json=row[3],
        provider=row[4],
        created_at=row[5],
    )


def _draft_artifact_from_row(row: tuple[str, str, int, str, str, str]) -> DraftArtifact:
    return DraftArtifact(
        id=row[0],
        job_id=row[1],
        revision=row[2],
        artifact_type=row[3],
        path=row[4],
        created_at=row[5],
    )


def _revision_event_from_row(row: tuple[str, str, str, str]) -> RevisionEvent:
    return RevisionEvent(
        id=row[0],
        job_id=row[1],
        requested_change=row[2],
        created_at=row[3],
    )


def _approval_event_from_row(row: tuple[str, str, str, str]) -> ApprovalEvent:
    return ApprovalEvent(
        id=row[0],
        job_id=row[1],
        decision=row[2],
        created_at=row[3],
    )


def _upload_attempt_from_row(row: tuple[str, str, str, str, str | None, str | None, str, str]) -> UploadAttempt:
    return UploadAttempt(
        id=row[0],
        job_id=row[1],
        provider=row[2],
        status=row[3],
        provider_reference=row[4],
        error_message=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


def _source_citation_from_row(row: tuple[str, str, str, str, str, float, str]) -> SourceCitation:
    return SourceCitation(
        id=row[0],
        script_id=row[1],
        label=row[2],
        source_type=row[3],
        reference=row[4],
        confidence=row[5],
        created_at=row[6],
    )
