from __future__ import annotations

import sys
import time
from typing import Callable, Optional, Tuple

from pynput import keyboard, mouse

from .base import BaseIndicator, BasePlatform, BaseTextInjector


class WindowsIndicator(BaseIndicator):
    pass


class WindowsTextInjector(BaseTextInjector):
    def __init__(self):
        self._controller = keyboard.Controller()
        self._mouse = mouse.Controller()

    def _restore_click_focus(self, click_target: Optional[Tuple[int, int]]) -> None:
        if click_target is None:
            return
        self._mouse.position = click_target
        time.sleep(0.04)
        self._mouse.click(mouse.Button.left, 1)
        time.sleep(0.06)

    def _try_clipboard_paste(self, text: str, click_target: Optional[Tuple[int, int]]) -> bool:
        try:
            import pyperclip
        except Exception:
            return False
        try:
            pyperclip.copy(text)
        except Exception:
            return False
        self._restore_click_focus(click_target)
        with self._controller.pressed(keyboard.Key.ctrl):
            self._controller.press("v")
            self._controller.release("v")
        print("[VoiceType] Fallback inject used: clipboard paste via Ctrl+V", file=sys.stderr)
        return True

    def paste_text(
        self,
        text: str,
        focused_element: Optional[object] = None,
        click_target: Optional[Tuple[int, int]] = None,
        target_app: Optional[str] = None,
    ) -> None:
        if not text:
            return
        if self._try_clipboard_paste(text, click_target):
            return
        self._restore_click_focus(click_target)
        self._controller.type(text)
        print("[VoiceType] Fallback inject used: keyboard typing", file=sys.stderr)


class WindowsPlatform(BasePlatform):
    name = "windows"

    def create_indicator(self, on_event: Optional[Callable[[str], None]] = None) -> BaseIndicator:
        return WindowsIndicator(on_event=on_event)

    def create_text_injector(self) -> BaseTextInjector:
        return WindowsTextInjector()

    def get_frontmost_app(self) -> Optional[str]:
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return None
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            return title or None
        except Exception:
            return None

    def focus_app(self, _app: Optional[str]) -> None:
        return None

    def capture_focused_element(self) -> Optional[object]:
        return None

    def run_quartz_hotkey_loop(self, _hotkey: str, _on_trigger: Callable[[], None]) -> None:
        return None
