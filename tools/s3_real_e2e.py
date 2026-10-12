#!/usr/bin/env python3
"""S3 design 10: the three real-model end-to-end runs, driven through the console's HTTP API.

A developer check, never part of the product. It starts a real console and (through the console's own autostart) a real
runtime daemon on a temporary port, with ``VBEAR_HOME`` = ``_sandbox/vbear-home`` (the dedicated state directory whose
``codex-home`` holds the reviewer's login), then plays the user's few acts through the API: approve the plan and accept the
risks (one preview, one confirmation), start the executor. Everything after that is the product's own: the runner
dispatches to a real Claude Code (Haiku, stream mode), starts real Codex reviews, forwards the review comments, and
stops at the merge gate.

    python3 tools/s3_real_e2e.py --scenario dry        # setup and the approval preview only: no model call
    python3 tools/s3_real_e2e.py --scenario full       # run 1: the whole flow, a NEEDS WORK and then a PASS
    python3 tools/s3_real_e2e.py --scenario stop       # run 2: stop in the middle of a review
    python3 tools/s3_real_e2e.py --scenario restart    # run 3: restart the console in the middle of a review

What it does not do: read ``codex-home/auth.json`` or ``~/.claude.json`` itself (the product computes the account
fingerprints; nothing here prints one), touch ``~/.vbear``, port 7788 or ``~/.vbear/runtime.sock`` (their metadata is
compared before and after, and the processes' open files are checked), merge, push or tag. The toy repository is created
here as a base commit; the work in it is the executor's.

Caps (a run that goes past one is stopped and reported, not widened): 45 minutes wall clock for the whole run; the
flow's own limits are in LIMITS (at most 3 reviews, 6 dispatches, an executor budget of USD 0.50).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SANDBOX = REPO / "_sandbox"
STATE = SANDBOX / "vbear-home"
OUT_ROOT = SANDBOX / "e2e-real"
KEEP = {"codex-home", "codex-login-key", "verifications", "claude-verified.json"}
HOME = Path.home()
REAL_STATE = HOME / ".vbear"
WALL_CAP_S = 45 * 60
REVIEW_STOP_AFTER_S = 15            # a review must have run this long before the stop / restart scenarios act

LIMITS = {"max_reviews": 3, "max_dispatches": 6, "review_max_responses": 100, "executor_turn_max_responses": 60,
          "executor_total_max_responses": 150, "review_timeout_min": 20, "executor_turn_timeout_min": 20,
          "max_elapsed_h": 1, "executor_budget_usd": 0.5}

TASK = {
    "title": "合併重疊區間 merge_ranges",
    "goal": ("在 toy/ranges.py 實作 merge_ranges(ranges)，需求見 SPEC.md。這一階段只交最小實作：新增 toy/__init__.py 與 "
             "toy/ranges.py 並 git commit，不要新增或修改任何測試檔（測試留到下一階段，依審查意見補齊）。"),
    "scope": ["toy/__init__.py", "toy/ranges.py"],
    "out_of_scope": ["SPEC.md 與 README.md 不要改", "這一階段不新增任何測試檔"],
    "acceptance_criteria": [
        "merge_ranges 回傳排序後、合併過的 (start, end) 元組串列",
        "重疊或相接（前一個的 end 等於下一個的 start）的區間要合併",
        "start 大於 end 的區間丟 ValueError，且不改動傳入的串列",
        "已 git commit，回報裡的 head 是該 commit",
    ],
}
SPEC = """# merge_ranges

`toy.ranges.merge_ranges(ranges)` takes a list of `(start, end)` integer pairs and returns the merged list.

Requirements:

1. The result is sorted by start and every item is a `(start, end)` tuple.
2. Intervals that overlap, or touch (`end` of one equals `start` of the next), are merged.
3. An interval whose start is greater than its end raises `ValueError`.
4. The argument is not modified.

