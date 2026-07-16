# OpenClaw Telegram Integration

This is the source of truth for how Telegram connects to this repository.

## Ownership Boundary

OpenClaw is the live Telegram transport for this project. This repository does
not own the gateway, Telegram bot creation, token storage, global routing, or
OpenClaw channel security.

This repository owns only the TikTok trivia workflow:

- saving ideas
- listing the idea queue
- producing one draft at a time
- showing the current draft
- applying supported revisions
- approving or rejecting drafts
- preparing approved drafts, running CLI TikTok API uploads, or handing approved
  drafts to TikTok inbox upload and recording attempts
- regenerating the active draft with current local rules
- discarding or clearing active/queued workflow state with confirmation

Known working integration point:

- OpenClaw agent: `tiktok`
- Telegram bot name: `v1_tiktok_bot`
- Project workspace: `C:\Users\vgeor\GitHub\tiktok-trivia-factory`
- Repo command: `python -m tiktok_trivia_factory telegram handle "MESSAGE"`

## Message Flow

The intended live flow is:

1. The user sends a Telegram message to `v1_tiktok_bot`.
2. Global OpenClaw receives the message through its Telegram channel.
3. OpenClaw routes project messages to the `tiktok` agent.
4. The `tiktok` agent works from this repository workspace.
5. The agent runs the repo-local command:

   ```powershell
   python -m tiktok_trivia_factory telegram handle "MESSAGE"
   ```

6. The command returns JSON with `ok`, `message`, and optionally `media_path`,
   `media_type`, and `reply_options`.
7. The agent sends the `message` value back to Telegram.
8. If `media_path` is present, the agent also attaches that local file as
   Telegram media through OpenClaw.
9. If `reply_options` is present, the agent should render the options as
   Telegram buttons when supported. The user-facing button text comes from
   `label`; the command sent back to this repo comes from `value`.

## Operator Commands

Use the same phrases in Telegram and local validation:

| Telegram message | Local validation command | Behavior |
| --- | --- | --- |
| `help` | `python -m tiktok_trivia_factory telegram handle "help"` | Shows the supported command list. |
| `status` | `python -m tiktok_trivia_factory telegram handle "status"` | Shows active job and queue state. |
| `save idea PROMPT` | `python -m tiktok_trivia_factory telegram handle "save idea 10 trivia questions about FIFA World Cup"` | Saves a queued idea from Telegram. |
| `ideas` | `python -m tiktok_trivia_factory telegram handle "ideas"` | Lists saved ideas and statuses. |
| `produce next` | `python -m tiktok_trivia_factory telegram handle "produce next"` | Produces the oldest queued idea into a preview MP4 draft and returns `media_path`. |
| `show draft` | `python -m tiktok_trivia_factory telegram handle "show draft"` | Shows the active draft path and returns `media_path`. |
| `revise CHANGE` | `python -m tiktok_trivia_factory telegram handle "revise make it faster"` | Applies supported deterministic revisions, renders a new draft, and returns `media_path`. |
| `regenerate active` | `python -m tiktok_trivia_factory telegram handle "regenerate active"` | Rebuilds the active script, manifest, and MP4 using current local generation/render rules. |
| `approve` | `python -m tiktok_trivia_factory telegram handle "approve"` | Approves the active draft and completes the job. |
| `reject` | `python -m tiktok_trivia_factory telegram handle "reject"` | Rejects the active draft and returns the idea to the queue. |
| `uploads status` | `python -m tiktok_trivia_factory telegram handle "uploads status"` | Lists approved MP4 drafts awaiting TikTok upload handoff. |
| `upload packet` | `python -m tiktok_trivia_factory telegram handle "upload packet"` | Writes a TikTok inbox upload packet and returns `media_path`. |
| `upload approved` | `python -m tiktok_trivia_factory telegram handle "upload approved"` | Starts or shows the oldest pending upload handoff and returns `media_path`. |
| `upload succeeded JOB_ID REFERENCE` | `python -m tiktok_trivia_factory telegram handle "upload succeeded JOB_ID REFERENCE"` | Marks the upload handoff succeeded with an optional provider reference. |
| `upload failed JOB_ID REASON` | `python -m tiktok_trivia_factory telegram handle "upload failed JOB_ID REASON"` | Marks the upload handoff failed and stores the reason. |
| `cancel active` | `python -m tiktok_trivia_factory telegram handle "cancel active"` | Cancels the active job and returns the idea to the queue. |
| `discard active` | `python -m tiktok_trivia_factory telegram handle "discard active"` | Asks for confirmation before discarding the active job without requeueing its idea. |
| `confirm discard active` | `python -m tiktok_trivia_factory telegram handle "confirm discard active"` | Confirms active-job discard. |
| `clear ideas` | `python -m tiktok_trivia_factory telegram handle "clear ideas"` | Asks for confirmation before clearing all active and queued ideas. |
| `clear active` | `python -m tiktok_trivia_factory telegram handle "clear active"` | Asks for confirmation before clearing active work. |
| `clear queued` | `python -m tiktok_trivia_factory telegram handle "clear queued"` | Asks for confirmation before clearing queued ideas. |
| `confirm clear active` | `python -m tiktok_trivia_factory telegram handle "confirm clear active"` | Confirms active clear. |
| `confirm clear queued` | `python -m tiktok_trivia_factory telegram handle "confirm clear queued"` | Confirms queued clear. |
| `confirm clear all` | `python -m tiktok_trivia_factory telegram handle "confirm clear all"` | Confirms clearing all active and queued ideas. |

