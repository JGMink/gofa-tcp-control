"""
Phrase Bank - Manages vocabulary mapping phrases to intents.
Supports exact matching, fuzzy matching, and runtime learning.
"""

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Tuple, Dict, Any, List

from .config import (
    PHRASE_BANK_PATH,
    FUZZY_MATCH_THRESHOLD,
    FUZZY_CONFIRM_THRESHOLD,
    ENABLE_FUZZY_MATCHING,
    VERBOSE_LOGGING
)


class PhraseBank:
    def __init__(self, path: str = None):
        self.path = path or PHRASE_BANK_PATH
        self.data = self._load()
        
    def _load(self) -> dict:
        """Load phrase bank from JSON file."""
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[PhraseBank] No phrase bank found at {self.path}, starting fresh")
            return {
                "meta": {"version": 1, "last_updated": datetime.now().isoformat()},
                "intents": {},
                "phrases": {},
                "locations": {}
            }
        except json.JSONDecodeError as e:
            print(f"[PhraseBank] Error loading phrase bank: {e}")
            return {"meta": {}, "intents": {}, "phrases": {}, "locations": {}}
    
    def save(self):
        """Save phrase bank to JSON file."""
        self.data["meta"]["last_updated"] = datetime.now().isoformat()
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2)
        if VERBOSE_LOGGING:
            print(f"[PhraseBank] Saved to {self.path}")
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching."""
        text = text.lower().strip()
        # Remove punctuation except hyphens
        text = re.sub(r'[^\w\s\-]', '', text)
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        return text
    
    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Calculate similarity ratio between two strings."""
        return SequenceMatcher(None, a, b).ratio()
    
    def extract_distance(self, text: str) -> Tuple[str, Optional[float]]:
        """
        Extract distance from text if present.
        Returns (text_without_distance, distance_value or None)
        """
        text_lower = text.lower()
        
        # Match patterns like "5 centimeters", "10 cm", "3.5 millimeters"
        pattern = r'(\d+(?:\.\d+)?)\s*(?:centimeters?|cm|millimeters?|mm)?'
        match = re.search(pattern, text_lower)
        
        if match:
            distance = float(match.group(1))
            # Convert mm to cm
            if 'millimeter' in text_lower or 'mm' in text_lower:
                distance = distance / 10.0
            # Remove the distance part from text for phrase matching
            text_without_distance = re.sub(pattern, '', text_lower).strip()
            text_without_distance = re.sub(r'\s+', ' ', text_without_distance)
            return text_without_distance, distance
        
        return text_lower, None
    
    def lookup(self, utterance: str) -> Tuple[Optional[Dict[str, Any]], float, bool]:
        """
        Look up an utterance in the phrase bank.
        
        Returns:
            (match_result, confidence, needs_confirmation)
            - match_result: {intent, parameters, source} or None
            - confidence: 0.0 to 1.0
            - needs_confirmation: True if we should ask user to confirm
        """
        # Extract distance first (so "move right 5 cm" matches "move right")
        text_for_matching, extracted_distance = self.extract_distance(utterance)
        normalized = self.normalize(text_for_matching)
        
        if VERBOSE_LOGGING:
            print(f"[PhraseBank] Looking up: '{normalized}' (distance: {extracted_distance})")
        
        # 1. Try exact match first
        if normalized in self.data["phrases"]:
            result = self.data["phrases"][normalized].copy()
            # Merge extracted distance if applicable
            if extracted_distance is not None and "direction" in result.get("parameters", {}):
                result["parameters"]["distance"] = extracted_distance
            if VERBOSE_LOGGING:
                print(f"[PhraseBank] Exact match: {result['intent']}")
            return result, 1.0, False
        
        # 2. Try fuzzy matching
        if ENABLE_FUZZY_MATCHING:
            best_match = None
            best_score = 0.0
            best_phrase = None
            
            for phrase, data in self.data["phrases"].items():
                score = self.similarity(normalized, phrase)
                if score > best_score:
                    best_score = score
                    best_match = data
                    best_phrase = phrase
            
            if best_score >= FUZZY_MATCH_THRESHOLD:
                result = best_match.copy()
                if extracted_distance is not None and "direction" in result.get("parameters", {}):
                    result["parameters"]["distance"] = extracted_distance
                if VERBOSE_LOGGING:
                    print(f"[PhraseBank] Fuzzy match: '{best_phrase}' ({best_score:.2f})")
                return result, best_score, False
            
            elif best_score >= FUZZY_CONFIRM_THRESHOLD:
                # Found something but not confident enough
                result = best_match.copy()
                if extracted_distance is not None and "direction" in result.get("parameters", {}):
                    result["parameters"]["distance"] = extracted_distance
                if VERBOSE_LOGGING:
                    print(f"[PhraseBank] Low confidence match: '{best_phrase}' ({best_score:.2f}) - needs confirmation")
                return result, best_score, True
        
        # 3. No match found
        if VERBOSE_LOGGING:
            print(f"[PhraseBank] No match found for: '{normalized}'")
        return None, 0.0, False
    
    def add_phrase(self, phrase: str, intent: str, parameters: dict = None, 
                   source: str = "learned", confirmed: bool = True) -> bool:
        """
        Add a new phrase to the bank.
        
        Returns True if added, False if phrase already exists.
        """
        normalized = self.normalize(phrase)
        
        if normalized in self.data["phrases"]:
            if VERBOSE_LOGGING:
                print(f"[PhraseBank] Phrase already exists: '{normalized}'")
            return False
        
        self.data["phrases"][normalized] = {
            "intent": intent,
            "parameters": parameters or {},
            "source": source,
            "learned_at": datetime.now().isoformat(),
            "confirmed": confirmed
        }
        
        self.save()
        print(f"[PhraseBank] ✅ Learned: '{normalized}' → {intent}")
        return True
    
    def add_location(self, name: str, position: dict) -> bool:
        """Add or update a named location."""
        name_lower = name.lower()
        self.data["locations"][name_lower] = position
        self.save()
        print(f"[PhraseBank] 📍 Saved location '{name_lower}': {position}")
        return True
    
    def get_location(self, name: str) -> Optional[dict]:
        """Get a named location's position."""
        return self.data["locations"].get(name.lower())
    
    def get_intent_info(self, intent_name: str) -> Optional[dict]:
        """Get information about an intent."""
        return self.data["intents"].get(intent_name)
    
    def is_intent_implemented(self, intent_name: str) -> bool:
        """Check if an intent is implemented."""
        intent_info = self.get_intent_info(intent_name)
        if intent_info is None:
            return False
        return intent_info.get("implemented", True)
    
    def get_not_implemented_message(self, intent_name: str) -> str:
        """Get the 'not implemented' message for an intent."""
        intent_info = self.get_intent_info(intent_name)
        if intent_info:
            return intent_info.get("not_implemented_message", 
                                   f"The '{intent_name}' capability isn't available yet.")
        return f"I don't know how to do '{intent_name}' yet."
    
    def get_all_intents(self) -> Dict[str, dict]:
        """Get all defined intents."""
        return self.data["intents"]
    
    def get_all_phrases(self) -> Dict[str, dict]:
        """Get all phrases."""
        return self.data["phrases"]
    
    def get_sample_phrases(self, n: int = 10) -> List[Tuple[str, str]]:
        """Get sample phrases for LLM context."""
        samples = []
        for phrase, data in list(self.data["phrases"].items())[:n]:
            samples.append((phrase, data["intent"]))
        return samples
    
    def get_all_locations(self) -> Dict[str, dict]:
        """Get all named locations."""
        return self.data["locations"]


# Singleton instance
_phrase_bank_instance = None

def get_phrase_bank() -> PhraseBank:
    """Get the singleton PhraseBank instance."""
    global _phrase_bank_instance
    if _phrase_bank_instance is None:
        _phrase_bank_instance = PhraseBank()
    return _phrase_bank_instance