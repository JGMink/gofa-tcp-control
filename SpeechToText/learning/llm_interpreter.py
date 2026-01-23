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

    def __init__(self):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed")

        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set in environment")

        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL

    def _build_prompt(self, voice_command: str) -> str:
        """
        Build prompt for Claude to extract intent from voice command.
        """
        prompt = f"""You are interpreting robot voice commands. Extract the intent and parameters.

Available Intents:
1. move_relative - Move in a direction by a distance
   Parameters: direction (right/left/up/down/forward/backward), distance (float), unit (cm/mm)
   Examples: "move right 5 cm", "go up", "shift left 10 centimeters"

2. move_to_previous - Return to the last position
   Parameters: (none)
   Examples: "go back", "return to previous position", "put it back where it was"

3. move_to_named - Move to a saved named location
   Parameters: location (string)
   Examples: "go home", "move to pickup position", "go to station A"

4. emergency_stop - Immediately halt all movement
   Parameters: (none)
   Examples: "stop", "halt", "emergency"

5. gripper_open - Open the gripper (future hardware)
   Parameters: (none)
   Examples: "open gripper", "release", "let go"

6. gripper_close - Close the gripper (future hardware)
   Parameters: (none)
   Examples: "close gripper", "grab", "grip"

7. save_named_location - Save current position with a name
   Parameters: location (string)
   Examples: "save this as home", "remember this as pickup"

Return a JSON object with:
{{
  "intent": "intent_name",
  "params": {{parameter_dict}},
  "confidence": 0.95
}}

Important:
- confidence should be 0.0-1.0 (how sure you are)
- Use 1.0 for exact matches, 0.9-0.95 for clear interpretations, lower for ambiguous
- For move_relative with no distance specified, use distance: 1.0, unit: "cm"
- direction must be lowercase

Command: "{voice_command}"

JSON Response:"""

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
