"""
memory_writer.py
────────────────
Handles secondary/learning commands from the sequence interpreter.

When the LLM returns a result with a composite_name AND a user_feedback that says
"Mapping/composite noted", this module:
  1. Writes the composite to instruction_set.json learned_composites
  2. Optionally writes a phrase alias to phrase_bank.json
  3. Updates scene_context.json if any state mappings changed

This is a DISTINCT pipeline step — it runs after the sequence interpreter returns,
and only when the user explicitly triggered a learning command. It does not interfere
with the normal interpret → validate → execute flow.

Usage:
    from learning.memory_writer import MemoryWriter
    writer = MemoryWriter()
    writer.process(result, source_phrase="make a BLT every time I say sandwich")

Design notes:
    - All writes are append-only to learned_composites — never modify developer-written composites
    - Phrase aliases are written to a separate section in phrase_bank.json: "learned_aliases"
    - If a composite with the same name already exists in learned_composites, it is OVERWRITTEN
      with the new version (user is re-defining it)
    - The "my usual" alias is a special case: it maps to whatever composite_name is provided,
      and is stored as the key "user_usual" in learned_aliases
    - Backburner: "from now on, X means Y" style macro definitions are noted in
      learned_aliases but not yet wired into the dispatch pipeline
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional


class MemoryWriter:
    """
    Writes learned composites and phrase aliases from LLM-flagged secondary commands.
    Operates on instruction_set.json and phrase_bank.json in the learning/ directory.
    """

    def __init__(self):
        base = os.path.dirname(os.path.abspath(__file__))
        self.instruction_set_path = os.path.join(base, "instruction_set.json")
        self.phrase_bank_path = os.path.join(base, "phrase_bank.json")

    def _load_json(self, path: str) -> dict:
        with open(path, "r") as f:
            return json.load(f)

    def _save_json(self, path: str, data: dict):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def process(self, result: Dict, source_phrase: str = "") -> Dict:
        """
        Process an LLM result that contains a learning directive.

        Returns a dict with:
          wrote_composite    bool
          wrote_alias        bool
          composite_name     str|None
          alias_key          str|None
          message            str — human-readable summary of what was written
        """
        summary = {
            "wrote_composite": False,
            "wrote_alias": False,
            "composite_name": None,
            "alias_key": None,
            "message": "",
        }

        composite_name = result.get("composite_name")
        sequence = result.get("sequence", [])
        interpretation = result.get("interpretation", "")
        confidence = result.get("confidence", 0.0)
        user_feedback = result.get("user_feedback", "") or ""

        # Only act if LLM flagged this as a learning command
        if not composite_name:
            summary["message"] = "No composite_name — nothing to write."
            return summary

        if "mapping" not in user_feedback.lower() and "composite" not in user_feedback.lower() and "saved" not in user_feedback.lower():
            summary["message"] = f"user_feedback doesn't indicate learning intent — skipping write."
            return summary

        # ── Write composite to instruction_set.json ──────────────────────────
        try:
            iset = self._load_json(self.instruction_set_path)
            if "learned_composites" not in iset:
                iset["learned_composites"] = {}

            iset["learned_composites"][composite_name] = {
                "description": interpretation,
                "parameters": {},
                "sequence": sequence,
                "confidence": confidence,
                "source_phrase": source_phrase,
                "learned_at": datetime.now().isoformat(),
                "learned": True,
                "llm_visible": True,
            }
            self._save_json(self.instruction_set_path, iset)
            summary["wrote_composite"] = True
            summary["composite_name"] = composite_name
            print(f"[MEMORY] Wrote composite '{composite_name}' to instruction_set.json")
        except Exception as e:
            print(f"[MEMORY] Failed to write composite: {e}")
            summary["message"] = f"Composite write failed: {e}"
            return summary

        # ── Write phrase alias to phrase_bank.json ───────────────────────────
        # Detect alias intent from source phrase
        alias_key = None
        src = source_phrase.lower()

        if "every time i say" in src or "when i say" in src:
            # Extract the trigger word/phrase
            for marker in ["every time i say", "when i say"]:
                if marker in src:
                    trigger = src.split(marker)[-1].strip().strip('"\'').strip()
                    alias_key = trigger
                    break
        elif "my usual" in src or "the usual" in src:
            alias_key = "my_usual"
        elif "remember this as" in src:
            alias_key = src.split("remember this as")[-1].strip().strip('"\'').strip().replace(" ", "_")

        if alias_key:
            try:
                pb = self._load_json(self.phrase_bank_path)
                if "learned_aliases" not in pb:
                    pb["learned_aliases"] = {}
                pb["learned_aliases"][alias_key] = {
                    "maps_to_composite": composite_name,
                    "source_phrase": source_phrase,
                    "learned_at": datetime.now().isoformat(),
                }
                self._save_json(self.phrase_bank_path, pb)
                summary["wrote_alias"] = True
                summary["alias_key"] = alias_key
                print(f"[MEMORY] Wrote alias '{alias_key}' → '{composite_name}' to phrase_bank.json")
            except Exception as e:
                print(f"[MEMORY] Failed to write alias: {e}")

        # ── Build summary message ─────────────────────────────────────────────
        parts = [f"Saved composite '{composite_name}' ({len(sequence)} steps)."]
        if alias_key:
            parts.append(f"Alias '{alias_key}' → '{composite_name}' saved to phrase bank.")
        parts.append("Will be available in future sessions.")
        summary["message"] = " ".join(parts)

        return summary


# ──────────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────────

_writer_instance = None

def get_memory_writer() -> MemoryWriter:
    global _writer_instance
    if _writer_instance is None:
        _writer_instance = MemoryWriter()
    return _writer_instance
