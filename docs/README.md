# Project Documentation

Use this page as the documentation map for the TikTok Trivia Factory.

## Operational References

- [Public website files](../website/README.md): static homepage, Terms, and
  Privacy pages for TikTok Developer Portal review.
- [OpenClaw Telegram integration](openclaw-telegram.md): how Telegram reaches
  this repo through the existing global OpenClaw `tiktok` agent, what commands
  are supported, and what not to change.
- [TikTok API upload setup](tiktok-api.md): official sandbox OAuth, redacted
  token status, and inbox upload CLI commands.
- [Phase roadmap](roadmap.md): completed phases, remaining phases, and current
  product boundaries.
- [Error log](error-log.md): recurring mistakes, fixes, and prevention notes.

## Source Of Truth

The live Telegram transport is owned by global OpenClaw configuration outside
this repository. This repository owns only the TikTok trivia workflow,
including idea queueing, draft production, review, and approval commands.

When in doubt, validate the repo behavior locally with:

```powershell
python -m tiktok_trivia_factory telegram handle "status"
```
