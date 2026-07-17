from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ENV_FILE = ".env"
DEFAULT_DATA_DIR = "var"
DEFAULT_DB_PATH = "var/trivia_factory.sqlite3"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WATERMARK_TEXT = "Trivia Clip Factory"
DEFAULT_VOICEOVER_PROVIDER = "none"
DEFAULT_TRIVIA_BANK_PATH = ""
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
VALID_VOICEOVER_PROVIDERS = {"none", "windows_sapi"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    artifacts_dir: Path
    logs_dir: Path
    tmp_dir: Path
    log_level: str
    watermark_text: str
    voiceover_provider: str
    trivia_bank_path: Path | None


def load_settings(cwd: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    base_dir = (cwd or Path.cwd()).resolve()
    raw_env = dict(environ if environ is not None else os.environ)
    raw_env.update(_load_dotenv(base_dir / ENV_FILE))

    data_dir = _resolve_path(base_dir, raw_env.get("TTF_DATA_DIR", DEFAULT_DATA_DIR))
    db_path = _resolve_path(base_dir, raw_env.get("TTF_DB_PATH", DEFAULT_DB_PATH))
    log_level = raw_env.get("TTF_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    watermark_text = raw_env.get("TTF_WATERMARK_TEXT", DEFAULT_WATERMARK_TEXT).strip()
    voiceover_provider = raw_env.get("TTF_VOICEOVER_PROVIDER", DEFAULT_VOICEOVER_PROVIDER).strip().lower()
    trivia_bank_path = raw_env.get("TTF_TRIVIA_BANK_PATH", DEFAULT_TRIVIA_BANK_PATH).strip()

    if log_level not in VALID_LOG_LEVELS:
        raise ValueError(f"Invalid TTF_LOG_LEVEL: {log_level}")
    if voiceover_provider not in VALID_VOICEOVER_PROVIDERS:
        raise ValueError(f"Invalid TTF_VOICEOVER_PROVIDER: {voiceover_provider}")

    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        artifacts_dir=data_dir / "artifacts",
        logs_dir=data_dir / "logs",
        tmp_dir=data_dir / "tmp",
        log_level=log_level,
        watermark_text=watermark_text or DEFAULT_WATERMARK_TEXT,
        voiceover_provider=voiceover_provider,
        trivia_bank_path=None if not trivia_bank_path else _resolve_path(base_dir, trivia_bank_path),
    )


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