Acceptance: a change is not acceptable without unit tests (standard-library `unittest`, `tests/test_ranges.py`)
that cover each of these edge cases: empty input, unsorted input, touching intervals, nested intervals, an invalid
interval, and that the input is not modified.
"""


# ---- small helpers -------------------------------------------------------------------------------------------

def now() -> float:
    return time.monotonic()


def log(msg: str, fh=None) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if fh is not None:
        fh.write(line + "\n")
        fh.flush()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CommandFailed(RuntimeError):
    pass


def run_cmd(*cmd, timeout=30) -> tuple[int, str, str]:
    """(returncode, stdout, stderr). A command that cannot run or times out is an error, never "no output"."""
    # the listing commands must not carry this run's state directory in their own environment (``ps -E`` would list
    # itself as a holder of it)
    env = {k: v for k, v in os.environ.items() if k not in ("VBEAR_HOME", "VBEAR_ACCESS_TOKEN")}
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandFailed(f"{cmd[0]}: {type(exc).__name__}") from exc
    return r.returncode, r.stdout, r.stderr


def sh(*cmd, timeout=30) -> str:
    """stdout of a command that must exit 0."""
    rc, out, err = run_cmd(*cmd, timeout=timeout)
    if rc != 0:
        raise CommandFailed(f"{cmd[0]} exited {rc}: {err.strip()[:120]}")
    return out


def lsof(*args, timeout=30) -> str:
    """lsof's stdout. Its exit 1 with no output and no message means "nothing found"; anything else that is not
    exit 0 is a failure of the check itself."""
    rc, out, err = run_cmd("lsof", *args, timeout=timeout)
    if rc == 0:
        return out
    if rc == 1 and not out.strip() and not err.strip():
        return ""
    raise CommandFailed(f"lsof exited {rc}: {err.strip()[:120]}")


def git(cwd: Path, *args) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "toy", "GIT_AUTHOR_EMAIL": "toy@example.invalid",
           "GIT_COMMITTER_NAME": "toy", "GIT_COMMITTER_EMAIL": "toy@example.invalid"}
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args], cwd=cwd, env=env,
                          check=True, capture_output=True, text=True).stdout.strip()


# ---- the sandbox state, the toy repository, the real-state witness -------------------------------------------

def clean_state() -> list[str]:
    """Everything in the dedicated state directory except codex-home and the login key (and the verification
    reports): flows, sessions, reviews, previews, tasks, locks, the socket."""
    assert STATE.resolve() == (SANDBOX / "vbear-home").resolve() and STATE.resolve().is_relative_to(SANDBOX.resolve())
    removed = []
    for entry in STATE.iterdir():
        if entry.name in KEEP:
            continue
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)
        removed.append(entry.name)
    return sorted(removed)


def write_config() -> None:
    os.environ["VBEAR_HOME"] = str(STATE)
    sys.path.insert(0, str(REPO))
    from vbear import config as cfg
    conf = json.loads(json.dumps(cfg.DEFAULT_CONFIG))
    for src in conf["sources"]:
        src["enabled"] = False
    conf.update(project_roots=[], usage_enabled=False)
    cfg.save(conf)


def make_toy(run_dir: Path) -> Path:
    toy = run_dir / "toy"
    toy.mkdir(parents=True)
    (toy / "README.md").write_text("# toy\n\nA toy repository for VBear's S3 end-to-end run.\n")
    (toy / "SPEC.md").write_text(SPEC)
    git(toy, "init", "-q", "-b", "main")
    git(toy, "config", "user.name", "toy-executor")
    git(toy, "config", "user.email", "toy@example.invalid")
    git(toy, "config", "gc.auto", "0")
    git(toy, "config", "maintenance.auto", "false")
    git(toy, "add", "README.md", "SPEC.md")
    git(toy, "commit", "-q", "-m", "base: spec only")
    return toy


def real_state_witness() -> dict:
    """Metadata only (never contents) of what must not be touched, and who listens on 7788."""
    out = {}
    for rel in ("", "runtime.sock", "runtimed.lock", "flows.json", "tasks.json", "server.token", "config.json"):
        p = REAL_STATE / rel if rel else REAL_STATE
        try:
            st = os.lstat(p)
            out[rel or "."] = {"exists": True, "mtime_ns": st.st_mtime_ns, "inode": st.st_ino, "size": st.st_size}
        except FileNotFoundError:
            out[rel or "."] = {"exists": False}
    out["port_7788_listeners"] = sorted(lsof("-nP", "-iTCP:7788", "-sTCP:LISTEN", "-Fp").split())
    return out


def open_files_touching_real_state(pids: list[int]) -> list[str]:
    """Names of open files (of the given processes) that are under ~/.vbear or are port 7788; paths only. A process
    that is gone by the time it is looked at has no files; a lookup that fails for a live one is an error."""
    bad = []
    for pid in pids:
        try:
            txt = lsof("-nP", "-p", str(pid), "-Fn", timeout=20)
        except CommandFailed:
            if _alive(pid):
                raise
            continue
        for line in txt.splitlines():
            if line.startswith("n") and (str(REAL_STATE) in line or ":7788" in line):
                bad.append(f"{pid}:{line[1:]}")
    return bad


def ps_rows() -> list[dict]:
    rows = []
    txt = sh("ps", "-axo", "pid=,ppid=,pgid=,command=")
    for line in txt.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)", line)
        if m:
            rows.append({"pid": int(m[1]), "ppid": int(m[2]), "pgid": int(m[3]), "command": m[4]})
    return rows


RELEVANT = re.compile(r"(claude|codex|vbear|runtimed|/private/tmp/sr-|/private/tmp/vbp-)")


def relevant_pids() -> dict[int, str]:
    me = os.getpid()
    return {r["pid"]: r["command"] for r in ps_rows()
            if RELEVANT.search(r["command"]) and r["pid"] != me and "s3_real_e2e" not in r["command"]
            and not r["command"].startswith(("ps ", "lsof ", "grep "))}


def descendants(roots: list[int]) -> dict[int, str]:
    """Every process below the given pids (children, their children, ...), by pid -> command."""
    rows = ps_rows()
    kids: dict[int, list[dict]] = {}
    for r in rows:
        kids.setdefault(r["ppid"], []).append(r)
    out: dict[int, str] = {}
    todo = list(roots)
    while todo:
        for r in kids.get(todo.pop(), []):
            if r["pid"] not in out:
                out[r["pid"]] = r["command"]
                todo.append(r["pid"])
    return out


def redact(text: str) -> str:
    text = text.replace(str(HOME), "~").replace(str(REPO), "<repo>")
    return re.sub(r"/Users/[^/\s]+", "/Users/<user>", text)


# ---- the console -------------------------------------------------------------------------------------------

class Console:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.token = ""

    def start(self) -> None:
        self.port = free_port()
        self.token = secrets.token_urlsafe(32)
        env = dict(os.environ)
        env.update(VBEAR_HOME=str(STATE), VBEAR_ACCESS_TOKEN=self.token)
        env.pop("VBEAR_RUNTIME_AUTOSTART", None)
        out = open(self.log_path, "ab")
        try:
            self.proc = subprocess.Popen([sys.executable, "-m", "vbear", "serve", "--port", str(self.port)], cwd=REPO,
                                         env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                         start_new_session=True)
        finally:
            out.close()
        end = now() + 60
        while now() < end:
            try:
                st, _ = self.call("/api/flows")
                if st == 200:
                    return
            except OSError:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"the console exited at start ({self.proc.returncode})")
            time.sleep(0.5)
        raise RuntimeError("the console did not answer in 60 s")

    def call(self, path: str, method: str = "GET", body=None, timeout: float = 90.0):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            headers={"X-VBear": "1", "Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read() or b"null")
            finally:
                exc.close()
            return exc.code, data

    def stop(self, sig=signal.SIGTERM, wait: float = 60.0) -> int | None:
        if self.proc is None:
            return None
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(wait)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(10)
        return self.proc.returncode


LOCK_RE = re.compile(r"^[0-9]{1,10}\n?\Z")


def daemon_pids() -> list[int]:
    """The runtime daemon on the dedicated state directory, by its lock file's pid. No lock file: none. A lock file
    that cannot be read or is not a pid is an error (a daemon may be running and unseen), and so is a pid we may not
    signal (it is someone else's)."""
    try:
        text = (STATE / "runtimed.lock").read_text()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise CommandFailed(f"runtimed.lock cannot be read: {type(exc).__name__}") from exc
    if not LOCK_RE.match(text):
        raise CommandFailed("runtimed.lock does not hold a pid")
    pid = int(text)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return []
    except OSError as exc:
        raise CommandFailed(f"pid {pid} of runtimed.lock cannot be checked: {type(exc).__name__}") from exc
    return [pid]


def processes_with_state() -> dict[int, str]:
    """Every process whose command line or environment names this dedicated state directory (the daemon is started
    with it in its environment, not in its arguments): ``ps -E`` must succeed. This driver is not counted."""
    rc, out, err = run_cmd("ps", "-axwwE", "-o", "pid=,command=")
    if rc != 0:
        raise CommandFailed(f"ps exited {rc}: {err.strip()[:120]}")
    needle, me = str(STATE), os.getpid()
    found: dict[int, str] = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if m and int(m[1]) != me and needle in m[2]:
            found[int(m[1])] = m[2]
    return found


def daemon_rpc(op: str, timeout: float = 10.0, **fields) -> dict:
    sys.path.insert(0, str(REPO))
    from vbear.runtime import daemon as d
    return d.rpc(op, base=STATE, timeout=timeout, **fields)


def shutdown_daemon() -> dict:
    """Shut the daemon down and prove it is gone. "Not running" needs the socket missing (ENOENT) or refusing
    (ECONNREFUSED) AND no process holding this state directory; any other failure of the hello is an error."""
    out = {"was_running": False}
    try:
        daemon_rpc("hello", timeout=2.0)
        out["was_running"] = True
    except (FileNotFoundError, ConnectionRefusedError):
        out["still_alive"] = sorted(processes_with_state())
        return out
    except OSError as exc:
        raise CommandFailed(f"the daemon's hello failed: {type(exc).__name__}: {exc}") from exc
    pids = daemon_pids()
    try:
        daemon_rpc("shutdown", timeout=30.0, force=True)
    except OSError:
        pass                                  # the daemon may close the connection as it goes; the proof is below
    end = now() + 30
    while now() < end and any(_alive(p) for p in pids):
        time.sleep(0.3)
    out["still_alive"] = sorted(set(p for p in pids if _alive(p)) | set(processes_with_state()))
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# ---- one run ------------------------------------------------------------------------------------------------

class Run:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = OUT_ROOT / f"run-{self.stamp}-{scenario}"
        self.dir.mkdir(parents=True)
        self.fh = open(self.dir / "driver.log", "a")
        self.console = Console(self.dir / "console.log")
        self.t0 = now()
        self.wall0 = time.time()
        self.result: dict = {"scenario": scenario, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "limits": LIMITS,
                             "notes": []}
        self.fid = ""
        self.launch = ""
        self.seen = 0
        self.tracked: dict[int, str] = {}       # every process that was below our console or daemon, ever seen

    def say(self, msg: str) -> None:
        log(msg, self.fh)

    def expect(self, name: str, ok: bool, detail: str = "") -> None:
        """An acceptance target of the scenario, written as an assertion: recorded, and the scenario fails if any is
        false (settle())."""
        self.result.setdefault("assertions", []).append({"name": name, "ok": bool(ok), "detail": detail[:300]})
        self.say(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + detail) if detail and not ok else ''}")

    def settle(self) -> None:
        bad = [a["name"] for a in self.result.get("assertions", []) if not a["ok"]]
        if bad:
            raise AssertionError("acceptance not met: " + "; ".join(bad))

    def auto_events(self) -> list[dict]:
        return [e for e in self.events() if e["kind"].startswith("auto_")]

    def common_expectations(self) -> None:
        """What every run must show, whatever the scenario: no duplicate dispatch, review round or job; every
        automatic event marked as the runner's; every review whole and cleaned (or, for an interrupted one, not
        left holding anything)."""
        evs = self.events()
        intents = [e["dispatch_id"] for e in evs if e["kind"] == "auto_dispatch_intent"]
        rounds = [e["round"] for e in evs if e["kind"] == "auto_review_intent"]
        jobs = [e.get("job_id") for e in evs if e["kind"] == "auto_review_started"]
        self.expect("no dispatch id was used twice", len(intents) == len(set(intents)), str(len(intents)))
        self.expect("no review round was started twice", len(rounds) == len(set(rounds)), str(rounds))
        self.expect("no review job was started twice", len(jobs) == len(set(jobs)), str(len(jobs)))
        self.expect("every automatic event is marked as the automation's own",
                    all(e["source"] == "automation" for e in evs if e["kind"].startswith("auto_")))
        self.result["counts"] = {"dispatches": len(intents), "review_rounds": len(rounds), "review_jobs": len(jobs)}

    def api(self, path, method="GET", body=None, ok=(200,)):
        st, data = self.console.call(path, method, body)
        if st not in ok:
            raise RuntimeError(f"{method} {path} -> {st} {json.dumps(data, ensure_ascii=False)[:400]}")
        return data

    # -- stages

    def setup(self) -> None:
        self.result["state_cleaned"] = clean_state()
        write_config()
        self.toy = make_toy(self.dir)
        self.result["base_commit"] = git(self.toy, "rev-parse", "HEAD")[:12]
        self.baseline = relevant_pids()
        self.real_before = real_state_witness()
        self.console.start()
        self.say(f"console up on a temporary port (pid {self.console.proc.pid})")
        self.track()
        task = self.api("/api/tasks", "POST", {**TASK, "workdir": str(self.toy)})["task"]
        roles = {"planner": {"name": "planner", "family": "anthropic"},
                 "executor": {"name": "claude-haiku", "family": "anthropic"},
                 "reviewers": [{"name": "codex", "family": "openai"}]}
        self.fid = self.api("/api/flows", "POST", {"task_id": task["id"], "roles": roles})["flow"]["id"]
        self.say(f"task and flow created ({self.fid})")

    def preview(self) -> dict:
        pre = self.api(f"/api/flows/{self.fid}/automation-preview", "POST", {"limits": LIMITS})
        v = pre.get("values", {})
        self.result["preview"] = {
            "plan_bytes": pre.get("plan_bytes"), "plan_sha256_prefix": str(pre.get("plan_sha256", ""))[:16],
            "executor_model": v.get("executor_model"), "review_model": v.get("model") or v.get("review_model"),
            "executor_claude_version": v.get("executor_claude_version"), "codex_version": v.get("codex_version"),
            "limits": v.get("limits"), "fixed_rules": pre.get("fixed_rules"),
            "executor_account_present": bool(v.get("executor_account")), "review_account_present": bool(v.get("review_account")),
        }
        self.say("approval preview: " + json.dumps(self.result["preview"], ensure_ascii=False))
        return pre

    def approve_and_start(self, pre: dict) -> None:
        r = self.api(f"/api/flows/{self.fid}/automation", "POST", {"preview_id": pre["preview_id"]})
        self.result["approval_id"] = r.get("approval_id")
        self.say(f"plan approved, risks accepted, automatic mode on (approval {r.get('approval_id')})")
        r = self.api(f"/api/flows/{self.fid}/executor", "POST", {})
        self.launch = r["launch_id"]
        self.say("executor started (a human act, played by this driver)")

    def events(self) -> list[dict]:
        return self.api(f"/api/flows/{self.fid}")["flow"]["events"]

    def automation(self) -> dict:
        return self.api(f"/api/flows/{self.fid}/automation")

    def reviews(self) -> list[dict]:
        return self.api(f"/api/flows/{self.fid}/reviews")["reviews"]

    def executor(self) -> dict:
        return self.api(f"/api/flows/{self.fid}/executor")

    def new_events(self) -> list[dict]:
        evs = self.events()
        fresh = evs[self.seen:]
        self.seen = len(evs)
        for e in fresh:
            if e["kind"].startswith("auto_") or e["kind"] in ("automation_mode", "risk_acknowledged"):
                extra = {k: e[k] for k in ("verdict", "round", "reason_code", "state") if k in e}
                self.say(f"event {e['seq']:>3} {e['source']:<10} {e['kind']} {extra or ''}")
        return fresh

    def track(self) -> None:
        try:
            daemon = daemon_pids()
        except CommandFailed as exc:               # the lock is written in two steps; the final check is strict
            self.result["notes"].append(f"tracking: {exc}")
            daemon = []
        roots = ([self.console.proc.pid] if self.console.proc and self.console.proc.poll() is None else []) + daemon
        if roots:
            self.tracked.update(descendants(roots))

    def over_cap(self) -> bool:
        return now() - self.t0 > WALL_CAP_S

    def wait_until(self, pred, what: str, seconds: float, every: float = 3.0):
        end = now() + seconds
        while now() < end:
            self.track()
            evs = self.new_events()
            got = pred()
            if got:
                return got
            if self.over_cap():
                raise RuntimeError(f"wall-clock cap reached while waiting for {what}")
            time.sleep(every)
        raise RuntimeError(f"timed out waiting for {what} ({seconds:.0f} s)")

    def last_auto_stop(self):
        evs = self.events()
        for e in reversed(evs):
            if e["kind"] == "auto_stopped":
                return e
        return None

    def review_running(self):
        evs = self.events()
        started = [e for e in evs if e["kind"] == "auto_review_started"]
        results = [e for e in evs if e["kind"] == "auto_review_result"]
        return started[-1] if len(started) > len(results) else None

    def to_gate(self, seconds: float = WALL_CAP_S) -> dict:
        def done():
            e = self.last_auto_stop()
            return e if e and e["seq"] == self.events()[-1]["seq"] else None
        stop = self.wait_until(done, "the merge gate or a stop", seconds, every=4.0)
        self.result["end"] = {"kind": "auto_stopped", "reason_code": stop.get("reason_code"),
                              "detail": str(stop.get("detail", ""))[:300]}
        self.say(f"loop ended: {stop.get('reason_code')} {str(stop.get('detail', ''))[:120]}")
        return stop

    # -- evidence

    def snapshot(self, tag: str) -> None:
        keep = {}
        for name, fn in (("flow", lambda: self.api(f"/api/flows/{self.fid}")), ("executor", self.executor),
                         ("reviews", lambda: self.api(f"/api/flows/{self.fid}/reviews")),
                         ("automation", self.automation), ("merge_gate", lambda: self.api(f"/api/flows/{self.fid}/merge-gate")),
                         ("reports", lambda: self.api(f"/api/flows/{self.fid}/reports"))):
            try:
                keep[name] = fn()
            except Exception as exc:
                keep[name] = {"error": f"{type(exc).__name__}: {exc}"}
        (self.dir / f"snapshot-{tag}.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1))

    def finish(self, error: str | None) -> None:
        """Always cleans up, and every check of the cleanup and of the real state can fail the run: a leftover
        process, a difference in ``~/.vbear``, an open file there, a check that could not run."""
        r = self.result
        r["error"] = error
        problems: list[str] = []

        def attempt(what: str, fn, default=None):
            try:
                return fn()
            except Exception as exc:
                problems.append(f"{what}: {type(exc).__name__}: {exc}"[:300])
                return default
        try:
            if self.console.proc and self.console.proc.poll() is None:
                attempt("final snapshot", lambda: self.snapshot("final"))
                if self.launch:
                    def close_executor():
                        st, _ = self.console.call(f"/api/flows/{self.fid}/executor/close", "POST",
                                                  {"launch_id": self.launch})
                        r["executor_close_status"] = st
                        end = now() + 60
                        while now() < end:
                            sess = self.executor().get("sessions") or []
                            if not sess or sess[-1].get("status", {}).get("state") in ("exited", "ended", "closed"):
                                return
                            time.sleep(1)
                        raise RuntimeError("the executor session did not end in 60 s")
                    attempt("executor close", close_executor)
        finally:
            attempt("tracking", self.track)
            dpids = attempt("the daemon's lock file", daemon_pids, default=[])
            pids_during = [p for p in ([self.console.proc.pid] if self.console.proc else []) + dpids if _alive(p)]
            holders = attempt("processes holding the state directory", processes_with_state, default={})
            r["state_holders_before_shutdown"] = len(holders)
            r["open_files_touching_real_state"] = attempt(
                "open files", lambda: open_files_touching_real_state(pids_during), default=[])
            if r["open_files_touching_real_state"]:
                problems.append("a process of this run had a file open under ~/.vbear or on port 7788")
            r["console_exit"] = attempt("console stop", self.console.stop)
            if r["console_exit"] not in (0, None):
                problems.append(f"the console exited {r['console_exit']}")
            time.sleep(2)
            r["daemon_shutdown"] = attempt("daemon shutdown", shutdown_daemon, default={})
            if r["daemon_shutdown"].get("still_alive"):
                problems.append("a process of the runtime daemon is still running")
            time.sleep(2)
            after = attempt("process listing", relevant_pids, default={})
            r["tracked_processes_seen"] = len(self.tracked)
            r["leftover_processes"] = [redact(c)[:160] for p, c in sorted(self.tracked.items()) if _alive(p)]
            if r["leftover_processes"]:
                problems.append(f"{len(r['leftover_processes'])} process(es) of this run are still running")
            # new processes that look related but were never below our console or daemon (other sessions' own CLIs)
            r["unattributed_new_processes"] = [redact(c).split()[0][-60:] for p, c in sorted(after.items())
                                              if p not in self.baseline and p not in self.tracked]
            # the last word: nothing at all names this state directory (the daemon's environment included)
            last = attempt("final process check", processes_with_state, default=None)
            if last:
                problems.append(f"{len(last)} process(es) still hold the state directory")
            r["real_state_before"] = self.real_before
            r["real_state_after"] = attempt("real state", real_state_witness, default={})
            r["real_state_unchanged"] = bool(r["real_state_after"]) and self.real_before == r["real_state_after"]
            if not r["real_state_unchanged"]:
                problems.append("the real ~/.vbear, port 7788 or runtime.sock metadata differs from before the run")
            r["cleanup_problems"] = problems
            r["clean"] = not problems
            if problems and error is None:
                r["error"] = "cleanup or real-state checks failed: " + "; ".join(problems)[:600]
            r["passed"] = r["error"] is None
            r["wall_seconds"] = round(time.time() - self.wall0, 1)
            (self.dir / "result.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
            self.say(f"result written: {self.dir.name}/result.json (passed={r['passed']})")
            self.fh.close()


# ---- scenarios ---------------------------------------------------------------------------------------------

def scenario_dry(run: Run) -> None:
    run.setup()
    run.preview()
    run.result["dry"] = True


def final_reviews(run: Run) -> list[dict]:
    rv = run.reviews()
    run.result["reviews"] = [{k: r.get(k) for k in ("round", "state", "outcome", "record", "verdict")} for r in rv]
    return rv


def scenario_full(run: Run) -> None:
    run.setup()
    run.approve_and_start(run.preview())
    stop = run.to_gate()
    run.new_events()
    evs = run.events()
    verdicts = [e["verdict"] for e in evs if e["kind"] == "auto_review_result"]
    run.result["verdicts"] = verdicts
    run.expect("the loop ended at the merge gate", stop.get("reason_code") == "awaiting_merge",
               str(stop.get("reason_code")))
    run.expect("a NEEDS WORK came before the PASS",
               "NEEDS WORK" in verdicts and verdicts[-1] == "PASS" and verdicts.index("NEEDS WORK") < len(verdicts) - 1,
               str(verdicts))
    rv = final_reviews(run)
    run.expect("every review is valid, complete and cleaned",
               bool(rv) and all((r.get("outcome"), r.get("record"), r.get("state")) == ("valid", "complete", "cleaned")
                                for r in rv), json.dumps(run.result["reviews"]))
    run.expect("one dispatch per review round", run.result.get("end") is not None and
               len([e for e in evs if e["kind"] == "auto_dispatch_intent"]) == len(verdicts))
    run.common_expectations()
    run.settle()


def scenario_stop(run: Run) -> None:
    run.setup()
    run.approve_and_start(run.preview())
    started = run.wait_until(run.review_running, "a review to be running", WALL_CAP_S, every=2.0)
    time.sleep(REVIEW_STOP_AFTER_S)
    still = run.review_running()
    run.result["stop"] = {"review_round": started.get("round"), "still_running_when_stopped": bool(still)}
    run.expect("a review was running when the stop was pressed", bool(still))
    run.snapshot("before-stop")
    t = time.time()
    r = run.api(f"/api/flows/{run.fid}/hold", "POST", {})
    run.say("stop pressed (the flow, not the executor session)")
    seq_at_stop = run.events()[-1]["seq"]

    def review_done():
        rv = run.reviews()
        return rv and rv[-1]["state"] in ("cleaned", "manual_review")
    run.wait_until(review_done, "the stopped review to end", 5 * 60, every=2.0)
    run.result["stop"]["review_ended_after_s"] = round(time.time() - t, 1)
    time.sleep(90)
    run.new_events()
    evs = run.events()
    after_stop = [e for e in evs if e["seq"] > seq_at_stop]
    st = run.automation()
    rv = final_reviews(run)
    run.result["stop"].update(held=bool((st.get("step") or {}).get("held")),
                              kinds_after_the_stop=[e["kind"] for e in after_stop])
    run.expect("the flow is held", run.result["stop"]["held"])
    run.expect("the review's process was cleaned up", bool(rv) and rv[-1]["state"] == "cleaned",
               json.dumps(run.result["reviews"]))
    run.expect("the stopped review is not a valid review", bool(rv) and rv[-1].get("outcome") != "valid",
               json.dumps(run.result["reviews"]))
    run.expect("nothing was dispatched or reviewed after the stop",
               not any(e["kind"] in ("auto_dispatch_intent", "auto_dispatch_sent", "auto_review_intent",
                                     "auto_review_started") for e in after_stop),
               str([e["kind"] for e in after_stop]))
    run.expect("the flow did not resume by itself", not any(e["kind"] == "automation_mode" for e in after_stop)
               and run.result["stop"]["held"])
    run.result["end"] = {"kind": "stopped_by_user", "held": run.result["stop"]["held"]}
    run.common_expectations()
    run.settle()


def scenario_restart(run: Run) -> None:
    run.setup()
    run.approve_and_start(run.preview())
    started = run.wait_until(run.review_running, "a review to be running", WALL_CAP_S, every=2.0)
    time.sleep(REVIEW_STOP_AFTER_S)
    run.snapshot("before-restart")
    rv = run.reviews()
    running = bool(run.review_running())
    run.result["restart"] = {"review_round": started.get("round"), "reviews_before": len(rv),
                             "events_before": len(run.events()), "still_running": running}
    run.expect("a review was running when the console was restarted", running)
    old_pid = run.console.proc.pid
    code = run.console.stop(signal.SIGTERM)
    run.result["restart"]["console_exit_code"] = code
    run.say(f"console stopped (SIGTERM, exit {code}); the daemon, the executor and the review keep running")
    time.sleep(5)
    run.result["restart"]["daemon_alive_while_console_down"] = bool(daemon_pids())
    run.expect("the daemon kept running while the console was down", run.result["restart"]["daemon_alive_while_console_down"])
    run.console.start()
    run.say(f"console restarted (new pid, new temporary port; old {old_pid})")
    run.seen = len(run.events())
    stop = run.to_gate()
    run.new_events()
    evs = run.events()
    verdicts = [e["verdict"] for e in evs if e["kind"] == "auto_review_result"]
    run.result["verdicts"] = verdicts
    run.expect("the loop ended at the merge gate", stop.get("reason_code") == "awaiting_merge",
               str(stop.get("reason_code")))
    run.expect("the last verdict is PASS", bool(verdicts) and verdicts[-1] == "PASS", str(verdicts))
    rv = final_reviews(run)
    run.expect("every review is valid, complete and cleaned",
               bool(rv) and all((r.get("outcome"), r.get("record"), r.get("state")) == ("valid", "complete", "cleaned")
                                for r in rv), json.dumps(run.result["reviews"]))
    run.expect("one dispatch per review round",
               len([e for e in evs if e["kind"] == "auto_dispatch_intent"]) == len(verdicts))
    run.common_expectations()
    run.settle()


SCENARIOS = {"dry": scenario_dry, "full": scenario_full, "stop": scenario_stop, "restart": scenario_restart}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    args = ap.parse_args()
    if not (STATE / "codex-home").is_dir():
        print("the dedicated state directory has no codex-home (the reviewer's login is the user's to do)")
        return 2
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    run = Run(args.scenario)
    error = None
    try:
        SCENARIOS[args.scenario](run)
    except BaseException as exc:                   # cleanup always runs; the reason is recorded, not hidden
        error = f"{type(exc).__name__}: {exc}"
        run.say(f"FAILED: {error}")
        if run.fid and run.console.proc and run.console.proc.poll() is None:
            try:
                run.console.call(f"/api/flows/{run.fid}/hold", "POST", {})
            except Exception:
                pass
    finally:
        run.finish(error)
    return 0 if run.result.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
