from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .config import ENV_FILE, _load_dotenv


AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
TOKEN_REFRESH_SKEW_SECONDS = 300
TIKTOK_DIR_NAME = "tiktok"
TOKEN_FILE_NAME = "tokens.json"
OAUTH_SESSION_FILE_NAME = "oauth_session.json"


class TikTokApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class TikTokCredentials:
    client_key: str
    client_secret: str
    redirect_uri: str
    scopes: str
    environment: str
    account_name: str


@dataclass(frozen=True)
class OAuthSession:
    state: str
    code_verifier: str
    code_challenge: str
    redirect_uri: str
    scopes: str
    created_at: int
    auth_url: str


@dataclass(frozen=True)
class TikTokTokenSet:
    open_id: str
    scope: str
    access_token: str
    expires_at: int
    refresh_token: str | None
    refresh_expires_at: int | None
    token_type: str


@dataclass(frozen=True)
class UploadInitResult:
    publish_id: str
    upload_url: str


@dataclass(frozen=True)
class TikTokUploadStatus:
    publish_id: str
    status: str
    fail_reason: str | None
    publicaly_available_post_id: list[str]
    uploaded_bytes: int | None
    raw: dict[str, Any]


def load_tiktok_credentials(
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TikTokCredentials:
    base_dir = (cwd or Path.cwd()).resolve()
    raw_env = dict(environ if environ is not None else os.environ)
    raw_env.update(_load_dotenv(base_dir / ENV_FILE))

    client_key = raw_env.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = raw_env.get("TIKTOK_CLIENT_SECRET", "").strip()
    redirect_uri = raw_env.get("TIKTOK_REDIRECT_URI", "").strip()
    scopes = raw_env.get("TIKTOK_SCOPES", "user.info.basic,video.upload").strip()
    environment = raw_env.get("TIKTOK_ENV", "sandbox").strip() or "sandbox"
    account_name = raw_env.get("TIKTOK_ACCOUNT_NAME", "Trivia Clip Factory").strip() or "Trivia Clip Factory"

    missing = [
        name
        for name, value in (
            ("TIKTOK_CLIENT_KEY", client_key),
            ("TIKTOK_CLIENT_SECRET", client_secret),
            ("TIKTOK_REDIRECT_URI", redirect_uri),
            ("TIKTOK_SCOPES", scopes),
        )
        if not value
    ]
    if missing:
        raise TikTokApiError(f"Missing TikTok configuration: {', '.join(missing)}")

    return TikTokCredentials(
        client_key=client_key,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        environment=environment,
        account_name=account_name,
    )


def create_oauth_session(
    credentials: TikTokCredentials,
    state: str | None = None,
    code_verifier: str | None = None,
    now: int | None = None,
) -> OAuthSession:
    verifier = code_verifier or secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("utf-8")).hexdigest()
    session_state = state or secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_key": credentials.client_key,
            "scope": credentials.scopes,
            "response_type": "code",
            "redirect_uri": credentials.redirect_uri,
            "state": session_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return OAuthSession(
        state=session_state,
        code_verifier=verifier,
        code_challenge=challenge,
        redirect_uri=credentials.redirect_uri,
        scopes=credentials.scopes,
        created_at=now if now is not None else int(time.time()),
        auth_url=f"{AUTH_URL}?{query}",
    )


def save_oauth_session(data_dir: Path, session: OAuthSession) -> Path:
    path = _oauth_session_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(session), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_oauth_session(data_dir: Path) -> OAuthSession:
    path = _oauth_session_path(data_dir)
    if not path.exists():
        raise TikTokApiError("No saved TikTok OAuth session. Run `tiktok auth-url` or `tiktok auth-listen` first.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return OAuthSession(
        state=str(payload["state"]),
        code_verifier=str(payload["code_verifier"]),
        code_challenge=str(payload["code_challenge"]),
        redirect_uri=str(payload["redirect_uri"]),
        scopes=str(payload["scopes"]),
        created_at=int(payload["created_at"]),
        auth_url=str(payload["auth_url"]),
    )


def exchange_authorization_code(
    credentials: TikTokCredentials,
    code: str,
    session: OAuthSession,
    *,
    now: int | None = None,
    post_form: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
) -> TikTokTokenSet:
    payload = _post_form(
        TOKEN_URL,
        {
            "client_key": credentials.client_key,
            "client_secret": credentials.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": session.redirect_uri,
            "code_verifier": session.code_verifier,
        },
        post_form=post_form,
    )
    return _token_set_from_response(payload, now=now)


def refresh_access_token(
    credentials: TikTokCredentials,
    token_set: TikTokTokenSet,
    *,
    now: int | None = None,
    post_form: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
) -> TikTokTokenSet:
    if not token_set.refresh_token:
        raise TikTokApiError("No TikTok refresh token is available. Re-run OAuth authorization.")
    payload = _post_form(
        TOKEN_URL,
        {
            "client_key": credentials.client_key,
            "client_secret": credentials.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token_set.refresh_token,
        },
        post_form=post_form,
    )
    return _token_set_from_response(payload, now=now)


