#!/usr/bin/env python3
"""
Test script for object manipulation with compound commands.
Demonstrates picking, placing, and stacking objects.
"""

from learning.llm_interpreter import LLMInterpreter
from learning.intent_executor import get_executor
from learning.phrase_bank import get_phrase_bank
import time


def test_compound_commands():
    """Test compound command parsing and execution."""
    print("=== Testing Compound Commands ===\n")

    interpreter = LLMInterpreter()
    executor = get_executor()

    # Register some test objects
    executor.register_object("red_cube", {"x": 0.5, "y": 0.6, "z": -0.2}, {"color": "red"})
    executor.register_object("blue_cube", {"x": 0.65, "y": 0.6, "z": -0.2}, {"color": "blue"})
    executor.register_object("green_cube", {"x": 0.8, "y": 0.6, "z": -0.2}, {"color": "green"})

    print("Registered objects:")
    for name, obj in executor.get_objects().items():
        print(f"  - {name}: {obj['position']}")
    print()

    test_commands = [
        "move up and close gripper",
        "grab it and move left",
        "open gripper and go back",
        "pick up the red cube",
        "move to the blue cube",
        "place it here",
    ]

    for cmd in test_commands:
        print(f"\n>>> Command: '{cmd}'")
        print("-" * 50)

        # Parse command
        result = interpreter.interpret_command(cmd)

        if result:
            print(f"Intent: {result['intent']}")
            print(f"Params: {result['params']}")
            print(f"Confidence: {result['confidence']:.2f}")

            # Execute
            if result['confidence'] >= 0.7:
                executed = executor.execute(result['intent'], result['params'])
                if executed:
                    print(f"✓ Executed: {executed.get('command_type')}")
                    if 'sequence' in executed:
                        print(f"  Steps completed: {executed['steps_completed']}")
                else:
                    print("✗ Execution failed")
            else:
                print("⚠️  Confidence too low to execute")
        else:
            print("✗ Failed to parse command")

        time.sleep(0.5)

    print("\n" + "=" * 50)
    print("Final state:")
    state = executor.get_state()
    print(f"Position: {state['current_position']}")
    print(f"Gripper: {state['gripper_state']}")
    print(f"Held object: {executor.held_object or 'None'}")
    print(f"Known objects: {len(executor.known_objects)}")


def test_stacking_sequence():
    """Test a full stacking sequence."""
    print("\n\n=== Testing Object Stacking Sequence ===\n")

    interpreter = LLMInterpreter()
    executor = get_executor()

    # Reset position
    executor.set_position({"x": 0.0, "y": 0.567, "z": -0.24})

    sequence = [
        "go to the red cube",
        "move down a tiny bit",
        "close gripper",
        "move up 10",
        "go to the blue cube",
        "move up 5",
        "move down a tiny bit",
        "open gripper",
        "move up",
    ]

    print("Stacking red cube on blue cube:\n")

    for i, cmd in enumerate(sequence, 1):
        print(f"{i}. '{cmd}'")

        result = interpreter.interpret_command(cmd)
        if result and result['confidence'] >= 0.7:
            executor.execute(result['intent'], result['params'])
            time.sleep(0.3)
        else:
            print(f"   ⚠️  Skipped (low confidence or parse error)")

    print("\n✓ Stacking sequence complete!")


def test_object_queries():
    """Test querying object information."""
    print("\n\n=== Testing Object Queries ===\n")

    executor = get_executor()

    objects = executor.get_objects()
    print(f"Total objects tracked: {len(objects)}\n")

    for name, obj in objects.items():
        pos = obj['position']
        props = obj.get('properties', {})
        print(f"Object: {name}")
        print(f"  Position: ({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f})")
        print(f"  Color: {props.get('color', 'unknown')}")
        print(f"  Held: {props.get('held', False)}")
        print()


if __name__ == "__main__":
    try:
        # Test 1: Compound commands
        test_compound_commands()

        # Test 2: Object stacking
        test_stacking_sequence()

        # Test 3: Object queries
        test_object_queries()

        print("\n✅ All tests completed!")

    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
