# Learning Module — Voice Command Interpretation

This module handles all LLM-based voice command interpretation for the GoFa robot arm. It converts natural language speech (or CLI text) into structured robot instruction sequences via a self-learning phrase bank and a three-pass Claude pipeline.

## Architecture

```
Voice Input (Azure Speech-to-Text)   OR   CLI text (cli_control.py)
    ↓                                          ↓
           Both share the same phrase_bank.json
    ↓
Phrase Bank  (exact + fuzzy match — fast path for known phrases)
    │  modifier-word bypass: phrases with modifiers skip cache → LLM
    ↓
Sequence Interpreter  (three-pass LLM pipeline)
    ↓
Instruction Compiler  (composites → primitives)
    ↓
InstructionExecutor  →  tcp_commands.json  (one step at a time, ack-waited)
    ↓
Unity (TCPHotController.cs)  →  tcp_ack.json  →  next step
    ↓
ABB GoFa / RobotStudio
```

**Fast path:** If the phrase bank has a confident match for the command, the LLM is never called. A cached `"make a BLT"` returns in ~0ms. Commands with modifier words (`no`, `with`, `extra`, `slow`, etc.) automatically bypass the cache so the LLM can handle the variation correctly.

**LLM path:** Novel commands, creative instructions, modifier variations, and multi-zone builds are handled by `sequence_interpreter.py` using a three-pass pipeline (generation → validation → optional regeneration).

**Execution queue:** `InstructionExecutor` streams compiled primitives one at a time via `_send_and_wait()`, waiting for Unity to acknowledge each move before writing the next. Position is read back from the ack to keep local state accurate.

---

## Files

| File | Purpose |
|------|---------|
| `sequence_interpreter.py` | Three-pass LLM pipeline — converts voice/CLI commands to instruction sequences |
| `instruction_compiler.py` | Expands composite instructions into primitive robot calls; contains `InstructionExecutor` with ack-wait queue and gripper state tracking |
| `sandwich_executor.py` | Sandwich-specific composites: `add_layer` (height-aware), `serve`, `clear_assembly`, speed control |
| `phrase_bank.py` | Phrase bank manager — fuzzy matching, cache read/write, modifier-word bypass, pick-up item-noun guard |
| `phrase_bank.json` | Live phrase bank data — grows at runtime; includes gripper command aliases |
| `config.py` | API keys, model selection, thresholds (fuzzy match, LLM confidence) |
| `memory_writer.py` | Writes learned composites and aliases back to `instruction_set.json` / `phrase_bank.json` |

---

## Configuration

### Environment Variables (`.env` in `SpeechToText/`)

```env
# Required
ANTHROPIC_API_KEY=your_api_key_here

# Optional — defaults shown
ANTHROPIC_MODEL=claude-3-haiku-20240307
FUZZY_MATCH_THRESHOLD=0.6
LLM_CONFIDENCE_THRESHOLD=0.80
VERBOSE_LOGGING=false
```

### Key Config Values (`config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_MODEL` | `claude-3-haiku-20240307` | Model used for all LLM calls |
| `FUZZY_MATCH_THRESHOLD` | `0.6` | Minimum ratio for a phrase bank fuzzy hit (see Known Issues) |
| `LLM_CONFIDENCE_THRESHOLD` | `0.80` | Minimum confidence for auto-saving a learned composite |
| `DISTANCE_SCALE` | `0.01` | Centimeters → Unity units conversion |
| `VERBOSE_LOGGING` | `false` | Enables detailed pipeline step logging |

---

## Running the Observation Suite

The observation suite runs all 55 test cases across 8 categories and saves results to `observation_logs/`.

```bash
# Run all categories
~/miniconda3/bin/python run_observations.py --category all --save

# Run a specific category
~/miniconda3/bin/python run_observations.py --category modifiers --save
```

**Categories:** `baseline`, `ambiguous`, `modifiers`, `multi_stack`, `recovery`, `edge`, `creative`, `secondary`

**Python note:** The Anthropic SDK must be installed in the Python environment used. Use `~/miniconda3/bin/python` if the system Python doesn't have it.

---

## Phrase Bank

`phrase_bank.json` has two sections:

### `phrases`
Simple single-intent lookups (movement, speed, gripper). Used by `fuzzy_match()` in the legacy `llm_interpreter` path. Also contains gripper command aliases: `"release"`, `"let go"`, `"drop it"` → `gripper_open`; `"grab"`, `"grip"` → `gripper_close`; `"close to 50mm"` / `"close to 30mm"` / `"close to 20mm"` → `gripper_close` with `width_mm` param.

### `sequence_phrases`
Full LLM-compatible result dicts for multi-step commands. Keyed by normalized phrase string (lowercase, stripped). Each entry stores the full sequence, `composite_name`, `confidence`, and `usage_count`.

