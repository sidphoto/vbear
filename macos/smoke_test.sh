#!/bin/bash
# Install acceptance for a built VBear .dmg, as a brand-new user would see it:
# an empty HOME, no Claude/Codex config, no earlier VBear state.
#
#   macos/smoke_test.sh dist/VBear-0.6.0-arm64.dmg [--browser]
# --browser also checks browser startup and server survival after app exit.
#
# Opens a VBear window for about a minute (it quits it again). Everything is
# created under one temporary directory and removed at the end; your real
# ~/.vbear, ~/.claude and running VBear are not touched.
set -euo pipefail

DMG="${1:?usage: smoke_test.sh <VBear-x.y.z-arm64.dmg>}"
[ -f "$DMG" ] || { echo "no such file: $DMG" >&2; exit 2; }
ROOT="$(mktemp -d /private/tmp/vbqa.XXXX)"   # short: unix socket paths are limited
MNT="$ROOT/mnt"
QA_HOME="$ROOT/home"
export VBEAR_HOME="$ROOT/s"                    # state dir (short path for the socket)
mkdir -p "$MNT" "$QA_HOME"
APP="$ROOT/VBear.app"
APP_PID=""
BROWSER_PID=""
export HOME="$QA_HOME"
export VBEAR_RUNTIME_AUTOSTART=0
# Reserve a fresh non-production port; never probe or send requests to 7788.
QA_PORT="$(/usr/bin/python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
[ "$QA_PORT" != 7788 ] || { echo "refusing production port" >&2; exit 1; }
export VBEAR_APP_PORT="$QA_PORT"
FAILS=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAILS=$((FAILS + 1)); }

cleanup() {
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  if [ -f "$VBEAR_HOME/server.token" ]; then
    "$PY" -B -c 'import json, os, signal; p=json.load(open(os.environ["VBEAR_HOME"] + "/server.token")); os.kill(p["pid"], signal.SIGTERM)' 2>/dev/null || true
  fi
  if [ -n "$BROWSER_PID" ]; then
    kill "$BROWSER_PID" 2>/dev/null || true
    wait "$BROWSER_PID" 2>/dev/null || true
  fi
  if [ -S "$VBEAR_HOME/runtime.sock" ] && [ -x "$APP/Contents/Resources/python/bin/python3" ]; then
    (cd "$APP/Contents/Resources/app" && ../python/bin/python3 -B -c \
      "from vbear.runtime import daemon as d; from pathlib import Path; d.rpc('shutdown', base=Path('$VBEAR_HOME'), force=True, timeout=15)" \
      >/dev/null 2>&1) || true
  fi
  hdiutil detach "$MNT" -quiet 2>/dev/null || true
  rm -rf "$ROOT"
}
trap cleanup EXIT

# 1. The disk image and the bundle.
hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MNT" -quiet
[ -d "$MNT/VBear.app" ] && pass "dmg contains VBear.app" || fail "dmg contains VBear.app"
[ -L "$MNT/Applications" ] && pass "dmg has an Applications link" || fail "dmg has an Applications link"
ditto "$MNT/VBear.app" "$APP"
hdiutil detach "$MNT" -quiet
codesign --verify --deep --strict "$APP" && pass "signature valid" || fail "signature valid"
PY="$APP/Contents/Resources/python/bin/python3"
[ -x "$PY" ] || { fail "bundled python exists"; exit 1; }
# Every Mach-O file in the bundle may link only to the system or to the bundle itself.
OUTSIDE=0
while IFS= read -r f; do
  deps="$(otool -L "$f" 2>/dev/null)" || { OUTSIDE=1; echo "  otool failed: $f"; continue; }
  if echo "$deps" | tail -n +2 | awk '{print $1}' | grep -vE '^(/usr/lib/|/System/Library/|@rpath/|@loader_path/|@executable_path/)' | grep -q .; then
    OUTSIDE=1; echo "  links outside: $f"
  fi
done < <(find "$APP/Contents" -type f \( -perm -u+x -o -name "*.dylib" -o -name "*.so" \) -exec sh -c 'file -b "$1" | grep -q Mach-O' _ {} \; -print)
[ "$OUTSIDE" = 0 ] && pass "every binary links only to macOS or the bundle" || fail "every binary links only to macOS or the bundle"
PLIST="$APP/Contents/Info.plist"
[ "$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$PLIST")" = "io.github.sidphoto.vbear" ] \
  && pass "bundle id" || fail "bundle id"
