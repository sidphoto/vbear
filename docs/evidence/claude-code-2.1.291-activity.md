# Activity evidence: Claude Code 2.1.291

Recorded on 2026-10-07. It is the evidence behind the `claude-title` rung being authoritative for this version in
[`vbear/activity.py`](../../vbear/activity.py), the same rung recorded for 2.1.292 in
[claude-code-2.1.292-activity.md](claude-code-2.1.292-activity.md).

- Binary: Claude Code **2.1.291**, native build, macOS arm64.
- Launch: VBear's managed argv and sandbox settings (`claude_argv()`, `claude_settings()`), Haiku.
- Two runs, both through VBear's own code, with a temporary state directory:
  1. 「驗證這個版本」 (`vbear/claude_verify.py` → `vbear/boundary_check.py --mode interactive`): the TUI in a real
     PTY, one prompt; every terminal title's first-character class recorded with its time.
  2. An end-to-end managed launch through the runtime daemon (`create_managed_claude_session`), reading the
     arbitrated activity while one short prompt runs.

## Terminal title during the verification run

Prompt typed at 5.14 s. Title classes in order: 1.42s ✳, 5.22s ◐/◑, 6.18s ◐/◑, 6.40s ◐/◑, 7.14s ◐/◑, 8.10s ◐/◑, 9.06s ◐/◑, 10.03s ◐/◑, 10.99s ◐/◑, 11.36s ✳.

| Check | Result |
|---|---|
| ✳ before the prompt | pass |
| ◐/◑ after the prompt | pass |
| ✳ again after the last working frame | pass |
| Working frames at most 5 s apart | pass (largest gap 0.968 s) |

The same run passed every launch-boundary check (headless and interactive).

## Arbitrated activity, end to end

This run used VBear with 2.1.291 already in `VERIFIED`, so the title rung was consulted (as it will be for users).

| Time (s) | Step | Activity | Reason shown |
|---|---|---|---|
| 0.13 |  | unknown | 尚未收到 Claude 的終端標題（可能停在啟動時的信任確認畫面） |
| 1.39 |  | waiting | 終端標題顯示閒置符號 ✳：Claude 沒有在工作，正在等你輸入或確認 |
| 2.00 | prompt sent | waiting | 終端標題顯示閒置符號 ✳：Claude 沒有在工作，正在等你輸入或確認 |
| 2.63 |  | working | 終端標題顯示工作中的動畫 |
| 4.10 |  | waiting | 終端標題顯示閒置符號 ✳：Claude 沒有在工作，正在等你輸入或確認 |
| 4.90 |  | working | 終端標題顯示工作中的動畫 |
| 5.11 |  | unknown | Claude 已清除終端標題（通常是正在結束） |
| 5.95 |  | exited | 程序已結束 |
| 5.96 | closed |  |  |

The activity went unknown → waiting → working → waiting, as for 2.1.292. The short "working" after `/exit` is Claude
Code handling the exit command before it clears the title.

## Compared with 2.1.292

Same glyphs (✳ idle, ◐/◑ working, empty on exit), same frame interval (about 0.96 s), the idle mark already set at
start-up under `--safe-mode` (no trust dialog). So 2.1.291 is added to `VERIFIED`.

**2.1.286** is not installed on this Mac, so it could not be observed; its title signal stays **trial** (recorded,
not used). On a Mac that has it, 「驗證這個版本」 checks it.
