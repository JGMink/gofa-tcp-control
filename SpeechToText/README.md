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

---

## How the System Works (Plain English)

Here's the full picture from voice/keyboard to robot motion:

1. **Input** — The user either speaks a command ("move right 10 centimeters") or types it into the CLI.
2. **Speech-to-Text** — For voice, Azure Speech SDK transcribes the audio to a text string in real time. The CLI skips this step entirely.
3. **Command Parser** — A regex-based parser (no AI, no LLM) reads the text, figures out direction(s) and distance, and computes an XYZ delta. Compound commands like "move left then down 3" are split and processed as a sequence.
4. **Position Tracking** — Python maintains a running XYZ position in memory, initialized from whatever Unity last wrote. Each parsed command adds a delta to that position.
5. **JSON Write** — Python writes the new target position to `tcp_commands.json` (a plain JSON file on disk that both Python and Unity can see).
6. **Unity Pickup** — `TCPHotController.cs` in Unity watches that file. When it changes, Unity reads the new XYZ and sends a movement command to the ABB GoFa controller over TCP/IP.
7. **Robot Moves** — The GoFa arm moves its TCP (Tool Center Point — the tip of the tool) to the target position.

The JSON file is the entire communication layer between Python and Unity. There is no socket, no API, no message queue — just a file that one side writes and the other polls. It's simple and it works.

**Unit system:** 1.0 unit in the JSON = 0.1 m = 10 cm. So `"x": 0.15` means 1.5 cm from the origin in X. The parser handles `cm` and `mm` keywords and converts automatically.

---

## For Junior Developers — What to Build Next

This repo gives you a working foundation: you can move the robot's TCP anywhere in its workspace with a voice command or a typed command. The natural next step is to make the robot **draw shapes**.

### The Core Idea

Right now Python sends one position at a time, and Unity moves there immediately. To draw a shape, you need to send a **sequence of waypoints** and have Unity execute them in order. The robot traces a path through those points — connect enough of them and you get a shape.

A square, for example, is just four corners fed to the robot one after another at a fixed Z (height). A circle is trickier because a circle isn't made of straight lines.

### Suggested JSON Extension

Extend `tcp_commands.json` to support a `motion_type` field and, eventually, a list of waypoints:

```json
{
  "x": 0.15,
  "y": 0.30,
  "z": -0.10,
  "motion_type": "linear",
  "gripper_position": 0.11
}
```

Two motion types to think about:

- **`"linear"`** — Move in a straight line from current position to target. This is what the robot does now. Good for polygons (triangles, squares, etc.).
- **`"arc"`** — Move along a curved path. ABB robots support arc motion natively (MoveC in RAPID). For arc moves you need three points: start, a midpoint on the curve, and end. This is how you get smooth circles and ellipses without needing hundreds of tiny straight-line steps.

### Drawing a Circle

A practical approach for a circle:

1. Pick 4 points evenly spaced around the circumference (like compass points — N, E, S, W).
2. Send them as two arc moves: N→E→S (arc through E), then S→W→N (arc through W).
3. Each arc move needs: start point (implicit — where the robot is), a via-point on the curve, and an end point.

Alternatively, approximate a circle with many short linear moves — simpler to implement in Python, but slower and less smooth.

### Where to Start

- **Python side:** Build a `draw_shape.py` script that generates a list of waypoints for a given shape (square, circle, triangle) and writes them to `tcp_commands.json` one at a time, waiting for Unity to acknowledge each move before sending the next.
- **Unity/C# side (`TCPHotController.cs`):** Add support for reading `motion_type` from the JSON and dispatching either a `MoveL` (linear) or `MoveC` (arc) call to the robot controller. Write an ack file (`tcp_ack.json`) after each move so Python knows when to send the next waypoint.
- **RAPID (robot-side):** If you're going straight to hardware, you may need to update the RAPID program on the controller to accept and execute the motion type. In simulation (RobotStudio), Unity handles this.

The acknowledgment loop (Python writes → Unity moves → Unity acks → Python sends next) is the key piece that turns a pile of waypoints into a controlled, ordered path.
