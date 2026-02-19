"""
Sequence Interpreter - LLM-based natural language to instruction sequence compiler.

Uses Claude to interpret voice commands and generate instruction sequences
that can be compiled and executed by the InstructionCompiler.

Architecture: three-pass pipeline
  Pass 1 — Generation (temperature 0, or 1.0 for creative commands)
  Pass 2 — Validation (check instruction names, params, fix or remove bad steps)
  Pass 3 — Regeneration (if validator found issues, feed them back to generator for one retry)

Result dict always contains:
  interpretation      str   — what the LLM understood
  sequence            list  — list of instruction steps (may be empty)
  composite_name      str|null
  confidence          float
  validated           bool
  validation_issues   list
  user_feedback       str|null — message to show/speak to user for impossible commands
  is_creative         bool — True if this was a creative/open-ended command
  creative_reasoning  str|null — LLM's reasoning for creative choices (creative only)
  pass1_sequence      list — raw Pass 1 sequence before validation (for display)
  raw_response        str|null — raw LLM text if JSON parse failed
"""

import json
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_CONFIDENCE_THRESHOLD
from .instruction_compiler import get_compiler, get_executor, InstructionCompiler


# ── Creative command detection ─────────────────────────────────────────────────
_CREATIVE_PATTERNS = [
    r"\bimpress\b", r"\bgo wild\b", r"\bsurprise\b", r"\bcreative\b",
    r"\bbeautiful\b", r"\bwork of art\b", r"\bwork of art\b",
    r"\bbuild a tower\b", r"\bbest .* can\b", r"\bsomething delicious\b",
    r"\bsomething interesting\b", r"\bmake it interesting\b",
    r"\bsomething beautiful\b", r"\bmake me something\b",
    r"\bdo something\b", r"\bgo crazy\b", r"\bhave fun\b",
    r"\bfancy\b", r"\belaborate\b",
]

def _is_creative(command: str) -> bool:
    cmd = command.lower()
    return any(re.search(p, cmd) for p in _CREATIVE_PATTERNS)


# Axis pairs that are logically contradictory — never assign these together.
# palindrome requires a symmetric structure; random_ordered/full_set/category_grouped
# all imply asymmetric orderings that can't be palindromic.
_INCOMPATIBLE_PAIRS = {
    "palindrome": {"random_ordered", "category_grouped", "full_set"},
    "inverted":   {"all_one"},          # inverting one repeated ingredient = same thing
    "single_short": {"all_one"},         # 2-3 layers of one item is fine actually — remove this if desired
}

def _compatible_axes(axis1: str, axis2: str) -> bool:
    blocked = _INCOMPATIBLE_PAIRS.get(axis1, set())
    return axis2 not in blocked


def _collapse_unescaped_newlines(text: str) -> str:
    """
    Fix JSON where the LLM wrote literal newlines inside string values.
    Walks character by character; inside a JSON string, replaces bare \n with \\n.
    Handles escaped quotes (\") correctly.
    """
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string:
            # Escaped character — pass both chars through unchanged
            result.append(ch)
            i += 1
            if i < len(text):
                result.append(text[i])
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if ch == '\n' and in_string:
            result.append('\\n')
            i += 1
            continue
        if ch == '\r' and in_string:
            i += 1
            continue
        result.append(ch)
        i += 1
    return ''.join(result)


