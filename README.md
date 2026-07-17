# TikTok Trivia Factory

Telegram-operated content factory for producing TikTok trivia drafts.

The current implementation covers the local foundation, queue memory,
structured script generation using free local curated seed packs, render
manifest generation, MP4 draft rendering, procedural audio, and a Telegram
operator command surface for the existing OpenClaw `tiktok` agent. Approved
drafts can be handed off manually, prepared as TikTok inbox upload packets, or
uploaded to the TikTok inbox through the official Content Posting API sandbox
flow. Broad model-backed generation, Direct Post, and analytics come in later
phases.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\trivia-factory smoke
```

Without installing, run:

```powershell
python -m tiktok_trivia_factory smoke
```

## Commands

```powershell
trivia-factory status
trivia-factory db init
trivia-factory smoke
trivia-factory ideas add "10 trivia questions about FIFA World Cup"
trivia-factory ideas list
trivia-factory jobs start <idea_id>
trivia-factory jobs active
trivia-factory jobs cancel-active
trivia-factory scripts generate
trivia-factory scripts show
trivia-factory manifests generate
trivia-factory manifests show
trivia-factory drafts render --preview
trivia-factory drafts show
trivia-factory reviews show
trivia-factory reviews revise "make it faster" --preview
trivia-factory reviews approve
trivia-factory reviews reject
trivia-factory uploads status
trivia-factory uploads next
trivia-factory uploads prepare
trivia-factory uploads send --dry-run
trivia-factory uploads send --job-id <job_id>
trivia-factory uploads check <job_id>
trivia-factory uploads confirm <job_id> --reference <tiktok_reference>
trivia-factory uploads fail <job_id> "reason"
trivia-factory tiktok auth-url
trivia-factory tiktok auth-listen
trivia-factory tiktok auth-exchange <code>
trivia-factory tiktok auth-status
trivia-factory tiktok auth-refresh
trivia-factory telegram handle "help"
trivia-factory telegram handle "status"
trivia-factory telegram handle "save idea 10 trivia questions about FIFA World Cup"
trivia-factory telegram handle "ideas"
trivia-factory telegram handle "produce next"
trivia-factory telegram handle "show draft"
trivia-factory telegram handle "revise make it faster"
trivia-factory telegram handle "regenerate active"
trivia-factory telegram handle "approve"
trivia-factory telegram handle "uploads status"
trivia-factory telegram handle "upload packet"
trivia-factory telegram handle "upload approved"
trivia-factory telegram handle "send approved to TikTok JOB_ID"
trivia-factory telegram handle "check TikTok upload JOB_ID"
trivia-factory telegram handle "upload succeeded JOB_ID REFERENCE"
trivia-factory telegram handle "upload failed JOB_ID REASON"
trivia-factory telegram handle "discard active"
trivia-factory telegram handle "confirm discard active"
trivia-factory telegram handle "clear queued"
trivia-factory telegram handle "confirm clear queued"
```

## Runtime Files

Local runtime state defaults to `var/`, which is ignored by git:

- SQLite database: `var/trivia_factory.sqlite3`
- generated artifacts: `var/artifacts/`
- TikTok upload packets: `var/uploads/`
- TikTok OAuth session and token files: `var/tiktok/`
- future logs/temp files: `var/logs/`, `var/tmp/`

Copy `.env.example` to `.env` for local overrides. Never commit secrets.

## Current Data Model

Phase 2 initializes durable tables for:

- ideas
- production jobs
- video scripts
- render manifests
- draft artifacts
- revision events
- approval events
- TikTok upload attempts
- future analytics snapshots
- source citations

SQLite enforces that only one production job can be active at a time.

## Project Notes

- [Documentation map](docs/README.md): operational docs and source-of-truth
  links.
- [Public website files](website/README.md): static homepage, Terms, and
  Privacy pages for TikTok Developer Portal review.
- [OpenClaw Telegram integration](docs/openclaw-telegram.md): how Telegram
  reaches this repo, supported commands, and OpenClaw boundaries.
- [TikTok API upload setup](docs/tiktok-api.md): sandbox OAuth and official
  inbox upload commands.
- [Phase roadmap](docs/roadmap.md): completed phases, remaining phases, and
  current product boundaries.
- [Error log](docs/error-log.md): mistakes encountered, fixes applied, and
  recurring issue prevention notes.

## Script Generation

Phase 3 generates structured JSON scripts for the active production job:

```powershell
trivia-factory ideas add "10 trivia questions about FIFA World Cup"
trivia-factory jobs start <idea_id>
trivia-factory scripts generate
trivia-factory scripts show
```

The script generator checks local sources before using any web/research
fallback. Current provider order:

1. Local trivia question bank text files.
2. Local curated seed packs.
3. Wikimedia/Wikipedia APIs for supported researched topics.
4. Open Trivia DB for free no-key trivia fallback.
5. Codex web search as a last-resort agent-mediated research fallback.
6. Gemini web search as the final agent-mediated fallback.

By default, the local trivia bank scans rewritten batch files under
`var/trivia-rewrite/` and common final bank file names such as
`trivia-questions.txt` or `triviaquestions.txt`. Set `TTF_TRIVIA_BANK_PATH` to
point at a specific final text file or folder. When a Telegram prompt matches a
bank topic, generated scripts use provider `local_trivia_bank` and store the
source heading/path in script metadata and citations.

When a bank-backed draft is approved, the matched topic block is removed from
the source bank file and appended to `used-trivia-bank.txt` next to that source
file with the job ID and prompt. Rejected or cancelled drafts do not consume
the topic, so unused ideas can safely return to the queue.

The curated seed-pack fallback is free and offline, but deliberately limited to:

- FIFA World Cup
- Led Zeppelin
- grade-school science / Are You Smarter Than a 5th Grader style science

Unsupported topics fail closed instead of producing unsupported facts unless a
local bank topic or free research provider supports the prompt.

Generated A/B/C choices are context-aware. Each question carries an
`answer_type` such as country, year, person, award, album, or science concept.
Wrong answers are selected from the same topic/category bank so a country answer
gets country distractors, a year answer gets year distractors, and so on. Future
web/model-backed providers should preserve that same contract instead of using
random filler options.

The local Python worker directly executes the first four providers. Codex and
Gemini web search are represented in the provider chain for OpenClaw/agent
handoff, but are not direct Python APIs in this repo yet.

The first researched topic is NBA Finals trivia. Research-backed scripts store
source citations and mark `metadata.needs_external_research` as `true` so drafts
can be reviewed carefully before publishing.

## Render Manifests

Phase 4 defines a manifest contract before rendering MP4 files:

```powershell
trivia-factory scripts generate
trivia-factory manifests generate
trivia-factory manifests show
```

The current MVP format is standard Q&A countdown trivia rendered as a
three-choice mobile quiz:

- 9:16 vertical layout at 1080x1920.
- Large mobile-readable text.
- Hook scene first.
- Question screen with a 5-second countdown.
- Real A/B/C answer choices shown during the countdown.
- Immediate answer reveal after each countdown.
- Correct answer choice highlighted green on reveal.
- Optional ticking sound cue during countdown.
- Optional ding sound cue on answer reveal.
- Voiceover text per scene.
- Explicit pacing metadata per scene.

The manifest advertises future format support for:

- `qa`
- `multiple_choice`
- `true_false`
- `fill_in_blank`
- `guess_image`

Only `qa` is generated in the current MVP.

## MP4 Draft Rendering

Phase 4 renders manifest-driven MP4 drafts using Pillow-generated frames and
the FFmpeg binary provided by `imageio-ffmpeg`.

```powershell
trivia-factory drafts render --preview
trivia-factory drafts show
```

The current renderer creates:

- MP4/H.264 video.
- 9:16 vertical frames.
- Visual sandwich layout inspired by mobile game-show trivia.
- Question, visual hook card, countdown, and answer reveal scenes.
- Procedural AAC audio with background tone, countdown ticks, and answer ding.

Phase 4.5 adds procedural audio:

- Generated countdown ticks.
- Generated answer ding.
- Generated low-volume game-show background loop.

Voiceover text is represented per scene in the manifest. By default it is not
synthesized so draft rendering remains free, offline, and deterministic. On the
local Windows production machine, set `TTF_VOICEOVER_PROVIDER=windows_sapi` in
`.env` to synthesize scene voiceover with Windows Speech API and mix it into
rendered drafts. Leave the value as `none` for CI, Linux/macOS, or silent test
renders.

The renderer uses procedural audio by default because it is free forever,
offline, attribution-free, and not subject to API limits. Optional external
asset sources can be added later for better sound design variety.

## OpenClaw Telegram Operator

OpenClaw is configured globally outside this repository. The project-level
integration is the local command that the OpenClaw `tiktok` agent can run from
this workspace:

```powershell
trivia-factory telegram handle "status"
trivia-factory telegram handle "save idea 10 trivia questions about FIFA World Cup"
trivia-factory telegram handle "ideas"
trivia-factory telegram handle "produce next"
```

Supported messages:

- `help`
- `status`
- `save idea PROMPT`
- `ideas`
- `produce next`
- `show draft`
- `revise CHANGE`
- `regenerate active`
- `approve`
- `reject`
- `uploads status`
- `upload packet`
- `upload approved`
- `send approved to TikTok [JOB_ID]`
- `check TikTok upload JOB_ID`
- `upload succeeded JOB_ID REFERENCE`
- `upload failed JOB_ID REASON`
- `discard active`
- `clear ideas`
- `clear active`
- `clear queued`
- `clear all`

`produce next` starts the oldest queued idea, generates a script from the local
trivia question bank when the prompt matches a bank topic, then falls back to
local seed/research providers, builds the render manifest, renders a preview
MP4 draft, and returns the draft path for review. One active job is still
enforced by SQLite.
`produce next`, `show draft`, and successful revision responses also return a
`media_path` value so OpenClaw can attach the MP4 back into Telegram.

The Telegram adapter also accepts common natural-language phrasing and routes it
through the same safe command handlers. Examples:

- `show me the status`
- `can you show me the ideas we have?`
- `save this idea of having 15 questions about NBA Finals statistics`
- `I have some ideas for production. Maybe we can do a short-form video asking 10 questions about Led Zeppelin.`
- `please start the next queued video`
- `send the approved draft to TikTok`
- `can you get rid of the active draft?`
- `please make it faster`

When phrasing is ambiguous, the adapter either asks a narrow clarification
question, such as NBA Finals statistics versus player trivia, or falls back to
step-by-step command formats instead of guessing.

If a job is already active, `produce next` returns actionable review options
instead of trying to start another job. Use `approve` to complete the active
draft, `reject` or `cancel active` to return its idea to the queue,
`regenerate active` to rebuild the draft with current script/render rules, or
`discard active` to retire the active job without requeueing its idea.

Destructive queue controls require explicit confirmation. For example,
`discard active` prompts for `confirm discard active`, and `clear queued`
prompts for `confirm clear queued`. Cleared/discarded ideas are retained as
cancelled records for audit history but hidden from the default `ideas` view.
Confirmation prompts also return `reply_options` so Telegram can show simple
`Yes` and `No` buttons while still sending the safe command payload.

Approved drafts can be handed off for TikTok inbox/manual upload without
bypassing the review gate. Use `uploads status` to list approved MP4 drafts
that have no successful upload attempt. Use `upload packet` or
`trivia-factory uploads prepare` to write a JSON packet under `var/uploads/`
with the MP4 path, caption, hashtags, citations, and TikTok inbox upload
requirements.

Phase 8.6 also adds the official sandbox API path. Configure `.env`, run
`trivia-factory tiktok auth-listen`, then use
`trivia-factory uploads send --dry-run` and
`trivia-factory uploads send --job-id JOB_ID`. The API path uploads to TikTok
inbox/drafts only; the operator still finishes review/posting inside TikTok.
Use `trivia-factory uploads check JOB_ID` to refresh TikTok processing status.

Telegram has both manual and official API upload paths. Use `upload approved`
to start or show the oldest pending manual handoff; the response includes
`media_path` so OpenClaw can attach the MP4. Use
`send approved to TikTok [JOB_ID]` to upload a specific approved draft through
the official inbox API, or omit `JOB_ID` to send the oldest approved draft. Use
`check TikTok upload JOB_ID` to refresh TikTok processing status. After a
manual upload, reply `upload succeeded JOB_ID REFERENCE` or
`upload failed JOB_ID REASON` to persist the result. Repeating a packet
preparation or handoff reuses the existing pending attempt where possible, and
repeating a success confirmation returns the existing successful attempt
instead of duplicating it.

For the full Telegram/OpenClaw operating contract, see
[docs/openclaw-telegram.md](docs/openclaw-telegram.md). That document is the
source of truth for what the repo owns, what OpenClaw owns, and what settings
must not be changed.

## Review Gate

Phase 5 adds a local approval gate before any upload phase:

```powershell
trivia-factory reviews show
trivia-factory reviews revise "make it faster and change hook to Lightning round" --preview
trivia-factory reviews approve
trivia-factory reviews reject
```

The review gate requires an active job and an MP4 draft. Approval marks the
production job and idea as completed. Rejection cancels the active job and
returns the idea to the queue.

Supported MVP revision requests are intentionally narrow and deterministic:

- shorten/faster pacing
- change hook text
- change background color to blue, green, black, gold, or yellow

Review commands use the same local OpenClaw-facing adapter:

```powershell
trivia-factory telegram handle "show draft"
trivia-factory telegram handle "request changes make it faster"
trivia-factory telegram handle "approve"
```

It maps plain text into the same review service used by the CLI. Real Telegram
transport is provided by the global OpenClaw gateway; this repository does not
store Telegram tokens or bot credentials.