APPVER="$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$PLIST")"
case "$(basename "$DMG")" in *"-$APPVER-"*) pass "app version $APPVER matches the dmg name" ;; *) fail "app version $APPVER matches the dmg name" ;; esac
if [ -f "$DMG.sha256" ]; then
  [ "$(shasum -a 256 "$DMG" | awk '{print $1}')" = "$(awk '{print $1}' "$DMG.sha256")" ] \
    && pass "dmg matches its .sha256" || fail "dmg matches its .sha256"
fi
# Compiled code must record bundle paths, not the build machine's (its user name).
if "$PY" -B - "$APP/Contents/Resources/app/vbear" <<'PYEOF'
import marshal, pathlib, sys
bad = []
for pyc in pathlib.Path(sys.argv[1]).rglob("*.pyc"):
    code = marshal.loads(pyc.read_bytes()[16:])
    if not code.co_filename.startswith("/Applications/VBear.app/"):
        bad.append(f"{pyc.name}: {code.co_filename}")
print("\n".join(bad[:3]))
sys.exit(1 if bad else 0)
PYEOF
then pass "compiled code records bundle paths only"; else fail "compiled code records bundle paths only"; fi
"$PY" -B -c "import ctypes, pty, termios, fcntl, selectors, tomllib, http.server, ssl, hashlib, secrets" \
  && pass "bundled python has the modules VBear needs" || fail "bundled python has the modules VBear needs"

# 2. Start our own isolated daemon; the app may not autostart any daemon.
(cd "$APP/Contents/Resources/app" && exec "$PY" -B -m vbear runtimed) >"$ROOT/runtime.log" 2>&1 &
for _ in $(seq 1 100); do [ -S "$VBEAR_HOME/runtime.sock" ] && break; sleep 0.1; done
# Start it as a new user (no ~/.claude, ~/.codex, ~/.vbear).
env -i HOME="$QA_HOME" USER="$USER" LOGNAME="$USER" VBEAR_HOME="$VBEAR_HOME" \
    VBEAR_RUNTIME_AUTOSTART=0 VBEAR_APP_PORT="$QA_PORT" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" "$APP/Contents/MacOS/VBear" -BrowserOnLaunch NO >"$ROOT/app.log" 2>&1 &
APP_PID=$!
for _ in $(seq 1 240); do [ -f "$VBEAR_HOME/server.token" ] && break; sleep 0.5; done
[ -f "$VBEAR_HOME/server.token" ] && pass "app started its server" || { fail "app started its server"; cat "$ROOT/app.log"; exit 1; }
[ "$(stat -f %Lp "$VBEAR_HOME/server.token")" = "600" ] && pass "token file is 0600" || fail "token file is 0600"

# 3. API, built-in terminal, quit; driven with the bundled Python itself.
cd "$APP/Contents/Resources/app"
"$PY" -B - "$VBEAR_HOME" "$QA_HOME" <<'PYEOF' || FAILS=$((FAILS + 1))
import base64, http.client, json, sys, time, urllib.request, urllib.error
state, home = sys.argv[1], sys.argv[2]
tok = json.load(open(f"{state}/server.token"))
port, token = tok["port"], tok["token"]
assert port != 7788, "refusing production port"
base = f"http://127.0.0.1:{port}"
bad = 0
def check(ok, what):
    global bad
    print(("PASS  " if ok else "FAIL  ") + what)
    bad += 0 if ok else 1
