"""
Command Processor - Orchestrates the learning system flow.
Phrase Bank (instant) → Fuzzy Match → LLM (fallback) → Execute + Learn
"""
import time
from typing import Dict, Optional

from .phrase_bank import PhraseBank
from .llm_interpreter import LLMInterpreter
from .config import LLM_CONFIDENCE_THRESHOLD


class CommandProcessor:
    """
    Orchestrates the three-tier command interpretation system:
    1. Exact phrase bank match (instant)
    2. Fuzzy phrase bank match (instant, if confident)
    3. LLM interpretation (1-2s, learns new phrases)
    """

    def __init__(self, intent_executor, enable_llm=True):
        """
        Initialize command processor.

        Args:
            intent_executor: IntentExecutor instance for executing commands
            enable_llm: Whether to use LLM fallback (disable for testing)
        """
        self.executor = intent_executor
        self.phrase_bank = PhraseBank(auto_save=True)
        self.enable_llm = enable_llm

        self.llm_interpreter = None
        if enable_llm:
            try:
                self.llm_interpreter = LLMInterpreter()
                print("✓ LLM fallback enabled")
            except Exception as e:
                print(f"⚠️  LLM fallback disabled: {e}")
                self.enable_llm = False

        # Statistics
        self.stats = {
            "total_commands": 0,
            "exact_matches": 0,
            "fuzzy_matches": 0,
            "llm_interpretations": 0,
            "phrases_learned": 0,
            "failed_parses": 0
        }

    def process_command(self, voice_command: str) -> bool:
        """
        Process a voice command through the three-tier system.

        Args:
            voice_command: Natural language command from speech recognition

        Returns:
            True if command was successfully executed, False otherwise
        """
        self.stats["total_commands"] += 1

        print(f"\n🎤 Processing: '{voice_command}'")

        # Tier 1: Exact match
        result = self.phrase_bank.exact_match(voice_command)
        if result:
            print(f"✓ Exact match → {result['intent']}")
            self.stats["exact_matches"] += 1
            return self._execute_intent(result)

        # Tier 2: Fuzzy match
        fuzzy_result = self.phrase_bank.fuzzy_match(voice_command)
        if fuzzy_result:
            matched_phrase, result, confidence = fuzzy_result
            print(f"✓ Fuzzy match ({confidence:.2f}) → {result['intent']}")
            print(f"  Matched: '{matched_phrase}'")
            self.stats["fuzzy_matches"] += 1
            return self._execute_intent(result)

        # Tier 3: LLM interpretation
        if not self.enable_llm or not self.llm_interpreter:
            print("✗ No match and LLM disabled")
            self.stats["failed_parses"] += 1
            return False

        print("🤖 Querying LLM...")
        start_time = time.time()

        llm_result = self.llm_interpreter.interpret_command(voice_command)
        elapsed = time.time() - start_time

        if not llm_result:
            print(f"✗ LLM failed to interpret ({elapsed:.2f}s)")
            self.stats["failed_parses"] += 1
            return False

        print(f"✓ LLM interpreted ({elapsed:.2f}s) → {llm_result['intent']}")
        print(f"  Confidence: {llm_result['confidence']:.2f}")
        self.stats["llm_interpretations"] += 1

        # Execute the command
        success = self._execute_intent(llm_result)

        # Learn if confident and successful
        if success and self.llm_interpreter.is_confident(llm_result):
            self._learn_phrase(voice_command, llm_result)

        return success

    def _execute_intent(self, result: Dict) -> bool:
        """Execute an intent result."""
        intent = result["intent"]
        params = result["params"]

        return self.executor.execute_intent(intent, params)

    def _learn_phrase(self, phrase: str, llm_result: Dict):
        """Add a new phrase to the phrase bank."""
        self.phrase_bank.add_phrase(
            phrase=phrase,
            intent=llm_result["intent"],
            params=llm_result["params"],
            confidence=llm_result["confidence"]
        )
        self.stats["phrases_learned"] += 1

        print(f"📚 Learned new phrase (total learned: {self.stats['phrases_learned']})")

    def get_stats(self) -> Dict:
        """Get processing statistics."""
        stats = self.stats.copy()

        # Add derived metrics
        if stats["total_commands"] > 0:
            stats["exact_match_rate"] = stats["exact_matches"] / stats["total_commands"]
            stats["fuzzy_match_rate"] = stats["fuzzy_matches"] / stats["total_commands"]
            stats["llm_usage_rate"] = stats["llm_interpretations"] / stats["total_commands"]
            stats["success_rate"] = 1.0 - (stats["failed_parses"] / stats["total_commands"])

        # Add phrase bank stats
        stats["phrase_bank"] = self.phrase_bank.get_stats()

        return stats

    def print_stats(self):
        """Print processing statistics."""
        stats = self.get_stats()

        print("\n" + "="*60)
        print("COMMAND PROCESSING STATISTICS")
        print("="*60)

        print(f"\nTotal Commands: {stats['total_commands']}")
        print(f"  Exact Matches: {stats['exact_matches']} ({stats.get('exact_match_rate', 0)*100:.1f}%)")
        print(f"  Fuzzy Matches: {stats['fuzzy_matches']} ({stats.get('fuzzy_match_rate', 0)*100:.1f}%)")
        print(f"  LLM Calls: {stats['llm_interpretations']} ({stats.get('llm_usage_rate', 0)*100:.1f}%)")
        print(f"  Failed: {stats['failed_parses']}")

        print(f"\nLearning:")
        print(f"  Phrases Learned This Session: {stats['phrases_learned']}")

        print(f"\nPhrase Bank:")
        pb_stats = stats['phrase_bank']
        print(f"  Total Phrases: {pb_stats['total_phrases']}")
        print(f"  Named Locations: {pb_stats['named_locations']}")
        if pb_stats['most_used_phrase']:
            print(f"  Most Used: '{pb_stats['most_used_phrase']}'")

        print(f"\nSuccess Rate: {stats.get('success_rate', 0)*100:.1f}%")
        print("="*60 + "\n")


def test_command_processor():
    """Test command processor with mock executor."""
    print("\n=== Command Processor Test ===\n")

    # Mock executor
    class MockExecutor:
        def __init__(self):
            self.current_position = {"x": 0.0, "y": 0.0, "z": 0.0}

        def execute_intent(self, intent, params):
            print(f"  [MockExecutor] Executing {intent} with {params}")
            return True

        def get_position(self):
            return self.current_position.copy()

    executor = MockExecutor()
    processor = CommandProcessor(executor, enable_llm=False)  # Disable LLM for quick test

    # Test commands
    test_commands = [
        "go back",  # Should hit exact match
        "go bak",   # Should hit fuzzy match
        "move right 5 centimeters",  # Should hit exact match
        "stop",  # Should hit exact match
    ]

    for cmd in test_commands:
        processor.process_command(cmd)

    # Print stats
    processor.print_stats()


if __name__ == "__main__":
    test_command_processor()
