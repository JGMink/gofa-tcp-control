# Self-Learning Voice Command System

A three-tier command interpretation system that learns from user interactions, combining instant phrase matching with AI-powered fallback.

## 🎯 Purpose

Instead of hardcoding every possible way to say a command, this system:
1. **Instantly** recognizes known phrases (phrase bank)
2. **Quickly** handles typos and variations (fuzzy matching)
3. **Learns** new phrasings using Claude AI (LLM fallback)
4. **Remembers** for next time (auto-saves to phrase bank)

### Example Learning Flow

```
User: "put it back where it was"
[No phrase bank match]
[No fuzzy match]
[Claude interprets → move_to_previous, confidence 0.95]
[Executes + Saves phrase]

Next time:
User: "put it back where it was"
[Phrase bank: instant match → move_to_previous]
[No Claude call needed]
```

Over time, the system becomes faster and cheaper as it learns your preferred phrasing.

---

## 🏗️ Architecture

```
Voice Input (Azure Speech-to-Text)
    ↓
┌─────────────────────────────────────┐
│   COMMAND PROCESSOR (Orchestrator)  │
└─────────────────────────────────────┘
    │
    ├──► Tier 1: Exact Match (instant)
    │    └─ phrase_bank.json lookup
    │
    ├──► Tier 2: Fuzzy Match (instant)
    │    └─ Similarity threshold (85% default)
    │
    └──► Tier 3: LLM Fallback (~1-2s)
         ├─ Claude API interprets intent
         ├─ Extract intent + params + confidence
         └─ If confident (≥90%), save to phrase bank
    ↓
┌─────────────────────────────────────┐
│   INTENT EXECUTOR                   │
│   - Converts intent → robot commands│
│   - Tracks position history         │
│   - Manages named locations         │
└─────────────────────────────────────┘
    ↓
tcp_commands.json (Unity reads this)
    ↓
ABB GoFa Robot Execution
```

---

## 📁 File Structure

```
SpeechToText/
├── SpeechToText_learning.py         # Main entry point (replaces SpeechToText.py)
├── intent_executor.py                # Converts intents → robot commands
│
├── learning/
│   ├── config.py                     # Configuration & thresholds
│   ├── phrase_bank.json              # Persistent vocabulary (grows over time)
│   ├── phrase_bank.py                # Phrase lookup + fuzzy matching
│   ├── llm_interpreter.py            # Claude API fallback
│   ├── command_processor.py          # Orchestrates the 3-tier flow
│   └── README.md                     # Module documentation
│
└── tests/
    └── test_learning.py              # Test without microphone
```

---

## 🎬 Quick Start

### 1. Install Dependencies

```bash
cd SpeechToText
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit .env and add:
AZURE_SPEECH_KEY=your_azure_key
AZURE_SPEECH_REGION=your_region
ANTHROPIC_API_KEY=your_claude_key  # Required for learning
```

### 3. Test Without Microphone

```bash
# Run all tests
python tests/test_learning.py

# Interactive testing
python tests/test_learning.py --interactive

# Test specific components
python tests/test_learning.py --phrase-bank
python tests/test_learning.py --executor
```

### 4. Run Full System

```bash
python SpeechToText_learning.py
```

Say commands like:
- "move right 5 centimeters" (instant - phrase bank)
- "go back" (instant - phrase bank)
- "put it back where it was" (LLM → learns → next time instant)
- "shift a bit left" (LLM → learns → next time instant)

---

## 🧠 Supported Intents

| Intent | Status | Description | Example Phrases |
|--------|--------|-------------|-----------------|
| `move_relative` | ✅ | Move in a direction by distance | "move right 5 cm", "go up", "shift left" |
| `move_to_previous` | ✅ | Return to last position | "go back", "put it back", "return" |
| `move_to_named` | ✅ | Go to saved location | "go home", "move to pickup" |
| `emergency_stop` | ✅ | Halt all movement | "stop", "halt", "emergency" |
| `save_named_location` | ✅ | Save current position | "save this as home", "remember this" |
| `gripper_open` | ⏳ | Open gripper (future) | "open gripper", "release" |
| `gripper_close` | ⏳ | Close gripper (future) | "close gripper", "grab" |