def call(path, method="GET", body=None, auth=True):
    h = {"X-VBear": "1", "Content-Type": "application/json"}
    if auth:
        h["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, method=method, headers=h,
                               data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
check(call("/api/config", auth=False)[0] == 401, "API refuses requests without the token")
st, cfg = call("/api/config")
check(st == 200 and cfg["state_dir"] == state, "API answers with the token, state dir is the test one")
check(urllib.request.urlopen(base + "/", timeout=10).status == 200, "web page is served")
st, ov = call("/api/overview")
check(st == 200, "overview loads for a user with no skills")
st, r = call("/api/native/terminals", "POST", {"cwd": "~"})
check(st == 200 and r["session"]["cwd"].rstrip("/") == home.rstrip("/"), "built-in terminal opens in the new user's home")
sid = r["session"]["session_id"]
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
conn.request("GET", f"/api/term/{sid}/stream", headers={"X-VBear": "1", "Authorization": f"Bearer {token}"})
resp = conn.getresponse()
check(resp.status == 200, "terminal stream attaches")
call(f"/api/term/{sid}/control", "POST", {"action": "takeover", "cols": 100, "rows": 30})
call(f"/api/term/{sid}/input", "POST", {"text": "echo QA_$((20+22))\r"})
seen, end = b"", time.time() + 20
while b"QA_42" not in seen and time.time() < end:
    line = resp.fp.readline()
    if line.startswith(b"data: "):
        ev = json.loads(line[6:])
        if ev.get("type") == "terminal.frame":
            seen += base64.b64decode(ev.get("bytes", ""))
check(b"QA_42" in seen, "a command typed into the terminal runs")
conn.close()
open(f"{state}/qa-session", "w").write(sid)
sys.exit(1 if bad else 0)
PYEOF
cd - >/dev/null

# Address only the process this test started, never the shared bundle ID.
/usr/bin/swift -e 'import Cocoa; guard let app = NSRunningApplication(processIdentifier: Int32(CommandLine.arguments[1])!) else { exit(1) }; exit(app.terminate() ? 0 : 1)' "$APP_PID"
for _ in $(seq 1 20); do kill -0 "$APP_PID" 2>/dev/null || break; sleep 0.5; done
kill -0 "$APP_PID" 2>/dev/null && fail "app quits" || pass "app quits"
APP_PID=""
sleep 1
[ ! -f "$VBEAR_HOME/server.token" ] && pass "quitting removed the token files" || fail "quitting removed the token files"
SID="$(cat "$VBEAR_HOME/qa-session" 2>/dev/null || true)"
ALIVE="$(cd "$APP/Contents/Resources/app" && "$PY" -B -c "
from vbear.runtime import daemon as d; from pathlib import Path
r = d.rpc('list', base=Path('$VBEAR_HOME'))['result']['sessions']
print(any(s['session_id'] == '$SID' and not s['exited'] for s in r))" 2>/dev/null || echo False)"
[ "$ALIVE" = "True" ] && pass "the terminal keeps running after the app quits" || fail "the terminal keeps running after the app quits"
codesign --verify --deep --strict "$APP" && pass "bundle unchanged after running (signature still valid)" || fail "bundle unchanged after running"

if [ "${2:-}" = "--browser" ]; then
  "$APP/Contents/MacOS/VBear" -BrowserOnLaunch YES >"$ROOT/browser.log" 2>&1 &
  APP_PID=$!
  for _ in $(seq 1 200); do kill -0 "$APP_PID" 2>/dev/null || break; sleep 0.1; done
  if kill -0 "$APP_PID" 2>/dev/null; then
    fail "browser-mode app exits without a window"
    kill -TERM "$APP_PID"
  else
    wait "$APP_PID" && pass "browser-mode app exits successfully without a window" || fail "browser-mode app exit status"
  fi
  APP_PID=""
  # Authenticate after the app has gone, not merely while its child starts.
  "$PY" -B - "$VBEAR_HOME" "$QA_PORT" <<'PYEOF' || FAILS=$((FAILS + 1))
import json, pathlib, sys, urllib.request
state, port = pathlib.Path(sys.argv[1]), int(sys.argv[2])
assert port != 7788
access = json.loads((state / "server.token").read_text())
assert access["port"] == port
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/config",
                             headers={"Authorization": "Bearer " + access["token"]})
with urllib.request.urlopen(req, timeout=10) as r:
    assert json.load(r)["state_dir"] == str(state)
assert (state / "open.html").is_file()
print("PASS  browser server survives app exit with the existing private handoff")
PYEOF
  FIRST_SERVER_PID="$("$PY" -B -c 'import json, os; print(json.load(open(os.environ["VBEAR_HOME"] + "/server.token"))["pid"])')"
  # Reuse that server on a second browser-mode launch.
  "$APP/Contents/MacOS/VBear" -BrowserOnLaunch YES >"$ROOT/reuse.log" 2>&1 &
  APP_PID=$!
  for _ in $(seq 1 200); do kill -0 "$APP_PID" 2>/dev/null || break; sleep 0.1; done
  if kill -0 "$APP_PID" 2>/dev/null; then
    fail "browser-mode reuse exits"
    kill -TERM "$APP_PID"
  else
    wait "$APP_PID" && pass "browser-mode reuse exits successfully" || fail "browser-mode reuse exit status"
  fi
  APP_PID=""
  # Only the PID from our isolated state may be stopped.
  BROWSER_PID="$("$PY" -B -c 'import json, os; print(json.load(open(os.environ["VBEAR_HOME"] + "/server.token"))["pid"])')"
  [ "$BROWSER_PID" = "$FIRST_SERVER_PID" ] && pass "second launch reuses the same server PID" || fail "second launch reuses the same server PID"
  kill -TERM "$BROWSER_PID"
  for _ in $(seq 1 100); do [ ! -f "$VBEAR_HOME/server.token" ] && break; sleep 0.1; done
  [ ! -f "$VBEAR_HOME/server.token" ] && pass "isolated browser server cleaned up" || fail "isolated browser server cleaned up"
  BROWSER_PID=""
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "SMOKE TEST PASSED"; else echo "SMOKE TEST FAILED ($FAILS)"; exit 1; fi
