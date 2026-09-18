"""python3 -m sidconsole [serve|scan|doctor] [--port N] [--open]"""

from __future__ import annotations

import argparse
import json
import sys

from . import config as cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sidconsole", description="SID Herdr 技能與團隊主控台")
    sub = parser.add_subparsers(dest="cmd")
    p_serve = sub.add_parser("serve", help="啟動本機主控台（預設）")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--open", action="store_true", help="啟動後開啟瀏覽器")
    p_serve.add_argument("--verbose", action="store_true")
    p_launch = sub.add_parser("launch", help="背景啟動主控台（若尚未執行）並開啟瀏覽器")
    p_launch.add_argument("--port", type=int)
    sub.add_parser("scan", help="重新掃描並輸出摘要")
    sub.add_parser("doctor", help="檢查來源與 herdr 連線")
    args = parser.parse_args(argv)

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
        from .bridge import herdr
        conf = cfg.load()
        ok = True
        for src in cfg.sources_from(conf):
            exists = src.resolved().exists()
            ok &= exists or not src.enabled
            print(f"[{'OK ' if exists else '缺 '}] {src.label:<24} {src.path}{'' if src.enabled else '（已停用）'}")
        snap = herdr.snapshot(conf.get("herdr_bin", ""))
        print(f"[{'OK ' if snap['available'] else '缺 '}] herdr 連線  {snap['version'] or ''} {snap['binary'] or ''}")
        for p in snap["problems"]:
            print("     ", p)
        print(f"狀態目錄：{cfg.state_dir()}")
        return 0 if ok else 1
    return 0


def launch(port: int | None) -> int:
    """Used by the herdr plugin action: never blocks herdr."""
    import subprocess
    import time
    import urllib.request
    import webbrowser
    from pathlib import Path

    conf = cfg.load()
    port = int(port or conf.get("port") or cfg.DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"

    def alive() -> bool:
        try:
            with urllib.request.urlopen(url + "api/config", timeout=1) as resp:
                return resp.status == 200
        except OSError:
            return False

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
