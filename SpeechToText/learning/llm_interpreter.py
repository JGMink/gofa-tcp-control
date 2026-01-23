"""
LLM Interpreter - Calls Claude API to understand unknown utterances.
"""

import json
from typing import Optional, Dict, Any

from .config import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    LLM_CONFIDENCE_THRESHOLD,
    VERBOSE_LOGGING
)
from .phrase_bank import get_phrase_bank

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("[LLMInterpreter] WARNING: anthropic package not installed. Install with: pip install anthropic")


SYSTEM_PROMPT = """You are an interpreter for a robot arm voice control system. Your job is to understand what the user wants the robot to do and map it to known intents.

You must respond with valid JSON only, no other text.

Guidelines:
1. Map the utterance to the most appropriate intent from the KNOWN INTENTS list
2. Extract any parameters mentioned (direction, distance, location name)
3. Provide a confidence score (0.0 to 1.0) for your interpretation
4. If you can map it, suggest a normalized phrase to save for future use
5. If the utterance doesn't map to any known intent, set "understood" to false

For move_relative intents:
- Directions: right, left, up, down, forward, backward
- Distance is optional, extract if mentioned (in centimeters)

For move_to_named intents:
- Extract the location name from the utterance
- If referencing "previous" or "last" position, use move_to_previous instead

Be generous in interpretation - if the user's intent is clear even with unusual phrasing, map it."""


USER_PROMPT_TEMPLATE = """KNOWN INTENTS:
{intents_json}

KNOWN LOCATIONS:
{locations_json}

SAMPLE PHRASES (for reference):
{sample_phrases}

CURRENT CONTEXT:
- Robot position: {current_position}
- Previous position: {previous_position}
- Gripper state: {gripper_state}

USER SAID: "{utterance}"

Respond with JSON:
{{
  "understood": true/false,
  "intent": "intent_name" or null,
  "parameters": {{}},
  "confidence": 0.0-1.0,
  "phrase_to_save": "normalized phrase" or null,
  "explanation": "brief explanation"
}}"""


class LLMInterpreter:
    def __init__(self):
        self.client = None
        if ANTHROPIC_AVAILABLE and CLAUDE_API_KEY:
            self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        elif not CLAUDE_API_KEY:
            print("[LLMInterpreter] WARNING: CLAUDE_API_KEY not set in environment")
    
    def interpret(self, 
                  utterance: str, 
                  current_position: dict = None,
                  previous_position: dict = None,
                  gripper_state: str = "unknown") -> Optional[Dict[str, Any]]:
        """
        Ask Claude to interpret an unknown utterance.
        
        Returns:
            {
                "understood": bool,
                "intent": str or None,
                "parameters": dict,
                "confidence": float,
                "phrase_to_save": str or None,
                "explanation": str,
                "needs_confirmation": bool
            }
        """
        if not self.client:
            print("[LLMInterpreter] No client available (missing API key or package)")
            return {
                "understood": False,
                "intent": None,
                "parameters": {},
                "confidence": 0.0,
                "phrase_to_save": None,
                "explanation": "LLM interpreter not available",
                "needs_confirmation": False
            }
        
        phrase_bank = get_phrase_bank()
        
        # Build context
        intents_json = json.dumps(phrase_bank.get_all_intents(), indent=2)
        locations_json = json.dumps(phrase_bank.get_all_locations(), indent=2)
        sample_phrases = "\n".join([f"  '{p}' → {i}" for p, i in phrase_bank.get_sample_phrases(15)])
        
        user_prompt = USER_PROMPT_TEMPLATE.format(
            intents_json=intents_json,
            locations_json=locations_json,
            sample_phrases=sample_phrases,
            current_position=json.dumps(current_position or {"x": 0, "y": 0, "z": 0}),
            previous_position=json.dumps(previous_position or {"x": 0, "y": 0, "z": 0}),
            gripper_state=gripper_state,
            utterance=utterance
        )
        
        if VERBOSE_LOGGING:
            print(f"[LLMInterpreter] Querying Claude for: '{utterance}'")
        
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=500,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            
            # Parse response
            response_text = response.content[0].text.strip()
            
            # Try to extract JSON (in case there's any wrapper text)
            json_match = response_text
            if not response_text.startswith('{'):
                import re
                match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if match:
                    json_match = match.group()
            
            result = json.loads(json_match)
            
            # Add needs_confirmation based on confidence
            result["needs_confirmation"] = result.get("confidence", 0) < LLM_CONFIDENCE_THRESHOLD
            
            if VERBOSE_LOGGING:
                print(f"[LLMInterpreter] Result: {result['intent']} (confidence: {result.get('confidence', 0):.2f})")
                if result.get("explanation"):
                    print(f"[LLMInterpreter] Explanation: {result['explanation']}")
            
            return result
            
        except json.JSONDecodeError as e:
            print(f"[LLMInterpreter] Failed to parse response as JSON: {e}")
            print(f"[LLMInterpreter] Raw response: {response_text[:200]}")
            return {
                "understood": False,
                "intent": None,
                "parameters": {},
                "confidence": 0.0,
                "phrase_to_save": None,
                "explanation": f"Failed to parse LLM response: {e}",
                "needs_confirmation": False
            }
            
        except anthropic.APIError as e:
            print(f"[LLMInterpreter] API error: {e}")
            return {
                "understood": False,
                "intent": None,
                "parameters": {},
                "confidence": 0.0,
                "phrase_to_save": None,
                "explanation": f"API error: {e}",
                "needs_confirmation": False
            }
        
        except Exception as e:
            print(f"[LLMInterpreter] Unexpected error: {e}")
            return {
                "understood": False,
                "intent": None,
                "parameters": {},
                "confidence": 0.0,
                "phrase_to_save": None,
                "explanation": f"Unexpected error: {e}",
                "needs_confirmation": False
            }


# Singleton instance
_llm_interpreter_instance = None

def get_llm_interpreter() -> LLMInterpreter:
    """Get the singleton LLMInterpreter instance."""
    global _llm_interpreter_instance
    if _llm_interpreter_instance is None:
        _llm_interpreter_instance = LLMInterpreter()
    return _llm_interpreter_instance