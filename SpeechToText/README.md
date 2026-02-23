# SpeechToText — Voice Control Module

Voice-to-robot-instruction pipeline for the ABB GoFa arm. Converts spoken commands (or CLI text) into structured JSON sequences that Unity reads and dispatches to the robot.

---

## System Overview

```
Microphone / CLI (cli_control.py)
    ↓
Azure Speech-to-Text  (cloud ASR — speech path only)
    ↓
speech_control_llm.py  /  cli_control.py  (main dispatchers — share same phrase bank)
    ↓
Phrase Bank  (fast cached lookups)  ──→  learning/phrase_bank.json
    ↓ (cache miss or modifier command)
Sequence Interpreter  (three-pass Claude pipeline)  ──→  learning/sequence_interpreter.py
    ↓
Instruction Compiler  (composites → primitives)  ──→  learning/instruction_compiler.py
    ↓
InstructionExecutor  (_send_and_wait: write → wait for Unity ack per step)
    ↓
tcp_commands.json  ──→  Unity (TCPHotController.cs) → tcp_ack.json → next step
    ↓
ABB GoFa / RobotStudio
```

The LLM layer uses **Anthropic Claude 3 Haiku** via the Claude API. See `learning/README.md` for a full description of the learning module architecture, and `docs/SEQUENCE_INTERPRETER.md` for the detailed design of the three-pass pipeline.

---

## Requirements

### Python

Python **3.9 – 3.12** recommended. The Anthropic SDK requires a 3.8+ environment; `~/miniconda3/bin/python` is the tested interpreter if system Python lacks the SDK.

### Audio (sounddevice / PortAudio)

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

### Azure Resources

Full speech recognition requires:
- Azure Speech resource (key + region)
- Azure Language / CLU resource (key + endpoint)

Add these to `SpeechToText/.env`:
```env
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
AZURE_LANGUAGE_KEY=...
AZURE_LANGUAGE_ENDPOINT=...
ANTHROPIC_API_KEY=...
```

### Microsoft C++ Build Tools (Windows only)

Required for native audio dependencies:
- MSVC v143 — VS 2022 C++ x64/x86 build tools
- Windows 10 or 11 SDK
- C++ CMake tools for Windows (optional but recommended)

```powershell
powershell -Command "Invoke-WebRequest https://aka.ms/vs/17/release/vs_BuildTools.exe -OutFile vs_BuildTools.exe; Start-Process .\vs_BuildTools.exe -Wait -ArgumentList '--quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows10SDK --add Microsoft.VisualStudio.Component.VC.CMake.Project'"
```

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Running

```bash
# Full speech control (requires Azure + Anthropic keys)
python speech_control_llm.py

# CLI text control (no microphone required — same pipeline as speech)
python cli_control.py

# Observation suite (LLM pipeline only, no microphone required)
~/miniconda3/bin/python run_observations.py --category all --save
```

---

## Key Files

| File | Description |
|------|-------------|
| `speech_control_llm.py` | Speech entry point — audio capture, ASR, dispatch loop; gripper state tracked globally |
| `cli_control.py` | CLI entry point — same two-tier routing as speech; shares phrase bank |
| `run_observations.py` | Offline test runner — 55 cases across 8 categories |
| `learning/sequence_interpreter.py` | Three-pass LLM pipeline |
| `learning/phrase_bank.py` | Phrase bank manager with fuzzy matching and modifier-word bypass |
| `learning/phrase_bank.json` | Live phrase bank — grows at runtime; includes gripper aliases |
| `learning/instruction_compiler.py` | Composite → primitive expansion; `InstructionExecutor` with ack-wait queue |
| `learning/sandwich_executor.py` | Sandwich-specific composites (`add_layer`, `serve`, `clear_assembly`, speed control) |
| `learning/config.py` | All thresholds and API settings |
| `docs/SEQUENCE_INTERPRETER.md` | Full design document for the LLM pipeline |
| `observation_logs/` | Saved observation run results (JSON) |

---

## Execution Queue — How tcp_commands.json Works

The `InstructionExecutor` does **not** fire-and-forget primitives. After writing each move step to `tcp_commands.json`, it blocks until Unity acknowledges the move via `tcp_ack.json`:

```
[Python] write tcp_commands.json
    ↓
[Unity TCPHotController.cs] detects file change → moves TCP → writes tcp_ack.json
    ↓
[Python _send_and_wait()] detects fresh tcp_ack.json (via file mtime) → reads confirmed position → proceeds to next step
```

- **Stale ack detection:** ack must have been written *after* the command — checked by comparing `os.path.getmtime(tcp_ack.json) >= write_time`.
- **Timeout:** if no ack arrives within 10 seconds, Python logs a warning and uses local position.
- **Gripper primitives** (`gripper_open`, `gripper_close`) write position to `tcp_commands.json` but do **not** wait for ack — fire-and-forget.
- **Position sync on startup:** `InstructionExecutor` reads the current `tcp_commands.json` at startup so it always knows Unity's last known state.

---

## Gripper Commands

The gripper is fully integrated across both speech and CLI paths. `gripper_position` (in metres, 0.0 = closed, 0.11 = fully open) is included in every `tcp_commands.json` write.

**Phrase bank aliases (in `phrase_bank.json`):**

| Phrase | Action |
|--------|--------|
| `"open gripper"`, `"release"`, `"let go"`, `"drop it"` | `gripper_open` → 0.11m |
| `"close gripper"`, `"grab"`, `"grip"` | `gripper_close` → 0.0m |
| `"close to 50mm"` | `gripper_close` with `width_mm: 50` → 0.05m |
| `"close to 30mm"` | `gripper_close` with `width_mm: 30` → 0.03m |
| `"close to 20mm"` | `gripper_close` with `width_mm: 20` → 0.02m |

Width-specific grips clamp to the RG2 range (0–110mm).

---

## Known Issues / Tuning Notes

- **Fuzzy match threshold** (`FUZZY_MATCH_THRESHOLD=0.6` in `.env`) — permissive by design, but can cause false cache hits as the phrase bank grows. Raise to `0.75` if modifier commands start returning wrong cached results; see `docs/SEQUENCE_INTERPRETER.md` for details.
- **`"make two sandwiches"` → returns one** — quantity words aren't in the modifier-bypass list, so the command hits the single-sandwich cache entry. Known limitation; see `learning/README.md`.
- **Creative commands skip LLM validation** — Pass 2 is bypassed for creative commands; a post-validation Python safety net still runs but is less thorough than the full validator.
- **Phrase bank writes on every cache hit** — `usage_count` increments trigger a file save each time. Use `PhraseBank(auto_save=False)` for automated/bulk testing.
- **Gripper ack-wait skipped** — gripper changes (`gripper_open`, `gripper_close`) do not wait for Unity acknowledgment. Unity always processes them since they're included in every position write, but there's no confirmed-state readback for gripper width. This means very fast gripper + move sequences may arrive at Unity slightly out of order relative to the gripper state.
- **Ack timeout tuning** — the 10-second ack timeout (`ACK_TIMEOUT` in `instruction_compiler.py`) was set conservatively. For fast moves in simulation, 2–3s is typically sufficient. For real hardware with EGM latency, the full 10s may be needed. Tune if the step queue feels slow.
