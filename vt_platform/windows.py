from __future__ import annotations

import sys
import threading
import time
from queue import Queue, Empty
from typing import Callable, Optional, Tuple

from pynput import keyboard, mouse

from .base import BaseIndicator, BasePlatform, BaseTextInjector


class WindowsIndicator(BaseIndicator):
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        super().__init__(on_event=on_event)
        self._thread: Optional[threading.Thread] = None
        self._queue: "Queue[Tuple[str, Optional[str]]]" = Queue()
        self._root = None
        self.requires_main_thread = True
        self._debug = False
        self._style = "auto"

    def set_debug(self, enabled: bool) -> None:
        self._debug = bool(enabled)

    def set_style(self, style: str) -> None:
        style = (style or "").lower()
        if style not in {"auto", "normal", "borderless"}:
            style = "auto"
        self._style = style

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(("exit", None))
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def set_idle(self) -> None:
        self._queue.put(("state", "idle"))

    def set_recording(self) -> None:
        self._queue.put(("state", "recording"))

    def set_processing(self) -> None:
        self._queue.put(("state", "processing"))

    def set_language(self, language: str) -> None:
        self._queue.put(("lang", language))

    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception as exc:
            print(f"[VoiceType] Windows indicator unavailable: {exc}", file=sys.stderr)
            return

        state = "idle"
        language = "en"

        def build_label_text() -> str:
            label_lang = {
                "en": "EN",
                "zh-hans": "ZH-S",
                "zh-hant": "ZH-T",
            }.get(language, language)
            return f"VoiceType | {state} | {label_lang}"

        def apply_state(st: str) -> None:
            nonlocal state
            state = st
            if state == "recording":
                label.configure(fg="#ffffff", bg="#c0392b")
                menu_label.configure(fg="#ffffff", bg="#c0392b")
            elif state == "processing":
                label.configure(fg="#ffffff", bg="#d35400")
                menu_label.configure(fg="#ffffff", bg="#d35400")
            else:
                label.configure(fg="#000000", bg="#ecf0f1")
                menu_label.configure(fg="#000000", bg="#ecf0f1")
            label.configure(text=build_label_text())

        def apply_language(lang: str) -> None:
            nonlocal language
            language = lang
            label.configure(text=build_label_text())

        root = tk.Tk()
        self._root = root
        if self._debug:
            root.title("VoiceType Indicator (Debug)")
        borderless = self._style == "borderless"
        if self._style == "auto":
            borderless = False
        if borderless:
            root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#ecf0f1")

        container = tk.Frame(root, bg="#ecf0f1")
        container.pack()

        label = tk.Label(
            root,
            text=build_label_text(),
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=6,
            bg="#ecf0f1",
            fg="#000000",
        )
        label.pack(in_=container, side="left")

        menu_label = tk.Label(
            root,
            text="v",
            font=("Segoe UI", 9, "bold"),
            padx=6,
            pady=6,
            bg="#ecf0f1",
            fg="#000000",
        )
        menu_label.pack(in_=container, side="left")

        def on_click(_event):
            if self._on_event is not None:
                self._on_event("toggle")

        label.bind("<Button-1>", on_click)

        def on_toggle_language(lang: str) -> None:
            if self._on_event is not None:
                self._on_event(f"mode:{lang}")
            apply_language(lang)

        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="English", command=lambda: on_toggle_language("en"))
        menu.add_command(label="Chinese Simplified", command=lambda: on_toggle_language("zh-hans"))
        menu.add_command(label="Chinese Traditional", command=lambda: on_toggle_language("zh-hant"))

        def open_menu(event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        menu_label.bind("<Button-1>", open_menu)
        label.bind("<Button-3>", open_menu)

        root.update_idletasks()
        width = container.winfo_reqwidth() or container.winfo_width() or 240
        height = container.winfo_reqheight() or container.winfo_height() or 34
        width = max(width, 240)
        height = max(height, 34)
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = int((screen_w - width) / 2)
        y = int(screen_h - height - 60)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(200, 30)
        root.resizable(True, True)
        if self._debug:
            print(
                "[VoiceType] Indicator geometry:",
                f"{width}x{height}+{x}+{y}",
                file=sys.stderr,
            )
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
            except Exception as exc:
                print(f"[VoiceType] Indicator debug lift failed: {exc}", file=sys.stderr)

        def on_close() -> None:
            self._queue.put(("exit", None))
            try:
                root.destroy()
            except Exception:
                pass

        root.protocol("WM_DELETE_WINDOW", on_close)

        def poll_queue() -> None:
            try:
                while True:
                    command, payload = self._queue.get_nowait()
                    if command == "exit":
                        root.destroy()
                        return
                    if command == "state" and payload is not None:
                        apply_state(payload)
                    if command == "lang" and payload is not None:
                        apply_language(payload)
            except Empty:
                pass
            root.after(100, poll_queue)

        poll_queue()
        try:
            root.mainloop()
        except Exception as exc:
            print(f"[VoiceType] Indicator mainloop error: {exc}", file=sys.stderr)

    def run_forever(self) -> None:
        self._run()


class WindowsTextInjector(BaseTextInjector):
    def __init__(self, force_clipboard: bool = False, allow_typing: bool = False, restore_click: bool = False):
        self._controller = keyboard.Controller()
        self._mouse = mouse.Controller()
        self._force_clipboard = force_clipboard
        self._allow_typing = allow_typing
        self._restore_click = restore_click
        self._use_sendinput = True

    def _release_modifiers(self) -> None:
        keys = [
            keyboard.Key.shift,
            keyboard.Key.shift_l,
            keyboard.Key.shift_r,
            keyboard.Key.alt,
            keyboard.Key.alt_l,
            keyboard.Key.alt_r,
            keyboard.Key.alt_gr,
            keyboard.Key.ctrl,
            keyboard.Key.ctrl_l,
            keyboard.Key.ctrl_r,
            keyboard.Key.cmd,
            keyboard.Key.cmd_l,
            keyboard.Key.cmd_r,
        ]
        for key in keys:
            try:
                self._controller.release(key)
            except Exception:
                pass
        time.sleep(0.02)

    def _focus_window(self, hwnd: Optional[int]) -> bool:
        if not hwnd:
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            SW_RESTORE = 9
            SW_SHOW = 5

            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)
            foreground = user32.GetForegroundWindow()
            if foreground == hwnd:
                return True

            fg_pid = ctypes.c_ulong(0)
            target_pid = ctypes.c_ulong(0)
            fg_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(fg_pid))
            target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
            current_thread = kernel32.GetCurrentThreadId()

            if fg_thread != target_thread:
                user32.AttachThreadInput(fg_thread, current_thread, True)
                user32.AttachThreadInput(target_thread, current_thread, True)

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)

            if fg_thread != target_thread:
                user32.AttachThreadInput(fg_thread, current_thread, False)
                user32.AttachThreadInput(target_thread, current_thread, False)

            return user32.GetForegroundWindow() == hwnd
        except Exception as exc:
            print(f"[VoiceType] Win32 focus failed: {exc}", file=sys.stderr)
            return False

    def _try_sendinput(self, text: str) -> bool:
        if not text or not self._use_sendinput:
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32

            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002
            KEYEVENTF_UNICODE = 0x0004

            PUL = ctypes.POINTER(ctypes.c_ulong)

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", ctypes.c_ushort),
                    ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", PUL),
                ]

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [
                    ("dx", ctypes.c_long),
                    ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", PUL),
                ]

            class HARDWAREINPUT(ctypes.Structure):
                _fields_ = [
                    ("uMsg", ctypes.c_ulong),
                    ("wParamL", ctypes.c_ushort),
                    ("wParamH", ctypes.c_ushort),
                ]

            class INPUT_I(ctypes.Union):
                _fields_ = [
                    ("ki", KEYBDINPUT),
                    ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT),
                ]

            class INPUT(ctypes.Structure):
                _fields_ = [("type", ctypes.c_ulong), ("ii", INPUT_I)]

            inputs = (INPUT * (len(text) * 2))()
            extra = ctypes.cast(0, PUL)
            for i, ch in enumerate(text):
                code = ord(ch)
                inputs[2 * i].type = INPUT_KEYBOARD
                inputs[2 * i].ii.ki = KEYBDINPUT(
                    wVk=0,
                    wScan=code,
                    dwFlags=KEYEVENTF_UNICODE,
                    time=0,
                    dwExtraInfo=extra,
                )
                inputs[2 * i + 1].type = INPUT_KEYBOARD
                inputs[2 * i + 1].ii.ki = KEYBDINPUT(
                    wVk=0,
                    wScan=code,
                    dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=extra,
                )

            sent = user32.SendInput(len(inputs), ctypes.byref(inputs), ctypes.sizeof(INPUT))
            return sent == len(inputs)
        except Exception as exc:
            print(f"[VoiceType] Win32 SendInput failed: {exc}", file=sys.stderr)
            return False

    def _restore_click_focus(self, click_target: Optional[Tuple[int, int]]) -> None:
        if click_target is None or not self._restore_click:
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
        self._release_modifiers()
        with self._controller.pressed(keyboard.Key.ctrl):
            self._controller.press("v")
            self._controller.release("v")
        print("[VoiceType] Inject used: clipboard paste via Ctrl+V", file=sys.stderr)
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
        hwnd = focused_element if isinstance(focused_element, int) else None
        self._focus_window(hwnd)
        self._release_modifiers()
        if self._try_sendinput(text):
            print("[VoiceType] Inject used: Win32 SendInput", file=sys.stderr)
            return
        if self._force_clipboard:
            if self._try_clipboard_paste(text, click_target):
                return
            if not self._allow_typing:
                print(
                    "[VoiceType] Clipboard paste failed and typing is disabled.",
                    file=sys.stderr,
                )
                return
        else:
            if self._try_clipboard_paste(text, click_target):
                return
        self._restore_click_focus(click_target)
        self._release_modifiers()
        self._controller.type(text)
        print("[VoiceType] Inject used: keyboard typing", file=sys.stderr)


