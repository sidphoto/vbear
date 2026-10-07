# Ideas adopted from OpenRig

[OpenRig](https://github.com/mvschwarz/openrig) (Apache-2.0, v0.6.6 read on 2026-10-07) runs teams of coding agents
in tmux. It solves a neighbouring problem, so a few of its mechanisms carry over. VBear re-implements the ideas in its
own code; no OpenRig code or text is copied.

| OpenRig mechanism | Where it lives there | What VBear does with it |
|---|---|---|
| Agent state taxonomy: separate axes, `unknown` as a first-class value, needs-input as a count plus a reason, one arbitration point, an evidence ladder where new sources start on trial | `packages/daemon/src/domain/activity-taxonomy.ts`, `docs/reference/agent-state-taxonomy.md` | [`vbear/activity.py`](../../vbear/activity.py): session / activity / resumability axes, `claude-title` rung authoritative only for versions with recorded evidence ([2.1.292](claude-code-2.1.292-activity.md)), trial otherwise; the UI shows the basis of every state |
| Proof judgments bound to the item and policy revision, single-use gate verdicts bound to the candidate commit | `packages/daemon/src/domain/proof/judgments.ts`, `scripts/gate-lane-consume.mjs` | Task Cards bind a test result and an approval to the commit their workdir was on ([`vbear/tasks.py`](../../vbear/tasks.py), [`vbear/git_head.py`](../../vbear/git_head.py)); a moved HEAD makes the assertion stale |
| Closure obligation: a queue item moving to done must say what follows | `packages/daemon/src/domain/hot-potato-enforcer.ts` | Completing or blocking a Task Card requires a closure reason, enforced in the data layer |
| Atomic handoff with a chain of record | `packages/daemon/src/domain/queue-repository.ts` | `handoff_task()` closes a card and creates its successor in one locked write |
| Pickup status derived, never self-reported | `packages/daemon/src/domain/queue-pickup.ts` | `tasks.pickup()` from the card and the live sessions, at read time |
| An explicit `CODEX_HOME` per Codex seat | `packages/daemon/src/adapters/codex-runtime-adapter.ts` | Researched only: [a per-launch CODEX_HOME on 0.160.0](codex-0.160.0-isolated-codex-home.md). Codex launches stay refused |

Where VBear differs on purpose:

- **No hooks.** OpenRig relays Claude Code and Codex hook events to its daemon. VBear launches Claude Code with
  `--safe-mode`, which disables settings hooks, and keeps it that way; the terminal title is the evidence instead.
- **"Waiting", not "idle at prompt".** The only signal VBear has shows the same mark at the prompt and on dialogs,
  so VBear does not claim which.
- **No `git` commands.** Reading HEAD runs nothing, because a managed Agent may write `.git` and repository config
  can make git execute programs.
- **No automatic promotion.** OpenRig promotes a trial source after enough agreeing observations. VBear promotes a
  rung for a Claude Code version only with a recorded evidence file, the same way it verifies launch boundaries.