class SequenceInterpreter:
    """
    Interprets natural language commands into instruction sequences.
    Can learn new composite instructions from successful interpretations.
    """

    def __init__(self, compiler: InstructionCompiler = None):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed")
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = ANTHROPIC_MODEL
        self.compiler = compiler or get_compiler()

    # ══════════════════════════════════════════════════════════════════════════
    # PROMPT BUILDERS
    # ══════════════════════════════════════════════════════════════════════════

    def _build_prompt(self, voice_command: str, is_creative: bool = False,
                      correction_hints: List[str] = None) -> str:
        """
        Build the sequence generation prompt.
        - is_creative: tells the LLM it has full creative latitude
        - correction_hints: Pass 3 — list of issues from validator to fix
        """
        context = self.compiler.get_llm_context()

        correction_section = ""
        if correction_hints:
            hints_str = "\n".join(f"  - {h}" for h in correction_hints)
            correction_section = f"""
━━━ CORRECTION REQUIRED (Pass 3) ━━━
Your previous response had these problems that the validator caught:
{hints_str}

Please regenerate a corrected sequence that fixes ALL of these issues.
Use ONLY valid instruction names from the list above. Do not invent new ones.

"""

        creative_section = ""
        if is_creative:
            import random as _r
            _axis1_options = [
                ("single_tall",       "one zone only — stack as many layers as possible, no cap"),
                ("single_short",      "one zone only — exactly 2 or 3 layers, stop there, negative space is the point"),
                ("three_zone_split",  "use all three zones: set_active_zone(assembly_left), build, set_active_zone(assembly_fixture), build, set_active_zone(assembly_right), build"),
                ("two_zone_contrast", "use exactly two zones with opposing ingredient sets — set_active_zone to switch between them"),
                ("palindrome",        "one zone — the ingredient sequence must read IDENTICALLY forwards and backwards. Write it out letter by letter to verify before finalising. e.g. bread,meat,cheese,meat,bread or lettuce,tomato,lettuce"),
                ("inverted",          "one zone — place ingredients in REVERSE of conventional sandwich order. Normally: bread,meat,cheese,veg,bread. Inverted: lettuce,tomato,cheese,meat,bread. Top ingredient first, bread absolutely last"),
            ]
            _axis2_options = [
                ("all_one",          "choose exactly ONE ingredient and repeat it 4–6 times. Use nothing else."),
                ("category_grouped", "group by food category: all proteins (meat) first, then all vegetables (lettuce, tomato), then all starch/dairy (bread, cheese)"),
                ("full_set",         "use every available ingredient at least once: bread, meat, cheese, lettuce, tomato. Order them unusually."),
                ("random_ordered",   "use all ingredients but in a non-obvious, surprising order — NOT bread-first or bread-last"),
                ("doubled",          "pick exactly TWO ingredients and alternate them: A,B,A,B,A,B. Nothing else."),
            ]
            # Force ingredient constraint if command names specific items
            _cmd_lower = voice_command.lower()
            _named = [i for i in ["bread","meat","cheese","lettuce","tomato"] if i in _cmd_lower]
            if _named:
                _axis2_choice, _axis2_desc = ("constrained", f"use ONLY these named ingredients: {_named}. Repeat them, alternate them, stack them — but add nothing else.")
                _axis1_choice, _axis1_desc = _r.choice(_axis1_options)
            else:
                # Pick compatible pair — retry until valid (max 10 attempts)
                for _ in range(10):
                    _axis1_choice, _axis1_desc = _r.choice(_axis1_options)
                    _axis2_choice, _axis2_desc = _r.choice(_axis2_options)
                    if _compatible_axes(_axis1_choice, _axis2_choice):
                        break

            creative_section = f"""
━━━ CREATIVE MODE — AXES ━━━
This is a creative/open-ended command. Do NOT produce a standard sandwich (bread-filling-bread).

YOUR ASSIGNED COMBINATION FOR THIS COMMAND:

  AXIS 1 (spatial structure): {_axis1_choice}
  → {_axis1_desc}

  AXIS 2 (ingredient logic): {_axis2_choice}
  → {_axis2_desc}

You MUST follow both axes literally when building the sequence.
Do not override them. Do not revert to a standard sandwich shape.

Axis 1 construction rules:
- single_tall: keep adding layers until you would exceed stack capacity. No go_home until the stack is tall.
- single_short: stop at exactly 2 or 3 layers. Resist the urge to add more.
- three_zone_split: you MUST call set_active_zone() three times, once per zone.
- two_zone_contrast: you MUST call set_active_zone() twice. Each zone gets a distinct ingredient set.
- palindrome: write out your planned sequence first in creative_reasoning, verify it reads the same backwards, THEN generate the JSON steps. If it's not symmetric, fix it before outputting.
- inverted: the LAST step before go_home() must be add_layer(bread). Bread goes last.

Speed (adjust_speed) is expressive punctuation — use it to add drama, contrast, or rhythm. Optional but encouraged.

In creative_reasoning: state "Axis 1: {_axis1_choice} × Axis 2: {_axis2_choice}" then explain the sequence you built.
Set composite_name to null. Always produce a non-empty sequence.

━━━ CREATIVE EXAMPLES ━━━

Command: "impress me"
{{"interpretation": "inverted structure, full ingredient set — upside-down sandwich built tall", "sequence": [{{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "cheese"}}}}, {{"instruction": "add_layer", "params": {{"item": "meat"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.85, "user_feedback": null, "creative_reasoning": "Axis 1: inverted × Axis 2: full_set — started with what normally goes on top, ended with bread at the bottom. Every ingredient used once. Slow speed because this is deliberate, not accidental."}}

Command: "build a tower"
{{"interpretation": "single tall structure, one ingredient only — bread monolith", "sequence": [{{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "fast"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "fast"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.9, "user_feedback": null, "creative_reasoning": "Axis 1: single_tall × Axis 2: all_one — bread only, maximize height. A tower is a structural thing, not a food thing. Speed alternates slow/fast between layers for rhythmic drama."}}

Command: "do something with the lettuce and tomato"
{{"interpretation": "two-zone contrast, constrained to named ingredients only", "sequence": [{{"instruction": "set_active_zone", "params": {{"zone": "assembly_left"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "set_active_zone", "params": {{"zone": "assembly_right"}}}}, {{"instruction": "adjust_speed", "params": {{"modifier": "fast"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.9, "user_feedback": null, "creative_reasoning": "Axis 1: two_zone_contrast × Axis 2: constrained — lettuce gets left, tomato gets right, only named ingredients. The contrast is the point: slow careful lettuce tower vs fast stacked tomato tower side by side."}}
"""

        prompt = f"""You are the instruction generator for an ABB GoFa robot arm that builds sandwich assemblies.
Your job: convert a voice command into a JSON sequence of robot instructions.

{context}
{correction_section}
━━━ OUTPUT FORMAT ━━━
Return ONLY a JSON object — no explanation, no prose, no markdown fences. Just JSON.

{{
  "interpretation": "one sentence: what this command means in robot terms",
  "sequence": [
    {{"instruction": "instruction_name", "params": {{"param": "value"}}}},
    ...
  ],
  "composite_name": "snake_case_name_if_reusable_else_null",
  "confidence": 0.95,
  "user_feedback": null,
  "creative_reasoning": null
}}

━━━ RULES ━━━
1. Use ONLY instructions listed in AVAILABLE INSTRUCTIONS — never invent new ones like move_absolute
2. For assembly, ALWAYS use add_layer — never transfer or place_at — when adding to a zone
3. Every complete assembly sequence ends with go_home()
4. Parameters must be actual values — never placeholders like {{item}}
5. confidence: 0.9–1.0 clear · 0.7–0.9 interpreted · 0.5–0.7 best-guess · <0.5 very unclear
6. Always produce a sequence even for unclear commands — make your best interpretation
7. composite_name: snake_case reusable name if this is worth saving, else null. NEVER set for creative commands.
8. For fragile items (lettuce, tomato), prepend adjust_speed("slow") unless already slow
9. MULTI-ZONE: When building in a non-default zone, call set_active_zone("zone") FIRST, then add_layer calls.
   Zone names: assembly_fixture (default/center), assembly_left, assembly_right
   Spatial words in ASSEMBLY context: "left" → assembly_left, "right" → assembly_right, "center"/"middle" → assembly_fixture
   "over there" / no specifier → use assembly_fixture (default)
   set_active_zone is ONLY for switching assembly build targets — NEVER use it for robot motion.
   Spatial words like "move right", "shift left", "go forward" → use move_relative, NOT set_active_zone.
10. Bread can go ANYWHERE in a stack — it is not required only at the ends. Treat it like any other ingredient.

{creative_section}
━━━ RECOVERY COMMANDS ━━━
"put it back" / "undo" → return_to_stack() (no-op if not holding — safe to call always)
"start over" / "never mind" / "cancel" → clear_assembly() then go_home()
"take the [item] off" → return_to_stack() as best approximation (note: partial undo not yet supported)
"I made a mistake" → return_to_stack() if holding, else clear_assembly()

━━━ SPEED + ACTION COMBINED ━━━
"carefully pick up X" → adjust_speed("slow") then pick_up(X)
"do it faster" / "speed up" → adjust_speed("fast") with no other action
"gently" / "nice and slow" / "take your time" → adjust_speed("slow") prepended to sequence

━━━ UNKNOWN INGREDIENTS — SUBSTITUTE, DON'T REFUSE ━━━
If a command references an item not in the available items list, DO NOT return an empty sequence.
Instead: pick the closest available item based on the item descriptions (each item lists what it represents),
substitute it, produce the full sequence using that substitute, and note the swap in user_feedback.

Substitution guide (use item descriptions to reason — these are examples, not exhaustive):
- avocado, pickle, onion, cucumber, roasted pepper → tomato (juicy/acidic topping)
- bacon, ham, turkey, chicken, tuna, tofu, falafel → meat (protein layer)
- spinach, arugula, kale, greens, cabbage → lettuce (leafy green)
- cheddar, swiss, brie, mozzarella, sauce, spread, hummus → cheese (dairy/soft layer)
- bun, roll, pita, wrap, sourdough, toast, waffle → bread (starch/base)

user_feedback for substitutions: "I don't have [requested] — using [substitute] as the closest match"
Keep confidence at 0.75–0.85 for substitutions (you understood the intent, just swapped the tile).

If a command is physically impossible or makes no sense (not just an unknown ingredient):
- Set confidence low (< 0.4)
- Set user_feedback explaining the issue
- Still try to produce the closest valid sequence if possible

━━━ SECONDARY / LEARNING COMMANDS ━━━
If the command tries to define a new mapping ("make a BLT every time I say sandwich",
"remember this as my usual", "call it X"):
- Produce the sequence for the underlying action
- Set composite_name to the requested name
- Set user_feedback to "Mapping/composite noted — will be saved to memory system"
- These will be handled by the memory writer downstream

━━━ EXAMPLES ━━━

Command: "pick up the cheese"
{{"interpretation": "Pick up cheese from its slot", "sequence": [{{"instruction": "pick_up", "params": {{"item": "cheese"}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "make a cheese sandwich"
{{"interpretation": "Build cheese sandwich: bread, cheese, bread", "sequence": [{{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "add_layer", "params": {{"item": "cheese"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": "make_cheese_sandwich", "confidence": 0.9, "user_feedback": null, "creative_reasoning": null}}

Command: "make a cheese sandwich on the left and a BLT on the right"
{{"interpretation": "Build cheese sandwich at left zone, then BLT at right zone", "sequence": [{{"instruction": "set_active_zone", "params": {{"zone": "assembly_left"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "add_layer", "params": {{"item": "cheese"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}, {{"instruction": "set_active_zone", "params": {{"zone": "assembly_right"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "add_layer", "params": {{"item": "meat"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.9, "user_feedback": null, "creative_reasoning": null}}

Command: "move right a little"
{{"interpretation": "Nudge TCP right by 1cm", "sequence": [{{"instruction": "move_relative", "params": {{"direction": "right", "distance": 1.0}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "shift forward a lot"
{{"interpretation": "Move TCP forward 5cm", "sequence": [{{"instruction": "move_relative", "params": {{"direction": "forward", "distance": 5.0}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "move diagonally forward and right"
{{"interpretation": "Diagonal move — forward then right, 1cm each", "sequence": [{{"instruction": "move_relative", "params": {{"direction": "forward", "distance": 1.0}}}}, {{"instruction": "move_relative", "params": {{"direction": "right", "distance": 1.0}}}}], "composite_name": null, "confidence": 0.9, "user_feedback": null, "creative_reasoning": null}}

Command: "start over"
{{"interpretation": "Clear the assembly and return home", "sequence": [{{"instruction": "clear_assembly", "params": {{}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "put it back"
{{"interpretation": "Return held item to its slot (no-op if not holding)", "sequence": [{{"instruction": "return_to_stack", "params": {{}}}}], "composite_name": null, "confidence": 0.9, "user_feedback": null, "creative_reasoning": null}}

Command: "do it faster"
{{"interpretation": "Increase robot speed", "sequence": [{{"instruction": "adjust_speed", "params": {{"modifier": "fast"}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "carefully pick up the lettuce"
{{"interpretation": "Set slow speed then pick up lettuce", "sequence": [{{"instruction": "adjust_speed", "params": {{"modifier": "slow"}}}}, {{"instruction": "pick_up", "params": {{"item": "lettuce"}}}}], "composite_name": null, "confidence": 0.95, "user_feedback": null, "creative_reasoning": null}}

Command: "pick up the avocado"
{{"interpretation": "No avocado — picking up tomato as closest match (juicy topping)", "sequence": [{{"instruction": "pick_up", "params": {{"item": "tomato"}}}}], "composite_name": null, "confidence": 0.8, "user_feedback": "I don't have avocado — using tomato as the closest match", "creative_reasoning": null}}

Command: "make me a BLT with pickles"
{{"interpretation": "BLT with pickles substituted as tomato (juicy/acidic topping)", "sequence": [{{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "add_layer", "params": {{"item": "meat"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": null, "confidence": 0.8, "user_feedback": "I don't have pickles — using tomato as the closest match", "creative_reasoning": null}}

Command: "make a BLT every time I say sandwich"
{{"interpretation": "Define BLT as the default sandwich mapping", "sequence": [{{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "add_layer", "params": {{"item": "meat"}}}}, {{"instruction": "add_layer", "params": {{"item": "lettuce"}}}}, {{"instruction": "add_layer", "params": {{"item": "tomato"}}}}, {{"instruction": "add_layer", "params": {{"item": "bread"}}}}, {{"instruction": "go_home", "params": {{}}}}], "composite_name": "make_blt", "confidence": 0.9, "user_feedback": "Mapping noted — 'sandwich' will be saved as an alias for make_blt", "creative_reasoning": null}}

Now interpret this command:

Command: "{voice_command}"

JSON:"""

        return prompt

    def _build_validation_prompt(self, voice_command: str, raw_sequence: List[Dict],
                                  interpretation: str) -> str:
        """
        Build the validation prompt for Pass 2.
        Checks that the generated sequence only uses real instructions with valid params.
        """
        valid_composites = list(self.compiler.get_composites().keys())
        valid_items = list(self.compiler.get_items().keys())
        valid_locations = list(self.compiler.get_locations().keys())

        prompt = f"""You are a robot instruction validator. A sequence was generated for a voice command.
Your job: check it and return a corrected version if needed. Return ONLY JSON — no prose.

VOICE COMMAND: "{voice_command}"
INTERPRETATION: "{interpretation}"

VALID INSTRUCTIONS: {valid_composites}
VALID ITEMS: {valid_items}
VALID LOCATIONS: {valid_locations}

GENERATED SEQUENCE:
{json.dumps(raw_sequence, indent=2)}

VALIDATION RULES:
1. Every "instruction" value must be in VALID INSTRUCTIONS — fix or remove if not
   (e.g. move_absolute is NOT valid — remove it or replace with move_relative)
2. Every "item" param must be in VALID ITEMS — remove steps with unknown items
3. Every "location" param must be in VALID LOCATIONS — fix or remove if not
4. move_relative direction must be one of: right, left, up, down, forward, backward
5. Assembly sequences must use add_layer, not transfer or place_at
6. set_active_zone zone must be one of: assembly_fixture, assembly_left, assembly_right
7. Do NOT change the intent — only fix invalid instruction/param names
8. If a step is unfixable, remove it
9. If the sequence is empty after fixes, return an empty sequence (do not invent steps)

Return this JSON:
{{
  "valid": true/false,
  "issues": ["list of what was wrong, empty if none"],
  "sequence": [corrected sequence here]
}}

JSON:"""
        return prompt

    # ══════════════════════════════════════════════════════════════════════════
    # JSON PARSING
    # ══════════════════════════════════════════════════════════════════════════

    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """
        Robustly parse a JSON response from the LLM.
        Handles: markdown fences, leading prose, trailing content,
        and unescaped literal newlines inside JSON string values
        (which the LLM produces in multiline creative_reasoning fields).
        """
        # Strip markdown fences
        if "```" in text:
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```"))

        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = text[start:end + 1]

        # Try the block as-is
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # The LLM sometimes writes multiline strings in JSON without escaping
        # the newlines — fix by collapsing literal newlines inside string values.
        # Strategy: replace \n that appear between quotes with \\n, carefully.
        # Use a simple state machine rather than regex to avoid breaking JSON structure.
        fixed = _collapse_unescaped_newlines(candidate)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        return None

    # ══════════════════════════════════════════════════════════════════════════
    # MAIN INTERPRET
    # ══════════════════════════════════════════════════════════════════════════

    def interpret(self, voice_command: str) -> Optional[Dict]:
        """
        Three-pass pipeline:
          Pass 1 — Generation (temperature 1.0 for creative, 0 otherwise)
          Pass 2 — Validation (fix invalid instruction/param names)
          Pass 3 — Regeneration (if validator found issues, retry with hints)

        Returns None only for empty/trivial input.
        Always returns a structured dict otherwise — never silently drops a result.
        """
        if not voice_command or len(voice_command.strip()) < 2:
            return None

        creative = _is_creative(voice_command)
        temperature = 1.0 if creative else 0

        # ── Pass 1: Generation ────────────────────────────────────────────────
        raw_response_text = ""
        try:
            prompt = self._build_prompt(voice_command, is_creative=creative)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=900,
                temperature=temperature,
                timeout=30,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_response_text = response.content[0].text.strip()
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() or "529" in err or "overloaded" in err.lower():
                print(f"[SEQ] Pass 1 rate limit / overloaded: {e}")
                user_fb = "API rate limit or overloaded — try again in a moment"
            elif "timeout" in err.lower():
                print(f"[SEQ] Pass 1 timed out after 30s: {e}")
                user_fb = "API call timed out — check connection or try again"
            else:
                print(f"[SEQ] Pass 1 API call failed: {e}")
                user_fb = f"API error: {err}"
            return {
                "interpretation": user_fb,
                "sequence": [], "pass1_sequence": [],
                "composite_name": None, "confidence": 0.0,
                "validated": False, "validation_issues": [],
                "user_feedback": user_fb, "is_creative": creative,
                "creative_reasoning": None, "raw_response": err,
            }

        result = self._parse_json_response(raw_response_text)

        if result is None:
            print(f"[SEQ] Pass 1 JSON parse failed — raw: {raw_response_text[:120]}")
            return {
                "interpretation": raw_response_text[:300],
                "sequence": [], "pass1_sequence": [],
                "composite_name": None, "confidence": 0.0,
                "validated": False,
                "validation_issues": ["Pass 1 returned non-JSON response"],
                "user_feedback": None, "is_creative": creative,
                "creative_reasoning": None, "raw_response": raw_response_text,
            }

        # Ensure required fields with safe defaults
        result.setdefault("interpretation", "")
        result.setdefault("sequence", [])
        result.setdefault("composite_name", None)
        result.setdefault("confidence", 0.5)
        result.setdefault("validated", False)
        result.setdefault("validation_issues", [])
        result.setdefault("user_feedback", None)
        result.setdefault("creative_reasoning", None)
        result["is_creative"] = creative
        result["pass1_sequence"] = list(result["sequence"])  # snapshot before validation

        # Creative commands must never save a composite name
        if creative:
            result["composite_name"] = None

        # ── Pass 2: Validation ────────────────────────────────────────────────
        # Python-side pre-check: catch obvious structural problems without an LLM call.
        # If any of these fire, Pass 2 is warranted. Otherwise we skip it.
        def _python_issues(seq: list) -> list:
            issues = []
            valid_instructions = set(self.compiler.get_instruction_list_for_prompt().split(", "))
            valid_items = set(self.compiler.get_items().keys())
            for step in seq:
                inst = step.get("instruction", "")
                if inst and inst not in valid_instructions:
                    issues.append(f"unknown instruction: {inst}")
                if inst == "add_layer":
                    item = step.get("params", {}).get("item", "")
                    if item and item not in valid_items:
                        issues.append(f"unknown item: {item}")
            return issues

        def _matches_known_recipe(seq: list) -> bool:
            recipes = self.compiler.scene_context.get("recipes", {})
            p1_items = [s["params"].get("item") for s in seq
                        if s.get("instruction") == "add_layer"]
            for recipe in recipes.values():
                if isinstance(recipe, dict) and p1_items == recipe.get("layers", []):
                    return True
            return False

        _py_issues = _python_issues(result["sequence"])
        _needs_pass2 = bool(_py_issues)  # structural problem Python caught — always validate

        _skip_pass2 = (
            not _needs_pass2 and (
                creative                                     # no correct answer to validate
                or result["confidence"] >= 0.88             # data: P2 never changes high-conf outputs
                or _matches_known_recipe(result["sequence"]) # exact recipe — Python-verified
                or not result["sequence"]                    # empty sequence — nothing to validate
            )
        )
        if _skip_pass2:
            result["validated"] = True
            result["validation_issues"] = []

        if result["sequence"] and not _skip_pass2:
            try:
                val_prompt = self._build_validation_prompt(
                    voice_command, result["sequence"], result["interpretation"]
                )
                val_response = self.client.messages.create(
                    model=self.model,
                    max_tokens=700,
                    temperature=0,
                    timeout=30,
                    messages=[{"role": "user", "content": val_prompt}]
                )
                val_text = val_response.content[0].text.strip()
                val_result = self._parse_json_response(val_text)

                if val_result and "sequence" in val_result:
                    issues = val_result.get("issues", [])
                    if issues:
                        print(f"[SEQ] Validator found {len(issues)} issue(s): {issues}")
                    result["sequence"] = val_result["sequence"]
                    result["validated"] = val_result.get("valid", True)
                    result["validation_issues"] = issues
                else:
                    print(f"[SEQ] Validator returned unparseable response — keeping original")
                    result["validated"] = False
                    result["validation_issues"] = ["Validator response unparseable"]

            except Exception as e:
                print(f"[SEQ] Pass 2 validation failed: {e}")
                result["validated"] = False
                result["validation_issues"] = [f"Validation error: {e}"]
        else:
            result["validated"] = True
            result["validation_issues"] = []

        # ── Pass 3: Regeneration (if validator found fixable issues) ──────────
        issues_after_p2 = result.get("validation_issues", [])
        if issues_after_p2 and not result.get("raw_response"):
            # Only retry if there were real structural issues (not just "unparseable")
            real_issues = [i for i in issues_after_p2
                           if "unparseable" not in i.lower() and "error" not in i.lower()]
            if real_issues:
                print(f"[SEQ] Pass 3: regenerating with {len(real_issues)} correction hint(s)")
                try:
                    p3_prompt = self._build_prompt(
                        voice_command,
                        is_creative=creative,
                        correction_hints=real_issues
                    )
                    p3_response = self.client.messages.create(
                        model=self.model,
                        max_tokens=900,
                        temperature=0,  # Correction pass always deterministic
                        timeout=30,
                        messages=[{"role": "user", "content": p3_prompt}]
                    )
                    p3_text = p3_response.content[0].text.strip()
                    p3_result = self._parse_json_response(p3_text)

                    if p3_result and "sequence" in p3_result:
                        # Accept the corrected sequence, note that Pass 3 ran
                        result["sequence"] = p3_result.get("sequence", result["sequence"])
                        result["interpretation"] = p3_result.get("interpretation", result["interpretation"])
                        result["confidence"] = p3_result.get("confidence", result["confidence"])
                        result["user_feedback"] = p3_result.get("user_feedback", result["user_feedback"])
                        result["creative_reasoning"] = p3_result.get("creative_reasoning", result["creative_reasoning"])
                        result["validation_issues"] = [f"[P3 fixed] {i}" for i in real_issues]
                        result["validated"] = True
                        if creative:
                            result["composite_name"] = None
                        print(f"[SEQ] Pass 3 succeeded — sequence regenerated with corrections")
                    else:
                        print(f"[SEQ] Pass 3 returned unparseable — keeping Pass 2 result")
                except Exception as e:
                    print(f"[SEQ] Pass 3 failed: {e}")
                    # Non-fatal — keep Pass 2 result

        return result

    def interpret_and_execute(self, voice_command: str) -> bool:
        """
        Interpret a command and execute it.
        Learns new composites if confident.
        Returns True if execution succeeded.
        """
        print(f"[SEQ] Interpreting: '{voice_command}'")

        result = self.interpret(voice_command)
        if not result:
            print(f"[SEQ] Failed to interpret")
            return False

        print(f"[SEQ] Interpretation: {result['interpretation']}")
        print(f"[SEQ] Confidence: {result['confidence']:.2f}")
        print(f"[SEQ] Sequence: {len(result['sequence'])} steps")

        if result.get("user_feedback"):
            print(f"[SEQ] User feedback: {result['user_feedback']}")

        # Compile the sequence
        plan = self.compiler.compile_sequence(result["sequence"])
        if not plan or not plan.steps:
            print(f"[SEQ] Failed to compile sequence")
            return False

        # Execute
        executor = get_executor()
        success = executor.execute_plan(plan)

        # Learn if confident and successful (never learn creative outputs)
        if success and result["confidence"] >= LLM_CONFIDENCE_THRESHOLD and not result.get("is_creative"):
            composite_name = result.get("composite_name")
            if composite_name and not self.compiler.is_composite(composite_name):
                self.compiler.learn_composite(
                    name=composite_name,
                    description=result["interpretation"],
                    parameters={},
                    sequence=result["sequence"],
                    confidence=result["confidence"],
                    source_phrase=voice_command
                )

        return success

    def is_confident(self, result: Dict) -> bool:
        """Check if interpretation meets confidence threshold."""
        return result.get("confidence", 0) >= LLM_CONFIDENCE_THRESHOLD


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

_interpreter_instance = None

def get_sequence_interpreter() -> SequenceInterpreter:
    """Get singleton SequenceInterpreter."""
    global _interpreter_instance
    if _interpreter_instance is None:
        _interpreter_instance = SequenceInterpreter()
    return _interpreter_instance


# ──────────────────────────────────────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────────────────────────────────────

def test_interpreter():
    print("=== Sequence Interpreter Test ===\n")
    try:
        interpreter = SequenceInterpreter()
    except Exception as e:
        print(f"Cannot test: {e}")
        return

    test_commands = [
        "move right a little",
        "pick up the cheese",
        "go wild",
        "put it back",
        "pick up the avocado",
    ]

    for cmd in test_commands:
        print(f"\nCommand: '{cmd}'")
        result = interpreter.interpret(cmd)
        if result:
            print(f"  Interpretation: {result['interpretation']}")
            print(f"  Confidence: {result['confidence']:.2f}")
            print(f"  Creative: {result.get('is_creative')}")
            print(f"  Validated: {result.get('validated')} issues={result.get('validation_issues')}")
            if result.get("user_feedback"):
                print(f"  ⚠ User feedback: {result['user_feedback']}")
            if result.get("creative_reasoning"):
                print(f"  💡 Reasoning: {result['creative_reasoning']}")
            print(f"  Sequence ({len(result['sequence'])} steps):")
            for step in result["sequence"]:
                print(f"    - {step['instruction']}({step.get('params', {})})")
        else:
            print("  → None (empty input)")


if __name__ == "__main__":
    test_interpreter()
