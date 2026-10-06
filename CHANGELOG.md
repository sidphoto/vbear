# Changelog

## Unreleased

- **Built-in terminal**: a 「終端機」 page opens your login shell in a folder under your home directory,
  with tabs and direct typing. Labelled as an ordinary, unsandboxed terminal.

## v0.1.0 — first public release

First open-source release under the MIT License.

- **Renamed from SID Console to VBear.** The package is now `vbear` and the state directory is
  `~/.vbear` (an existing `~/.sid-console` is moved on first start). Environment variables are now
  `VBEAR_HOME` and `VBEAR_RUNTIME_AUTOSTART`, and the CSRF header is now `X-VBear`.

- **VBear runtime.** A local daemon that owns agent terminals, so they survive console restarts. Terminals can
  be watched in the browser, typed into after an explicit takeover (one controller at a time),
  and closed from the UI.
- **Profile-managed Claude Code launches** with a preview of seven permission labels, followed by confirmation.
  Bash writes are limited to the work directory and a scratch directory for each session, the network is
  off, Edit and Write are disabled, and files are cleaned up only after every process is proven gone.
  Requires Claude Code 2.1.286 exactly.
- **Codex.** Its terminals can be watched and typed into; profile-managed launch is not available yet (fail closed).
- Skill and agent-role library for Claude Code, Codex and shared skills, with load status, sources,
  search and your own notes.
- Projects and team views, task cards that keep self-reported and verified status separate.
- The Herdr compatibility layer was removed. The last Herdr-based version is tagged `last-herdr`.
- Requires macOS and Python 3.13 or newer.