The adapter also supports deterministic conversational phrasing for common
operator requests. These messages are parsed locally and routed into the same
safe command handlers:

| Natural message example | Routed behavior |
| --- | --- |
| `show me the status` | `status` |
| `can you show me the ideas we have?` | `ideas` |
| `save this idea of having 15 questions about NBA Finals statistics` | `save idea 15 trivia questions about NBA Finals statistics` |
| `show me the status and save this idea of having 15 questions about NBA Finals statistics` | Runs `status`, then saves the idea. |
| `I have some ideas for production. Maybe we can do a short-form video asking 10 questions about Led Zeppelin.` | Saves `10 trivia questions about Led Zeppelin`. |
| `please start the next queued video` | `produce next` |
| `prepare an upload packet` | `upload packet` |
| `please upload the approved draft` | `upload approved` |
| `can you get rid of the active draft?` | `discard active` confirmation prompt. |
| `please make it faster` | `revise make it faster` |

This is not yet an open-ended LLM planner. Ambiguous or unsupported phrasing
falls back to the command help response instead of guessing.
For narrow known ambiguity, the adapter may ask a clarification question. For
example, broad NBA Finals trivia phrasing asks whether the user wants
statistics trivia or player trivia before saving the idea.

If the adapter cannot parse a message, it returns a safe fallback with command
formats such as `status`, `ideas`, `save idea PROMPT`, `produce next`,
`show draft`, `revise CHANGE`, `regenerate active`, `approve`, `reject`,
`uploads status`, `upload packet`, `upload approved`, `discard active`,
`clear active`, and `clear queued`.

`reject` and `cancel active` intentionally requeue the active idea. Use
`discard active` when the active idea should not come back through
`produce next`.

Cleared or discarded ideas are retained locally with `cancelled` status for
audit history, but they are hidden from the default `ideas` queue view.

Confirmation prompts return button metadata in this shape:

```json
{
  "reply_options": [
    {"label": "Yes", "value": "confirm discard active"},
    {"label": "No", "value": "cancel"}
  ]
}
```

If Telegram buttons are unavailable, send the `message` text and include the
same values as plain-text fallback choices.

Supported revision requests are currently limited to:

- shorter/faster pacing
- changing the hook text
- changing background color to blue, green, black, gold, or yellow

## Research Provider Chain

For trivia topics outside the local seed packs, the repo uses a free research
fallback chain where available:

1. Local curated seed packs.
2. Wikimedia/Wikipedia APIs.
3. Open Trivia DB.
4. Codex web search as an agent-mediated fallback.
5. Gemini web search as the final agent-mediated fallback.

The local Python command can directly call the first three providers. Codex and
Gemini web search are last-resort resources for the OpenClaw/Codex/Gemini agent
layer and should be used only after the direct free providers fail or return
insufficient evidence.

Current direct research support is intentionally narrow: NBA Finals and broad
basketball/sports prompts. Unsupported topics fail before creating an active
job, so a failed research attempt does not block `produce next`.

Research-backed scripts include source citations and mark
`metadata.needs_external_research` as `true`.

## Upload Handoff

Approved drafts are eligible for TikTok inbox upload preparation only after the
review gate records an `approved` decision. `upload packet` writes
`var/uploads/JOB_ID/upload_packet.json` with the MP4 path, caption, hashtags,
citations, and TikTok inbox upload requirements. It also records a pending
`upload_attempts` row with provider `tiktok_upload_packet` and returns the MP4
as `media_path`.

`upload approved` remains the manual handoff path. It starts a pending
`upload_attempts` row for the oldest eligible job and returns the MP4 as
`media_path`. If a matching pending handoff already exists, the same handoff is
reused instead of creating duplicates.