**Cache grows at runtime** — every time the LLM generates a result with `composite_name` set and `confidence ≥ LLM_CONFIDENCE_THRESHOLD`, the phrase is added to `sequence_phrases`. On the next run of the same command, it's served from cache with `_from_cache: true` at ~0ms.

**Modifier-word bypass** — `fuzzy_sequence_match()` checks the input phrase for modifier tokens before doing any fuzzy scoring. If found, it returns `None` immediately, bypassing the cache entirely so the LLM receives the full modified command. This prevents stale base-recipe cache entries from swallowing modifier commands like `"make a classic with no tomato"`.

**Pick-up item-noun guard** — for pick-up style phrases, the terminal item word must match exactly. A fuzzy hit on a different item is rejected, preventing `"pick up the avocado"` from hitting `"pick up the lettuce"` at 0.6 similarity.

---

## CLI Control (`cli_control.py`)

The CLI shares the full pipeline — same phrase bank, same routing, same `InstructionExecutor`.

**Routing heuristic (`_looks_like_sequence_command`):**
- Multi-word phrases checked first: `"start over"`, `"never mind"`, `"go home"`, `"put it back"` → sequence path
- Keyword set: `pick`, `place`, `put`, `make`, `build`, `assemble`, `stack`, `transfer`, `grab`, `get`, `take`, `add`, `layer`, `clear` → sequence path
- All other commands → simple intent path (`LLMInterpreter` + `IntentExecutor`)

**Sequence path flow (complex commands):**
1. Exact phrase bank match (`sequence_match`)
2. Fuzzy phrase bank match (`fuzzy_sequence_match` — with modifier-bypass and item guard)
3. Full `SequenceInterpreter` LLM call
4. Auto-learn result if `composite_name` set and `confidence ≥ 0.80`

**Simple path flow (move, gripper, etc.):**
- `LLMInterpreter` → `IntentExecutor` (delta-based movement, gripper open/close)

---

## Instruction Execution Queue

`InstructionExecutor` (in `instruction_compiler.py`) controls how compiled primitives reach Unity:

### `_send_and_wait(position)` — move primitives
1. Writes `{x, y, z, gripper_position}` to `tcp_commands.json`
2. Records `write_time = time.time()`
3. Polls `tcp_ack.json` every 50ms until `os.path.getmtime(ack) >= write_time`
4. Reads back Unity-confirmed position from ack → updates local state
5. Falls back to local position after `ACK_TIMEOUT = 10.0` seconds with a warning

### Gripper primitives — fire-and-forget
`_execute_gripper_open` / `_execute_gripper_close` update `self.gripper_position` and write to `tcp_commands.json` (position + new gripper value) but do **not** wait for ack. Unity will apply the gripper change on the next file read.

### Startup sync
On `__init__`, `InstructionExecutor` reads the current `tcp_commands.json` to initialize `self.gripper_position` and `self.current_position` so it starts from Unity's last known state rather than defaults.

---

## Gripper State Tracking

Both `speech_control_llm.py` and `InstructionExecutor` maintain a gripper position float (metres):
- `0.11` = fully open (RG2 max stroke, 110mm)
- `0.0` = fully closed

Every `tcp_commands.json` write includes `gripper_position`, so Unity always knows the current state regardless of whether the last command was a move or a gripper change.

---

## Supported Command Types

### Standard Recipes
Named recipes with optional modifiers:
- `"make a BLT"` → bread, meat, lettuce, tomato, bread + go_home
- `"make a club sandwich with extra meat"` → club recipe with double meat layer
- `"make a veggie sandwich, hold the cheese"` → veggie recipe with cheese omitted
- `"make a BLT nice and slow"` → `adjust_speed(slow)` prepended to BLT sequence

### Pick-Up / Placement
- `"pick up the cheese"` → `pick_up(item='cheese')`
- `"carefully pick up the lettuce"` → `adjust_speed(slow)` + `pick_up(item='lettuce')`
- `"put some bread down"` → `add_layer(item='bread')`

### Gripper
- `"open gripper"` / `"release"` / `"let go"` / `"drop it"` → `gripper_open`
- `"close gripper"` / `"grab"` / `"grip"` → `gripper_close`
- `"close to 50mm"` → `gripper_close(width_mm=50)`

### Recovery
- `"put it back"` / `"undo"` → `return_to_stack()`
- `"start over"` / `"never mind"` / `"cancel"` → `clear_assembly()` + `go_home()`
- `"I made a mistake"` → `return_to_stack()` + `clear_assembly()`

### Multi-Zone Builds
- `"make a cheese sandwich on the left and a BLT on the right"` → `set_active_zone` + sequences per zone
- `"start a BLT over there"` → defaults to center zone (`assembly_fixture`)

