#!/usr/bin/env python3
"""Re-runnable boundary check for VBear's managed Claude Code launch.

Thin wrapper; the check lives in vbear/boundary_check.py (also used by the
「驗證這個版本」 button). See that module for what is checked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear.boundary_check import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