After the operator uploads the MP4 to TikTok inbox/drafts, send
`upload succeeded JOB_ID REFERENCE` to record success. The reference can be a
TikTok draft ID, URL, or short operator label if TikTok does not expose a stable
ID. If upload fails, send `upload failed JOB_ID REASON`; the job remains
eligible for retry because only a successful upload removes it from the
awaiting-upload list.

The official TikTok API runner is CLI-only in Phase 8.6:

```powershell
python -m tiktok_trivia_factory tiktok auth-listen
python -m tiktok_trivia_factory uploads send --dry-run
python -m tiktok_trivia_factory uploads send --job-id JOB_ID
python -m tiktok_trivia_factory uploads check JOB_ID
```

These commands use the Content Posting API `FILE_UPLOAD` inbox flow and still
require the operator to finish review/posting inside TikTok. Telegram commands
do not trigger official API uploads yet; they remain the media handoff and
manual outcome-recording surface.

This phase does not public-post automatically and does not store TikTok
credentials, browser cookies, or session data in packet files or Telegram
responses. TikTok OAuth tokens are stored locally under `var/tiktok/`, which is
ignored by git.

## Draft Media Delivery

`produce next`, `show draft`, successful `revise ...`, `upload packet`, and
`upload approved` responses include a `media_path` pointing at the generated
MP4 draft. In live Telegram operation, the OpenClaw agent should send the text
response and attach the MP4.

The OpenClaw media command shape is:

```powershell
openclaw message send --channel telegram --target INCOMING_CHAT_TARGET --message "MESSAGE" --media "MEDIA_PATH"
```

Use the incoming Telegram chat/session as the target. Do not hard-code chat IDs
in this repository. For local validation, use `--dry-run` first:

```powershell
openclaw message send --channel telegram --target INCOMING_CHAT_TARGET --message "Draft ready for review." --media "C:\path\to\draft.mp4" --dry-run
```

If Telegram compresses a video too aggressively during review, add
`--force-document` to send the MP4 as a document instead of a compressed video.

## Validation Checklist

Validate repo behavior locally before relying on Telegram:

```powershell
python -m tiktok_trivia_factory smoke
python -m tiktok_trivia_factory telegram handle "status"
python -m unittest discover -s tests -v
```

Use a full local operator flow when changing command behavior:

```powershell
python -m tiktok_trivia_factory telegram handle "save idea 10 trivia questions about FIFA World Cup"
python -m tiktok_trivia_factory telegram handle "ideas"
python -m tiktok_trivia_factory telegram handle "produce next"
python -m tiktok_trivia_factory telegram handle "show draft"
python -m tiktok_trivia_factory telegram handle "regenerate active"
python -m tiktok_trivia_factory telegram handle "revise make it faster"
python -m tiktok_trivia_factory telegram handle "approve"
python -m tiktok_trivia_factory telegram handle "uploads status"
python -m tiktok_trivia_factory telegram handle "upload packet"
python -m tiktok_trivia_factory telegram handle "upload approved"
python -m tiktok_trivia_factory telegram handle "upload succeeded JOB_ID REFERENCE"
```

For draft media delivery checks, confirm the JSON includes `media_path` and that
the path exists before asking OpenClaw to send it.

OpenClaw health checks are separate from repo workflow checks. Safe read-only
diagnostics include:

```powershell
openclaw agents list
openclaw status
```

## Security Rules

Do not expose secrets in Telegram responses, logs, source code, or config.
Never include:

- Telegram bot token values
- OpenClaw gateway tokens
- environment variable values
- credential file contents
- raw global OpenClaw config dumps
- full secret audit output

It is acceptable to report that a secret exists, is missing, or is invalid,
but not to print the value.

## Do Not Change

Do not make these changes from this repository:

- Do not reinstall OpenClaw.
- Do not recreate `v1_tiktok_bot`.
- Do not rotate or request new Telegram API keys unless diagnostics prove the
  current credentials are invalid.
- Do not add a direct Telegram Bot API polling loop in this repo while OpenClaw
  is the configured transport.
- Do not use unsupported gateway workspace flags such as
  `openclaw gateway start --workspace ...`.
- Do not add invalid OpenClaw config keys:
  - `channels.telegram.ownerId`
  - `channels.telegram.allowlist`
  - `channels.telegram.groupAllowlist`
  - `workspace.path`

## Related Docs

- [Project documentation map](README.md)
- [Error log](error-log.md)
- [Repository operator instructions](../AGENTS.md)
- [Main README](../README.md)
