from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple, Dict

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXSelectedTextAttribute,
    kAXValueAttribute,
)
from pynput import keyboard, mouse

from .base import BaseIndicator, BasePlatform, BaseTextInjector


class RecordingIndicator(BaseIndicator):
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        super().__init__(on_event=on_event)
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._proc is not None or sys.platform != "darwin":
            return

        try:
            helper_binary = self._ensure_helper_binary()
            self._proc = subprocess.Popen(
                [str(helper_binary)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if self._proc.stdout is not None and self._on_event is not None:
                self._reader_thread = threading.Thread(target=self._read_events, daemon=True)
                self._reader_thread.start()
        except Exception as exc:
            self._proc = None
            print(f"[VoiceType] Indicator disabled: {exc}", file=sys.stderr)

    def stop(self) -> None:
        self._send("exit")
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.wait(timeout=1.0)
            except Exception:
                self._proc.kill()
            self._proc = None
            self._reader_thread = None

    def set_idle(self) -> None:
        self._send("idle")

    def set_recording(self) -> None:
        self._send("recording")

    def set_processing(self) -> None:
        self._send("processing")

    def set_language(self, language: str) -> None:
        self._send(f"lang:{language}")

    def _send(self, command: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(command + "\n")
            self._proc.stdin.flush()
        except Exception:
            return

    def _read_events(self) -> None:
        if self._proc is None or self._proc.stdout is None or self._on_event is None:
            return
        try:
            for line in self._proc.stdout:
                command = line.strip().lower()
                if not command:
                    continue
                self._on_event(command)
        except Exception as exc:
            print(f"[VoiceType] Indicator event reader stopped: {exc}", file=sys.stderr)

    def _ensure_helper_binary(self) -> Path:
        repo_dir = Path(__file__).resolve().parent.parent
        source_path = repo_dir / "indicator_helper.m"
        binary_path = repo_dir / ".indicator_helper"

        needs_build = not binary_path.exists()
        if not needs_build and source_path.exists():
            needs_build = source_path.stat().st_mtime > binary_path.stat().st_mtime

        if needs_build:
            subprocess.run(
                [
                    "clang",
                    "-fobjc-arc",
                    str(source_path),
                    "-o",
                    str(binary_path),
                    "-framework",
                    "Cocoa",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        return binary_path


class MacOSTextInjector(BaseTextInjector):
    def __init__(self):
        self._controller = keyboard.Controller()
        self._mouse = mouse.Controller()

    def _normalize_app_name(self, target_app: Optional[str]) -> str:
        return (target_app or "").strip().lower()

    def _should_force_direct_typing(self, target_app: Optional[str]) -> bool:
        app_name = self._normalize_app_name(target_app)
        if not app_name:
            return False
        # Some macOS apps either ignore AX value updates or accept synthetic paste
        # keystrokes without actually inserting text. Use raw typing for those.
        direct_type_apps = ("terminal", "iterm", "wechat", "微信")
        return any(name in app_name for name in direct_type_apps)

    def _restore_click_focus(self, click_target: Optional[Tuple[int, int]]) -> None:
        if click_target is None:
            return
        self._mouse.position = click_target
        time.sleep(0.04)
        self._mouse.click(mouse.Button.left, 1)
        time.sleep(0.06)

    def _type_text(self, text: str, click_target: Optional[Tuple[int, int]], reason: str) -> None:
        self._restore_click_focus(click_target)
        self._controller.type(text)
        print(f"[VoiceType] Fallback inject used: {reason}", file=sys.stderr)

    def _inject_ax(self, text: str, focused_element: object) -> bool:
        selected_err = AXUIElementSetAttributeValue(
            focused_element,
            kAXSelectedTextAttribute,
            text,
        )
        if selected_err == 0:
            print("[VoiceType] AX inject success: kAXSelectedTextAttribute", file=sys.stderr)
            return True
        print(
            f"[VoiceType] AX inject failed: kAXSelectedTextAttribute AXError={selected_err}",
            file=sys.stderr,
        )

        value_err = AXUIElementSetAttributeValue(
            focused_element,
            kAXValueAttribute,
            text,
        )
        if value_err == 0:
            print("[VoiceType] AX inject success: kAXValueAttribute", file=sys.stderr)
            return True
        print(f"[VoiceType] AX inject failed: kAXValueAttribute AXError={value_err}", file=sys.stderr)
        return False

    def paste_text(
        self,
        text: str,
        focused_element: Optional[object] = None,
        click_target: Optional[Tuple[int, int]] = None,
        target_app: Optional[str] = None,
    ) -> None:
        if not text:
            return
        if self._should_force_direct_typing(target_app):
            self._type_text(text, click_target, "app-specific direct typing")
            return

        if focused_element is not None and self._inject_ax(text, focused_element):
            return
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        self._restore_click_focus(click_target)

        # Use one paste method at a time to avoid duplicate insertion.
        apple_paste = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if apple_paste.returncode == 0:
            print("[VoiceType] Fallback inject used: clipboard paste via AppleScript", file=sys.stderr)
            return
        with self._controller.pressed(keyboard.Key.cmd):
            self._controller.press("v")
            self._controller.release("v")
        print("[VoiceType] Fallback inject used: clipboard paste via Cmd+V", file=sys.stderr)


class MacOSPlatform(BasePlatform):
    name = "macos"

    def create_indicator(self, on_event: Optional[Callable[[str], None]] = None) -> BaseIndicator:
        return RecordingIndicator(on_event=on_event)

    def create_text_injector(self) -> BaseTextInjector:
        return MacOSTextInjector()

    def get_frontmost_app(self) -> Optional[str]:
        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        try:
            out = subprocess.check_output(["osascript", "-e", script], text=True)
            return out.strip() or None
        except Exception:
            return None

    def focus_app(self, app: Optional[str]) -> None:
        if not app:
            return
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app}" to activate'],
                check=False,
                capture_output=True,
                text=True,
            )
            time.sleep(0.12)
        except Exception:
            return

    def capture_focused_element(self) -> Optional[object]:
        try:
            system = AXUIElementCreateSystemWide()
            err, focused_element = AXUIElementCopyAttributeValue(
                system,
                kAXFocusedUIElementAttribute,
                None,
            )
            if err == 0 and focused_element is not None:
                print("[VoiceType] Captured focused AX element for session.", file=sys.stderr)
                return focused_element
            print(
                f"[VoiceType] Failed to capture focused AX element. AXError={err}",
                file=sys.stderr,
            )
            return None
        except Exception as exc:
            print(f"[VoiceType] AX capture error: {exc}", file=sys.stderr)
            return None

    def run_quartz_hotkey_loop(self, hotkey: str, on_trigger: Callable[[], None]) -> None:
        try:
            import Quartz
        except Exception as exc:
            print(f"[VoiceType] Quartz hotkey unavailable: {exc}", file=sys.stderr)
            return

        parsed = self._parse_simple_hotkey(hotkey)
        if parsed is None:
            print(
                "[VoiceType] Quartz hotkey expects format like <ctrl>+<shift>+r",
                file=sys.stderr,
            )
            return
        required_flags, keycode = parsed

        def callback(_proxy, event_type, event, _refcon):
            if event_type != Quartz.kCGEventKeyDown:
                return event
            flags = Quartz.CGEventGetFlags(event)
            if (flags & required_flags) != required_flags:
                return event
            event_keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            if event_keycode == keycode:
                on_trigger()
            return event

        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            callback,
            None,
        )
        if tap is None:
            print(
                "[VoiceType] Quartz hotkey failed to attach (check Input Monitoring).",
                file=sys.stderr,
            )
            return
        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), run_loop_source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()

    def _parse_simple_hotkey(self, hotkey: str) -> Optional[Tuple[int, int]]:
        parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
        if not parts:
            return None
        key_part = None
        required_flags = 0
        for part in parts:
            if part.startswith("<") and part.endswith(">"):
                mod = part[1:-1]
                if mod in {"ctrl", "control"}:
                    required_flags |= 1 << 18  # kCGEventFlagMaskControl
                elif mod in {"shift"}:
                    required_flags |= 1 << 17  # kCGEventFlagMaskShift
                elif mod in {"cmd", "command", "meta"}:
                    required_flags |= 1 << 20  # kCGEventFlagMaskCommand
                elif mod in {"alt", "option"}:
                    required_flags |= 1 << 19  # kCGEventFlagMaskAlternate
                else:
                    return None
            else:
                key_part = part
        if key_part is None or len(key_part) != 1:
            return None
        keycode_map: Dict[str, int] = {
            "a": 0,
            "s": 1,
            "d": 2,
            "f": 3,
            "h": 4,
            "g": 5,
            "z": 6,
            "x": 7,
            "c": 8,
            "v": 9,
            "b": 11,
            "q": 12,
            "w": 13,
            "e": 14,
            "r": 15,
            "y": 16,
            "t": 17,
            "1": 18,
            "2": 19,
            "3": 20,
            "4": 21,
            "6": 22,
            "5": 23,
            "=": 24,
            "9": 25,
            "7": 26,
            "-": 27,
            "8": 28,
            "0": 29,
            "]": 30,
            "o": 31,
            "u": 32,
            "[": 33,
            "i": 34,
            "p": 35,
            "l": 37,
            "j": 38,
            "'": 39,
            "k": 40,
            ";": 41,
            "\\": 42,
            ",": 43,
            "/": 44,
            "n": 45,
            "m": 46,
            ".": 47,
            "`": 50,
        }
        keycode = keycode_map.get(key_part.lower())
        if keycode is None:
            return None
        return required_flags, keycode
