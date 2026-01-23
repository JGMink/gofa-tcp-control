"""
Test script for the learning system.
Run this to verify phrase bank, LLM interpretation, and command execution
without needing the microphone.

Run from SpeechToText folder:
    python tests/test_learning.py
"""

import sys
import os

# Add parent directory (SpeechToText) to path so we can import learning module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning import get_processor, get_phrase_bank, get_executor


def print_state():
    """Print current system state."""
    executor = get_executor()
    state = executor.get_state()
    print(f"  Position: {state['current_position']}")
    print(f"  Previous: {state['previous_position']}")
    print(f"  Gripper: {state['gripper_state']}")
    print()


def test_phrase(phrase: str):
    """Test a single phrase."""
    print(f"\n{'='*50}")
    print(f"Testing: '{phrase}'")
    print('='*50)
    
    processor = get_processor()
    result = processor.process(phrase)
    
    print(f"\nResult:")
    print(f"  Success: {result['success']}")
    print(f"  Intent: {result.get('intent')}")
    print(f"  Message: {result['message']}")
    if result.get('learned'):
        print(f"  📚 LEARNED NEW PHRASE!")
    if result.get('needs_confirmation'):
        print(f"  ❓ Confirmation needed: {result['confirmation_prompt']}")
    if result.get('command'):
        print(f"  Command: {result['command']}")
    
    print(f"\nState after:")
    print_state()


def interactive_mode():
    """Interactive testing mode."""
    print("\n" + "="*60)
    print("Learning System Interactive Test")
    print("="*60)
    print("\nType phrases to test, or:")
    print("  'state' - show current state")
    print("  'phrases' - list known phrases")
    print("  'intents' - list known intents")
    print("  'locations' - list known locations")
    print("  'quit' - exit")
    print()
    
    processor = get_processor()
    phrase_bank = get_phrase_bank()
    executor = get_executor()
    
    print("Initial state:")
    print_state()
    
    while True:
        try:
            user_input = input("\n> ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == 'quit':
                print("Goodbye!")
                break
            
            elif user_input.lower() == 'state':
                print_state()
            
            elif user_input.lower() == 'phrases':
                phrases = phrase_bank.get_all_phrases()
                print(f"\nKnown phrases ({len(phrases)}):")
                for phrase, data in sorted(phrases.items()):
                    source = data.get('source', 'unknown')
                    marker = '📚' if source != 'hardcoded' else ''
                    print(f"  '{phrase}' → {data['intent']} {marker}")
            
            elif user_input.lower() == 'intents':
                intents = phrase_bank.get_all_intents()
                print(f"\nKnown intents ({len(intents)}):")
                for name, data in intents.items():
                    impl = "✅" if data.get('implemented', True) else "⏳"
                    print(f"  {impl} {name}: {data.get('description', '')}")
            
            elif user_input.lower() == 'locations':
                locations = phrase_bank.get_all_locations()
                print(f"\nKnown locations ({len(locations)}):")
                for name, pos in locations.items():
                    print(f"  '{name}': {pos}")
            
            else:
                # Process as a command
                result = processor.process(user_input)
                
                if result['success']:
                    print(f"✅ {result['message']}")
                    if result.get('learned'):
                        print("📚 Learned this phrase!")
                elif result.get('needs_confirmation'):
                    print(f"❓ {result['confirmation_prompt']}")
                else:
                    print(f"❌ {result['message']}")
                
                print(f"\nCurrent position: {executor.current_position}")
                
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


def run_test_suite():
    """Run a suite of test phrases."""
    test_phrases = [
        # Known phrases (should match instantly)
        "move right",
        "move right 5 centimeters",
        "go up",
        "go left 10 centimeters",
        
        # Should trigger go back
        "go back",
        
        # Named location
        "go home",
        
        # These might need LLM interpretation (if not in phrase bank)
        "move to the right a bit",
        "go back to where you were",
        "return to the last position",
        
        # Gripper (not implemented yet, should say so)
        "grab it",
        "let go",
        
        # Unknown (should fall back to LLM)
        "scoot over to the left",
    ]
    
    print("\n" + "="*60)
    print("Running Test Suite")
    print("="*60)
    
    for phrase in test_phrases:
        test_phrase(phrase)
        input("\nPress Enter for next test...")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_test_suite()
    else:
        interactive_mode()