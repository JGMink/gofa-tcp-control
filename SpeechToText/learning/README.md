# LLM-Based Voice Command Interpreter

This module provides an alternative to rule-based parsing using Large Language Models (LLMs) for interpreting natural language voice commands.

## Overview

The LLM interpreter uses Anthropic's Claude API to parse voice commands into robot movement deltas. This approach offers several advantages over rule-based parsing:

- **Natural Language Understanding**: Handles variations in phrasing more flexibly
- **Context Awareness**: Better understanding of complex multi-step commands
- **Extensibility**: Easy to add new command types without writing regex patterns

## Architecture

```
Voice Input (Azure Speech-to-Text)
    ↓
Text Command (e.g., "move right 5 centimeters")
    ↓
LLM Interpreter (Claude API)
    ↓
Structured Deltas [{"x": 0.05, "y": 0.0, "z": 0.0}]
    ↓
Position Calculation
    ↓
TCP Command Queue (JSON file)
    ↓
Unity Controller
    ↓
Robot Movement
```

## Files

- **`llm_interpreter.py`**: Main LLM interpreter class
- **`config.py`**: Configuration constants and environment variables
- **`phrase_bank.json`**: Example commands and direction mappings for few-shot learning
- **`phrase_bank.py`**: Utilities for managing the phrase bank (future expansion)

## Usage

### Basic Usage

```python
from learning.llm_interpreter import LLMInterpreter

# Initialize interpreter
interpreter = LLMInterpreter()

# Parse a single command
deltas = interpreter.parse_command("move right 5 centimeters")
# Returns: [{"x": 0.05, "y": 0.0, "z": 0.0}]

# Parse with position context
current_pos = {"x": 0.0, "y": 0.0, "z": 0.0}
positions = interpreter.parse_command_with_context(
    "go left 3 cm then move up 2 cm",
    current_pos
)
# Returns: [
#   {"x": -0.03, "y": 0.0, "z": 0.0},
#   {"x": -0.03, "y": 0.02, "z": 0.0}
# ]
```

### Full Integration

The `SpeechToText_learning.py` script provides a complete implementation:

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run the LLM-based speech recognizer
python SpeechToText_learning.py
```

### Testing Without Speech

Use the standalone test script to verify LLM parsing without microphone:

```bash
# Run automated tests
python test_llm_only.py

# Interactive testing
python test_llm_only.py --interactive
```

## Configuration

### Environment Variables

Add these to your `.env` file:

```env
# Required
ANTHROPIC_API_KEY=your_api_key_here

# Optional (defaults shown)
ANTHROPIC_MODEL=claude-3-5-haiku-20241022
```

### Model Selection

The default model is **Claude 3.5 Haiku**, chosen for:
- **Speed**: Fast response times (~1-2 seconds)
- **Cost**: Lowest cost option (~$0.25 per million tokens)
- **Accuracy**: Sufficient for structured parsing tasks

You can change the model in `config.py`:

```python
ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"  # Fast and cheap (recommended)
# ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"  # More capable but slower/pricier
```

### Distance Scale

The `DISTANCE_SCALE` parameter converts centimeters to Unity units:

```python
DISTANCE_SCALE = 0.01  # 1 cm = 0.01 Unity units
```

Adjust this in `config.py` to match your robot's coordinate system.

## Coordinate System

The interpreter uses the following coordinate mapping:

| Axis | Positive Direction | Negative Direction |
|------|-------------------|--------------------|
| X    | Right             | Left               |
| Y    | Up                | Down               |
| Z    | Forward           | Backward           |

## Supported Commands

### Direction Keywords

- **Right/Left**: `right`, `left`
- **Up/Down**: `up`, `upward`, `down`, `downward`
- **Forward/Backward**: `forward`, `ahead`, `backward`, `back`

### Distance Specifications

- **Explicit**: "5 centimeters", "10 cm", "7 millimeters"
- **Implicit**: "move right" (uses default 1 cm)
- **Qualitative**: "a little bit", "slightly" (uses 0.5 cm)

### Multi-Command Sentences

The LLM naturally handles compound commands:

- "move right **and** go up 5 centimeters"
- "go left 3 cm **then** move down 2 cm"
- "move forward 10 cm**,** then go right 5 cm**,** then move up 3 cm"

## Cost Optimization

To minimize API costs:

1. **Use Haiku Model**: The default Claude 3.5 Haiku is 10x cheaper than Sonnet
2. **Short Prompts**: Uses only 4 few-shot examples (~200 tokens)
3. **Limited Output**: Max tokens set to 200 (typical response is ~30 tokens)
4. **Temperature 0**: Deterministic responses reduce variability

### Estimated Costs

Assuming average command is 300 tokens total (input + output):

- **Haiku**: ~$0.075 per 1000 commands
- **10,000 commands**: ~$0.75
- **Typical session (50 commands)**: ~$0.004 (less than half a cent)

## Phrase Bank

The `phrase_bank.json` file contains:

1. **Example Commands**: Few-shot learning examples
2. **Direction Mappings**: Keyword-to-axis mappings (for future hybrid approaches)

### Adding Examples

To improve parsing for specific command patterns, add examples to `phrase_bank.json`:

```json
{
  "example_commands": [
    {
      "input": "your new command pattern",
      "output": [{"x": 0.0, "y": 0.0, "z": 0.0}]
    }
  ]
}
```

The interpreter uses the first 4 examples for few-shot learning.

## Error Handling

The interpreter handles various error cases:

- **JSON Parsing Errors**: Returns `None` if LLM output isn't valid JSON
- **Invalid Structure**: Validates delta objects have x, y, z fields
- **API Errors**: Catches and logs Anthropic API exceptions
- **Missing API Key**: Raises clear error on initialization

## Logging

The main script logs all recognitions to `asr_llm_log.jsonl`:

```json
{
  "timestamp": "2025-01-22T10:30:45.123456",
  "text": "move right 5 centimeters",
  "emergency_halt": false,
  "queue_length": 1,
  "llm_result": {
    "positions": [{"x": 0.05, "y": 0.0, "z": 0.0}],
    "success": true
  }
}
```

## Comparison: LLM vs Rule-Based

| Aspect | Rule-Based | LLM-Based |
|--------|------------|-----------|
| **Speed** | Instant (~1ms) | Fast (~1-2s) |
| **Cost** | Free | ~$0.075 per 1000 commands |
| **Flexibility** | Limited patterns | Natural variations |
| **Accuracy** | 100% for known patterns | ~95-98% |
| **Offline** | Yes | No (requires API) |
| **Extensibility** | Requires coding | Update examples |

## Troubleshooting

### "Anthropic SDK not installed"

```bash
pip install anthropic
```

### "ANTHROPIC_API_KEY not set"

Create a `.env` file with your API key:

```bash
cp .env.example .env
# Edit .env and add your key
```

### "LLM could not parse command"

- Check the log output for JSON parsing errors
- Add similar commands to `phrase_bank.json` as examples
- Verify the command uses supported direction keywords

### API Rate Limits

If you hit rate limits:
- Add delays between commands
- Use a higher tier API key
- Consider caching common commands

## Future Enhancements

Potential improvements:

1. **Prompt Caching**: Reuse system prompts to reduce costs
2. **Hybrid Approach**: Use rules for simple commands, LLM for complex ones
3. **Fine-Tuning**: Train a smaller custom model for offline use
4. **Command Prediction**: Suggest completions as user speaks
5. **Context Memory**: Remember previous commands for relative movements

## License

Same as parent project.
