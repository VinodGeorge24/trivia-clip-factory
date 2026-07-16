# Phase Roadmap

This roadmap tracks what is already implemented and what remains.

## Completed

- **Phase 1: Foundation** - Python package, CLI, runtime directories, smoke
  checks, and local configuration.
- **Phase 2: Persistence** - SQLite tables for ideas, jobs, scripts,
  manifests, drafts, review events, future uploads, analytics, and citations.
- **Phase 3: Local Script Generation** - Free offline seed-pack generation for
  supported trivia topics.
- **Phase 4: Render Manifest And MP4 Drafts** - 9:16 render manifests and
  preview MP4 generation.
- **Phase 4.5: Game-Show Format** - Real A/B/C choices, context-aware
  distractors, countdown/reveal pacing, and procedural audio.
- **Phase 5: Review Gate** - Show draft, revise, approve, and reject flows.
- **Phase 6: Telegram/OpenClaw Operator** - Repo-local Telegram command
  adapter for the existing global OpenClaw bot.
- **Phase 6.5: Telegram Media Preview** - Draft responses include `media_path`
  and `media_type` so OpenClaw can attach MP4s in Telegram.
- **Phase 6.7: Workflow State Controls** - Active-job guidance, regenerate
  active, discard active, clear controls, and Yes/No reply options.
- **Phase 6.8: Conversational Telegram Control** - Deterministic natural
  phrasing for common Telegram requests, including simple multi-intent status
  plus idea-save messages.
- **Phase 7: Research-Backed Trivia Generation** - Free provider fallback
  chain for researched topics, starting with NBA Finals and broad
  basketball/sports prompts. Direct providers are local seed packs,
  Wikimedia/Wikipedia, and Open Trivia DB; Codex and Gemini web search are
  recorded as last-resort agent-mediated fallbacks.
- **Phase 8: TikTok Upload Handoff** - Approved MP4 drafts can be listed for
  upload, handed off as pending TikTok inbox/manual upload attempts, and marked
  succeeded or failed with durable `upload_attempts` records. Telegram returns
  the draft media path for upload handoff and `status` reports approved drafts
  awaiting upload.
- **Phase 8.5: TikTok Inbox Automation Prep** - Approved MP4 drafts can be
  converted into TikTok inbox upload packets under `var/uploads/`. Packets
  include draft path, caption, hashtags, citations, required TikTok Upload API
  scope, and operator steps while preserving the approval gate and blocking
  public auto-posting.
- **Phase 8.6: Live TikTok Upload Runner** - Local CLI commands can create a
  TikTok sandbox OAuth session, save redacted-status token state under
  `var/tiktok/`, upload approved MP4 drafts through the official Content
  Posting API `FILE_UPLOAD` inbox flow, and check TikTok processing status.
  Direct Post remains disabled and Telegram remains the manual handoff surface.

## Remaining

- **Phase 9: Analytics And Performance Tracking** - Capture TikTok performance
  snapshots and connect outcomes back to topic, format, and pacing decisions.
- **Phase 10: Production Autopilot** - Use Telegram as the operating surface
  for idea intake, draft production, approval, upload handoff, and learning
  loops while preserving review gates.

## Phase 8 Detail: TikTok Upload Handoff

The goal is to take an already approved local MP4 draft and hand it to the
TikTok upload surface while recording every attempt locally.

Implementation should stay inside the repo-local workflow boundary:

- CLI commands: `uploads status`, `uploads next`, `uploads confirm JOB_ID`,
  and `uploads fail JOB_ID ERROR_MESSAGE`.
- Telegram commands: `uploads status`, `upload approved`,
  `upload succeeded JOB_ID REFERENCE`, and `upload failed JOB_ID REASON`.
- Select only jobs with an approved draft and no successful upload attempt.
- Record `upload_attempts` rows for pending, succeeded, and failed handoffs.
- Store provider references when TikTok or the upload surface returns one.
- Never upload an unapproved draft.
- Never print TikTok credentials, cookies, session data, or raw config.
- Prefer a dry-run or inbox-only handoff first, then make live upload explicit.
- Official API upload automation stays separate from OpenClaw Telegram
  transport and is documented under Phase 8.6.
- Return short Telegram responses and include actionable next commands.

## Phase 8.5 Detail: TikTok Inbox Automation Prep

The goal is to package an approved MP4 draft into a deterministic handoff file
that the official API upload runner or a manual operator can consume without
re-reading the whole database.

Implemented behavior:

- CLI command: `uploads prepare [--job-id JOB_ID]`.
- Telegram command: `upload packet`.
- Packet path: `var/uploads/JOB_ID/upload_packet.json`.
- Packet contents: job, idea, draft path, latest script summary, caption,
  hashtags, citations, TikTok inbox upload requirements, and operator steps.
- Upload attempt provider: `tiktok_upload_packet`.
- Public auto-posting is explicitly disabled.
- TikTok credentials, OAuth tokens, browser cookies, and session data are not
  stored in packet files or Telegram responses.

