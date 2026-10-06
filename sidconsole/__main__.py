"""python3 -m sidconsole [serve|scan|doctor] [--port N] [--open]"""

from __future__ import annotations

import argparse
import json
import sys

MIN_PYTHON = (3, 13)  # os.waitid on macOS (safe Agent CLI version probe) arrived in 3.13


def python_too_old(version_info=sys.version_info) -> str | None:
    if tuple(version_info[:2]) >= MIN_PYTHON:
        return None
    return (f"SID Console 需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上，目前是 "
            f"{version_info[0]}.{version_info[1]}。請改用 Homebrew 或 python.org 的較新版本。\n"
            f"SID Console requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+.")


if (_too_old := python_too_old()) is not None:
    sys.exit(_too_old)

from . import config as cfg  # noqa: E402  (after the version check on purpose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sidconsole", description="SID Console：技能與團隊主控台")
    sub = parser.add_subparsers(dest="cmd")
    p_serve = sub.add_parser("serve", help="啟動本機主控台（預設）")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--open", action="store_true", help="啟動後開啟瀏覽器")
    p_serve.add_argument("--verbose", action="store_true")
    p_launch = sub.add_parser("launch", help="背景啟動主控台（若尚未執行）並開啟瀏覽器")
    p_launch.add_argument("--port", type=int)
    sub.add_parser("scan", help="重新掃描並輸出摘要")
    sub.add_parser("doctor", help="檢查來源與 SID runtime 連線")
    sub.add_parser("runtimed", help="SID runtime 背景程序（通常由主控台自動啟動）")
    args = parser.parse_args(argv)

    if args.cmd == "runtimed":
        from .runtime.daemon import main as runtimed_main
        return runtimed_main()

    if args.cmd in (None, "serve"):
        from .server import serve
        serve(getattr(args, "port", None), getattr(args, "open", False))
        return 0

    if args.cmd == "launch":
        return launch(args.port)

    from .index import Store
    store = Store()
    if args.cmd == "scan":
        data = store.rescan()
        counts: dict = {}
        for s in data["skills"]:
            counts.setdefault(s["tool"], {}).setdefault(s["activation"], 0)
            counts[s["tool"]][s["activation"]] += 1
        print(json.dumps({"skills": len(data["skills"]), "roles": len(data["roles"]),
                          "by_tool": counts, "problems": data["problems"],
                          "scan_seconds": data["scan_seconds"],
                          "index": str(cfg.index_path())}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "doctor":
        from . import runtime as rt
        conf = cfg.load()
        ok = True
        for src in cfg.sources_from(conf):
            exists = src.resolved().exists()
            ok &= exists or not src.enabled
            print(f"[{'OK ' if exists else '缺 '}] {src.label:<24} {src.path}{'' if src.enabled else '（已停用）'}")
        # Doctor only reports; it never spawns the runtime daemon.
        snap = rt.get_runtime().snapshot()
        print(f"[{'OK ' if snap['available'] else '缺 '}] SID runtime  {snap['version'] or ''} {snap['binary'] or ''}")
        for p in snap["problems"]:
            print("     ", p)
        print(f"狀態目錄：{cfg.state_dir()}")
        return 0 if ok else 1
    return 0


def is_sid_console(url: str, timeout: float = 1.0) -> bool:
    """Whether `url` is served by a SID Console, not merely something on the port.

    Checks the Server header this console sends and the shape of its config
    reply. This tells a stray service apart from the console; it is not
    authentication, and a local program could imitate both.
    """
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/config", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            if not (resp.headers.get("Server") or "").startswith("SIDConsole/"):
                return False
            payload = json.loads(resp.read(256 * 1024).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return (isinstance(payload, dict)
            and isinstance(payload.get("config"), dict)
            and isinstance(payload.get("state_dir"), str))


def launch(port: int | None) -> int:
    """Start the console in the background if needed and open the browser; returns at once."""
    import subprocess
    import time
    import webbrowser
    from pathlib import Path

    conf = cfg.load()
    port = int(port or conf.get("port") or cfg.DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"

    def alive() -> bool:
        return is_sid_console(url)

    if not alive():
        log = cfg.state_dir() / "server.log"
        root = Path(__file__).resolve().parent.parent
        with cfg.open_private_log(log) as out:
            subprocess.Popen([sys.executable, "-m", "sidconsole", "serve", "--port", str(port)],
                             cwd=root, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        for _ in range(60):
            if alive():
                break
            time.sleep(0.25)
        else:
            print(f"主控台未能啟動，請查看 {log}", file=sys.stderr)
            return 1
    webbrowser.open(url)
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
