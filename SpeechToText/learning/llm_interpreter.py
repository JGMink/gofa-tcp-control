"""
LLM-based voice command interpreter using Anthropic Claude API.
Extracts structured intents from natural language commands.
"""
import json
import os
from typing import Optional, Dict

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("WARNING: Anthropic SDK not installed. Install with: pip install anthropic")

from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_CONFIDENCE_THRESHOLD
)


class LLMInterpreter:
    """
    Uses Claude to interpret voice commands and extract structured intents.
    Returns intent + parameters + confidence for learning system.
    """

    def __init__(self, phrase_bank=None):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed")

        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL
        self.phrase_bank = phrase_bank  # Optional reference for dynamic context

    def set_phrase_bank(self, phrase_bank):
        """Set phrase bank reference for dynamic context in prompts."""
        self.phrase_bank = phrase_bank

    def _get_named_locations(self) -> str:
        """Get list of named locations for prompt context."""
        if self.phrase_bank:
            locations = self.phrase_bank.data.get("named_locations", {})
            if locations:
                # Include position info for context
                parts = []
                for name, pos in locations.items():
                    parts.append(f'"{name}"')
                return ", ".join(parts)
        return '"home", "start"'  # Default

    def _build_prompt(self, voice_command: str) -> str:
        """
        Build prompt for Claude to extract intent from voice command.
        """
        prompt = f"""You are interpreting voice commands for an ABB GoFa robot arm. Extract the intent and parameters.

IMPORTANT CONTEXT:
- This is a speech-to-robot control system
- Users speak naturally, often using qualitative terms instead of exact measurements
- The robot understands relative movements in 6 directions

Available Intents:

1. move_relative - Move in a direction by a distance
   Parameters: direction (right/left/up/down/forward/backward), distance (float in cm)

   Qualitative distance mappings (use these exact values):
   - "tiny", "teensy", "small", "just a hair" -> distance: 0.3
   - "little bit", "slightly", "a bit", "a tad" -> distance: 0.5
   - No qualifier or "normal" -> distance: 1.0
   - "large", "big", "a lot", "far" -> distance: 2.0

   Examples:
   - "move right 5" -> direction: "right", distance: 5.0
   - "shift left a teensy bit" -> direction: "left", distance: 0.3
   - "go up a little" -> direction: "up", distance: 0.5
   - "move forward" -> direction: "forward", distance: 1.0
   - "nudge it right" -> direction: "right", distance: 0.3

2. move_to_previous - Return to the last position
   Parameters: (none)
   Examples: "go back", "undo", "return to previous", "put it back"

3. move_to_named - Move to a saved named location
   Parameters: location_name (string)
   Available locations: {self._get_named_locations()}
   Examples: "go home", "go to start", "move to starting position", "return to home"
   Note: "starting position", "start", "origin" should map to "home"

4. emergency_stop - Immediately halt all movement
   Parameters: (none)
   Examples: "stop", "halt", "emergency", "freeze"

5. gripper_open - Open the gripper
   Parameters: (none)
   Examples: "open gripper", "release", "let go", "drop it"

6. gripper_close - Close the gripper
   Parameters: (none)
   Examples: "close gripper", "grab", "grip", "pick up"

7. save_named_location - Save current position with a name
   Parameters: location_name (string)
   Examples: "save this as home", "remember this position as pickup"

Return ONLY a JSON object:
{{
  "intent": "intent_name",
  "params": {{}},
  "confidence": 0.95
}}

Rules:
- confidence: 0.9-1.0 for clear commands, 0.7-0.9 for interpreted, below 0.7 for unclear
- direction must be lowercase
- If the command is gibberish, empty, or not a robot command, return confidence: 0.0
- For commands like "I moved..." (past tense describing what happened), interpret as a command to move

Command: "{voice_command}"

JSON:"""

        return prompt

    def interpret_command(self, voice_command: str) -> Optional[Dict]:
        """
        Interpret a voice command and extract intent.

        Args:
            voice_command: Natural language command

        Returns:
            Dict with {intent, params, confidence} or None if parsing fails
        """
        try:
            prompt = self._build_prompt(voice_command)

            # Use Claude with minimal settings for speed and cost
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,  # Slightly more for intent JSON
                temperature=0,   # Deterministic for consistency
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Extract the JSON response
            response_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = [l for l in lines if l and not l.startswith("```")]
                response_text = "\n".join(json_lines)

            result = json.loads(response_text)

            # Validate structure
            if not all(k in result for k in ["intent", "params", "confidence"]):
                print(f"Warning: Invalid LLM response structure: {result}")
                return None

            # Validate confidence
            if not (0.0 <= result["confidence"] <= 1.0):
                print(f"Warning: Invalid confidence value: {result['confidence']}")
                result["confidence"] = 0.5  # Default to low confidence

            return result

        except json.JSONDecodeError as e:
            print(f"LLM JSON parsing error: {e}")
            print(f"Response was: {response_text}")
            return None
        except Exception as e:
            print(f"LLM interpretation error: {e}")
            return None

    def is_confident(self, interpretation: Dict) -> bool:
        """Check if LLM interpretation meets confidence threshold."""
        return interpretation.get("confidence", 0.0) >= LLM_CONFIDENCE_THRESHOLD


def test_llm_interpreter():
    """Test the LLM interpreter with various commands."""
    if not ANTHROPIC_AVAILABLE:
        print("Cannot test: Anthropic SDK not installed")
        return

    if not ANTHROPIC_API_KEY:
        print("Cannot test: ANTHROPIC_API_KEY not set")
        return

    interpreter = LLMInterpreter()

    test_commands = [
        "move right 5 centimeters",
        "go back to where it was",
        "go home",
        "stop",
        "open gripper",
        "save this as pickup position"
    ]

    print("\n=== LLM Intent Interpreter Test ===\n")

    for cmd in test_commands:
        print(f"Command: '{cmd}'")
        result = interpreter.interpret_command(cmd)
        if result:
            print(f"Intent: {result['intent']}")
            print(f"Params: {result['params']}")
            print(f"Confidence: {result['confidence']:.2f}")
            print(f"Confident enough to learn: {interpreter.is_confident(result)}")
        else:
            print("Result: Failed to parse")
        print()


if __name__ == "__main__":
    test_llm_interpreter()