---

## 📊 Phrase Bank Structure

`learning/phrase_bank.json`:

```json
{
  "phrases": {
    "move right 5 centimeters": {
      "intent": "move_relative",
      "params": {"direction": "right", "distance": 5.0, "unit": "cm"},
      "confidence": 1.0,
      "usage_count": 0
    },
    "put it back where it was": {
      "intent": "move_to_previous",
      "params": {},
      "confidence": 0.95,
      "usage_count": 3
    }
  },
  "named_locations": {
    "home": {"x": 0.0, "y": 0.0, "z": 0.0}
  },
  "metadata": {
    "version": "1.0",
    "last_updated": "2026-01-22T19:45:00",
    "total_phrases_learned": 5
  }
}
```

- **Grows automatically** as LLM interprets new phrases
- **Persists between sessions**
- **Tracks usage** for analytics

---

## ⚙️ Configuration

### Environment Variables (`.env`)

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional (defaults shown)
ANTHROPIC_MODEL=claude-3-5-haiku-20241022
FUZZY_MATCH_THRESHOLD=0.85
LLM_CONFIDENCE_THRESHOLD=0.90
```

### Tuning Parameters

#### Fuzzy Match Threshold (0.0-1.0)

- **0.85 (default)**: Balanced - catches typos but not too lenient
- **0.90**: Stricter - reduces false matches
- **0.75**: Looser - more forgiving of variations

#### LLM Confidence Threshold (0.0-1.0)

- **0.90 (default)**: Only learn phrases Claude is very confident about
- **0.95**: Ultra-conservative learning
- **0.80**: Learn more aggressively (more phrases, some might be wrong)

---

## 💰 Cost Analysis

### Using Claude 3.5 Haiku (Recommended)

- **Input**: ~$0.25 per million tokens
- **Output**: ~$1.25 per million tokens
- **Typical command**: ~300 tokens total
- **Cost per LLM call**: ~$0.00008 (less than 1/100th of a cent)

### Expected Usage

- **First session (cold start)**: 20-30 LLM calls → ~$0.002
- **After learning**: 90%+ instant matches → ~$0.0002 per session
- **Typical project**: $0.05-0.10 total over entire development cycle

**Your phrase bank grows, costs go down.**

---

## 📈 Performance Metrics

The system tracks statistics:

```python
processor.print_stats()
```

Output:
```
COMMAND PROCESSING STATISTICS
============================================================

Total Commands: 50
  Exact Matches: 35 (70.0%)
  Fuzzy Matches: 10 (20.0%)
  LLM Calls: 5 (10.0%)
  Failed: 0

Learning:
  Phrases Learned This Session: 5

Phrase Bank:
  Total Phrases: 25
  Named Locations: 3
  Most Used: 'go back'

Success Rate: 100.0%
============================================================
```

---

## 🔧 Testing

### Test Modes

```bash
# All automated tests
python tests/test_learning.py

# Interactive mode (type commands)
python tests/test_learning.py --interactive

# Test phrase bank only
python tests/test_learning.py --phrase-bank

# Test intent executor
python tests/test_learning.py --executor