### Creative Commands
Open-ended creative directives use a two-axis composition system (spatial structure × ingredient logic) with temperature 1.0:
- `"go wild"`, `"impress me"`, `"make something beautiful"`, `"build a tower"`, etc.

### Learning / Secondary Commands
Meta-commands that try to define or name sequences:
- `"from now on, careful means slow speed and go home after"` → suggests `careful_macro` composite
- `"call this sequence 'classic plus'"` → generates the sequence and tags it with the requested name

### Unknown Items
Items not in the system (avocado, pickles, etc.) prompt either a substitution or an empty sequence with `user_feedback` explaining the issue.

---

## Cost

Model: `claude-3-haiku-20240307` — $0.25/MTok input · $1.25/MTok output

| Scenario | LLM calls | Approx cost |
|----------|-----------|-------------|
| Cache hit | 0 | $0.00 |
| Standard command (Pass 1 + 2) | 2 | ~$0.001–0.002 |
| Command with Pass 3 correction | 3 | ~$0.002–0.003 |
| Full 55-case observation suite | 110–165 | ~$0.07–0.10 |

---

## Known Issues and Tuning Notes

### Fuzzy Threshold (0.6) Can Cause Cache Collisions as Phrase Bank Grows

At the default `FUZZY_MATCH_THRESHOLD=0.6`, two phrases with similar structure but different intent can fuzzy-match at runtime. As more recipes are cached, the probability of false hits increases.

**Current mitigation:** the modifier-word bypass catches most problem cases. But if you observe modifier commands returning wrong cached results, raise the threshold:

```env
FUZZY_MATCH_THRESHOLD=0.75
```

Then re-run `run_observations.py --category modifiers` to verify no regressions.

### `"make two sandwiches"` Returns One Sandwich

The word `"two"` is not in the modifier-bypass list, so `"make two sandwiches"` fuzzy-matches `"make a sandwich"` at 0.82 and returns the cached single classic. The multi-sandwich intent is silently dropped.

To fix for a specific case: add `"make two sandwiches"` as its own phrase bank entry, or add quantity words to the bypass pattern in `phrase_bank.py`.

### Creative Commands Skip Pass 2 Validation

Creative commands bypass the LLM validator entirely. The post-validation Python safety net still runs (catches `place_at`/`transfer` and unknown items), but instruction name errors in creative output would pass through. In practice this is rarely an issue with Haiku, but worth keeping in mind if creative outputs cause executor errors.

### `usage_count` Writes on Every Cache Hit

Each cache hit increments `usage_count` and triggers a file save to `phrase_bank.json`. For automated test runs, initialize with `PhraseBank(auto_save=False)` to suppress this.

### Gripper Changes Are Fire-and-Forget

Gripper open/close primitives do not wait for Unity acknowledgment — `tcp_ack.json` is only written by Unity after a move completes. If a sequence does `gripper_close` immediately followed by `move_to`, the move ack will confirm the move position but won't validate the gripper width. In practice this works because Unity processes commands in order, but there's no readback confirming the gripper reached the target width.

### Ack Timeout Is Conservative

The `ACK_TIMEOUT = 10.0` seconds in `InstructionExecutor` was set for real-hardware latency. In simulation (Unity only, no real robot), moves complete in ~0.5–2s. You can lower this constant if step-queue throughput feels slow in simulation, but keep it higher when running with actual EGM/RobotStudio in the loop.

---

## Troubleshooting

### "Anthropic SDK not installed"
```bash
~/miniconda3/bin/pip install anthropic
```
Or verify the Python environment: `which python` should point to an env with `anthropic` installed.

### "ANTHROPIC_API_KEY not set"
Create `SpeechToText/.env`:
```env
ANTHROPIC_API_KEY=your_key_here
```

### Modifier commands returning wrong cached results
Raise `FUZZY_MATCH_THRESHOLD` in `.env` and re-run the modifiers observation category. Also check that the modifier token isn't missing from the bypass list in `phrase_bank.py → fuzzy_sequence_match()`.

### Pass 3 firing unexpectedly often
Check `VERBOSE_LOGGING=true` output to see what Pass 2 is catching. Common triggers: `place_at` / `transfer` instead of `add_layer` (now auto-corrected by post-validation safety net), or `move_absolute` in output (not a valid composite).

### Creative output causes executor errors
Enable `VERBOSE_LOGGING=true` and compare `pass1_sequence` vs final `sequence` in the result. Since Pass 2 is skipped for creative commands, any invalid instruction would appear in `pass1_sequence` but also survive to `sequence`. Check the instruction name against `instruction_compiler.get_composites()`.

### Step queue not advancing / hanging
If the executor appears stuck between steps, check that `tcp_ack.json` is being written by Unity. `TCPHotController.cs` writes it via `WriteAcknowledgment()` after each move completes. If the file is stale or missing, the 10-second timeout will fire and execution will continue. Check Unity console for `"TCP reached target"` logs.
