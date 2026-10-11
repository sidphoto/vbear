"""One error type for the console's flow actions (S2c): an HTTP status, a
short code the screen can switch on, a message for people, and optional extra
fields that are safe to send (never a secret). Raised by the services in
risk_acceptance and flow_executor, answered once by the server."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.extra = status, code, extra
