"""Simplified-Chinese character check shared by the translation and suggestion modules.

This module imports no other vbear module on purpose: ``translations`` pulls in the runtime daemon, and the daemon pulls in
``meetings``, which needs ``SIMPLIFIED``. Keeping the set here is what breaks that cycle (#22); do not make this a lazy import instead.
"""
from __future__ import annotations

# Only distinct simplified forms; shared forms such as 查/入/程 are excluded.
SIMPLIFIED = frozenset("这个们审门时发说对为开关读写数据软档应该过还进选项页网络认证设计统务组详细输无问题状态线码")
