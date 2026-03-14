#!/usr/bin/env python3
import argparse
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional, Tuple, Dict
import pyaudio
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXSelectedTextAttribute,
    kAXValueAttribute,
)
from faster_whisper import WhisperModel
from pynput import keyboard, mouse


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


class RecordingIndicator:
    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._on_event = on_event

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
        repo_dir = Path(__file__).resolve().parent
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


class TextInjector:
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
        if sys.platform == "darwin":
            if self._should_force_direct_typing(target_app):
                self._type_text(text, click_target, "app-specific direct typing")
                return

        if focused_element is not None and self._inject_ax(text, focused_element):
            return
        if sys.platform == "darwin":
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
            return
        self._controller.type(text)
        print("[VoiceType] Fallback inject used: keyboard typing", file=sys.stderr)


class VoiceTypeAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._indicator = RecordingIndicator(on_event=self._handle_indicator_event)
        self._recorder = AudioRecorder(config)
        self._english_transcriber = WhisperTranscriber(self._build_english_config(config))
        self._chinese_transcriber: Optional[WhisperTranscriber] = None
        self._chinese_text_converter = ChineseTextConverter()
        self._injector = TextInjector()
        self._state_lock = threading.Lock()
        self._recording_active = False
        self._stop_recording_event = threading.Event()
        self._mouse_listener: Optional[mouse.Listener] = None
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
        self._indicator.start()
        self._indicator.set_idle()
        self._indicator.set_language(self._active_language_mode)
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        def on_hotkey() -> None:
            self._toggle_recording(trigger="hotkey")

        hotkey = keyboard.HotKey(keyboard.HotKey.parse(self.config.hotkey), on_hotkey)
        listener: Optional[keyboard.Listener] = None
        quartz_thread: Optional[threading.Thread] = None

        def on_press(key: object, injected: bool = False) -> None:
            # macOS media keys can arrive without the injected flag in pynput's
            # Darwin backend, so accept both callback shapes here.
            if injected or listener is None:
                return
            hotkey.press(listener.canonical(key))

        def on_release(key: object, injected: bool = False) -> None:
            if injected or listener is None:
                return
            hotkey.release(listener.canonical(key))

        try:
            if self.config.hotkey_backend in {"pynput", "both"}:
                listener = keyboard.Listener(on_press=on_press, on_release=on_release)
                listener.start()
            if self.config.hotkey_backend in {"quartz", "both"}:
                quartz_thread = threading.Thread(target=self._run_quartz_hotkey_loop, daemon=True)
                quartz_thread.start()
            if listener is not None:
                listener.join()
            elif quartz_thread is not None:
                while quartz_thread.is_alive():
                    time.sleep(0.25)
        finally:
            if self._mouse_listener is not None:
                self._mouse_listener.stop()
            self._indicator.stop()
            self._recorder.close()

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
        if sys.platform != "darwin":
            return None
        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        try:
            out = subprocess.check_output(["osascript", "-e", script], text=True)
            return out.strip() or None
        except Exception:
            return None

    def _focus_target_app(self) -> None:
        app = self._target_app_for_session
        if sys.platform != "darwin" or not app:
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

    def _capture_focused_element(self) -> Optional[object]:
        if sys.platform != "darwin":
            return None
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

    def _run_quartz_hotkey_loop(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            import Quartz
        except Exception as exc:
            print(f"[VoiceType] Quartz hotkey unavailable: {exc}", file=sys.stderr)
            return

        parsed = self._parse_simple_hotkey(self.config.hotkey)
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
                self._toggle_recording(trigger="quartz")
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
        if sys.platform != "darwin":
            return None
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

    def _get_transcriber_for_mode(self, language_mode: str) -> WhisperTranscriber:
        if language_mode in {"zh-hans", "zh-hant"}:
            if self._chinese_transcriber is None:
                print("[VoiceType] Loading Chinese Whisper model: small")
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
        return replace(config, whisper_model="small", language="zh")

    def _normalize_language_mode(self, language: str) -> str:
        normalized = language.lower()
        if normalized in {"zh", "zh-hans", "zh-cn", "zh-simplified"}:
            return "zh-hans"
        if normalized in {"zh-hant", "zh-tw", "zh-traditional"}:
            return "zh-hant"
        return "en"


def parse_args() -> AgentConfig:
    parser = argparse.ArgumentParser(description="Local hotkey voice-to-text typer.")
    parser.add_argument("--hotkey", default="<ctrl>+<shift>+r")
    parser.add_argument("--hotkey-backend", default="pynput", choices=["pynput", "quartz", "both"])
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="default")
    parser.add_argument("--max-record-seconds", type=float, default=0.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-size", type=int, default=1024)
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
    )


if __name__ == "__main__":
    cfg = parse_args()
    agent = VoiceTypeAgent(cfg)
    agent.run()
