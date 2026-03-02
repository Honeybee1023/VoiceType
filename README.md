# VoiceType

VoiceType is a local, hotkey-driven voice-to-text agent for macOS.

It is intentionally built as a **single Python script** ([voicetype_agent.py](./voicetype_agent.py)) to keep the system understandable, debuggable, and easy to run.

## Highlights
- Global hotkey workflow: press once to start recording, press again to stop and inject text.
- Local transcription pipeline (no cloud API required).
- Focus-aware text injection using macOS Accessibility APIs.
- Practical fallback strategies for apps/inputs that behave differently (for example, terminal inputs).

## Technical Implementation
- `pynput`
  - Registers a global hotkey listener.
  - Tracks mouse clicks for target app/context awareness.
  - Provides keyboard/mouse fallback injection paths.
- `PyAudio`
  - Captures microphone PCM frames in real time.
  - Runs in a controlled recording loop with max-duration bounds.
- `faster-whisper` (local Whisper model)
  - Transcribes recorded audio locally.
  - Supports selectable model size/device/compute mode.
- `pyobjc-framework-ApplicationServices`
  - Accesses macOS Accessibility (`AXUIElement`) APIs.
  - Captures the focused UI element at hotkey start.
  - Injects transcript via `kAXSelectedTextAttribute` with `kAXValueAttribute` fallback.

## Architecture (Single-Script)
1. Hotkey pressed -> capture current focused AX element + start audio recording thread.
2. Hotkey pressed again -> stop recording.
3. Transcribe buffered audio with local Whisper.
4. Inject transcript into the stored focused element.
5. If AX injection fails, fall back to clipboard/keyboard injection.

## Requirements
- macOS
- Python 3.10+
- Microphone access
- Accessibility access for the terminal/app running the script

## Setup
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

Default hotkey: `<ctrl>+<shift>+r`

## Example Flags
```bash
python voicetype_agent.py \
  --hotkey "<ctrl>+<shift>+r" \
  --model "base.en" \
  --language "en" \
  --max-record-seconds 30
```

## macOS Permissions (First Run)
1. `System Settings -> Privacy & Security -> Microphone`: allow your terminal.
2. `System Settings -> Privacy & Security -> Accessibility`: allow your terminal.
3. `System Settings -> Privacy & Security -> Automation`: allow terminal -> System Events.

## Notes
- Transcription speed depends on chosen Whisper model size.
- Some text inputs have app-specific behavior; fallback injection paths are included for robustness.
