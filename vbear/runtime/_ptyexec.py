"""PTY trampoline for the native runtime daemon (Phase R2 S1).

Run as ``python -I <this file> argv...`` with stdin/stdout/stderr already on
the PTY slave and a fresh session (``start_new_session=True``). It makes
the slave the controlling terminal, then execs the real command in place
(same pid, so the daemon's pid == pgid bookkeeping stays true).

Why a trampoline instead of ``pty.fork()``: the daemon may be threaded in
tests and in-process embeddings, and forking a threaded Python process can
deadlock the child. ``subprocess`` spawns via C; only this tiny, import-free
script runs in the new process before exec.
"""

import fcntl
import os
import sys
import termios


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        os.write(2, b"vbear runtime: missing command\r\n")
        os._exit(127)
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError as exc:  # still usable, but no job control / SIGWINCH
        os.write(2, f"vbear runtime: no controlling tty ({exc})\r\n".encode())
    try:
        os.execvp(argv[0], argv)
    except OSError as exc:
        os.write(2, f"vbear runtime: cannot run {argv[0]}: {exc}\r\n".encode())
        os._exit(127)


if __name__ == "__main__":
    main()
