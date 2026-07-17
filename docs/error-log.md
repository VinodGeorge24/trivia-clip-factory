# Error Log

Record repeated mistakes, validation failures, and the fixes that prevented
them from recurring. Keep entries concrete and update this file when a bug
teaches us something useful.

## 2026-07-15 - SQLite Connections Stayed Locked On Windows

- **Phase:** 1
- **Symptom:** Unit tests failed during temporary-directory cleanup with
  `PermissionError: [WinError 32]` for SQLite files.
- **Cause:** `sqlite3.Connection` used as a context manager commits or rolls
  back transactions, but it does not close the connection. Windows then kept
  the database file locked.
- **Fix:** Explicitly close SQLite connections in `finally` blocks in
  `database.py` and test code.
- **Prevention:** Do not rely on `with sqlite3.connect(...)` alone when the
  file must be deleted or reused immediately. Use explicit close handling.

## 2026-07-15 - Idea Ordering Was Nondeterministic Within One Second

- **Phase:** 2
- **Symptom:** Queue test expected insertion order, but two ideas created in
  the same second sorted by random UUID order.
- **Cause:** `ORDER BY created_at, id` was not stable for same-second inserts.
- **Fix:** Changed list queries to `ORDER BY created_at ASC, rowid ASC`.
- **Prevention:** For SQLite tables with second-resolution timestamps, add a
  deterministic insertion-order tie breaker.

## 2026-07-15 - Schema Metadata Update Is Too Coupled

- **Phase:** 3
- **Symptom:** Tests pass, but schema-version metadata update currently lives
  inside `_ensure_column`, which is not the right ownership boundary.
- **Cause:** A migration helper patch placed the `app_meta` update inside the
  column helper instead of keeping version stamping in `_set_schema_version`.
- **Fix:** Moved schema-version metadata updates back into
  `_set_schema_version`; `_ensure_column` now only ensures columns.
- **Prevention:** Keep migration helpers focused on one responsibility:
  schema changes in helpers, version stamping in version-stamping code.

## 2026-07-15 - Parallel Compileall Can Race With Test Pycache Writes

- **Phase:** 4
- **Symptom:** `python -m compileall -q src tests` failed with
  `PermissionError: [WinError 5]` while tests were running in parallel.
- **Cause:** Both validation commands wrote Python bytecode under
  `__pycache__` at the same time on Windows.
- **Fix:** Reran `compileall` sequentially after tests completed.
- **Prevention:** Do not run `compileall` in parallel with unit tests on
  Windows. Keep it as a separate final validation step.

## 2026-07-15 - Renderer Layout Assumed TikTok Canvas

- **Phase:** 4
- **Symptom:** A renderer unit test using a tiny canvas failed because fixed
  TikTok layout boxes produced an invalid rounded-rectangle coordinate range.
- **Cause:** The renderer is intentionally designed around the 1080x1920
  TikTok manifest contract, not arbitrary canvas sizes.
- **Fix:** Adjusted the renderer test to use the product canvas size with a
  short clip duration instead of shrinking the canvas.
- **Prevention:** Keep renderer tests on the supported 9:16 canvas contract
  unless/until responsive rendering is explicitly added.

## 2026-07-15 - Audio Duration Assumed Manifest Video Duration

- **Phase:** 4.5
- **Symptom:** Renderer tests failed when a small test manifest omitted
  `video.duration_seconds`.
- **Cause:** The procedural audio generator read only the top-level video
  duration, while lightweight tests may define duration only through scenes.
- **Fix:** Audio generation now derives duration from scene start/duration
  values when the video duration is absent.
- **Prevention:** Manifest consumers should prefer explicit manifest fields
  but handle derivable values defensively when practical.

## 2026-07-15 - Telegram Stripped Angle-Bracket Placeholder Text

- **Phase:** 6.5
- **Symptom:** Telegram displayed `Reply with approve, reject, or revise .`
  instead of showing the placeholder after `revise`.
- **Cause:** Angle-bracket placeholder text such as `<change>` can be treated
  as Telegram/HTML-style markup and removed during delivery.
- **Fix:** Replaced Telegram-facing placeholders with plain uppercase words
  such as `CHANGE`, `PROMPT`, `MESSAGE`, and `MEDIA_PATH`.
- **Prevention:** Do not use angle-bracket placeholders in text intended for
  Telegram delivery.

## 2026-07-15 - Draft Options Were Placeholder Prompts

- **Phase:** 6.5
- **Symptom:** Draft videos showed `KNOW IT`, `GUESS IT`, and
  `WAIT FOR REVEAL` instead of actual answer choices.
- **Cause:** The renderer used hardcoded engagement prompts instead of durable
  A/B/C choice data from the script and manifest.
- **Fix:** Added deterministic choices and `correct_choice_label` to generated
  scripts, passed them through render manifests, and rendered real choices with
  the correct option highlighted green on reveal.
