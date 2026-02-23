#!/usr/bin/env python3
"""
CLI Robot Control - Type commands to control the robot.
Supports simple commands ("move 10cm left", "close gripper") via the phrase
bank + LLM interpreter, and complex commands ("pick up the cheese",
"make a BLT") via the same sequence interpreter used by speech_control_llm.py.

Both paths share the same phrase_bank.json so learned phrases and cached
sequences are available from both the CLI and the speech interface.
"""

import sys
import json
import os

from learning.llm_interpreter import LLMInterpreter
from learning.intent_executor import get_executor
from learning.phrase_bank import get_phrase_bank
from learning.instruction_compiler import get_compiler, InstructionExecutor
from learning.sequence_interpreter import SequenceInterpreter


# ---------------------------------------------------------------------------
# Sequence-command keywords — same heuristic as speech_control_llm.py
# ---------------------------------------------------------------------------
_SEQ_KEYWORDS = {
    "pick", "place", "put", "make", "build", "assemble", "stack",
    "transfer", "grab", "get", "take", "add", "layer", "clear",
}

# Multi-word phrases that should also go through the sequence path
_SEQ_PHRASES = {"start over", "never mind", "go home", "put it back"}

def _looks_like_sequence_command(text: str) -> bool:
    """Return True if the command is likely complex enough for the sequence interpreter."""
    low = text.lower()
    if any(p in low for p in _SEQ_PHRASES):
        return True
    words = set(low.split())
    return bool(words & _SEQ_KEYWORDS)


# ---------------------------------------------------------------------------
# Help / status / object listing
# ---------------------------------------------------------------------------

def print_help():
    print("""
=== CLI Robot Control ===

Type natural language commands to control the robot.
Complex commands (pick up, make a sandwich, etc.) go through the full
sequence interpreter — same pipeline as speech control.

MOVEMENT:
  move 10 left          go right 5cm
  move up a little      go back

GRIPPER:
  open gripper          release / let go / drop it
  close gripper         grab / grip
  close to 50mm

SANDWICH / ASSEMBLY:
  pick up the cheese
  make a BLT
  make a club sandwich with extra meat
  start over

COMPOUND:
  move up and close gripper
  grab it and move left

NAVIGATION:
  go home
  return to previous
  save this as pickup_zone

META:
  help   - this message
  status - current robot state
  quit   - exit
============================
""")


def print_status(executor, seq_executor=None):
    state = executor.get_state()
    pos = state['current_position']
    print("\n--- Current Status ---")
    print(f"Position:       ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f})")
    print(f"Gripper:        {state['gripper_state'].upper()}")
    print(f"Emergency Halt: {state['emergency_halt']}")
    if executor.held_object:
        print(f"Holding:        {executor.held_object}")
    if state['previous_position']:
        prev = state['previous_position']
        print(f"Previous pos:   ({prev['x']:.3f}, {prev['y']:.3f}, {prev['z']:.3f})")
    if seq_executor:
        print(f"Seq gripper:    {seq_executor.gripper_position*1000:.1f}mm")
    print("--------------------\n")


def list_objects(executor):
    objects = executor.get_objects()
    if not objects:
        print("\nNo objects registered yet.\n")
        return
    print("\n--- Known Objects ---")
    for name, obj in objects.items():
        pos = obj['position']
        props = obj.get('properties', {})
        held = "(HELD)" if props.get('held') else ""
        color = props.get('color', 'unknown')
        print(f"  • {name}: ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f}) [{color}] {held}")
    print("--------------------\n")


# ---------------------------------------------------------------------------
# Sequence path (pick up / make a sandwich / etc.)
# ---------------------------------------------------------------------------

def _run_sequence_command(text: str, phrase_bank, seq_interpreter: SequenceInterpreter,
                          seq_executor: InstructionExecutor) -> bool:
    """
    Try the phrase bank sequence cache first, then the LLM sequence interpreter.
    Returns True if handled, False if it should fall through to the simple path.
    """
    # 1. Exact sequence cache hit
    cached = phrase_bank.sequence_match(text)
    if cached:
        print(f"  [cache hit] {cached.get('interpretation', '')}")
        _execute_plan(cached['sequence'], seq_executor)
        return True

    # 2. Fuzzy sequence cache hit
    fuzzy = phrase_bank.fuzzy_sequence_match(text)
    if fuzzy:
        matched_phrase, cached, ratio = fuzzy
        print(f"  [fuzzy cache {ratio:.2f}] matched '{matched_phrase}'")
        print(f"  {cached.get('interpretation', '')}")
        _execute_plan(cached['sequence'], seq_executor)
        return True

    # 3. Full LLM sequence interpretation
    result = seq_interpreter.interpret(text)
    if result is None:
        return False  # empty / trivial — fall through

    interp = result.get('interpretation', '')
    seq = result.get('sequence', [])
    conf = result.get('confidence', 0.0)
    issues = result.get('validation_issues', [])
    feedback = result.get('user_feedback')

    print(f"  Interpretation: {interp}")
    print(f"  Confidence:     {conf:.2f}  ({'HIGH' if conf>=0.9 else 'MED' if conf>=0.75 else 'LOW'})")
    if issues:
        print(f"  Validation:     {'; '.join(issues)}")
    if feedback:
        print(f"  Feedback:       {feedback}")

    if not seq:
        print("  (empty sequence — nothing to execute)\n")
        return True

    if conf < 0.6:
        confirm = input("  Low confidence — execute anyway? (y/n): ").strip().lower()
        if confirm != 'y':
            print("  Skipped.\n")
            return True

    _execute_plan(seq, seq_executor)

    # Learn if confident enough and composite name suggested
    composite = result.get('composite_name')
    if composite and conf >= 0.80 and not result.get('_from_cache') and not result.get('is_creative'):
        phrase_bank.add_sequence_phrase(
            phrase=text,
            interpretation=interp,
            sequence=seq,
            composite_name=composite,
            confidence=conf,
        )
        print(f"  [learned] saved as '{composite}'\n")

    return True


