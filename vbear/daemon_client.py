"""The console's side of a runtime-daemon call (S2c): one function, one
error type. The daemon answers {"ok": true, "result": ...} or {"ok": false,
"error": {"code", "message"}}; here that becomes the result or a DaemonError
that already carries the HTTP status the console answers with. An unreachable
daemon is a 503, never a made-up success.

Codes of the daemon: bad_request (400), refused (409: the thing is not
allowed now, and the message says why), limit (429), internal (500).
"""

from __future__ import annotations

STATUS = {"bad_request": 400, "refused": 409, "limit": 429, "internal": 500}


class DaemonError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def call(runtime, op: str, *, timeout: float = 10.0, **fields) -> dict:
    """The result of ``op`` on the daemon behind ``runtime`` (anything with
    ``_rpc(op, timeout, **fields)``). DaemonError for a refusal or when the
    daemon cannot be reached or answers something that is not an answer."""
    try:
        reply = runtime._rpc(op, timeout=timeout, **fields)
    except (OSError, ValueError) as exc:           # no socket, refused, closed, or not JSON
        raise DaemonError(503, "unavailable", f"VBear runtime 背景程序無法連線（{type(exc).__name__}）") from exc
    except Exception as exc:                        # NativeRuntimeError and the like
        raise DaemonError(503, "unavailable", f"VBear runtime 背景程序無法使用（{type(exc).__name__}）") from exc
    if not isinstance(reply, dict):
        raise DaemonError(502, "bad_reply", "背景程序的回應不是物件")
    if reply.get("ok") is True and isinstance(reply.get("result"), dict):
        return reply["result"]
    err = reply.get("error")
    if reply.get("ok") is False and isinstance(err, dict):
        code = err.get("code") if isinstance(err.get("code"), str) else "internal"
        message = err.get("message") if isinstance(err.get("message"), str) else "（背景程序沒有說明原因）"
        raise DaemonError(STATUS.get(code, 500), code, message[:500])
    raise DaemonError(502, "bad_reply", "背景程序的回應格式不符")