class WindowsPlatform(BasePlatform):
    name = "windows"
    def __init__(self):
        self._injector_options = {
            "force_clipboard": False,
            "allow_typing": False,
            "restore_click": False,
        }

    def set_text_injector_options(
        self,
        force_clipboard: bool = True,
        allow_typing: bool = False,
        restore_click: bool = False,
    ) -> None:
        self._injector_options = {
            "force_clipboard": bool(force_clipboard),
            "allow_typing": bool(allow_typing),
            "restore_click": bool(restore_click),
        }

    def create_indicator(self, on_event: Optional[Callable[[str], None]] = None) -> BaseIndicator:
        return WindowsIndicator(on_event=on_event)

    def create_text_injector(self) -> BaseTextInjector:
        return WindowsTextInjector(**self._injector_options)

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
        if not _app:
            return None
        if isinstance(_app, int):
            try:
                import ctypes

                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                SW_RESTORE = 9
                SW_SHOW = 5

                if user32.IsIconic(_app):
                    user32.ShowWindow(_app, SW_RESTORE)
                else:
                    user32.ShowWindow(_app, SW_SHOW)
                foreground = user32.GetForegroundWindow()
                if foreground == _app:
                    return None

                fg_pid = ctypes.c_ulong(0)
                target_pid = ctypes.c_ulong(0)
                fg_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(fg_pid))
                target_thread = user32.GetWindowThreadProcessId(_app, ctypes.byref(target_pid))
                current_thread = kernel32.GetCurrentThreadId()

                if fg_thread != target_thread:
                    user32.AttachThreadInput(fg_thread, current_thread, True)
                    user32.AttachThreadInput(target_thread, current_thread, True)

                user32.BringWindowToTop(_app)
                user32.SetForegroundWindow(_app)

                if fg_thread != target_thread:
                    user32.AttachThreadInput(fg_thread, current_thread, False)
                    user32.AttachThreadInput(target_thread, current_thread, False)
            except Exception:
                return None
            return None
        return None

    def capture_focused_element(self) -> Optional[object]:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                print("[VoiceType] Captured focused window handle for session.", file=sys.stderr)
                return int(hwnd)
            return None
        except Exception:
            return None

    def run_quartz_hotkey_loop(self, _hotkey: str, _on_trigger: Callable[[], None]) -> None:
        return None
