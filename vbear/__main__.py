"""python3 -m vbear [serve|scan|doctor] [--port N] [--open]"""

from __future__ import annotations

import argparse
import json
import sys

MIN_PYTHON = (3, 13)  # os.waitid on macOS (safe Agent CLI version probe) arrived in 3.13


def python_too_old(version_info=sys.version_info) -> str | None:
    if tuple(version_info[:2]) >= MIN_PYTHON:
        return None
    return (f"VBear 需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上，目前是 "
            f"{version_info[0]}.{version_info[1]}。請改用 Homebrew 或 python.org 的較新版本。\n"
            f"VBear requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+.")


if (_too_old := python_too_old()) is not None:
    sys.exit(_too_old)

from . import config as cfg  # noqa: E402  (after the version check on purpose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vbear", description="VBear：技能與團隊主控台")
    sub = parser.add_subparsers(dest="cmd")
    p_serve = sub.add_parser("serve", help="啟動本機主控台（預設）")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--open", action="store_true", help="啟動後開啟瀏覽器")
    p_serve.add_argument("--verbose", action="store_true")
    p_launch = sub.add_parser("launch", help="背景啟動主控台（若尚未執行）並開啟瀏覽器")
    p_launch.add_argument("--port", type=int)
    sub.add_parser("scan", help="重新掃描並輸出摘要")
    sub.add_parser("doctor", help="檢查來源與 VBear runtime 連線")
    sub.add_parser("runtimed", help="VBear runtime 背景程序（通常由主控台自動啟動）")
    args = parser.parse_args(argv)

    if args.cmd == "runtimed":
        from .runtime.daemon import main as runtimed_main
        return runtimed_main()

    _migrate_state_dir(getattr(args, "port", None))

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
        print(f"[{'OK ' if snap['available'] else '缺 '}] VBear runtime  {snap['version'] or ''} {snap['binary'] or ''}")
        for p in snap["problems"]:
            print("     ", p)
        print(f"狀態目錄：{cfg.state_dir()}")
        return 0 if ok else 1
    return 0


def is_vbear(url: str, timeout: float = 1.0, token: str | None = None) -> bool:
    """Whether `url` is served by a VBear, not merely something on the port.

    Checks the Server header this console sends and the shape of its config
    reply. This tells a stray service apart from the console; it is not
    authentication, and a local program could imitate both.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url.rstrip("/") + "/api/config")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            if not (resp.headers.get("Server") or "").startswith("VBear/"):
                return False
            payload = json.loads(resp.read(256 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A VBear that does not accept our token (another instance, or a token
        # file from an earlier run) still identifies itself.
        try:
            body = json.loads(exc.read(64 * 1024).decode("utf-8")) if exc.code == 401 else None
        except (OSError, ValueError, UnicodeDecodeError):
            body = None
        finally:
            exc.close()
        return ((exc.headers.get("Server") or "").startswith("VBear/")
                and isinstance(body, dict) and body.get("code") == "auth_required")
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return (isinstance(payload, dict)
            and isinstance(payload.get("config"), dict)
            and isinstance(payload.get("state_dir"), str))


def launch(port: int | None) -> int:
    """Start the console in the background if needed and open the browser; returns at once."""
    import subprocess
    import time
    from pathlib import Path

    conf = cfg.load()
    port = int(port or conf.get("port") or cfg.DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"

    from .server import open_in_browser, read_access_token

    def alive() -> bool:
        return is_vbear(url, token=read_access_token(port))

    if not alive():
        log = cfg.state_dir() / "server.log"
        root = Path(__file__).resolve().parent.parent
        with cfg.open_private_log(log) as out:
            subprocess.Popen([sys.executable, "-m", "vbear", "serve", "--port", str(port)],
                             cwd=root, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        for _ in range(60):
            if alive():
                break
            time.sleep(0.25)
        else:
            print(f"主控台未能啟動，請查看 {log}", file=sys.stderr)
            return 1
    open_in_browser(port)
    print(url)
    return 0


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((cfg.DEFAULT_HOST, port)) == 0


def _migrate_state_dir(port: int | None) -> None:
    """One-time move of the pre-rename state directory (~/.sid-console)."""
    result = cfg.migrate_legacy_state_dir(
        lambda legacy_port: _port_in_use(legacy_port) or (port is not None and _port_in_use(port)))
    if result == "moved":
        print(f"已把舊的狀態目錄 ~/{cfg.LEGACY_STATE_NAME} 搬到 {cfg.state_dir()}", file=sys.stderr)
    elif result == "conflict":
        print(f"注意：~/{cfg.LEGACY_STATE_NAME} 與 {cfg.state_dir()} 同時存在，VBear 使用後者，"
              f"不會自動合併；舊目錄裡的設定、註記與任務卡請自行確認後搬移或刪除。", file=sys.stderr)
    elif result.startswith("kept:"):
        why = {"kept:console_running": "舊版主控台仍在執行",
               "kept:runtime_running": "舊版 runtime 仍在執行",
               "kept:managed_launches_pending":
                   f"~/{cfg.LEGACY_STATE_NAME}/sessions 裡還有等待清理或待人工檢查的受管 session",
               "kept:rename_failed": "搬移時發生檔案系統錯誤"}.get(result, result)
        print(f"暫時沿用舊的狀態目錄 ~/{cfg.LEGACY_STATE_NAME}（{why}）；停止後再啟動即會搬到 ~/.vbear",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
