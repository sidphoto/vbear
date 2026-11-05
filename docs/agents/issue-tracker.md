# Issue tracker: Local Markdown + GitHub mirror

Specs and tickets for this repo live **in both places**:

- **Local markdown under `.scratch/` is the source of truth.** Agents read and write here first.
- **GitHub Issues is a mirror** for visibility on GitHub. Use the `gh` CLI.

(Full `gh` command reference: `~/.codex/skills/setup-matt-pocock-skills/issue-tracker-github.md`. Local-only conventions: `issue-tracker-local.md` in the same folder.)

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Tickets are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Each local file carries, near the top:
  - `Status:` line (triage role or `claimed` / `resolved`)
  - `Blocked by: NN, NN` line when it has blockers
  - `GitHub: #<number>` line once mirrored
- Comments append to the bottom of the local file under `## Comments`

## When a skill says "publish to the issue tracker"

1. Write the local file under `.scratch/<feature-slug>/` first.
2. Then mirror it: `gh issue create --title "..." --body "..."` with the same body. For tickets, mirror the spec first and use `--parent <spec-issue>` when available; mirror blocking edges with `--blocked-by` (fall back to a `Blocked by: #<n>` line in the body).
3. Write the returned issue number back into the local file as `GitHub: #<number>`.

Before the first `gh issue create` of a session, check the target with `gh repo view --json nameWithOwner`. File only into the user's own repo; never into `mattpocock/skills`. If `gh` fails (offline, no auth), keep the local file, note `GitHub: pending` and tell the user. Do not block the work on the mirror.

## When a skill says "fetch the relevant ticket"

Read the local file. Accept either a local path / `NN` or a GitHub `#number` (find the local file whose `GitHub:` line matches). If GitHub has comments the local file lacks, pull them into `## Comments` first.

## Keeping them in sync

- Local wins on conflict. Never overwrite a local file from GitHub content without telling the user.
- When status changes locally (resolved, closed, relabelled), apply the same change on GitHub (`gh issue comment`, `gh issue close`, `gh issue edit --add-label`).
- Do not create GitHub labels unless the user asks.
