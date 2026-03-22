#!/usr/bin/env python3
import argparse
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple

import pyaudio
from faster_whisper import WhisperModel
from pynput import keyboard, mouse

from vt_platform import get_platform


@dataclass
class AgentConfig:
    hotkey: str = "<ctrl>+<shift>+r"
    hotkey_backend: str = "pynput"
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    max_record_s: float = 0.0
    pre_type_delay_s: float = 0.2
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    whisper_compute_type: str = "default"
    language: str = "en"
    debug_indicator: bool = False
    indicator_style: str = "auto"


class AudioRecorder:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._pa = pyaudio.PyAudio()

    def close(self) -> None:
        self._pa.terminate()

    def record_until_stop(self, stop_event: threading.Event) -> Path:
        fmt = pyaudio.paInt16
        stream = self._pa.open(
            format=fmt,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            frames_per_buffer=self.config.chunk_size,
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(self.config.channels)
                wf.setsampwidth(self._pa.get_sample_size(fmt))
                wf.setframerate(self.config.sample_rate)

                chunks_recorded = 0
                max_chunks = None
                if self.config.max_record_s > 0:
                    max_chunks = int(
                        self.config.max_record_s * self.config.sample_rate / self.config.chunk_size
                    )

                while True:
                    if stop_event.is_set():
                        break
                    if max_chunks is not None and chunks_recorded >= max_chunks:
                        print(
                            "[VoiceType] Max recording duration reached. Stopping capture.",
                            file=sys.stderr,
                        )
                        break
                    data = stream.read(self.config.chunk_size, exception_on_overflow=False)
                    wf.writeframes(data)
                    chunks_recorded += 1
        finally:
            stream.stop_stream()
            stream.close()

        return wav_path

class WhisperTranscriber:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._model = WhisperModel(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )

    def transcribe_wav(self, wav_path: Path) -> str:
        segments, _info = self._model.transcribe(
            str(wav_path),
            language=self.config.language,
            vad_filter=True,
            beam_size=1,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()


class ChineseTextConverter:
    def __init__(self):
        self._simplified = None
        self._traditional = None

    def convert(self, text: str, language_mode: str) -> str:
        if language_mode == "zh-hans":
            return self._get_simplified_converter().convert(text)
        if language_mode == "zh-hant":
            return self._get_traditional_converter().convert(text)
        return text

    def _get_simplified_converter(self):
        if self._simplified is None:
            self._simplified = self._build_converter("t2s")
        return self._simplified

    def _get_traditional_converter(self):
        if self._traditional is None:
            self._traditional = self._build_converter("s2t")
        return self._traditional

    def _build_converter(self, config: str):
        try:
            from opencc import OpenCC
        except ImportError as exc:
            raise RuntimeError(
                "Chinese script conversion requires opencc. "
                "Run `source .venv/bin/activate && python -m pip install -r requirements.txt`."
            ) from exc
        return OpenCC(config)


class VoiceTypeAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._platform = get_platform()
        self._indicator = self._platform.create_indicator(on_event=self._handle_indicator_event)
        if hasattr(self._indicator, "set_debug"):
            try:
                self._indicator.set_debug(self.config.debug_indicator)
            except Exception:
                pass
        if hasattr(self._indicator, "set_style"):
            try:
                self._indicator.set_style(self.config.indicator_style)
            except Exception:
                pass
        self._recorder = AudioRecorder(config)
        self._english_transcriber = WhisperTranscriber(self._build_english_config(config))
        self._chinese_transcriber: Optional[WhisperTranscriber] = None
        self._chinese_text_converter = ChineseTextConverter()
        self._injector = self._platform.create_text_injector()
        self._state_lock = threading.Lock()
        self._recording_active = False
        self._stop_recording_event = threading.Event()
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._quartz_thread: Optional[threading.Thread] = None
        self._last_click_app: Optional[str] = None
        self._last_click_pos: Optional[Tuple[int, int]] = None
        self._target_app_for_session: Optional[str] = None
        self._target_click_for_session: Optional[Tuple[int, int]] = None
        self._target_ax_element_for_session: Optional[object] = None
        self._active_language_mode = self._normalize_language_mode(config.language)
        self._language_mode_for_session = self._active_language_mode

    def run(self) -> None:
        print(f"[VoiceType] Listening for hotkey: {self.config.hotkey}")
        print("[VoiceType] Press Ctrl+C in this terminal to exit.")
        self._indicator.set_idle()
        self._indicator.set_language(self._active_language_mode)
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        try:
            self._start_hotkey_listeners()
            if getattr(self._indicator, "requires_main_thread", False) and hasattr(
                self._indicator, "run_forever"
            ):
                try:
                    self._indicator.run_forever()
                except KeyboardInterrupt:
                    self._indicator.stop()
            else:
                self._indicator.start()
                self._block_until_exit()
        finally:
            if self._mouse_listener is not None:
                self._mouse_listener.stop()
            if self._keyboard_listener is not None:
                self._keyboard_listener.stop()
            self._indicator.stop()
            self._recorder.close()

    def _start_hotkey_listeners(self) -> None:
        def on_hotkey() -> None:
            self._toggle_recording(trigger="hotkey")

        hotkey = keyboard.HotKey(keyboard.HotKey.parse(self.config.hotkey), on_hotkey)

        def on_press(key: object, injected: bool = False) -> None:
            # macOS media keys can arrive without the injected flag in pynput's
            # Darwin backend, so accept both callback shapes here.
            if injected or self._keyboard_listener is None:
                return
            hotkey.press(self._keyboard_listener.canonical(key))

        def on_release(key: object, injected: bool = False) -> None:
            if injected or self._keyboard_listener is None:
                return
            hotkey.release(self._keyboard_listener.canonical(key))

        if self.config.hotkey_backend in {"pynput", "both"}:
            self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._keyboard_listener.start()
        if self.config.hotkey_backend in {"quartz", "both"}:
            self._quartz_thread = threading.Thread(
                target=self._platform.run_quartz_hotkey_loop,
                args=(self.config.hotkey, on_hotkey),
                daemon=True,
            )
            self._quartz_thread.start()

    def _block_until_exit(self) -> None:
        if self._keyboard_listener is not None:
            self._keyboard_listener.join()
            return
        if self._quartz_thread is None:
            return
        while self._quartz_thread.is_alive():
            time.sleep(0.25)

    def _toggle_recording(self, trigger: str) -> None:
        with self._state_lock:
            if not self._recording_active:
                self._recording_active = True
                self._stop_recording_event.clear()
                self._language_mode_for_session = self._active_language_mode
                self._indicator.set_recording()
                self._target_ax_element_for_session = self._capture_focused_element()
                self._target_app_for_session = self._last_click_app or self._get_frontmost_app()
                self._target_click_for_session = self._last_click_pos
                worker = threading.Thread(target=self._handle_session, daemon=True)
                worker.start()
                print(
                    "[VoiceType] Recording started. Press hotkey again to stop."
                    f" Trigger: {trigger}"
                    f" Target app: {self._target_app_for_session or 'unknown'}"
                    f" Language: {self._language_mode_for_session}"
                )
                return
            self._stop_recording_event.set()
            self._indicator.set_processing()
            print(f"[VoiceType] Stop requested. Trigger: {trigger}. Transcribing...")

    def _handle_session(self) -> None:
        wav_path: Optional[Path] = None
        try:
            wav_path = self._recorder.record_until_stop(self._stop_recording_event)
            print(f"[VoiceType] Transcribing with language mode: {self._language_mode_for_session}")
            text = self._get_transcriber_for_mode(self._language_mode_for_session).transcribe_wav(wav_path)
            text = self._post_process_text(text, self._language_mode_for_session)
            if not text:
                print("[VoiceType] No speech detected.")
                return
            print(f"[VoiceType] Pasting: {text}")
            time.sleep(self.config.pre_type_delay_s)
            self._focus_target_app()
            self._injector.paste_text(
                text,
                focused_element=self._target_ax_element_for_session,
                click_target=self._target_click_for_session,
                target_app=self._target_app_for_session,
            )
        except Exception as exc:
            print(f"[VoiceType] Error: {exc}")
        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)
            with self._state_lock:
                self._recording_active = False
                self._stop_recording_event.clear()
                self._target_app_for_session = None
                self._target_click_for_session = None
                self._target_ax_element_for_session = None
                self._language_mode_for_session = self._active_language_mode
                self._indicator.set_idle()

    def _on_click(self, _x: int, _y: int, _button: mouse.Button, pressed: bool) -> None:
        if not pressed:
            return
        app = self._get_frontmost_app()
        if app:
            self._last_click_app = app
            self._last_click_pos = (_x, _y)

    def _get_frontmost_app(self) -> Optional[str]:
        return self._platform.get_frontmost_app()

    def _focus_target_app(self) -> None:
        self._platform.focus_app(self._target_app_for_session)

    def _capture_focused_element(self) -> Optional[object]:
        return self._platform.capture_focused_element()

    def _handle_indicator_event(self, event: str) -> None:
        if event == "toggle":
            self._toggle_recording(trigger="indicator")
            return
        if not event.startswith("mode:"):
            print(f"[VoiceType] Ignoring unknown indicator event: {event}", file=sys.stderr)
            return
        language_mode = self._normalize_language_mode(event.split(":", 1)[1])
        with self._state_lock:
            self._active_language_mode = language_mode
            self._indicator.set_language(language_mode)
        print(f"[VoiceType] Language mode switched to: {language_mode}")

    def _get_transcriber_for_mode(self, language_mode: str) -> WhisperTranscriber:
        if language_mode in {"zh-hans", "zh-hant"}:
            if self._chinese_transcriber is None:
                print("[VoiceType] Loading Chinese Whisper model: medium")
                self._chinese_transcriber = WhisperTranscriber(self._build_chinese_config(self.config))
            return self._chinese_transcriber
        return self._english_transcriber

    def _post_process_text(self, text: str, language_mode: str) -> str:
        if not text:
            return text
        if language_mode in {"zh-hans", "zh-hant"}:
            return self._chinese_text_converter.convert(text, language_mode)
        return text

    def _build_english_config(self, config: AgentConfig) -> AgentConfig:
        return replace(config, language="en")

    def _build_chinese_config(self, config: AgentConfig) -> AgentConfig:
        return replace(config, whisper_model="medium", language="zh")

    def _normalize_language_mode(self, language: str) -> str:
        normalized = language.lower()
        if normalized in {"zh", "zh-hans", "zh-cn", "zh-simplified"}:
            return "zh-hans"
        if normalized in {"zh-hant", "zh-tw", "zh-traditional"}:
            return "zh-hant"
        return "en"


def parse_args() -> AgentConfig:
    parser = argparse.ArgumentParser(description="Local hotkey voice-to-text typer.")
    default_hotkey = "<alt>+<shift>+r" if sys.platform == "win32" else "<ctrl>+<shift>+r"
    parser.add_argument("--hotkey", default=default_hotkey)
    parser.add_argument("--hotkey-backend", default="pynput", choices=["pynput", "quartz", "both"])
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="default")
    parser.add_argument("--max-record-seconds", type=float, default=0.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-size", type=int, default=1024)
    parser.add_argument("--debug-indicator", action="store_true")
    parser.add_argument(
        "--indicator-style",
        default="auto",
        choices=["auto", "normal", "borderless"],
        help="Indicator window style (Windows only).",
    )
    args = parser.parse_args()

    return AgentConfig(
        hotkey=args.hotkey,
        hotkey_backend=args.hotkey_backend,
        max_record_s=args.max_record_seconds,
        whisper_model=args.model,
        whisper_device=args.device,
        whisper_compute_type=args.compute_type,
        language=args.language,
        sample_rate=args.sample_rate,
        chunk_size=args.chunk_size,
        debug_indicator=args.debug_indicator,
        indicator_style=args.indicator_style,
    )


if __name__ == "__main__":
    cfg = parse_args()
    agent = VoiceTypeAgent(cfg)
    agent.run()
