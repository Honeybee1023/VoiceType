# VoiceType

VoiceType is a local, hotkey-driven voice-to-text agent for macOS and Windows.

It is intentionally built around a single entrypoint script ([voicetype_agent.py](./voicetype_agent.py)) with a small platform adapter layer in `vt_platform/` to keep the system understandable, debuggable, and easy to run without mixing OS-specific logic.

## Highlights
- Global hotkey workflow: press once to start recording, press again to stop and inject text.
- Local transcription pipeline (no cloud API required).
- Focus-aware text injection using platform-specific APIs.
- Practical fallback strategies for apps/inputs that behave differently (for example, terminal inputs).
- Bottom status pill with a language selector for English or Chinese (macOS).

## Technical Implementation
- `pynput`
  - Registers a global hotkey listener.
  - Tracks mouse clicks for target app/context awareness.
  - Provides keyboard/mouse fallback injection paths.
- `PyAudio`
  - Captures microphone PCM frames in real time.
  - Runs until you stop it, with optional max-duration bounds if configured.
- `faster-whisper` (local Whisper model)
  - Transcribes recorded audio locally.
  - Supports selectable model size/device/compute mode.
  - English mode uses the current English-only Whisper path.
  - Chinese mode uses a multilingual Whisper model.
- macOS platform adapter (`vt_platform/macos.py`)
  - Uses `pyobjc-framework-ApplicationServices` for Accessibility (`AXUIElement`) APIs.
  - Captures the focused UI element at hotkey start.
  - Injects transcript via `kAXSelectedTextAttribute` with `kAXValueAttribute` fallback.
- Windows platform adapter (`vt_platform/windows.py`)
  - Uses Win32 APIs (via `ctypes`) for frontmost window title.
  - Injects transcript via clipboard paste or direct typing.

## Architecture (Entrypoint + Platform Adapters)
1. Hotkey pressed -> capture current focused element (if supported) + start audio recording thread.
2. Hotkey pressed again -> stop recording.
3. Transcribe buffered audio with local Whisper.
4. Inject transcript into the stored focused element.
5. If native injection fails or is unavailable, fall back to clipboard/keyboard injection.

## Status
- macOS: full feature set (indicator pill, AX injection, Quartz hotkey optional).
- Windows: baseline support (hotkey, record/transcribe, clipboard paste or direct typing) plus a lightweight indicator.

## Requirements
- macOS or Windows
- Python 3.10+
- Microphone access
- macOS: Accessibility access for the terminal/app running the script

## Setup (macOS)
```bash
chmod +x setup.sh
./setup.sh
```

If `PyAudio` build fails, install native deps first:
```bash
brew install portaudio ffmpeg
```

## Run
```bash
source .venv/bin/activate
python voicetype_agent.py
```

Default hotkey (macOS): `<ctrl>+<shift>+r`

Default hotkey (Windows): `<alt>+<shift>+r`

Default language mode: `English`

Use the indicator language menu to switch between:

- `English`
- `Chinese Simplified`
- `Chinese Traditional`

## Example Flags
```bash
python voicetype_agent.py \
  --hotkey "<ctrl>+<shift>+r" \
  --model "base.en" \
  --language "en" \
  --max-record-seconds 0
```

`--max-record-seconds 0` means unlimited recording length. Any value greater than `0` restores a hard stop.

## Windows Setup (Baseline)
```bash
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python voicetype_agent.py
```

Notes:
- Windows uses clipboard paste if `pyperclip` is available; otherwise it falls back to direct typing.
- The Windows indicator uses Tkinter and runs in the main thread. Open the language menu with the `v` button or right-click.

## Chinese Mode

Chinese modes use the multilingual Whisper `medium` model.

- English mode remains on the existing English path.
- Chinese Simplified and Chinese Traditional use the same Mandarin transcription model and differ only in the final script conversion step.
- The first time a Chinese mode is used, the model may download automatically if it is not already cached.
- That first Chinese transcription can take longer while the model initializes.

Chinese script conversion uses `opencc-python-reimplemented`, which is installed via `requirements.txt`.

If you want to pre-download the Chinese-capable model manually:

```bash
cd /Users/honjar/Downloads/VoiceType
source .venv/bin/activate
python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='auto', compute_type='default')"
```

If you have not refreshed the virtualenv since this change, install the updated dependencies:

```bash
cd /Users/honjar/Downloads/VoiceType
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## macOS Permissions (First Run)
1. `System Settings -> Privacy & Security -> Microphone`: allow your terminal.
2. `System Settings -> Privacy & Security -> Accessibility`: allow your terminal.
3. `System Settings -> Privacy & Security -> Automation`: allow terminal -> System Events.

## Notes
- Transcription speed depends on chosen Whisper model size.
- Some text inputs have app-specific behavior; fallback injection paths are included for robustness.
- The Windows roadmap is tracked in `Windows_plan.md`.