# Test LLM (uses API credits)
python tests/test_learning.py --llm
```

### What Gets Tested

1. **Phrase Bank**: Exact match, fuzzy match, add phrase
2. **Intent Executor**: All 7 intent types, position tracking, history
3. **Command Processor**: 3-tier flow, learning, statistics
4. **Full Integration**: With LLM, learning new phrases

---

## 🆚 Comparison: Learning System vs Rule-Based

| Aspect | Rule-Based (SpeechToText.py) | Learning System (SpeechToText_learning.py) |
|--------|------------------------------|-------------------------------------------|
| **Speed** | Instant (~1ms) | Instant for known (phrase bank) |
| |  | ~1-2s for new (LLM) |
| **Cost** | Free | ~$0.05-0.10 per project |
| **Flexibility** | Limited patterns | Learns any phrasing |
| **Extensibility** | Requires coding | Automatic learning |
| **Offline** | Yes | No (needs Claude API) |
| **Accuracy** | 100% for patterns | ~95-98% |
| **Memory** | None | Remembers all phrases |

### When to Use Each

**Rule-Based** (Production):
- Proven, fast, free
- Well-defined command set
- No internet required

**Learning System** (Research/Development):
- Natural language variations
- User-specific phrasing
- Growing vocabulary
- Better UX over time

---

## 🐛 Troubleshooting

### "ANTHROPIC_API_KEY not set"

```bash
cp .env.example .env
# Edit .env and add your key
```

### "Fuzzy match too aggressive"

Increase threshold in `.env`:
```env
FUZZY_MATCH_THRESHOLD=0.90
```

### "Not learning new phrases"

Check LLM confidence in logs (`asr_learning_log.jsonl`):
```json
{"confidence": 0.85}  // Below 0.90 threshold - won't learn
```

Lower threshold if needed:
```env
LLM_CONFIDENCE_THRESHOLD=0.85
```

### "Phrase bank not saving"

Check file permissions:
```bash
ls -l learning/phrase_bank.json
```

Should be writable. Check logs for errors.

---

## 🔮 Future Enhancements

### Planned

1. **Hybrid Mode**: Use rule-based for simple, LLM for complex
2. **Prompt Caching**: 90% cost reduction for repeated sessions
3. **Multi-Command Learning**: Learn sequences ("pick up and move right")
4. **Voice Feedback**: Confirm learning ("Got it, I'll remember that")

### Possible

1. **Fine-Tuned Model**: Train custom model, run offline
2. **Command Prediction**: Autocomplete based on history
3. **Context Awareness**: "move it there" remembers "there"
4. **Collaborative Learning**: Share phrase banks between robots

---

## 📝 Logging

All commands logged to `asr_learning_log.jsonl`:

```jsonl
{"timestamp": "2026-01-22T19:45:12", "text": "go back", "result": {"success": true}}
{"timestamp": "2026-01-22T19:45:15", "text": "shift left a bit", "result": {"success": true, "learned": true}}
```

Analyze with:
```bash
# Count learned phrases
grep '"learned": true' asr_learning_log.jsonl | wc -l

# Find failed commands
grep '"success": false' asr_learning_log.jsonl
```

---

## 🤝 Contributing

To add a new intent:

1. **Update `llm_interpreter.py`**: Add intent to prompt
2. **Update `intent_executor.py`**: Implement execution logic
3. **Add examples to `phrase_bank.json`**: Seed the bank
4. **Test**: `python tests/test_learning.py --executor`

---

## 📄 License

Same as parent project.

---

## 🎓 How It Works (Deep Dive)

### Phrase Bank Lookup

```python
# 1. Normalize input
phrase = "GO BACK".lower().strip()  # → "go back"

# 2. Exact match
if phrase in phrase_bank:
    return phrase_bank[phrase]  # Instant O(1)

# 3. Fuzzy match
best_match = max(phrase_bank, key=lambda p: similarity(phrase, p))
if similarity(phrase, best_match) >= threshold:
    return phrase_bank[best_match]  # Still instant O(n)
```

### LLM Interpretation

```python
# 4. LLM fallback
prompt = f"""
Available Intents: move_relative, move_to_previous, ...

Command: "{phrase}"
Extract intent and params as JSON.
"""

response = claude.messages.create(prompt)
# → {"intent": "move_to_previous", "params": {}, "confidence": 0.95}

# 5. Learn if confident
if response.confidence >= 0.90:
    phrase_bank[phrase] = response
    phrase_bank.save()
```

### Intent Execution

```python
# 6. Execute intent
if intent == "move_relative":
    delta = calculate_delta(params)
    new_position = current_position + delta
    write_to_unity(new_position)

elif intent == "move_to_previous":
    previous = position_history.pop()
    write_to_unity(previous)
```

---

**Built with ❤️ for the ABB GoFa robot**

