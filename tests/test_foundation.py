from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tiktok_trivia_factory.cli import main
from tiktok_trivia_factory.config import load_settings
from tiktok_trivia_factory.database import initialize_database, probe_database


class FoundationTests(unittest.TestCase):
    def test_load_settings_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(cwd=Path(temp_dir), environ={})

        self.assertEqual(settings.data_dir.name, "var")
        self.assertEqual(settings.db_path.name, "trivia_factory.sqlite3")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.voiceover_provider, "none")
        self.assertIsNone(settings.trivia_bank_path)

    def test_load_settings_accepts_windows_sapi_voiceover_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(
                cwd=Path(temp_dir),
                environ={"TTF_VOICEOVER_PROVIDER": "windows_sapi"},
            )

        self.assertEqual(settings.voiceover_provider, "windows_sapi")

    def test_load_settings_accepts_trivia_bank_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = load_settings(
                cwd=Path(temp_dir),
                environ={"TTF_TRIVIA_BANK_PATH": "questions.txt"},
            )

        self.assertEqual(settings.trivia_bank_path, (Path(temp_dir) / "questions.txt").resolve())

    def test_database_initializes_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "state.sqlite3"
            initialize_database(db_path)
            probe_database(db_path)

            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute(
                    "SELECT value FROM app_meta WHERE key = 'schema_version'"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(version, ("4",))

    def test_cli_smoke_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / "runtime.sqlite3"
            settings_env = {"TTF_DATA_DIR": temp_dir, "TTF_DB_PATH": str(env_path)}
            old_cwd = Path.cwd()
            try:
                # main() reads process environment and cwd, so use a temporary cwd
                # while keeping all runtime state out of the repository.
                import os

                old_env = {key: os.environ.get(key) for key in settings_env}
                os.environ.update(settings_env)
                os.chdir(temp_dir)
                exit_code = main(["smoke"])
            finally:
                os.chdir(old_cwd)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
