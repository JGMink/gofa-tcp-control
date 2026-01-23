#!/usr/bin/env python3
"""
Standalone test script for LLM interpreter.
Tests the LLM command parsing without requiring microphone or Azure Speech.
"""
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Check if Anthropic API key is set
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in .env file")
    print("Please add: ANTHROPIC_API_KEY=your_key_here")
    exit(1)

from learning.llm_interpreter import LLMInterpreter


def test_llm_parser():
    """Test the LLM interpreter with various commands."""

    print("\n" + "="*60)
    print("LLM Command Interpreter Test")
    print("="*60 + "\n")

    # Initialize interpreter
    try:
        interpreter = LLMInterpreter()
        print("✓ LLM Interpreter initialized successfully\n")
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        return

    # Test commands
    test_commands = [
        # Simple single commands
        "move right 5 centimeters",
        "go left 10 centimeters",
        "move up 3 centimeters",
        "go down 7 centimeters",
        "move forward 15 centimeters",
        "go backward 8 centimeters",

        # Commands without explicit distance
        "move right",
        "go up",

        # Multi-command sentences
        "move right and go up 5 centimeters",
        "go left 3 centimeters then move down 2 centimeters",
        "move forward 10 centimeters, then go right 5 centimeters, then move up 3 centimeters",

        # Natural variations
        "go a little bit to the right",
        "move upward 4 centimeters",
        "shift left 6 centimeters and then move backward"
    ]

    current_position = {"x": 0.0, "y": 0.0, "z": 0.0}

    print("Starting position:", current_position)
    print("\n" + "-"*60 + "\n")

    for i, cmd in enumerate(test_commands, 1):
        print(f"Test {i}/{len(test_commands)}")
        print(f"Command: '{cmd}'")

        try:
            # Parse as deltas
            deltas = interpreter.parse_command(cmd)

            if deltas:
                print(f"✓ Parsed successfully:")
                for j, delta in enumerate(deltas, 1):
                    print(f"  Delta {j}: {delta}")

                # Also test with context
                positions = interpreter.parse_command_with_context(cmd, current_position)
                if positions:
                    print(f"  Final position: {positions[-1]}")
                    current_position = positions[-1]
            else:
                print("✗ Failed to parse")

        except Exception as e:
            print(f"✗ Error: {e}")

        print("-"*60 + "\n")

    print(f"Final TCP position after all commands: {current_position}\n")


def test_single_command():
    """Interactive test - parse a single command."""
    print("\n" + "="*60)
    print("Single Command Test")
    print("="*60 + "\n")

    try:
        interpreter = LLMInterpreter()
        print("✓ LLM Interpreter initialized\n")
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        return

    while True:
        cmd = input("Enter command (or 'quit' to exit): ").strip()

        if cmd.lower() in ['quit', 'exit', 'q']:
            break

        if not cmd:
            continue

        try:
            deltas = interpreter.parse_command(cmd)
            if deltas:
                print(f"✓ Result: {json.dumps(deltas, indent=2)}")
            else:
                print("✗ Failed to parse")
        except Exception as e:
            print(f"✗ Error: {e}")

        print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        test_single_command()
    else:
        test_llm_parser()
        print("\nTip: Run with --interactive flag for interactive testing")
