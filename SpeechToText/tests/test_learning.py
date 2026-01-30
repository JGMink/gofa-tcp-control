#!/usr/bin/env python3
"""
Test script for the self-learning command system.
Tests without requiring microphone or Azure Speech.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from learning.command_processor import CommandProcessor
from learning.intent_executor import IntentExecutor


def test_without_llm():
    """Test the system with phrase bank only (no LLM calls)."""
    print("\n" + "="*60)
    print("TEST 1: Phrase Bank Only (No LLM)")
    print("="*60 + "\n")

    # Initialize executor and processor
    executor = IntentExecutor(command_queue_file="test_commands.json")
    executor.set_position({"x": 0.0, "y": 0.0, "z": 0.0})
    processor = CommandProcessor(executor, enable_llm=False)

    # Test commands (should all hit exact or fuzzy matches)
    test_commands = [
        "move right 5 centimeters",  # Exact match
        "go back",                   # Exact match
        "go home",                   # Exact match
        "stop",                      # Exact match
        "go bak",                    # Fuzzy match (typo)
        "move up",                   # Exact match
        "stahp",                     # Fuzzy match if close enough
    ]

    print("Testing commands:\n")
    for cmd in test_commands:
        processor.process_command(cmd)
        print()

    # Print statistics
    processor.print_stats()


def test_with_llm():
    """Test the system with LLM enabled."""
    print("\n" + "="*60)
    print("TEST 2: Full System with LLM Fallback")
    print("="*60 + "\n")

    # Check if API key is set
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  ANTHROPIC_API_KEY not set - skipping LLM test")
        print("To enable LLM testing, add ANTHROPIC_API_KEY to .env file")
        return

    # Initialize executor and processor
    executor = IntentExecutor(command_queue_file="test_commands.json")
    executor.set_position({"x": 0.0, "y": 0.0, "z": 0.0})
    processor = CommandProcessor(executor, enable_llm=True)

    # Test commands (mix of known and unknown phrases)
    test_commands = [
        # Known phrases (should hit phrase bank)
        "move right 5 centimeters",
        "go back",

        # Unknown phrases (should trigger LLM and learn)
        "shift a bit to the left",
        "put it back where it was",
        "return to home position",

        # Now test if learned
        "put it back where it was",  # Should now be exact match
    ]

    print("Testing commands:\n")
    for i, cmd in enumerate(test_commands, 1):
        print(f"[{i}/{len(test_commands)}]")
        processor.process_command(cmd)
        print()

    # Print statistics
    processor.print_stats()

    print("\nNote: Check phrase_bank.json to see newly learned phrases!")


def test_intent_executor():
    """Test the intent executor directly."""
    print("\n" + "="*60)
    print("TEST 3: Intent Executor Direct Test")
    print("="*60 + "\n")

    executor = IntentExecutor(command_queue_file="test_commands.json")
    executor.set_position({"x": 0.0, "y": 0.0, "z": 0.0})

    print("Testing all intent types:\n")

    # Test move_relative
    print("1. move_relative (right 10cm):")
    executor.execute_intent("move_relative", {
        "direction": "right",
        "distance": 10.0,
        "unit": "cm"
    })

    # Test move_relative (up)
    print("\n2. move_relative (up 5cm):")
    executor.execute_intent("move_relative", {
        "direction": "up",
        "distance": 5.0,
        "unit": "cm"
    })

    # Test move_to_previous
    print("\n3. move_to_previous:")
    executor.execute_intent("move_to_previous", {})

    # Test save_named_location
    print("\n4. save_named_location (pickup):")
    executor.execute_intent("save_named_location", {
        "location": "pickup"
    })

    # Move somewhere else
    print("\n5. move_relative (left 20cm):")
    executor.execute_intent("move_relative", {
        "direction": "left",
        "distance": 20.0,
        "unit": "cm"
    })

    # Test move_to_named
    print("\n6. move_to_named (pickup):")
    executor.execute_intent("move_to_named", {
        "location": "pickup"
    })

    # Test gripper commands
    print("\n7. gripper_open:")
    executor.execute_intent("gripper_open", {})

    print("\n8. gripper_close:")
    executor.execute_intent("gripper_close", {})

    # Test emergency_stop
    print("\n9. emergency_stop:")
    executor.execute_intent("emergency_stop", {})

    print(f"\nFinal position: {executor.get_position()}")
    print(f"Position history length: {len(executor.position_history)}")


def test_phrase_bank():
    """Test phrase bank functionality."""
    print("\n" + "="*60)
    print("TEST 4: Phrase Bank Operations")
    print("="*60 + "\n")

    from learning.phrase_bank import PhraseBank

    bank = PhraseBank(auto_save=False)

    # Test exact match
    print("1. Exact match test:")
    result = bank.exact_match("go back")
    if result:
        print(f"   ✓ Found: {result['intent']}")
    else:
        print("   ✗ Not found")

    # Test fuzzy match
    print("\n2. Fuzzy match test (typo: 'go bak'):")
    fuzzy = bank.fuzzy_match("go bak")
    if fuzzy:
        phrase, intent, confidence = fuzzy
        print(f"   ✓ Matched '{phrase}' with confidence {confidence:.2f}")
        print(f"   Intent: {intent['intent']}")
    else:
        print("   ✗ No confident match")

    # Test add phrase
    print("\n3. Learning new phrase:")
    bank.add_phrase(
        "shift a bit to the right",
        "move_relative",
        {"direction": "right", "distance": 0.5, "unit": "cm"},
        confidence=0.95
    )

    # Test stats
    print("\n4. Phrase bank stats:")
    stats = bank.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


def interactive_test():
    """Interactive testing mode."""
    print("\n" + "="*60)
    print("INTERACTIVE TEST MODE")
    print("="*60 + "\n")

    # Check for API key
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    enable_llm = bool(api_key)

    if not enable_llm:
        print("⚠️  ANTHROPIC_API_KEY not set - LLM disabled")
        print("Only phrase bank matching will work\n")

    # Initialize
    executor = IntentExecutor(command_queue_file="test_commands.json")
    executor.set_position({"x": 0.0, "y": 0.0, "z": 0.0})
    processor = CommandProcessor(executor, enable_llm=enable_llm)

    print("Enter commands to test (or 'quit' to exit):")
    print("Examples: 'move right 5 cm', 'go back', 'shift left a bit'\n")

    while True:
        try:
            cmd = input("> ").strip()

            if cmd.lower() in ['quit', 'exit', 'q']:
                break

            if not cmd:
                continue

            processor.process_command(cmd)
            print()

        except KeyboardInterrupt:
            print("\n")
            break

    # Print final stats
    processor.print_stats()


def main():
    """Run all tests."""
    if len(sys.argv) > 1:
        if sys.argv[1] == "--interactive":
            interactive_test()
            return
        elif sys.argv[1] == "--llm":
            test_with_llm()
            return
        elif sys.argv[1] == "--executor":
            test_intent_executor()
            return
        elif sys.argv[1] == "--phrase-bank":
            test_phrase_bank()
            return

    # Run all automated tests
    print("\nRunning all automated tests...\n")

    test_phrase_bank()
    input("\nPress Enter to continue...")

    test_intent_executor()
    input("\nPress Enter to continue...")

    test_without_llm()
    input("\nPress Enter to continue...")

    # Ask before running LLM test
    print("\n" + "="*60)
    response = input("Run LLM test? This will use API credits (y/n): ").strip().lower()
    if response in ['y', 'yes']:
        test_with_llm()

    print("\n" + "="*60)
    print("All tests complete!")
    print("="*60)
    print("\nUsage:")
    print("  python tests/test_learning.py                # Run all tests")
    print("  python tests/test_learning.py --interactive  # Interactive mode")
    print("  python tests/test_learning.py --llm          # LLM test only")
    print("  python tests/test_learning.py --executor     # Executor test only")
    print("  python tests/test_learning.py --phrase-bank  # Phrase bank test only")


if __name__ == "__main__":
    main()