Current live-upload boundary:

- TikTok Direct Post is a separate path and should remain disabled unless the
  operator explicitly enables it after app review.
- The user must still finish editing/posting inside TikTok after an inbox/draft
  upload.

## Phase 8.6 Detail: Live TikTok Upload Runner

The goal is to use the official TikTok Content Posting API sandbox without
turning on public auto-posting.

Implemented behavior:

- CLI commands: `tiktok auth-url`, `tiktok auth-listen`,
  `tiktok auth-exchange CODE`, `tiktok auth-status`, and
  `tiktok auth-refresh`.
- CLI commands: `uploads send [--job-id JOB_ID] [--dry-run]` and
  `uploads check JOB_ID`.
- TikTok OAuth config remains in local `.env`; token files live under
  `var/tiktok/` and are ignored by git.
- `uploads send` selects only approved MP4 drafts with no successful upload
  attempt.
- The upload transport uses TikTok `FILE_UPLOAD` with the
  `/v2/post/publish/inbox/video/init/` endpoint.
- TikTok `publish_id` values are stored as provider references for
  `tiktok_api_file_upload` attempts.
- Before TikTok API upload, the latest approved manifest is rendered as a full
  publish-ready MP4 instead of sending the lower-FPS Telegram preview draft.
- Status checks record local success for `SEND_TO_USER_INBOX` or
  `PUBLISH_COMPLETE`, and local failure for `FAILED`.
- CLI auth/status outputs are redacted and never print access tokens, refresh
  tokens, or client secrets.

Current boundary:

- The API path uploads to TikTok inbox/drafts only. The user still approves and
  posts inside TikTok.
- Telegram does not trigger official API uploads yet; it continues to support
  packet preparation, manual media handoff, and outcome recording.
- Direct Post requires separate review, scope, UX, and operator approval before
  it should be added.

Acceptance criteria:

- `status` can distinguish queued, active, approved-awaiting-upload, uploaded,
  and failed-upload states.
- An approved draft can be selected and handed off without creating a new
  production job.
- Failed uploads leave enough local error detail to retry safely.
- Re-running the upload command does not duplicate a successful upload.
- Official TikTok API uploads use publish-ready media, not preview renders.
- Tests cover approval gating, idempotency, and upload-attempt persistence.

## Current Boundary

The application can produce and review local MP4 drafts through Telegram and can
research a narrow set of unsupported topics through free providers. Approved
drafts can be handed off for TikTok inbox/manual upload or uploaded through the
official TikTok API inbox flow from the CLI. The application does not yet fetch
live analytics, synthesize voiceover, perform open-ended web research for every
arbitrary topic automatically, or public-post directly to TikTok.

## Later Detail

Phase 9 should connect TikTok outcomes back to content decisions:

- Store analytics snapshots against production jobs.
- Track views, likes, comments, shares, watch time, retention, completion rate,
  and publish timing where available.
- Compare outcomes by topic, provider, script format, question count, pacing,
  and revision history.
- Keep source citations attached to research-backed scripts so low-confidence
  topics can be audited.

Phase 10 should borrow the useful parts of broader YouTube-style automation
without bypassing review:

- Add an automation event log for scheduled checks, generation attempts,
  upload attempts, and analytics pulls.
- Maintain a small production buffer, such as N approved drafts waiting for
  upload, before generating more.
- Use Telegram as the operator console for queue health, draft review, upload
  handoff, and learning-loop summaries.
- Keep the human approval gate before upload until explicitly changed.

Automation should be split into safe recurring jobs with clear ownership:

- **Maintenance scans:** run weekly dependency and vulnerability checks against
  the Python project, report outdated or vulnerable packages, and avoid
  changing dependencies without explicit approval.
- **Analytics scans:** run every few days after uploads exist, collect TikTok
  performance, summarize trends, and write durable snapshots before suggesting
  new topics or pacing changes.
- **Content inventory cleanup:** mark produced topics/questions as used after a
  successful upload so the factory does not repeat the same angle too soon.
- **Question bank growth:** periodically add 25-50 researched multiple-choice
  questions with one correct answer and source metadata.
- **Question bank rotation:** keep active unused question-bank files below a
  practical cap such as 2,000 unused questions, then start the next bank file.
- **Operator summaries:** send short Telegram summaries only when something
  needs attention, such as vulnerable dependencies, low content buffer, failed
  uploads, or strong analytics trends.

Suggested local data model for the autopilot phase:

- `automation_events`: every scheduled job run, status, duration, and summary.
- `question_banks`: topic bank files or future database-backed banks.
- `trivia_questions`: question text, three choices, correct choice, topic,
  source citation, status, and usage metadata.
- `topic_usage`: produced/uploaded topic angles with cooldown windows to avoid
  repetition.

The long-term operator goal is that Telegram can accept a request such as
`make 10 questions about Minecraft trivia`, ask for clarification only when
needed, produce an MP4 draft, hand approved media to the TikTok inbox/upload
flow, and keep enough researched content available that the user mainly manages
approval and direction.
