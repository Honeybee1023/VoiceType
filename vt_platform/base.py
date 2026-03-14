from __future__ import annotations

from typing import Callable, Optional, Tuple


class BaseIndicator:
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        self._on_event = on_event

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def set_idle(self) -> None:
        return None

    def set_recording(self) -> None:
        return None

    def set_processing(self) -> None:
        return None

    def set_language(self, _language: str) -> None:
        return None


class BaseTextInjector:
    def paste_text(
        self,
        text: str,
        focused_element: Optional[object] = None,
        click_target: Optional[Tuple[int, int]] = None,
        target_app: Optional[str] = None,
    ) -> None:
        raise NotImplementedError


class BasePlatform:
    name: str = "base"

    def create_indicator(self, on_event: Optional[Callable[[str], None]] = None) -> BaseIndicator:
        return BaseIndicator(on_event=on_event)

    def create_text_injector(self) -> BaseTextInjector:
        raise NotImplementedError

    def get_frontmost_app(self) -> Optional[str]:
        return None

    def focus_app(self, _app: Optional[str]) -> None:
        return None

    def capture_focused_element(self) -> Optional[object]:
        return None

    def run_quartz_hotkey_loop(self, _hotkey: str, _on_trigger: Callable[[], None]) -> None:
        return None
