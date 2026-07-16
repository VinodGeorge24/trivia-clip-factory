from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Idea:
    id: str
    prompt: str
    source: str
    status: str
    notes: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProductionJob:
    id: str
    idea_id: str
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class VideoScript:
    id: str
    job_id: str
    revision: int
    script_json: str
    provider: str
    confidence: float
    created_at: str


@dataclass(frozen=True)
class RenderManifest:
    id: str
    job_id: str
    revision: int
    manifest_json: str
    provider: str
    created_at: str


@dataclass(frozen=True)
class DraftArtifact:
    id: str
    job_id: str
    revision: int
    artifact_type: str
    path: str
    created_at: str


@dataclass(frozen=True)
class RevisionEvent:
    id: str
    job_id: str
    requested_change: str
    created_at: str


@dataclass(frozen=True)
class ApprovalEvent:
    id: str
    job_id: str
    decision: str
    created_at: str


@dataclass(frozen=True)
class UploadAttempt:
    id: str
    job_id: str
    provider: str
    status: str
    provider_reference: str | None
    error_message: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SourceCitation:
    id: str
    script_id: str
    label: str
    source_type: str
    reference: str
    confidence: float
    created_at: str


@dataclass(frozen=True)
class SourceCitationDraft:
    label: str
    source_type: str
    reference: str
    confidence: float
