"""One error type for the console's flow actions (S2c): an HTTP status, a
short code the screen can switch on, a message for people, and optional extra
fields that are safe to send (never a secret). Raised by the services in
risk_acceptance and flow_executor, answered once by the server."""

from __future__ import annotations


QUOTA_PHRASE = "請刪除不再需要的舊流程"      # runtime/quota.py: what the ledger says when the room is used up


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        # a full quota is said in the answer; the screen then lists the flows that can be deleted (S2c-5)
        if QUOTA_PHRASE in message:
            extra.setdefault("storage", True)
        self.status, self.code, self.extra = status, code, extra
