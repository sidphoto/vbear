"""Descendant tracking for managed Agent sessions (Phase R3 S2).

Why this exists: Claude Code runs every Bash-tool command in its own process
group, not in the session leader's. ``killpg(leader)`` therefore neither
reaches those processes nor proves they are gone (T-01 evidence, round 9).
A tracker walks the process table from the leader, remembers every
descendant it has seen as ``(pid, start time)`` and can later say which of
them still exist, even after they were re-parented to launchd.

Limits, stated rather than hidden:
  * a descendant that appears and exits between two observations is never
    recorded (it is also already gone);
  * one that detaches before it was observed is not tracked. Callers must
    treat "cannot prove dead" as retain, never as cleaned.
The table comes from libproc on macOS (``ps`` elsewhere). A process is
identified by pid plus start time, which tells a reused pid from the process
we recorded.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

PS = "/bin/ps"
PS_TIMEOUT = 1.0  # the daemon loop is single-threaded; never wait long for ps
_PROC_PIDTBSDINFO = 3
_PROC_PIDT_SHORTBSDINFO = 13
_SZOMB = 5


class ProcessTableUnavailable(RuntimeError):
    pass


class _ProcBsdInfo(ctypes.Structure):  # <sys/proc_info.h> struct proc_bsdinfo
    _fields_ = [("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
                ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
                ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
                ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
                ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
                ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
                ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
                ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
                ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
                ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64)]


class _ProcBsdShortInfo(ctypes.Structure):  # struct proc_bsdshortinfo
    _fields_ = [("pbsi_pid", ctypes.c_uint32), ("pbsi_ppid", ctypes.c_uint32),
                ("pbsi_pgid", ctypes.c_uint32), ("pbsi_status", ctypes.c_uint32),
                ("pbsi_comm", ctypes.c_char * 16), ("pbsi_flags", ctypes.c_uint32),
                ("pbsi_uid", ctypes.c_uint32), ("pbsi_gid", ctypes.c_uint32),
                ("pbsi_ruid", ctypes.c_uint32), ("pbsi_rgid", ctypes.c_uint32),
                ("pbsi_svuid", ctypes.c_uint32), ("pbsi_svgid", ctypes.c_uint32),
                ("pbsi_rfu", ctypes.c_uint32)]


def _load_libproc():
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_listallpids.restype = ctypes.c_int
        lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        return lib
    except (OSError, AttributeError):
        return None


_LIBPROC = _load_libproc()
# One source per process lifetime, never mixed: start times from the two
# sources are formatted differently, and a recorded identity must only ever be
# compared with one taken the same way. ``ps`` is setuid and cannot be run by
# a sandboxed process, which is why libproc is preferred where it exists.
SOURCE = "libproc" if _LIBPROC is not None else "ps"


def _table_libproc() -> list[dict]:
    lib = _LIBPROC
    n = lib.proc_listallpids(None, 0)
    if n <= 0:
        raise ProcessTableUnavailable("proc_listallpids failed")
    buf = (ctypes.c_int * (n + 64))()
    n = lib.proc_listallpids(buf, ctypes.sizeof(buf))
    if n <= 0:
        raise ProcessTableUnavailable("proc_listallpids failed")
    info, size, rows = _ProcBsdInfo(), ctypes.sizeof(_ProcBsdInfo), []
    short, short_size = _ProcBsdShortInfo(), ctypes.sizeof(_ProcBsdShortInfo)
    for pid in buf[:n]:
        if pid <= 0:
            continue
        if lib.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), size) == size:
            rows.append({"pid": info.pbi_pid, "ppid": info.pbi_ppid, "pgid": info.pbi_pgid,
                         "uid": info.pbi_uid, "stat": "Z" if info.pbi_status == _SZOMB else "R",
                         "start": f"{info.pbi_start_tvsec}.{info.pbi_start_tvusec:06d}"})
        elif lib.proc_pidinfo(pid, _PROC_PIDT_SHORTBSDINFO, 0, ctypes.byref(short), short_size) == short_size:
            # Another user's process (e.g. a setuid child): the full record is
            # not readable, so there is no start time. Keeping the row lets a
            # tracker see it as an unverifiable descendant instead of as gone.
            rows.append({"pid": short.pbsi_pid, "ppid": short.pbsi_ppid, "pgid": short.pbsi_pgid,
                         "uid": short.pbsi_uid, "stat": "Z" if short.pbsi_status == _SZOMB else "R",
                         "start": ""})
        # else: exited between the listing and the query
    if not any(r["pid"] == os.getpid() for r in rows):
        raise ProcessTableUnavailable("process table does not contain this process")
    return rows


def _table_ps() -> list[dict]:
    try:
        r = subprocess.run([PS, "-axo", "pid=,ppid=,pgid=,uid=,stat=,lstart="],
                           capture_output=True, text=True, timeout=PS_TIMEOUT,
                           env={"LC_ALL": "C", "PATH": "/bin:/usr/bin"})
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProcessTableUnavailable(str(exc)) from exc
    if r.returncode != 0:
        raise ProcessTableUnavailable(f"ps exit {r.returncode}")
    rows = []
    for line in r.stdout.splitlines():
        bits = line.strip().split(None, 5)
        if len(bits) != 6:
            continue
        try:
            pid, ppid, pgid, uid = map(int, bits[:4])
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "pgid": pgid, "uid": uid,
                     "stat": bits[4], "start": bits[5]})
    return rows


def process_table() -> list[dict]:
    return _table_libproc() if SOURCE == "libproc" else _table_ps()


def _live_index(rows: list[dict]) -> dict:
    return {(r["pid"], r["start"]): r for r in rows if "Z" not in r["stat"]}


class DescendantTracker:
    """Remembers every observed descendant of ``root_pid`` by (pid, start)."""

    def __init__(self, root_pid: int, identities=None, root_start: str | None = None):
        self.root_pid = int(root_pid)
        # Start time of the root: given, or taken at the first observation of
        # a fresh tracker. Once the root has been reaped its pid may be reused;
        # a process with another start time is not our root and its children
        # are not our descendants. A tracker restored from recorded identities
        # without ``root_start`` never follows the root pid at all.
        self.root_start: str | None = root_start
        # (pid, start) -> last seen row, for processes that still existed at
        # the last observation.
        self.identities: dict[tuple[int, str], dict] = {}
        # Process groups whose leader was an observed descendant. The kernel
        # does not reuse a pid while a group with that id still has members, so
        # a group stays ours until we see it empty; then it is forgotten.
        self.known_groups: set[int] = set()
        for pid, start in identities or ():
            self.identities[(int(pid), str(start))] = {"pid": int(pid), "start": str(start)}

    def observe(self, rows: list[dict] | None = None) -> bool:
        """Record current descendants. Returns True when a new one was added."""
        rows = process_table() if rows is None else rows
        by_pid = {r["pid"]: r for r in rows}
        root = by_pid.get(self.root_pid)
        if self.root_start is None and root is not None and not self.identities:
            self.root_start = root["start"]
        # Start from the root (only while it is still the same process) and from
        # every still-identical recorded process, so children of an already
        # re-parented descendant are still followed.
        live = _live_index(rows)
        seeds = {pid for (pid, start) in self.identities if (pid, start) in live}
        if root is not None and self.root_start is not None and root["start"] == self.root_start:
            seeds.add(self.root_pid)
        me = os.getuid()
        populated = {r["pgid"] for r in rows}
        self.known_groups &= populated  # an emptied group id may be reused by anyone
        seen, grew = set(seeds), True
        while grew:
            grew = False
            for r in rows:
                if r["pid"] in seen:
                    # A descendant leading its own group makes that group ours.
                    # The root's group is the caller's business, not tracked here.
                    # A group led by another user's process (setuid child) is never
                    # claimed: its members stay unverifiable and are left alone.
                    if (r["pid"] == r["pgid"] and r["pid"] != self.root_pid and r["uid"] == me
                            and r["pgid"] not in self.known_groups):
                        self.known_groups.add(r["pgid"])
                        grew = True
                elif r["ppid"] in seen or r["pgid"] in self.known_groups:
                    # Child of a descendant, or a member of one of our groups whose
                    # parent already exited (e.g. a command left running with ``&``).
                    seen.add(r["pid"])
                    grew = True
        added = False
        for pid in seen:
            r = by_pid.get(pid)
            if r is None:
                continue
            key = (r["pid"], r["start"])
            if key not in self.identities:
                added = True
            self.identities[key] = dict(r)
        # A (pid, start) that is gone never comes back, so forget it: the record
        # stays bounded however long the session runs. Zombies count as gone.
        for key in [k for k in self.identities if k not in live]:
            del self.identities[key]
        return added

    def live(self, rows: list[dict] | None = None, *, uid: int | None = None) -> list[dict]:
        """Recorded processes that still exist with the same start time."""
        rows = process_table() if rows is None else rows
        index = _live_index(rows)
        out = [index[k] for k in self.identities if k in index]
        return [r for r in out if uid is None or r["uid"] == uid]

    def groups(self, rows: list[dict], *, uid: int, exclude_pgid: int) -> tuple[list[int], list[dict]]:
        """Process groups that may be signalled, and rows that may not.

        A group qualifies only when it is one of ours (its leader was an
        observed descendant and it has not been seen empty since) and the
        recorded member is a same-uid process. Anything else is returned as
        uncertain and must be left alone."""
        index = _live_index(rows)
        live = {k: index[k] for k in self.identities if k in index}
        groups, uncertain = set(), []
        for (pid, _start), r in live.items():
            if r["pgid"] == exclude_pgid:
                continue  # the session leader's own group is signalled by the caller
            if r["uid"] == uid and r["pgid"] in self.known_groups and r["pgid"] > 1:
                groups.add(r["pgid"])
            else:
                uncertain.append(dict(r))
        return sorted(groups), uncertain

    def export(self) -> list[list]:
        return sorted([pid, start] for pid, start in self.identities)
