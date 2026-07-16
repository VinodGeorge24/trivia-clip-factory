from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 4


def initialize_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        _create_base_schema(connection)
        _set_schema_version(connection)
        connection.commit()
    finally:
        connection.close()


def probe_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        result = connection.execute("SELECT 1").fetchone()
        if result != (1,):
            raise RuntimeError("SQLite probe failed")
    finally:
        connection.close()


def _create_base_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ideas (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'cli',
            status TEXT NOT NULL DEFAULT 'queued',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (status IN ('queued', 'active', 'completed', 'cancelled'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS production_jobs (
            id TEXT PRIMARY KEY,
            idea_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE RESTRICT,
            CHECK (status IN ('active', 'completed', 'cancelled', 'failed'))
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_production_job
        ON production_jobs(status)
        WHERE status = 'active'
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS video_scripts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            script_json TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'local_seed',
            confidence REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE,
            UNIQUE (job_id, revision)
        )
        """
    )
    _ensure_column(connection, "video_scripts", "provider", "TEXT NOT NULL DEFAULT 'local_seed'")
    _ensure_column(connection, "video_scripts", "confidence", "REAL NOT NULL DEFAULT 0.0")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS render_manifests (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            manifest_json TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'manifest_v1',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE,
            UNIQUE (job_id, revision)
        )
        """
    )
    _ensure_column(connection, "render_manifests", "provider", "TEXT NOT NULL DEFAULT 'manifest_v1'")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS draft_artifacts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS revision_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            requested_change TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE,
            CHECK (decision IN ('approved', 'rejected'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_attempts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'tiktok',
            status TEXT NOT NULL,
            provider_reference TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE,
            CHECK (status IN ('pending', 'succeeded', 'failed'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            captured_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES production_jobs(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_citations (
            id TEXT PRIMARY KEY,
            script_id TEXT NOT NULL,
            label TEXT NOT NULL,
            source_type TEXT NOT NULL,
            reference TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (script_id) REFERENCES video_scripts(id) ON DELETE CASCADE
        )
        """
    )


def _set_schema_version(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    connection.execute(
        """
        INSERT INTO app_meta (key, value, updated_at)
        VALUES ('schema_version', ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (str(SCHEMA_VERSION),),
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {row[1] for row in rows}
    if column_name not in existing_columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