- **Prevention:** Renderer UI should consume manifest data. Avoid hardcoded
  placeholder copy in production draft surfaces.

## 2026-07-15 - Distractors Must Match The Answer Category

- **Phase:** 6.5
- **Symptom:** A future generator could pair unrelated answer types, such as a
  country answer with a number or a year answer with a person.
- **Cause:** Random filler choices ignore the semantic category of the correct
  answer.
- **Fix:** Added `answer_type` and topic-level distractor banks. Generated
  choices now select wrong answers from the same answer category before
  rendering.
- **Prevention:** Web/model-backed research providers must output or infer an
  answer category and choose distractors from the same category.

## 2026-07-16 - Idea Statuses Are Schema-Constrained

- **Phase:** 6.7
- **Symptom:** New workflow controls initially tried to mark ideas as
  `discarded` or `cleared`, but SQLite rejected those values with a CHECK
  constraint failure.
- **Cause:** The `ideas.status` schema currently allows only `queued`,
  `active`, `completed`, and `cancelled`.
- **Fix:** Used the existing non-actionable `cancelled` status for discarded
  and cleared ideas, while keeping Telegram messages descriptive.
- **Prevention:** Do not introduce new idea status values without a database
  migration for existing SQLite databases.

## 2026-07-16 - Unsupported Topics Must Not Create Active Jobs

- **Phase:** 6.8
- **Symptom:** A natural-language E2E check tried to produce an unsupported
  NBA Finals idea and failed after the job had already been marked active.
- **Cause:** `produce next` started the production job before preflighting
  local script generation support.
- **Fix:** Generate the local script before starting a new job. Unsupported
  topics now fail without changing queue state.
- **Prevention:** Future generation providers should validate support before
  moving an idea from queued to active.

## 2026-07-16 - Research Providers Need Ordered Fallbacks

- **Phase:** 7
- **Symptom:** Relying on a single free research source would make draft
  generation fragile when a source is unavailable or lacks enough facts.
- **Cause:** Free APIs and public knowledge sources can be temporarily
  unavailable, rate-limited, incomplete, or too generic for a topic.
- **Fix:** Added an ordered provider chain: local seed, Wikimedia/Wikipedia,
  Open Trivia DB, then agent-mediated Codex web search and Gemini web search as
  last-resort fallbacks.
- **Prevention:** New research providers should be additive, cite their sources,
  and fail before moving an idea to active.

## 2026-07-16 - TikTok API Rejected Low-FPS Preview Draft

- **Phase:** 8.6
- **Symptom:** The first official TikTok `FILE_UPLOAD` attempt reached TikTok
  but status polling returned `FAILED` with `frame_rate_check_failed`.
- **Cause:** The approved draft had been produced through the Telegram preview
  path at 12 fps. TikTok's Content Posting API accepted the upload request but
  rejected the MP4 during media validation.
- **Fix:** Re-rendered the approved manifest as a full 30 fps publish-ready MP4
  and retried the upload. The second attempt reached `SEND_TO_USER_INBOX`.
  `uploads send` now re-renders the latest approved manifest with
  `preview=False` before calling TikTok.
- **Prevention:** Never send Telegram preview MP4s to TikTok's API. Official
  API upload commands must produce or verify a publish-ready MP4 first,
  including TikTok-safe frame rate, H.264 video, AAC audio, 9:16 layout, and
  non-empty file output.

## 2026-07-16 - Telegram Upload Command Was Manual-Only

- **Phase:** 8.6
- **Symptom:** The intended operator flow was "Telegram produce, approve, send
  to TikTok," but `upload approved` only created a manual handoff and did not
  call the official TikTok API.
- **Cause:** The API upload runner existed in the CLI, while Telegram still
  exposed only packet/manual handoff commands.
- **Fix:** Added explicit Telegram commands `send approved to TikTok [JOB_ID]`
  and `check TikTok upload JOB_ID`, backed by the same official API functions
  as the CLI.
- **Prevention:** Keep manual handoff and live API upload commands separate in
  docs and tests. Any Telegram wording that implies a live TikTok API action
  must call the API path or fail clearly.

## 2026-07-16 - TikTok Inbox Success Is Not A Profile Draft Yet

- **Phase:** 8.6
- **Symptom:** TikTok returned `SEND_TO_USER_INBOX`, but the mobile profile did
  not show a draft or posted video.
- **Cause:** TikTok's Upload API sends an inbox notification for the creator to
  open and complete the editing flow. It is not equivalent to an already
  profile-visible draft or public post.
- **Fix:** Documented the operator expectation and verified successful uploads
  by polling `/v2/post/publish/status/fetch/`, checking account identity, and
  recording the `publish_id` in `upload_attempts`.
- **Prevention:** After `SEND_TO_USER_INBOX`, check TikTok inbox/system
  notifications on the authorized account, not only profile posts/drafts. Do
  not mark this as a public post unless status later reaches `PUBLISH_COMPLETE`
  after the user completes the TikTok flow.
