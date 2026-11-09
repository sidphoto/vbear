"""A stand-in for ``agy`` 1.5.3, for the AGY chat tests (P46-1). It never calls a model, reads a login or touches the network:
``agy --version`` prints the version alone on one line (as the real one does), and ``agy acp ...`` plays a synthetic script
(tests/fixtures/agy-chat/, see tests/agy_chat_fixtures.py) to what VBear writes, waiting for each line the script has VBear write
before it prints the next part. Anything else it is asked is refused (exit 2): nothing real is run.

Configuration: the JSON file named by $FAKE_AGY_CONFIG (else $HOME/fake-agy.json; tests/agy_chat_fixtures.py ``write_launcher`` makes an
executable that sets it, since a chat process is given a fixed environment):

  {"version": "1.5.3",                    what --version prints
   "scripts": [{"fixture": "text", "vars": {...}}, ...]}

Process number n of a configuration (counted in ``<config>.state.json``) plays ``scripts[n]``, the last one when there are fewer: a
process that resumes a session plays the next script. A script's variables (its ``defaults`` and ``vars``) make the branches: the
answer of VBear picks the branch of an ``answer`` row; ``BYPASS``, ``KIND``, ``RAW_INPUT``, ``MODELS``, ``MODES``, ``SESSION_NEW``,
``SET_MODEL_RESULT``, ``USAGE``, ``UPDATE``, ``METHOD`` and the others of the script files turn the same script into the
BypassSandbox request, a tool of another kind, a model that is missing, a session id that is not a UUID, a usage that does not add
up, an update of an unknown kind and so on. Scripts that start with an error (``auth-error``, ``resume-missing``) and one that
ends in a tool that never asked (``no-ask``) are scripts of their own.

Everything it is given and does goes to ``<config>.log.jsonl``: its arguments, working folder, the names (never the values) of its
environment, whether the settings file VBear writes into the ``--gemini-dir`` folder was there (its sha256, not its text), every line
it read, every line a script did not expect.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import agy_chat_fixtures as fx  # noqa: E402

# Variables macOS or the interpreter add to any process; the log names the others, which are the ones the parent gave.
_OS_ADDED = frozenset({"__CF_USER_TEXT_ENCODING", "LC_CTYPE", "PWD", "SHLVL", "_"})


def _option(argv, name):
    return argv[argv.index(name) + 1] if name in argv[:-1] else None


class Fake:
    def __init__(self, conf: dict, conf_path: str):
        self.conf = conf
        self.log_path = conf_path + ".log.jsonl"
        self.state_path = conf_path + ".state.json"

    def log(self, **kw):
        with open(self.log_path, "a") as f:
            f.write(json.dumps(kw) + "\n")

    def state(self) -> dict:
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def next_script(self) -> dict:
        scripts = self.conf.get("scripts") or [{"fixture": "text"}]
        state = self.state()
        index = state.get("next", 0)
        with open(self.state_path, "w") as f:
            json.dump({"next": index + 1}, f)
        return scripts[min(index, len(scripts) - 1)]

    def write(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def serve(self, argv) -> int:
        script = self.next_script()
        gemini_dir, shared = _option(argv, "--gemini-dir"), _option(argv, "--add-dir")
        settings = None
        if gemini_dir:
            try:
                settings = hashlib.sha256((Path(gemini_dir) / "antigravity-cli" / "settings.json").read_bytes()).hexdigest()
            except OSError:
                settings = None
        self.log(event="start", argv=argv, cwd=os.path.realpath(os.getcwd()), pid=os.getpid(), script=script.get("fixture"),
                 env_keys=sorted(k for k in os.environ if k not in _OS_ADDED and not k.startswith("FAKE_AGY")),
                 gemini_dir=gemini_dir, shared=shared, settings_sha256=settings)
        player = fx.Player(script.get("fixture", "text"), script.get("vars"), shared=shared)
        for out in player.initial:
            self.write(out)
        while True:
            raw = sys.stdin.readline()
            if not raw:
                self.log(event="eof", unexpected=len(player.unexpected))
                self.log(event="exit", code=0)
                return 0
            try:
                msg = json.loads(raw)
            except ValueError:
                self.log(event="bad_line", length=len(raw))
                continue
            self.log(event="stdin", line=msg)
            unexpected, chosen = len(player.unexpected), len(player.choices)
            for out in player.send(msg):
                self.write(out)
            for why, line in player.unexpected[unexpected:]:
                self.log(event="unexpected", why=why, method=line.get("method") if isinstance(line, dict) else None)
            for decision, option_id, kind in player.choices[chosen:]:
                self.log(event="choice", decision=decision, option_id=option_id, kind=kind)


def main(argv) -> int:
    path = os.environ.get("FAKE_AGY_CONFIG") or os.path.join(os.environ.get("HOME", ""), "fake-agy.json")
    try:
        with open(path) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    fake = Fake(conf, path)
    signal.signal(signal.SIGTERM, lambda *_: (fake.log(event="sigterm", pid=os.getpid()), sys.exit(143)))
    if argv[:1] == ["--version"]:
        print(conf.get("version", fx.VERSION))
        return 0
    if argv[:1] == ["acp"]:
        return fake.serve(argv)
    print("fake agy: only --version and acp are played", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
