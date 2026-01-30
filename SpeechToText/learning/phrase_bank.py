"""
Phrase Bank Manager with fuzzy matching for self-learning vocabulary system.
Handles lookup, fuzzy matching, and persistence of learned phrases.
"""
import json
import os
from typing import Optional, Dict, Tuple
from difflib import SequenceMatcher

from .config import FUZZY_MATCH_THRESHOLD

PHRASE_BANK_PATH = os.path.join(os.path.dirname(__file__), "phrase_bank.json")


class PhraseBank:
    """
    Manages learned phrases with fuzzy matching capabilities.
    Grows over time as new phrases are learned from LLM interpretations.
    """

    def __init__(self, auto_save=True):
        """
        Initialize phrase bank.

        Args:
            auto_save: Automatically save to disk when phrases are added
        """
        self.auto_save = auto_save
        self.data = self._load()

    def _load(self) -> Dict:
        """Load phrase bank from JSON file."""
        try:
            with open(PHRASE_BANK_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Warning: Phrase bank not found at {PHRASE_BANK_PATH}")
            return self._create_default()
        except json.JSONDecodeError as e:
            print(f"Error loading phrase bank: {e}")
            return self._create_default()

    def _create_default(self) -> Dict:
        """Create default phrase bank structure."""
        return {
            "phrases": {},
            "named_locations": {"home": {"x": 0.0, "y": 0.0, "z": 0.0}},
            "metadata": {
                "version": "1.0",
                "last_updated": "",
                "total_phrases_learned": 0
            }
        }

    def save(self):
        """Save phrase bank to disk."""
        try:
            with open(PHRASE_BANK_PATH, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving phrase bank: {e}")

    def exact_match(self, phrase: str) -> Optional[Dict]:
        """
        Look for exact match in phrase bank.

        Args:
            phrase: Input phrase (case-insensitive)

        Returns:
            Intent dict if found, None otherwise
        """
        phrase_lower = phrase.lower().strip()
        phrases = self.data.get("phrases", {})

        if phrase_lower in phrases:
            # Increment usage count
            phrases[phrase_lower]["usage_count"] = phrases[phrase_lower].get("usage_count", 0) + 1
            if self.auto_save:
                self.save()
            return phrases[phrase_lower]

        return None

    def fuzzy_match(self, phrase: str) -> Optional[Tuple[str, Dict, float]]:
        """
        Find best fuzzy match in phrase bank.

        Args:
            phrase: Input phrase

        Returns:
            Tuple of (matched_phrase, intent_dict, confidence) if confident match found
            None otherwise
        """
        phrase_lower = phrase.lower().strip()
        phrases = self.data.get("phrases", {})

        if not phrases:
            return None

        best_match = None
        best_ratio = 0.0
        best_phrase = None

        for known_phrase, intent_data in phrases.items():
            ratio = SequenceMatcher(None, phrase_lower, known_phrase).ratio()

            if ratio > best_ratio:
                best_ratio = ratio
                best_match = intent_data
                best_phrase = known_phrase

        # Only return if confidence exceeds threshold
        if best_ratio >= FUZZY_MATCH_THRESHOLD:
            # Increment usage count
            best_match["usage_count"] = best_match.get("usage_count", 0) + 1
            if self.auto_save:
                self.save()
            return (best_phrase, best_match, best_ratio)

        return None

    def add_phrase(self, phrase: str, intent: str, params: Dict, confidence: float = 0.95):
        """
        Add a new learned phrase to the bank.

        Args:
            phrase: Natural language phrase
            intent: Intent name (e.g., "move_relative", "move_to_previous")
            params: Intent parameters
            confidence: Confidence score from LLM (0.0-1.0)
        """
        phrase_lower = phrase.lower().strip()
        phrases = self.data.get("phrases", {})

        # Add or update phrase
        phrases[phrase_lower] = {
            "intent": intent,
            "params": params,
            "confidence": confidence,
            "usage_count": 1  # Start at 1 since we're using it now
        }

        # Update metadata
        if phrase_lower not in phrases:
            self.data["metadata"]["total_phrases_learned"] += 1

        from datetime import datetime
        self.data["metadata"]["last_updated"] = datetime.now().isoformat()

        if self.auto_save:
            self.save()

        print(f"✓ Learned new phrase: '{phrase}' → {intent}")

    def get_named_location(self, name: str) -> Optional[Dict]:
        """Get a named location's position."""
        locations = self.data.get("named_locations", {})
        return locations.get(name.lower())

    def save_named_location(self, name: str, position: Dict):
        """Save a named location."""
        locations = self.data.get("named_locations", {})
        locations[name.lower()] = position

        if self.auto_save:
            self.save()

        print(f"✓ Saved location '{name}': {position}")

    def get_location(self, name: str) -> Optional[Dict]:
        """Alias for get_named_location (for IntentExecutor compatibility)."""
        return self.get_named_location(name)

    def add_location(self, name: str, position: Dict):
        """Alias for save_named_location (for IntentExecutor compatibility)."""
        self.save_named_location(name, position)

    def is_intent_implemented(self, intent: str) -> bool:
        """Check if an intent is implemented (all standard intents are)."""
        implemented_intents = [
            "move_relative", "move_to_previous", "move_to_named",
            "save_named_location", "gripper_open", "gripper_close",
            "emergency_stop", "resume"
        ]
        return intent in implemented_intents

    def get_not_implemented_message(self, intent: str) -> str:
        """Get a user-friendly message for unimplemented intents."""
        return f"Intent '{intent}' is not yet implemented."

    def get_stats(self) -> Dict:
        """Get phrase bank statistics."""
        phrases = self.data.get("phrases", {})
        return {
            "total_phrases": len(phrases),
            "total_learned": self.data["metadata"].get("total_phrases_learned", 0),
            "named_locations": len(self.data.get("named_locations", {})),
            "most_used_phrase": self._get_most_used_phrase(),
            "last_updated": self.data["metadata"].get("last_updated", "never")
        }

    def _get_most_used_phrase(self) -> Optional[str]:
        """Find the most frequently used phrase."""
        phrases = self.data.get("phrases", {})
        if not phrases:
            return None

        most_used = max(
            phrases.items(),
            key=lambda x: x[1].get("usage_count", 0)
        )

        if most_used[1].get("usage_count", 0) > 0:
            return most_used[0]

        return None


# Singleton instance
_phrase_bank_instance = None

def get_phrase_bank() -> PhraseBank:
    """Get the singleton PhraseBank instance."""
    global _phrase_bank_instance
    if _phrase_bank_instance is None:
        _phrase_bank_instance = PhraseBank()
    return _phrase_bank_instance


def test_phrase_bank():
    """Test phrase bank functionality."""
    print("\n=== Phrase Bank Test ===\n")

    bank = PhraseBank(auto_save=False)

    # Test exact match
    print("1. Testing exact match:")
    result = bank.exact_match("go back")
    if result:
        print(f"   ✓ Found: {result}")
    else:
        print("   ✗ Not found")

    # Test fuzzy match
    print("\n2. Testing fuzzy match:")
    fuzzy = bank.fuzzy_match("go bak")  # Typo
    if fuzzy:
        phrase, intent, confidence = fuzzy
        print(f"   ✓ Matched '{phrase}' with confidence {confidence:.2f}")
        print(f"     Intent: {intent}")
    else:
        print("   ✗ No confident match")

    # Test add phrase
    print("\n3. Testing add phrase:")
    bank.add_phrase(
        "put it back where it was",
        "move_to_previous",
        {},
        confidence=0.95
    )

    # Test stats
    print("\n4. Phrase bank stats:")
    stats = bank.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


if __name__ == "__main__":
    test_phrase_bank()
