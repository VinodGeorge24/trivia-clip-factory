# TikTok API Upload Setup

Phase 8.6 adds a CLI-first official TikTok Content Posting API upload path.
It uploads only approved MP4 drafts to the TikTok inbox/draft flow. It does not
enable Direct Post and does not public-post automatically.

## Local Configuration

Put real values only in local `.env`:

```text
TIKTOK_ENV=sandbox
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=http://127.0.0.1:3455/callback/
TIKTOK_SCOPES=user.info.basic,video.upload
TIKTOK_ACCOUNT_NAME=Trivia Clip Factory
```

Keep `.env`, `var/tiktok/tokens.json`, and `var/tiktok/oauth_session.json`
out of git. They contain local credentials or OAuth material.

## OAuth

Preferred desktop flow:

```powershell
python -m tiktok_trivia_factory tiktok auth-listen
```

This starts a localhost callback server, opens TikTok authorization, exchanges
the callback code, and saves tokens under `var/tiktok/tokens.json`.

Manual fallback:

```powershell
python -m tiktok_trivia_factory tiktok auth-url
python -m tiktok_trivia_factory tiktok auth-exchange CODE_FROM_REDIRECT_URL
```

Check redacted token state:

```powershell
python -m tiktok_trivia_factory tiktok auth-status
python -m tiktok_trivia_factory tiktok auth-refresh
```

These commands never print access tokens, refresh tokens, or client secrets.

## Upload

Dry-run the approved draft selection first:

```powershell
python -m tiktok_trivia_factory uploads send --dry-run
```

Send the approved MP4 through TikTok FILE_UPLOAD:

```powershell
python -m tiktok_trivia_factory uploads send --job-id JOB_ID
```

Check TikTok processing status:

```powershell
python -m tiktok_trivia_factory uploads check JOB_ID
```

Expected TikTok success states are `SEND_TO_USER_INBOX` and
`PUBLISH_COMPLETE`. For the default inbox flow, the operator still finishes
reviewing/editing/posting inside TikTok after the upload is accepted.

## Boundary

- Only approved drafts are selectable.
- Successful uploads remove the draft from the awaiting-upload list.
- Failed uploads are recorded and remain retryable.
- Existing Telegram upload commands remain manual handoff commands for now.
- Direct Post stays disabled unless explicitly added in a later phase.