def _execute_plan(sequence: list, seq_executor: InstructionExecutor):
    """Drive InstructionExecutor through a compiled sequence list."""
    from learning.instruction_compiler import ExecutionStep
    print(f"  Executing {len(sequence)} step(s):")
    for step_dict in sequence:
        instr = step_dict.get('instruction', '')
        params = step_dict.get('params', {})
        step = ExecutionStep(instruction=instr, params=params)
        ok = seq_executor.execute_step(step)
        status = "✓" if ok else "✗"
        param_str = f"  {params}" if params else ""
        print(f"    {status} {instr}(){param_str}")
    print()


# ---------------------------------------------------------------------------
# Simple intent path (move, gripper, named location, etc.)
# ---------------------------------------------------------------------------

def _handle_simple_result(executed: dict):
    if not executed:
        print("✗ Execution failed\n")
        return
    cmd_type = executed.get('command_type', '')
    if cmd_type == 'not_implemented':
        print(f"⚠️  {executed.get('message', 'Not implemented')}\n")
    elif cmd_type == 'error':
        print(f"✗ Error: {executed.get('message', 'Unknown error')}\n")
    elif cmd_type == 'compound':
        print(f"✓ Compound command ({executed.get('steps_completed', 0)} steps)\n")
    elif cmd_type == 'move':
        pos = executed.get('position', {})
        print(f"✓ Moved to ({pos.get('x',0):.3f}, {pos.get('y',0):.3f}, {pos.get('z',0):.3f})\n")
    elif cmd_type == 'gripper':
        action = executed.get('action', 'unknown')
        pos_mm = executed.get('position_mm', executed.get('position', 0) * 1000)
        print(f"✓ Gripper {action.upper()} → {pos_mm:.0f}mm\n")
    elif cmd_type == 'pick':
        print(f"✓ Picked up '{executed.get('object_name', 'object')}'\n")
    elif cmd_type == 'place':
        print(f"✓ Placed '{executed.get('object_name', 'object')}'\n")
    elif cmd_type == 'emergency_halt':
        print("🛑 EMERGENCY HALT\n")
    elif cmd_type == 'resume':
        print("▶️  Resumed\n")
    else:
        print(f"✓ {cmd_type}\n")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    print("=== CLI Robot Control ===")
    print("Initializing...")

    try:
        phrase_bank    = get_phrase_bank()
        interpreter    = LLMInterpreter()
        interpreter.set_phrase_bank(phrase_bank)
        simple_executor = get_executor()

        compiler       = get_compiler()
        seq_executor   = InstructionExecutor(compiler)
        seq_interpreter = SequenceInterpreter(compiler)

        print("✓ Ready!  (type 'help' for commands)\n")

    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        print("\nMake sure ANTHROPIC_API_KEY is set in .env or environment.")
        return

    while True:
        try:
            command = input("robot> ").strip()
            if not command:
                continue

            low = command.lower()

            # ── meta commands ──────────────────────────────────────────
            if low in ('quit', 'exit', 'q'):
                print("Goodbye!")
                break
            elif low == 'help':
                print_help()
                continue
            elif low == 'status':
                print_status(simple_executor, seq_executor)
                continue
            elif low == 'objects':
                list_objects(simple_executor)
                continue
            elif low == 'clear':
                os.system('clear' if os.name == 'posix' else 'cls')
                continue

            print(f"→ '{command}'")

            # ── sequence path for complex commands ────────────────────
            if _looks_like_sequence_command(command):
                handled = _run_sequence_command(
                    command, phrase_bank, seq_interpreter, seq_executor
                )
                if handled:
                    continue
                # fall through to simple path if sequence returned nothing

            # ── simple path: phrase bank → LLM interpreter ────────────
            # Check phrase bank exact/fuzzy first (same bank, fast)
            matched = phrase_bank.exact_match(command) or (
                phrase_bank.fuzzy_match(command)[1]
                if phrase_bank.fuzzy_match(command) else None
            )

            result = interpreter.interpret_command(command)
            if not result:
                print("✗ Could not interpret command. Try 'help'.\n")
                continue

            intent     = result['intent']
            params     = result['params']
            confidence = result['confidence']

            print(f"  Intent:     {intent}")
            if params:
                print(f"  Params:     {params}")
            print(f"  Confidence: {confidence:.2f}")

            if confidence < 0.7:
                confirm = input("  Low confidence — execute anyway? (y/n): ").strip().lower()
                if confirm != 'y':
                    print("  Skipped.\n")
                    continue

            executed = simple_executor.execute(intent, params)
            _handle_simple_result(executed)

        except KeyboardInterrupt:
            print("\n\nUse 'quit' to exit.\n")
        except Exception as e:
            print(f"✗ Error: {e}\n")


if __name__ == "__main__":
    main()
