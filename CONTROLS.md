# Controls

## CLI (`cli_control.py`)

```bash
cd SpeechToText
python cli_control.py
```

Type movement commands at the `robot>` prompt. No API keys needed.

### Movement

| Command | Effect |
|---------|--------|
| `move right` | +X by 1 unit (10 cm) |
| `move right 5` | +X by 5 units (50 cm) |
| `go up 10cm` | +Y by 1 unit |
| `move left a tiny bit` | +X by 0.3 units |
| `go forward and up` | diagonal move in one step |
| `move left then down 3` | two sequential moves |

Qualitative distances: `tiny/teensy/small` = 0.3 · `a bit/slightly` = 0.5 · `large/big` = 2.0 · none = 1.0

Units: `cm` and `mm` are parsed automatically. `10cm` = 1 unit. `100mm` = 1 unit.

### Meta

| Command | Effect |
|---------|--------|
| `status` | Print current XYZ position |
| `help` | Show command reference |
| `quit` / `exit` | Exit |

---

## Voice (`speech_control.py`)

Same movement syntax as the CLI. Requires Azure Speech keys in `.env` and a microphone.

```bash
cd SpeechToText
python speech_control.py
```

Say commands out loud. Say **"stop"** or **"halt"** to emergency-stop.

---

## Unit System

`DISTANCE_SCALE = 0.1` — all moves are in Unity units where **1 unit = 0.1 m = 10 cm**.

The parser converts `cm` and `mm` keywords before scaling, so "move right 20cm" and "move right 2" produce the same move.
