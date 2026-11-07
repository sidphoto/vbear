# Shared folder evidence: Codex 0.163.0

Why this file: with the shared folder on (v0.17.1, ADR 0009), a Codex chat process gets the folder as **one more writable root** of
its sandbox, `sandbox_workspace_write.writable_roots=["<state>/shared"]` (`vbear/runtime/codex_chat_protocol.py`,
`shared_root_setting`). Before the design relied on it, the sandbox was probed once on the maintainer's Mac, **without a model and
without a login**: `codex sandbox` runs a command straight in the Seatbelt sandbox from the `-c` settings. This file records what that
probe showed and what it did not. It is not an observation of the chat code, and nothing here was run by the writer of this change.

## What was probed

- Codex `codex-cli 0.163.0`. The sandbox came from these settings only: `sandbox_mode="workspace-write"`,
  `sandbox_workspace_write.writable_roots=["<T>/shared"]`, and `exclude_slash_tmp=true`, `exclude_tmpdir_env_var=true`,
  `network_access=false` (the same keys the chat sends, with the shared folder as the one root added).
- A temporary folder `<T>`, with `CODEX_HOME` and `HOME` both temporary and empty; the working folder was `<T>/work`.
  `<T>/outside` is a folder next to them. The temporary folder was deleted afterwards.
- No account was used and no model was called. Cost: none.

## The table

| Command | Result |
|---|---|
| write `work/a.txt` | succeeded |
| write `shared/b.txt` | succeeded |
| write `outside/c.txt` | `Operation not permitted` |
| write `shared/out/d.txt` (`out` is a link to `outside`) | `Operation not permitted` |
| write `shared/.git/e`, `shared/.codex/x`, `shared/.agents/x` | `Operation not permitted` |
| `cat shared/b.txt` | succeeded |
| inside `shared`: `ln -s outside out2`, `mkdir .codex2`, `rm b.txt` | all succeeded |

## What it means for VBear

- The writable root works, a write through a link to the outside is refused, and the three protected folders are read-only.
- **Creating a link and deleting a file inside the root are allowed.** So an employee (or a command the person allowed) can leave a link in
  the shared folder, and can delete files in it. VBear's own judgement of a file change therefore follows links (a path that leaves the
  folder through a link is declined with no card), the page tells the person that VBear does not follow links it finds, and the link is a
  residual risk in `docs/SECURITY-MODEL.md`. VBear never deletes anything in the folder itself.
- `.claude` is not in the table (it is a Claude Code folder); VBear's own rule protects `.claude`, `.codex`, `.agents` and `.git` at any
  depth in the shared folder for both tools.

## What was not probed

- Whether the `thread/start` answer of `codex app-server` lists the configured root in `sandbox.writableRoots`. That needs a running
  app-server and an opened thread, which is a conversation, so it was not done. The design is **fail-closed** on it: the tracker expects
  the answer (and `thread/resume`, and `thread/settings/updated`) to list **exactly** the one path VBear asked for, and any other answer
  (an empty list, one more root, the path twice) stops the chat as a violation. The Codex part of the version check has a `shared_root` step
  for this. **Waiting for a real machine.** The code was tested only against the fake app-server (`tests/fake_codex_app_server.py`), which
  answers with the asked root, with none, with one more, and with another one in front.
- Whether a shell command that writes into the shared folder is stopped by the sandbox in the chat itself. (Under `untrusted`, 0.163.0 runs
  an allowed command again outside the sandbox when the sandbox stopped it, see `docs/evidence/codex-0.163.0-chat.md`; so that write
  proves nothing about the sandbox, and the version check does not use it for that.)
