# gofa-tcp-control

TCP movement control for the **ABB GoFa CRB 15000** arm via voice or typed commands.

Python parses spoken/typed directional commands and writes target positions to a JSON file. Unity picks up that file and sends the move to the robot over TCP. No LLM, no gripper — just clean TCP control as a starting point.

---

## Repo Structure

```
gofa-tcp-control/
├── SpeechToText/          ← Python voice + CLI control
│   ├── speech_control.py  ← Voice entry point (Azure ASR)
│   ├── cli_control.py     ← Typed command entry point
│   └── README.md          ← Full pipeline docs + jr. dev guide
├── UnityProject/          ← Unity scene + C# TCP controller
│   └── Assets/Scripts/
│       └── TCPHotController.cs
├── SETUP.md               ← Network setup and startup sequence
└── CONTROLS.md            ← CLI command reference
```

---

## Quick Start

1. Set up your `.env` (see `SETUP.md`)
2. Connect to robot WiFi and configure network (see `SETUP.md`)
3. Start Unity, hit Play
4. Run Python:

```bash
cd SpeechToText
python cli_control.py        # typed commands — no keys required
# OR
python speech_control.py     # voice commands — needs Azure keys + mic
```

---

## How It Works

See **`SpeechToText/README.md`** for the full pipeline explanation and the VIP Student guide (waypoint queues, shape drawing, arc motion).

See **`SETUP.md`** for hardware setup, network config, and startup order.
