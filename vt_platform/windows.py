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

    def set_debug(self, enabled: bool) -> None:
        self._debug = bool(enabled)

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
        else:
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
        width = container.winfo_width() or 220
        height = container.winfo_height() or 30
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = int((screen_w - width) / 2)
        y = int(screen_h - height - 60)
        root.geometry(f"{width}x{height}+{x}+{y}")
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
