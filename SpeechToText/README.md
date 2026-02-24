# SpeechToText — Voice / CLI Control Module

TCP movement control for the ABB GoFa arm via voice or typed commands. No LLM, no gripper. Converts spoken (or typed) directional commands into structured JSON that Unity reads and forwards to the robot.

---

## System Overview

```
Microphone → speech_control.py
  OR
Keyboard  → cli_control.py
    ↓
Command parser (regex-based, no LLM)
    ↓
tcp_commands.json  ──→  Unity (TCPHotController.cs)
    ↓
ABB GoFa / RobotStudio
```

---

## Requirements

### Python

Python **3.9 – 3.12** recommended.

### Audio (speech_control.py only)

```bash
pip install sounddevice
```

macOS:
```bash
brew install portaudio
```

Linux:
```bash
sudo apt-get install portaudio19-dev
```

### Azure Speech (speech_control.py only)

Add to `SpeechToText/.env`:
```env
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
```

### Microsoft C++ Build Tools (Windows only)

Required for native audio dependencies:
- MSVC v143 — VS 2022 C++ x64/x86 build tools
- Windows 10 or 11 SDK

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Running

```bash
# Voice control (requires Azure Speech keys + microphone)
python speech_control.py

# CLI text control (no microphone or API keys required)
python cli_control.py
```

---

## Key Files

| File | Description |
|------|-------------|
| `speech_control.py` | Voice entry point — Azure ASR, VAD, debounced command dispatch |
| `cli_control.py` | CLI entry point — typed commands, same parser as speech_control |
| `requirements.txt` | Python dependencies |

---

## Commands

Both `speech_control.py` and `cli_control.py` accept the same movement syntax:

| Command | Effect |
|---------|--------|
| `move right` | +X by 1.0 unit |
| `move right 5` | +X by 5.0 units |
| `move right a tiny bit` | +X by 0.3 units |
| `move up and forward` | diagonal +Y +Z (single move) |
| `move left then down 3` | two sequential moves |
| `stop` / `halt` | emergency shutdown (speech) / exit (CLI) |

Qualitative distances: `tiny/teensy/small` = 0.3, `little bit/slightly/bit` = 0.5, `large/big/lot` = 2.0, none = 1.0.

---

## How tcp_commands.json Works

Each command writes the latest target position to `../UnityProject/tcp_commands.json`:

```json
{
  "x": 0.15,
  "y": 0.567,
  "z": -0.24
}
```

Unity's `TCPHotController.cs` polls this file and moves the TCP to the specified position.
