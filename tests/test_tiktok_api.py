from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tiktok_trivia_factory.tiktok_api import (
    STATUS_URL,
    TOKEN_URL,
    UPLOAD_INIT_URL,
    TikTokCredentials,
    TikTokTokenSet,
    create_oauth_session,
    exchange_authorization_code,
    fetch_publish_status,
    init_file_upload,
    load_tiktok_credentials,
    load_tokens,
    refresh_access_token,
    save_tokens,
    token_status_payload,
)


class TikTokApiTests(unittest.TestCase):
    def test_load_tiktok_credentials_reads_dotenv_without_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text(
                "\n".join(
                    [
                        "TIKTOK_CLIENT_KEY=client-key",
                        "TIKTOK_CLIENT_SECRET=client-secret",
                        "TIKTOK_REDIRECT_URI=http://127.0.0.1:3455/callback/",
                        "TIKTOK_SCOPES=user.info.basic,video.upload",
                        "TIKTOK_ACCOUNT_NAME=Trivia Clip Factory",
                    ]
                ),
                encoding="utf-8",
            )

            credentials = load_tiktok_credentials(Path(temp_dir), environ={})

        self.assertEqual(credentials.client_key, "client-key")
        self.assertEqual(credentials.client_secret, "client-secret")
        self.assertEqual(credentials.redirect_uri, "http://127.0.0.1:3455/callback/")
        self.assertEqual(credentials.scopes, "user.info.basic,video.upload")
        self.assertEqual(credentials.account_name, "Trivia Clip Factory")

    def test_create_oauth_session_builds_pkce_authorization_url(self) -> None:
        credentials = _credentials()
        session = create_oauth_session(
            credentials,
            state="state-1",
            code_verifier="verifier-1",
            now=123,
        )
        query = parse_qs(urlparse(session.auth_url).query)

        self.assertEqual(query["client_key"], ["client-key"])
        self.assertEqual(query["scope"], ["user.info.basic,video.upload"])
        self.assertEqual(query["redirect_uri"], [credentials.redirect_uri])
        self.assertEqual(query["state"], ["state-1"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(
            query["code_challenge"],
            [hashlib.sha256(b"verifier-1").hexdigest()],
        )
        self.assertEqual(session.created_at, 123)

    def test_exchange_authorization_code_uses_saved_pkce_verifier(self) -> None:
        credentials = _credentials()
        session = create_oauth_session(credentials, state="state", code_verifier="verifier", now=100)
        calls: list[tuple[str, dict[str, str]]] = []

        def post_form(url: str, form: object) -> dict[str, object]:
            calls.append((url, dict(form)))  # type: ignore[arg-type]
            return {
                "open_id": "open-id",
                "scope": "user.info.basic,video.upload",
                "access_token": "access-token",
                "expires_in": 86400,
                "refresh_token": "refresh-token",
                "refresh_expires_in": 31536000,
                "token_type": "Bearer",
            }

        token_set = exchange_authorization_code(credentials, "auth-code", session, now=1000, post_form=post_form)

        self.assertEqual(calls[0][0], TOKEN_URL)
        self.assertEqual(calls[0][1]["grant_type"], "authorization_code")
        self.assertEqual(calls[0][1]["code"], "auth-code")
        self.assertEqual(calls[0][1]["code_verifier"], "verifier")
        self.assertEqual(token_set.expires_at, 87400)
        self.assertEqual(token_set.refresh_expires_at, 31537000)

    def test_refresh_access_token_saves_new_expiry_window(self) -> None:
        credentials = _credentials()
        existing = TikTokTokenSet(
            open_id="open-id",
            scope="user.info.basic,video.upload",
            access_token="old-token",
            expires_at=10,
            refresh_token="refresh-token",
            refresh_expires_at=999999,
            token_type="Bearer",
        )

        def post_form(url: str, form: object) -> dict[str, object]:
            self.assertEqual(url, TOKEN_URL)
            self.assertEqual(dict(form)["grant_type"], "refresh_token")  # type: ignore[arg-type]
            return {
                "open_id": "open-id",
                "scope": "user.info.basic,video.upload",
                "access_token": "new-token",
                "expires_in": 86400,
                "refresh_token": "new-refresh",
                "refresh_expires_in": 31536000,
                "token_type": "Bearer",
            }

        refreshed = refresh_access_token(credentials, existing, now=2000, post_form=post_form)

        self.assertEqual(refreshed.access_token, "new-token")
        self.assertEqual(refreshed.expires_at, 88400)
        self.assertEqual(refreshed.refresh_token, "new-refresh")

    def test_token_storage_and_status_do_not_expose_token_values(self) -> None:
        credentials = _credentials()
        token_set = TikTokTokenSet(
            open_id="open-id",
            scope="user.info.basic,video.upload",
            access_token="secret-access-token",
            expires_at=1000,
            refresh_token="secret-refresh-token",
            refresh_expires_at=2000,
            token_type="Bearer",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            save_tokens(Path(temp_dir), token_set)
            loaded = load_tokens(Path(temp_dir))

        status = token_status_payload(credentials, loaded, now=500)
        serialized = json.dumps(status)
        self.assertTrue(status["token_present"])
        self.assertNotIn("secret-access-token", serialized)
        self.assertNotIn("secret-refresh-token", serialized)

    def test_init_file_upload_uses_single_chunk_file_upload_body(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "draft.mp4"
            video_path.write_bytes(b"1234567890")
            calls: list[tuple[str, str, dict[str, object]]] = []

            def post_json(url: str, access_token: str, payload: object) -> dict[str, object]:
                calls.append((url, access_token, dict(payload)))  # type: ignore[arg-type]
                return {
                    "data": {
                        "publish_id": "publish-id",
                        "upload_url": "https://upload.example/video",
                    },
                    "error": {"code": "ok", "message": ""},
                }

            result = init_file_upload("access-token", video_path, post_json=post_json)

        self.assertEqual(result.publish_id, "publish-id")
        self.assertEqual(calls[0][0], UPLOAD_INIT_URL)
        self.assertEqual(calls[0][1], "access-token")
        self.assertEqual(calls[0][2]["source_info"]["source"], "FILE_UPLOAD")  # type: ignore[index]
        self.assertEqual(calls[0][2]["source_info"]["video_size"], 10)  # type: ignore[index]
        self.assertEqual(calls[0][2]["source_info"]["total_chunk_count"], 1)  # type: ignore[index]

    def test_fetch_publish_status_parses_tiktok_status(self) -> None:
        calls: list[tuple[str, str, dict[str, object]]] = []

        def post_json(url: str, access_token: str, payload: object) -> dict[str, object]:
            calls.append((url, access_token, dict(payload)))  # type: ignore[arg-type]
            return {
                "data": {
                    "status": "SEND_TO_USER_INBOX",
                    "uploaded_bytes": 123,
                    "publicaly_available_post_id": [],
                },
                "error": {"code": "ok", "message": ""},
            }

        status = fetch_publish_status("access-token", "publish-id", post_json=post_json)

        self.assertEqual(calls[0][0], STATUS_URL)
        self.assertEqual(calls[0][2]["publish_id"], "publish-id")
        self.assertEqual(status.status, "SEND_TO_USER_INBOX")
        self.assertEqual(status.uploaded_bytes, 123)


def _credentials() -> TikTokCredentials:
    return TikTokCredentials(
        client_key="client-key",
        client_secret="client-secret",
        redirect_uri="http://127.0.0.1:3455/callback/",
        scopes="user.info.basic,video.upload",
        environment="sandbox",
        account_name="Trivia Clip Factory",
    )


if __name__ == "__main__":
    unittest.main()
