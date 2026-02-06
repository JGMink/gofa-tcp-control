#!/usr/bin/env python3
"""
CLI Robot Control - Type commands to control the robot
Supports natural language commands like "move 10cm left" or "close gripper"
"""

import sys
from learning.llm_interpreter import LLMInterpreter
from learning.intent_executor import get_executor
from learning.phrase_bank import get_phrase_bank


def print_help():
    """Print help message with available commands."""
    print("""
=== CLI Robot Control ===

Type natural language commands to control the robot:

MOVEMENT EXAMPLES:
  move 10 left
  go right 5cm
  move up a little
  shift down 2 centimeters
  move forward
  go back

GRIPPER EXAMPLES:
  open gripper
  close gripper
  grab
  release

COMPOUND EXAMPLES:
  move up and close gripper
  grab it and move left
  open gripper and go back

OBJECT MANIPULATION:
  go to the red cube
  pick up the blue cube
  place it here
  move to the green cube

NAVIGATION:
  go home
  return to previous
  save this as pickup_zone

OTHER COMMANDS:
  help - show this message
  status - show current state
  objects - list known objects
  quit/exit - exit CLI

Just type naturally and press Enter!
============================
""")


def print_status(executor):
    """Print current robot status."""
    state = executor.get_state()
    pos = state['current_position']

    print("\n--- Current Status ---")
    print(f"Position: ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f})")
    print(f"Gripper: {state['gripper_state'].upper()}")
    print(f"Emergency Halt: {state['emergency_halt']}")
    print(f"Command Queue: {state['queue_length']} items")

    if executor.held_object:
        print(f"Holding: {executor.held_object}")

    if state['previous_position']:
        prev = state['previous_position']
        print(f"Previous Position: ({prev['x']:.3f}, {prev['y']:.3f}, {prev['z']:.3f})")

    print("--------------------\n")


def list_objects(executor):
    """List all known objects."""
    objects = executor.get_objects()

    if not objects:
        print("\nNo objects registered yet.\n")
        return

    print("\n--- Known Objects ---")
    for name, obj in objects.items():
        pos = obj['position']
        props = obj.get('properties', {})
        held = props.get('held', False)
        color = props.get('color', 'unknown')

        status = " (HELD)" if held else ""
        print(f"  • {name}: ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f}) [{color}]{status}")
    print("--------------------\n")


def main():
    """Main CLI loop."""
    print("=== CLI Robot Control ===")
    print("Initializing...")

    try:
        interpreter = LLMInterpreter()
        executor = get_executor()
        phrase_bank = get_phrase_bank()
        interpreter.set_phrase_bank(phrase_bank)

        print("✓ Ready!")
        print("Type 'help' for available commands\n")

    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        print("\nMake sure ANTHROPIC_API_KEY is set:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        return

    # Main command loop
    while True:
        try:
            # Get user input
            command = input("robot> ").strip()

            if not command:
                continue

            # Handle special commands
            if command.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            elif command.lower() == 'help':
                print_help()
                continue

            elif command.lower() == 'status':
                print_status(executor)
                continue

            elif command.lower() == 'objects':
                list_objects(executor)
                continue

            elif command.lower() == 'clear':
                import os
                os.system('clear' if os.name == 'posix' else 'cls')
                continue

            # Parse and execute command
            print(f"Interpreting: '{command}'")
            result = interpreter.interpret_command(command)

            if not result:
                print("✗ Failed to parse command. Try 'help' for examples.\n")
                continue

            # Show what was understood
            intent = result['intent']
            params = result['params']
            confidence = result['confidence']

            print(f"  Intent: {intent}")
            if params:
                print(f"  Params: {params}")
            print(f"  Confidence: {confidence:.2f}")

            # Check confidence
            if confidence < 0.7:
                print("⚠️  Low confidence - command may not be clear")
                confirm = input("Execute anyway? (y/n): ").strip().lower()
                if confirm != 'y':
                    print("Skipped.\n")
                    continue

            # Execute
            executed = executor.execute(intent, params)

            if executed:
                cmd_type = executed.get('command_type')

                if cmd_type == 'not_implemented':
                    print(f"⚠️  {executed.get('message', 'Not implemented')}\n")

                elif cmd_type == 'error':
                    print(f"✗ Error: {executed.get('message', 'Unknown error')}\n")

                elif cmd_type == 'compound':
                    steps = executed.get('steps_completed', 0)
                    print(f"✓ Executed compound command ({steps} steps)\n")

                elif cmd_type == 'move':
                    pos = executed.get('position', {})
                    print(f"✓ Moved to ({pos.get('x', 0):.3f}, {pos.get('y', 0):.3f}, {pos.get('z', 0):.3f})\n")

                elif cmd_type == 'gripper':
                    action = executed.get('action', 'unknown')
                    print(f"✓ Gripper {action.upper()}\n")

                elif cmd_type == 'pick':
                    obj_name = executed.get('object_name', 'object')
                    print(f"✓ Picked up '{obj_name}'\n")

                elif cmd_type == 'place':
                    obj_name = executed.get('object_name', 'object')
                    print(f"✓ Placed '{obj_name}'\n")

                elif cmd_type == 'emergency_halt':
                    print("🛑 EMERGENCY HALT ACTIVATED\n")

                elif cmd_type == 'resume':
                    print("▶️  RESUMED\n")

                else:
                    print(f"✓ Command executed: {cmd_type}\n")
            else:
                print("✗ Execution failed\n")

        except KeyboardInterrupt:
            print("\n\nUse 'quit' to exit.\n")

        except Exception as e:
            print(f"✗ Error: {e}\n")


if __name__ == "__main__":
    main()
