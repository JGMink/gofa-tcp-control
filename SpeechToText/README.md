# SpeechToText — Voice Control Module

Voice-to-robot-instruction pipeline for the ABB GoFa arm. Converts spoken commands into structured JSON sequences that Unity reads and dispatches to the robot.

---

## System Overview

```
Microphone
    ↓
Azure Speech-to-Text  (cloud ASR)
    ↓
speech_control_llm.py  (main dispatcher)
    ↓
Phrase Bank  (fast cached lookups)  ──→  learning/phrase_bank.json
    ↓ (cache miss or modifier command)
Sequence Interpreter  (three-pass Claude pipeline)  ──→  learning/sequence_interpreter.py
    ↓
Instruction Compiler  (composites → primitives)  ──→  learning/instruction_compiler.py
    ↓
tcp_commands.json  ──→  Unity / RobotStudio / ABB GoFa
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

# Observation suite (LLM pipeline only, no microphone required)
~/miniconda3/bin/python run_observations.py --category all --save
```

---

## Key Files

| File | Description |
|------|-------------|
| `speech_control_llm.py` | Main entry point — audio capture, ASR, dispatch loop |
| `run_observations.py` | Offline test runner — 55 cases across 8 categories |
| `learning/sequence_interpreter.py` | Three-pass LLM pipeline |
| `learning/phrase_bank.py` | Phrase bank manager with fuzzy matching and modifier-word bypass |
| `learning/phrase_bank.json` | Live phrase bank (grows at runtime) |
| `learning/instruction_compiler.py` | Composite → primitive expansion |
| `learning/config.py` | All thresholds and API settings |
| `docs/SEQUENCE_INTERPRETER.md` | Full design document for the LLM pipeline |
| `observation_logs/` | Saved observation run results (JSON) |

---

## Known Issues / Tuning Notes

- **Fuzzy match threshold** (`FUZZY_MATCH_THRESHOLD=0.6` in `.env`) — permissive by design, but can cause false cache hits as the phrase bank grows. Raise to `0.75` if modifier commands start returning wrong cached results; see `docs/SEQUENCE_INTERPRETER.md` for details.
- **`"make two sandwiches"` → returns one** — quantity words aren't in the modifier-bypass list, so the command hits the single-sandwich cache entry. Known limitation; see `learning/README.md`.
- **Creative commands skip LLM validation** — Pass 2 is bypassed for creative commands; a post-validation Python safety net still runs but is less thorough than the full validator.
- **Phrase bank writes on every cache hit** — `usage_count` increments trigger a file save each time. Use `PhraseBank(auto_save=False)` for automated/bulk testing.
