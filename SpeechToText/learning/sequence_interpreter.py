"""
Sequence Interpreter - LLM-based natural language to instruction sequence compiler.

Uses Claude to interpret voice commands and generate instruction sequences
that can be compiled and executed by the InstructionCompiler.

This is the "brain" that understands natural language and maps it to
the hierarchical instruction set.
"""

import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_CONFIDENCE_THRESHOLD
from .instruction_compiler import get_compiler, get_executor, InstructionCompiler


class SequenceInterpreter:
    """
    Interprets natural language commands into instruction sequences.
    Can learn new composite instructions from successful interpretations.
    """

    def __init__(self, compiler: InstructionCompiler = None):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed")
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL
        self.compiler = compiler or get_compiler()

    def _build_prompt(self, voice_command: str) -> str:
        """Build the LLM prompt with full instruction set context."""

        context = self.compiler.get_llm_context()

        prompt = f"""You are a robot arm controller. Convert voice commands into instruction sequences.

{context}

OUTPUT FORMAT:
Return a JSON object with:
{{
  "interpretation": "brief description of what the command means",
  "sequence": [
    {{"instruction": "instruction_name", "params": {{"param": "value"}}}},
    ...
  ],
  "composite_name": "optional_name_for_this_sequence",
  "confidence": 0.95
}}

RULES:
1. Use ONLY instructions from the lists above (primitives or composites)
2. For composites, just use them directly - they'll be expanded automatically
3. If a command matches an existing composite, just use that composite
4. For new multi-step tasks, generate a sequence of primitives/composites
5. Parameter substitution: use actual values, not placeholders
6. confidence: 0.9-1.0 for clear commands, 0.7-0.9 for interpreted, <0.7 for unclear
7. composite_name: suggest a name if this could be a reusable sequence (e.g., "make_blt")

EXAMPLES:

Command: "pick up the cheese"
{{
  "interpretation": "Pick up cheese from its stack",
  "sequence": [{{"instruction": "pick_up", "params": {{"item": "cheese"}}}}],
  "composite_name": null,
  "confidence": 0.95
}}

Command: "put the tomato in the assembly zone"
{{
  "interpretation": "Transfer tomato to assembly zone",
  "sequence": [{{"instruction": "transfer", "params": {{"item": "tomato", "destination": "assembly_zone"}}}}],
  "composite_name": null,
  "confidence": 0.95
}}

Command: "make a cheese sandwich"
{{
  "interpretation": "Build a cheese sandwich: bread, cheese, bread",
  "sequence": [
    {{"instruction": "transfer", "params": {{"item": "bread", "destination": "assembly_zone"}}}},
    {{"instruction": "transfer", "params": {{"item": "cheese", "destination": "assembly_zone"}}}},
    {{"instruction": "transfer", "params": {{"item": "bread", "destination": "assembly_zone"}}}},
    {{"instruction": "go_home", "params": {{}}}}
  ],
  "composite_name": "make_cheese_sandwich",
  "confidence": 0.90
}}

Command: "move right a little bit"
{{
  "interpretation": "Move right by a small amount (0.5cm)",
  "sequence": [{{"instruction": "move_relative", "params": {{"direction": "right", "distance": 0.5}}}}],
  "composite_name": null,
  "confidence": 0.95
}}

Now interpret this command:

Command: "{voice_command}"

JSON:"""

        return prompt

    def interpret(self, voice_command: str) -> Optional[Dict]:
        """
        Interpret a voice command and return structured result.

        Returns:
            Dict with interpretation, sequence, composite_name, confidence
            or None if interpretation failed
        """
        if not voice_command or len(voice_command.strip()) < 2:
            return None

        try:
            prompt = self._build_prompt(voice_command)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = [l for l in lines if l and not l.startswith("```")]
                response_text = "\n".join(json_lines)

            result = json.loads(response_text)

            # Validate
            if "sequence" not in result or "confidence" not in result:
                print(f"[WARN] Invalid LLM response structure")
                return None

            return result

        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parsing failed: {e}")
            return None
        except Exception as e:
            print(f"[ERROR] Interpretation failed: {e}")
            return None

    def interpret_and_execute(self, voice_command: str) -> bool:
        """
        Interpret a command and execute it.
        Learns new composites if confident.

        Returns True if execution succeeded.
        """
        print(f"[SEQ] Interpreting: '{voice_command}'")

        result = self.interpret(voice_command)
        if not result:
            print(f"[SEQ] Failed to interpret")
            return False

        print(f"[SEQ] Interpretation: {result['interpretation']}")
        print(f"[SEQ] Confidence: {result['confidence']:.2f}")
        print(f"[SEQ] Sequence: {len(result['sequence'])} steps")

        # Compile the sequence
        plan = self.compiler.compile_sequence(result["sequence"])
        if not plan or not plan.steps:
            print(f"[SEQ] Failed to compile sequence")
            return False

        # Execute
        executor = get_executor()
        success = executor.execute_plan(plan)

        # Learn if confident and successful
        if success and result["confidence"] >= LLM_CONFIDENCE_THRESHOLD:
            composite_name = result.get("composite_name")
            if composite_name and not self.compiler.is_composite(composite_name):
                # Learn new composite
                self.compiler.learn_composite(
                    name=composite_name,
                    description=result["interpretation"],
                    parameters={},  # Could extract from sequence
                    sequence=result["sequence"],
                    confidence=result["confidence"],
                    source_phrase=voice_command
                )

        return success

    def is_confident(self, result: Dict) -> bool:
        """Check if interpretation meets confidence threshold."""
        return result.get("confidence", 0) >= LLM_CONFIDENCE_THRESHOLD


# -----------------------------------------------------------------------------
# Convenience function
# -----------------------------------------------------------------------------

_interpreter_instance = None

def get_sequence_interpreter() -> SequenceInterpreter:
    """Get singleton SequenceInterpreter."""
    global _interpreter_instance
    if _interpreter_instance is None:
        _interpreter_instance = SequenceInterpreter()
    return _interpreter_instance


# -----------------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------------

def test_interpreter():
    """Test the sequence interpreter."""
    print("=== Sequence Interpreter Test ===\n")

    try:
        interpreter = SequenceInterpreter()
    except Exception as e:
        print(f"Cannot test: {e}")
        return

    test_commands = [
        "move right a little",
        "pick up the cheese",
        "put the tomato in the assembly area",
        "go home",
    ]

    for cmd in test_commands:
        print(f"\nCommand: '{cmd}'")
        result = interpreter.interpret(cmd)
        if result:
            print(f"  Interpretation: {result['interpretation']}")
            print(f"  Confidence: {result['confidence']:.2f}")
            print(f"  Sequence:")
            for step in result["sequence"]:
                print(f"    - {step['instruction']}({step.get('params', {})})")
        else:
            print("  Failed to interpret")


if __name__ == "__main__":
    test_interpreter()