def save_tokens(data_dir: Path, token_set: TikTokTokenSet) -> Path:
    path = _token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(token_set), indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_tokens(data_dir: Path) -> TikTokTokenSet:
    path = _token_path(data_dir)
    if not path.exists():
        raise TikTokApiError("No TikTok token file found. Run `tiktok auth-listen` or `tiktok auth-exchange CODE`.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TikTokTokenSet(
        open_id=str(payload["open_id"]),
        scope=str(payload["scope"]),
        access_token=str(payload["access_token"]),
        expires_at=int(payload["expires_at"]),
        refresh_token=None if payload.get("refresh_token") is None else str(payload["refresh_token"]),
        refresh_expires_at=None
        if payload.get("refresh_expires_at") is None
        else int(payload["refresh_expires_at"]),
        token_type=str(payload.get("token_type", "Bearer")),
    )


def load_tokens_if_present(data_dir: Path) -> TikTokTokenSet | None:
    try:
        return load_tokens(data_dir)
    except TikTokApiError:
        return None


def ensure_access_token(
    credentials: TikTokCredentials,
    data_dir: Path,
    *,
    now: int | None = None,
    post_form: Callable[[str, Mapping[str, str]], dict[str, Any]] | None = None,
) -> TikTokTokenSet:
    current_time = now if now is not None else int(time.time())
    token_set = load_tokens(data_dir)
    if token_set.expires_at - TOKEN_REFRESH_SKEW_SECONDS > current_time:
        return token_set
    refreshed = refresh_access_token(credentials, token_set, now=current_time, post_form=post_form)
    save_tokens(data_dir, refreshed)
    return refreshed


def init_file_upload(
    access_token: str,
    video_path: Path,
    *,
    post_json: Callable[[str, str, Mapping[str, Any]], dict[str, Any]] | None = None,
) -> UploadInitResult:
    if not video_path.is_file():
        raise TikTokApiError(f"Video file does not exist: {video_path}")
    video_size = video_path.stat().st_size
    if video_size <= 0:
        raise TikTokApiError(f"Video file is empty: {video_path}")
    payload = _post_json(
        UPLOAD_INIT_URL,
        access_token,
        {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            }
        },
        post_json=post_json,
    )
    data = _response_data(payload)
    publish_id = str(data.get("publish_id", "")).strip()
    upload_url = str(data.get("upload_url", "")).strip()
    if not publish_id or not upload_url:
        raise TikTokApiError("TikTok upload init response did not include publish_id and upload_url")
    return UploadInitResult(publish_id=publish_id, upload_url=upload_url)


def upload_video_file(
    upload_url: str,
    video_path: Path,
    *,
    put_file: Callable[[str, Path], None] | None = None,
) -> None:
    if put_file is not None:
        put_file(upload_url, video_path)
        return
    size = video_path.stat().st_size
    request = Request(
        upload_url,
        data=video_path.read_bytes(),
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        },
        method="PUT",
    )
    try:
        with urlopen(request, timeout=120) as response:
            response.read()
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise TikTokApiError(f"TikTok file upload failed with HTTP {error.code}: {body}") from error
    except URLError as error:
        raise TikTokApiError(f"TikTok file upload failed: {error.reason}") from error


def fetch_publish_status(
    access_token: str,
    publish_id: str,
    *,
    post_json: Callable[[str, str, Mapping[str, Any]], dict[str, Any]] | None = None,
) -> TikTokUploadStatus:
    payload = _post_json(
        STATUS_URL,
        access_token,
        {"publish_id": publish_id},
        post_json=post_json,
    )
    data = _response_data(payload)
    post_ids = data.get("publicaly_available_post_id", [])
    if not isinstance(post_ids, list):
        post_ids = []
    uploaded_bytes = data.get("uploaded_bytes")
    return TikTokUploadStatus(
        publish_id=publish_id,
        status=str(data.get("status", "")),
        fail_reason=None if data.get("fail_reason") is None else str(data["fail_reason"]),
        publicaly_available_post_id=[str(value) for value in post_ids],
        uploaded_bytes=None if uploaded_bytes is None else int(uploaded_bytes),
        raw=payload,
    )


