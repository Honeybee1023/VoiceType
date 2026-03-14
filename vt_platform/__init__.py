from __future__ import annotations

import sys

from .base import BasePlatform


def get_platform() -> BasePlatform:
    if sys.platform == "darwin":
        from .macos import MacOSPlatform

        return MacOSPlatform()
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    raise RuntimeError(f"Unsupported platform: {sys.platform}")
