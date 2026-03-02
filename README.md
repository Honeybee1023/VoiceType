# VoiceType

Local hotkey-triggered speech-to-text that injects into the currently focused text field.

## What it does
- Press global hotkey once to start recording.
- Press the same hotkey again to stop.
- Whisper transcribes locally.
- At hotkey press, the app captures the focused Accessibility element.
- After transcription, it injects text via macOS Accessibility APIs with fallback paste/typing paths.

## Requirements
- Python 3.10+
- Microphone access
- macOS: Accessibility permission for terminal/app running script
- macOS dependency: `pyobjc-framework-ApplicationServices` (installed by `setup.sh`)

## Install
```bash
chmod +x setup.sh
./setup.sh
```

Notes:
- `PyAudio` may require PortAudio dev libraries.
- On macOS with Homebrew:
```bash
brew install portaudio ffmpeg
```

## Run
```bash
source .venv/bin/activate
python voicetype_agent.py
```

Default hotkey is `<ctrl>+<shift>+r`.

## Useful flags
```bash
python voicetype_agent.py \
  --hotkey "<ctrl>+<shift>+r" \
  --model "base.en" \
  --language "en" \
  --max-record-seconds 30
```

## First-run macOS permissions
1. Open System Settings -> Privacy & Security -> Microphone, allow your terminal.
2. Open System Settings -> Privacy & Security -> Accessibility, allow your terminal.
3. Open System Settings -> Privacy & Security -> Automation, allow your terminal to control System Events (for app refocus).
4. Keep the terminal running while using the hotkey.

## Tuning tips
- If transcription is slow: use `--model tiny.en` or `--model base.en`.
- If you want a hard safety cap for long sessions: lower `--max-record-seconds`.

## Limitations
- Global hotkeys and synthetic typing behavior differ by OS/window manager.
- Some apps block synthetic keystrokes.
- Speech detection is energy-based and not full VAD; noisy rooms need threshold tuning.