def run_oauth_callback_server(
    credentials: TikTokCredentials,
    data_dir: Path,
    *,
    open_browser: bool = True,
    timeout_seconds: int = 300,
) -> TikTokTokenSet:
    session = create_oauth_session(credentials)
    save_oauth_session(data_dir, session)
    parsed = urlparse(credentials.redirect_uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port is None:
        raise TikTokApiError("TIKTOK_REDIRECT_URI must be a localhost URL with a fixed port for auth-listen.")

    result: dict[str, Any] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            error = query.get("error", [""])[0]
            if error:
                result["error"] = f"TikTok authorization failed: {error}"
                self._respond(400, "TikTok authorization failed. You can close this tab.")
                return
            if state != session.state:
                result["error"] = "TikTok authorization state did not match. OAuth flow was rejected."
                self._respond(400, "TikTok authorization state did not match. You can close this tab.")
                return
            if not code:
                result["error"] = "TikTok callback did not include an authorization code."
                self._respond(400, "TikTok callback did not include an authorization code.")
                return
            try:
                token_set = exchange_authorization_code(credentials, code, session)
                save_tokens(data_dir, token_set)
            except TikTokApiError as error_value:
                result["error"] = str(error_value)
                self._respond(500, "Token exchange failed. Return to Codex for details.")
                return
            result["token_set"] = token_set
            self._respond(200, "TikTok authorization complete. You can close this tab.")

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _respond(self, status: int, message: str) -> None:
            body = f"<!doctype html><title>TikTok Auth</title><p>{message}</p>".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer((parsed.hostname, parsed.port), CallbackHandler)
    server.timeout = timeout_seconds
    if open_browser:
        webbrowser.open(session.auth_url)
    server.handle_request()
    server.server_close()

    if "token_set" in result:
        return result["token_set"]
    if "error" in result:
        raise TikTokApiError(str(result["error"]))
    raise TikTokApiError("Timed out waiting for TikTok OAuth callback.")


def token_status_payload(
    credentials: TikTokCredentials,
    token_set: TikTokTokenSet | None,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    current_time = now if now is not None else int(time.time())
    if token_set is None:
        return {
            "configured": True,
            "environment": credentials.environment,
            "account_name": credentials.account_name,
            "token_present": False,
            "required_scopes": credentials.scopes,
        }
    return {
        "configured": True,
        "environment": credentials.environment,
        "account_name": credentials.account_name,
        "token_present": True,
        "open_id_present": bool(token_set.open_id),
        "scope": token_set.scope,
        "access_token_expires_at": token_set.expires_at,
        "access_token_expired": token_set.expires_at <= current_time,
        "refresh_token_present": bool(token_set.refresh_token),
        "refresh_token_expires_at": token_set.refresh_expires_at,
        "token_type": token_set.token_type,
    }


def _post_form(
    url: str,
    form: Mapping[str, str],
    *,
    post_form: Callable[[str, Mapping[str, str]], dict[str, Any]] | None,
) -> dict[str, Any]:
    if post_form is not None:
        return post_form(url, form)
    body = urlencode(form).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _send_json_request(request)


def _post_json(
    url: str,
    access_token: str,
    payload: Mapping[str, Any],
    *,
    post_json: Callable[[str, str, Mapping[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    if post_json is not None:
        return post_json(url, access_token, payload)
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    return _send_json_request(request)


def _send_json_request(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise TikTokApiError(f"TikTok API request failed with HTTP {error.code}: {body}") from error
    except URLError as error:
        raise TikTokApiError(f"TikTok API request failed: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise TikTokApiError("TikTok API response was not valid JSON") from error
    if not isinstance(payload, dict):
        raise TikTokApiError("TikTok API response was not a JSON object")
    _raise_for_tiktok_error(payload)
    return payload


def _raise_for_tiktok_error(payload: Mapping[str, Any]) -> None:
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return
    code = str(error.get("code", ""))
    if code and code != "ok":
        message = str(error.get("message", "") or error.get("log_id", "") or code)
        raise TikTokApiError(f"TikTok API error {code}: {message}")


def _response_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TikTokApiError("TikTok API response did not include a data object")
    return data


def _token_set_from_response(payload: Mapping[str, Any], *, now: int | None) -> TikTokTokenSet:
    required = ("open_id", "scope", "access_token", "expires_in", "token_type")
    missing = [name for name in required if name not in payload]
    if missing:
        raise TikTokApiError(f"TikTok token response missing fields: {', '.join(missing)}")
    current_time = now if now is not None else int(time.time())
    refresh_expires_in = payload.get("refresh_expires_in")
    return TikTokTokenSet(
        open_id=str(payload["open_id"]),
        scope=str(payload["scope"]),
        access_token=str(payload["access_token"]),
        expires_at=current_time + int(payload["expires_in"]),
        refresh_token=None if payload.get("refresh_token") is None else str(payload["refresh_token"]),
        refresh_expires_at=None if refresh_expires_in is None else current_time + int(refresh_expires_in),
        token_type=str(payload["token_type"]),
    )


def _token_path(data_dir: Path) -> Path:
    return data_dir / TIKTOK_DIR_NAME / TOKEN_FILE_NAME


def _oauth_session_path(data_dir: Path) -> Path:
    return data_dir / TIKTOK_DIR_NAME / OAUTH_SESSION_FILE_NAME
