#!/usr/bin/env python3
import argparse
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    max_record_s: float = 30.0
    pre_type_delay_s: float = 0.2
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    whisper_compute_type: str = "default"
    language: str = "en"


class RecordingIndicator:
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        if self._proc is not None or sys.platform != "darwin":
            return

        indicator_script = r"""
import queue
import sys
import threading
import tkinter as tk

commands = queue.Queue()

def reader():
    for line in sys.stdin:
        commands.put(line.strip().lower())
    commands.put("exit")

threading.Thread(target=reader, daemon=True).start()

root = tk.Tk()
root.title("VoiceType Indicator")
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="#111111")
root.attributes("-alpha", 0.9)

label = tk.Label(
    root,
    text="○ IDLE",
    fg="#CCCCCC",
    bg="#111111",
    font=("Menlo", 12, "bold"),
    padx=12,
    pady=8,
)
label.pack()

root.update_idletasks()
width = root.winfo_reqwidth()
height = root.winfo_reqheight()
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
x = max(0, (screen_w - width) // 2)
y = max(0, screen_h - height - 50)
root.geometry(f"{width}x{height}+{x}+{y}")

def set_state(state: str) -> None:
    if state == "recording":
        label.configure(text="● REC", fg="#FF4D4D")
    elif state == "processing":
        label.configure(text="◔ WORKING", fg="#FFD166")
    else:
        label.configure(text="○ IDLE", fg="#CFCFCF")

def pump() -> None:
    while True:
        try:
            cmd = commands.get_nowait()
        except queue.Empty:
            break
        if cmd == "exit":
            root.destroy()
            return
        set_state(cmd)
    root.after(100, pump)

pump()
root.mainloop()
"""
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "-c", indicator_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as exc:
            self._proc = None
            print(f"[VoiceType] Indicator disabled: {exc}", file=sys.stderr)

    def stop(self) -> None:
        self._send("exit")
        if self._proc is not None:
            try:
                self._proc.wait(timeout=1.0)
            except Exception:
                self._proc.kill()
            self._proc = None

    def set_idle(self) -> None:
        self._send("idle")

    def set_recording(self) -> None:
        self._send("recording")

    def set_processing(self) -> None:
        self._send("processing")

    def _send(self, command: str) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(command + "\n")
            self._proc.stdin.flush()
        except Exception:
            return


class AudioRecorder:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._pa = pyaudio.PyAudio()

    def close(self) -> None:
        self._pa.terminate()

    def record_until_stop(self, stop_event: threading.Event) -> bytes:
        fmt = pyaudio.paInt16
        stream = self._pa.open(
            format=fmt,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            frames_per_buffer=self.config.chunk_size,
        )
        frames: List[bytes] = []
        max_chunks = int(self.config.max_record_s * self.config.sample_rate / self.config.chunk_size)

        try:
            for _ in range(max_chunks):
                if stop_event.is_set():
                    break
                data = stream.read(self.config.chunk_size, exception_on_overflow=False)
                frames.append(data)
        finally:
            stream.stop_stream()
            stream.close()

        return b"".join(frames)

class WhisperTranscriber:
    def __init__(self, config: AgentConfig):
        self.config = config
        self._model = WhisperModel(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )

    def transcribe_pcm16(self, pcm_bytes: bytes, sample_rate: int, channels: int) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_bytes)

            segments, _info = self._model.transcribe(
                str(wav_path),
                language=self.config.language,
                vad_filter=True,
                beam_size=1,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            return text.strip()
        finally:
            wav_path.unlink(missing_ok=True)


class TextInjector:
    def __init__(self):
        self._controller = keyboard.Controller()
        self._mouse = mouse.Controller()

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
            # Terminal-like command inputs often report AX "success" without visible insertion.
            # Force direct typing for Terminal targets.
            if target_app and "Terminal" in target_app:
                if click_target is not None:
                    self._mouse.position = click_target
                    time.sleep(0.04)
                    self._mouse.click(mouse.Button.left, 1)
                    time.sleep(0.06)
                self._controller.type(text)
                print("[VoiceType] Fallback inject success: terminal direct typing", file=sys.stderr)
                return

        if focused_element is not None and self._inject_ax(text, focused_element):
            return
        if sys.platform == "darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
            if click_target is not None:
                self._mouse.position = click_target
                time.sleep(0.04)
                self._mouse.click(mouse.Button.left, 1)
                time.sleep(0.06)

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
        self._indicator = RecordingIndicator()
        self._recorder = AudioRecorder(config)
        self._transcriber = WhisperTranscriber(config)
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

    def run(self) -> None:
        print(f"[VoiceType] Listening for hotkey: {self.config.hotkey}")
        print("[VoiceType] Press Ctrl+C in this terminal to exit.")
        self._indicator.start()
        self._indicator.set_idle()
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

        def on_hotkey() -> None:
            with self._state_lock:
                if not self._recording_active:
                    self._recording_active = True
                    self._stop_recording_event.clear()
                    self._indicator.set_recording()
                    self._target_ax_element_for_session = self._capture_focused_element()
                    self._target_app_for_session = self._last_click_app or self._get_frontmost_app()
                    self._target_click_for_session = self._last_click_pos
                    worker = threading.Thread(target=self._handle_session, daemon=True)
                    worker.start()
                    print(
                        "[VoiceType] Recording started. Press hotkey again to stop."
                        f" Target app: {self._target_app_for_session or 'unknown'}"
                    )
                    return
                self._stop_recording_event.set()
                self._indicator.set_processing()
                print("[VoiceType] Stop requested. Transcribing...")

        listener = keyboard.GlobalHotKeys({self.config.hotkey: on_hotkey})
        try:
            listener.start()
            listener.join()
        finally:
            if self._mouse_listener is not None:
                self._mouse_listener.stop()
            self._indicator.stop()
            self._recorder.close()

    def _handle_session(self) -> None:
        try:
            pcm = self._recorder.record_until_stop(self._stop_recording_event)
            print("[VoiceType] Transcribing...")
            text = self._transcriber.transcribe_pcm16(
                pcm_bytes=pcm,
                sample_rate=self.config.sample_rate,
                channels=self.config.channels,
            )
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
            with self._state_lock:
                self._recording_active = False
                self._stop_recording_event.clear()
                self._target_app_for_session = None
                self._target_click_for_session = None
                self._target_ax_element_for_session = None
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


def parse_args() -> AgentConfig:
    parser = argparse.ArgumentParser(description="Local hotkey voice-to-text typer.")
    parser.add_argument("--hotkey", default="<ctrl>+<shift>+r")
    parser.add_argument("--model", default="base.en")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--compute-type", default="default")
    parser.add_argument("--max-record-seconds", type=float, default=30.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--chunk-size", type=int, default=1024)
    args = parser.parse_args()

    return AgentConfig(
        hotkey=args.hotkey,
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
