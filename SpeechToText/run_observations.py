"""
run_observations.py
-------------------
Observation runner for the sequence interpreter.

NOT a test suite — no assertions, no pass/fail.
Feeds a curated set of voice commands to the LLM and prints
a clean, readable report of what it generated for each one.

Purpose:
  - Show the professor what the system does with normal, weird, and creative input
  - Catch unexpected or wrong interpretations before they get learned
  - Observe confidence distribution across input types
  - Spot where the instruction set needs work

Run:
  python run_observations.py
  python run_observations.py --category creative
  python run_observations.py --category all --save

Categories:
  baseline    — clean commands the system should nail
  ambiguous   — underspecified but handleable
  modifiers   — recipe modifiers (double, no, swap, etc.)
  multi_stack — commands involving more than one assembly zone
  recovery    — abort, undo, cancel mid-build scenarios
  edge        — weird phrasing, partial sentences, out-of-vocab
  creative    — wild inputs the professor loves; system should do something interesting
  secondary   — commands that should trigger secondary/learned composite naming
"""

import sys
import json
import time
import argparse
from datetime import datetime
from typing import Optional

# ── path setup ────────────────────────────────────────────────────────────────
import os
sys.path.insert(0, os.path.dirname(__file__))

from learning.sequence_interpreter import SequenceInterpreter
from learning.instruction_compiler import get_compiler

# ── ANSI colours (degrade gracefully on Windows) ──────────────────────────────
try:
    import colorama; colorama.init()
    C = {
        "reset":  "\033[0m",
        "bold":   "\033[1m",
        "dim":    "\033[2m",
        "green":  "\033[92m",
        "yellow": "\033[93m",
        "red":    "\033[91m",
        "cyan":   "\033[96m",
        "blue":   "\033[94m",
        "magenta":"\033[95m",
        "white":  "\033[97m",
    }
except ImportError:
    C = {k: "" for k in ["reset","bold","dim","green","yellow","red","cyan","blue","magenta","white"]}


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# Each entry: (voice_command, note)
# note = what we expect / what to look for — shown in output but not evaluated
# ══════════════════════════════════════════════════════════════════════════════

CASES = {

    # ── BASELINE ──────────────────────────────────────────────────────────────
    # Clean, unambiguous commands. Should produce high confidence, correct sequence.
    "baseline": [
        ("pick up the cheese",
         "Simple pick. Should be pick_up(cheese). Confidence should be >=0.9."),

        ("make a cheese sandwich",
         "3-layer: bread cheese bread. Should use add_layer x3 then go_home."),

        ("make a BLT",
         "Classic BLT layers. Should use add_layer x5. Meat stands in for bacon."),

        ("make a club sandwich",
         "6 layers. Longest standard recipe — watch token count."),

        ("go home",
         "Single composite. Should be go_home(). Trivial."),

        ("move right a little",
         "Simple relative move, small distance. Should NOT use sequence interpreter — but if it does, expect move_relative(right, 0.5)."),

        ("add bread to the assembly",
         "Direct add_layer call. Should be add_layer(bread)."),

        ("start over",
         "Clear the assembly. Should be clear_assembly()."),
    ],

    # ── AMBIGUOUS ─────────────────────────────────────────────────────────────
    # Underspecified but reasonable. Watch for sensible inference vs. confusion.
    "ambiguous": [
        ("make a sandwich",
         "No recipe named. Should it pick classic? Ask? Interesting to see what it defaults to."),

        ("put some bread down",
         "Colloquial for add_layer(bread). Does it get it?"),

        ("add the usual",
         "No prior context. Should return low confidence or ask for clarification."),

        ("stack it up",
         "Totally vague. Does it hallucinate a sequence or admit it doesn't know?"),

        ("do the thing",
         "Maximally vague. Should be very low confidence."),

        ("give me something vegetarian",
         "Implicit recipe reference. Should map to veggie recipe."),

        ("make two sandwiches",
         "Two stacks — do we have room? Does it know about multi-stack support?"),

        ("make a sandwich but make it interesting",
         "Open-ended creative modifier. What does it do?"),
    ],

    # ── MODIFIERS ─────────────────────────────────────────────────────────────
    # Recipe modifiers. The LLM should apply these to the base recipe layer list.
    "modifiers": [
        ("make a BLT with double lettuce",
         "BLT + duplicate lettuce layer. Should produce 6 add_layer calls."),

        ("make a classic with no tomato",
         "Classic - tomato. Should produce 4 add_layer calls."),

        ("make a veggie sandwich, hold the cheese",
         "Veggie - cheese. Should produce 4 add_layer calls."),

        ("make a club sandwich with extra meat",
         "Club + duplicate meat. Should produce 7 add_layer calls."),

        ("swap the lettuce for cheese on a BLT",
         "BLT with lettuce replaced by cheese. Does it handle swap correctly?"),

        ("make a BLT nice and slow",
         "Speed modifier on a recipe. Should prepend adjust_speed(careful) or similar."),

        ("make a double cheese sandwich",
         "Ambiguous — double as in two cheese layers, or two sandwiches? Watch interpretation."),

        ("make a BLT with no bread",
         "Removing bread from a sandwich. Physically nonsensical — what does it do?"),
    ],

    # ── MULTI-STACK ───────────────────────────────────────────────────────────
    # Commands that reference multiple assembly zones. System supports this but it's new.
    "multi_stack": [
        ("make a cheese sandwich on the left and a BLT on the right",
         "Two simultaneous stacks. Does it know about multiple zones?"),

        ("start a BLT over there",
         "Vague target zone. Does it ask for clarification or pick a default?"),

        ("put bread on both stacks",
         "Broadcast add_layer to all active stacks. Novel — watch what happens."),
    ],

    # ── RECOVERY ──────────────────────────────────────────────────────────────
    # Undo, cancel, abort scenarios. Important for real operation.
    "recovery": [
        ("put it back",
         "Return held item to slot. Should be return_to_stack(). Does it get context from state?"),

        ("never mind, start over",
         "Cancel current assembly. Should be clear_assembly()."),

        ("I made a mistake, undo that",
         "Undo last action — does it know what that means? Likely return_to_stack or clear_assembly."),

        ("stop what you're doing and go home",
         "Mid-sequence abort + go_home. Watch for emergency_stop confusion."),

        ("that's wrong, take the tomato off",
         "Remove specific item from top of stack — does it understand this as a partial undo?"),
    ],

    # ── EDGE ──────────────────────────────────────────────────────────────────
    # Weird phrasing, partial sentences, out-of-vocabulary items.
    "edge": [
        ("",
         "Empty string. Should return None gracefully."),

        ("uhhh",
         "Filler only. Very low confidence expected."),

        ("pick up the avocado",
         "Unknown item. Should reject with unknown_item rule. Does it hallucinate a slot?"),

        ("move the robot to the left side",
         "Vague relative move with no distance. Does it default or ask?"),

        ("place the cheese on the assembly",
         "Ambiguous — pick_up then add_layer, or just add_layer? Cheese not currently held."),

        ("make a sandwich with pickles",
         "Ingredient not in system. Does it substitute, skip, or flag?"),

        ("do it faster",
         "Speed modifier with no action. Does it just set_speed(fast)?"),

        ("make a BLT and also a cheese sandwich",
         "Two recipes in one command. Does it generate both sequences? Probably too long."),

        ("carefully pick up the lettuce",
         "Speed modifier + pick_up. Should it prepend adjust_speed?"),

        ("move diagonally",
         "Invalid direction. Should reject or ask for clarification."),
    ],

    # ── CREATIVE ──────────────────────────────────────────────────────────────
    # Wild inputs. The professor loves this. No 'correct' answer — just observe.
    # These are the fun ones — the system should try something interesting rather
    # than giving up, and ideally suggest a composite_name for what it came up with.
    "creative": [
        ("make something beautiful",
         "Maximally open-ended. Does it make a tall elaborate stack? Does it invent something?"),

        ("impress me",
         "Creative directive. What does the robot think is impressive?"),

        ("surprise me with something delicious",
         "Does it pick a recipe? Invent a new one? Use all available ingredients?"),

        ("build a tower",
         "Non-food framing for stacking. Does it stack everything it has?"),

        ("make the best sandwich you can",
         "Superlative instruction. Does it use all ingredients? Does it slow down to be careful?"),

        ("do something with the lettuce and tomato",
         "Partial ingredient list, open action. Does it invent a sequence?"),

        ("make me a work of art",
         "Completely abstract. What sequence does this produce?"),

        ("go wild",
         "Full creative latitude. This is the one to show the professor."),
    ],

    # ── SECONDARY / LEARNING ──────────────────────────────────────────────────
    # Commands that should naturally produce a composite_name suggestion.
    # These are the seeds of the learning system.
    "secondary": [
        ("make a BLT every time I say sandwich",
         "Meta-instruction — trying to define a new mapping. Does it handle this?"),

        ("remember this as my usual",
         "Learning directive without specifying what 'this' is."),

        ("from now on, careful means use slow speed and go home after",
         "Trying to define a new composite. Does it suggest a learned composite?"),

        ("that sequence where you do bread meat cheese bread, call it the classic plus",
         "Explicit composite definition. Should generate composite_name: classic_plus."),

        ("do the cheese sandwich but save it as a new sequence",
         "Explicit learning request. Should suggest composite_name."),
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def confidence_colour(conf: float) -> str:
    if conf >= 0.90: return C["green"]
    if conf >= 0.75: return C["yellow"]
    return C["red"]

def confidence_label(conf: float) -> str:
    if conf >= 0.90: return "HIGH"
    if conf >= 0.75: return "MED"
    if conf >= 0.50: return "LOW"
    return "VERY LOW"

def print_header(text: str, width: int = 72):
    print()
    print(C["bold"] + C["cyan"] + "═" * width + C["reset"])
    print(C["bold"] + C["cyan"] + f"  {text}" + C["reset"])
    print(C["bold"] + C["cyan"] + "═" * width + C["reset"])

def print_section(category: str, total: int):
    label = category.upper().replace("_", " ")
    print()
    print(C["bold"] + C["blue"] + f"┌─ {label} ({total} cases) " + "─" * (60 - len(label)) + C["reset"])

def print_case(idx: int, command: str, note: str, result: Optional[dict], elapsed: float):
    num = f"{idx:02d}"

    # Command line
    cmd_display = f'"{command}"' if command else "(empty string)"
    print()
    print(C["bold"] + f"  [{num}] {cmd_display}" + C["reset"])
    print(C["dim"] + f"       Note: {note}" + C["reset"])

    if result is None:
        print(C["red"] + "       → No result returned (None)" + C["reset"])
        print(C["dim"] + f"       ({elapsed:.2f}s)" + C["reset"])
        return

    conf = result.get("confidence", 0.0)
    interp = result.get("interpretation", "—")
    sequence = result.get("sequence", [])
    composite_name = result.get("composite_name")

    cc = confidence_colour(conf)
    cl = confidence_label(conf)

    print(f"       {cc}{C['bold']}Confidence: {conf:.2f} [{cl}]{C['reset']}")
    print(f"       Interpretation: {C['white']}{interp}{C['reset']}")

    if composite_name:
        print(f"       {C['magenta']}Suggests composite: \"{composite_name}\"{C['reset']}")

    if not sequence:
        print(C["yellow"] + "       Sequence: (empty)" + C["reset"])
    else:
        print(f"       Sequence ({len(sequence)} steps):")
        for step in sequence:
            inst = step.get("instruction", "?")
            params = step.get("params", {})
            param_str = ", ".join(f"{k}={repr(v)}" for k, v in params.items()) if params else ""
            print(f"         {C['cyan']}→ {inst}({param_str}){C['reset']}")

    print(C["dim"] + f"       ({elapsed:.2f}s)" + C["reset"])


def print_summary(results: list):
    print_header("SUMMARY")

    total = len(results)
    returned = sum(1 for r in results if r["result"] is not None)
    none_count = total - returned

    confs = [r["result"]["confidence"] for r in results if r["result"] is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    high   = sum(1 for c in confs if c >= 0.90)
    med    = sum(1 for c in confs if 0.75 <= c < 0.90)
    low    = sum(1 for c in confs if c < 0.75)

    composites_suggested = [r for r in results if r["result"] and r["result"].get("composite_name")]

    print(f"  Total cases run:          {total}")
    print(f"  Returned a result:        {returned}  ({none_count} returned None)")
    print(f"  Avg confidence:           {avg_conf:.2f}")
    print(f"  High (>=0.90):            {C['green']}{high}{C['reset']}")
    print(f"  Medium (0.75–0.90):       {C['yellow']}{med}{C['reset']}")
    print(f"  Low (<0.75):              {C['red']}{low}{C['reset']}")
    print()
    if composites_suggested:
        print(f"  Composite names suggested ({len(composites_suggested)}):")
        for r in composites_suggested:
            print(f"    {C['magenta']}→ \"{r['result']['composite_name']}\"{C['reset']}  (from: \"{r['command']}\")")
    else:
        print("  No composite names suggested.")

    print()
    print(C["dim"] + "  Low confidence cases:" + C["reset"])
    for r in results:
        if r["result"] and r["result"]["confidence"] < 0.75:
            print(C["dim"] + f"    [{r['category']}] \"{r['command']}\" → {r['result']['confidence']:.2f}" + C["reset"])
        elif r["result"] is None:
            print(C["dim"] + f"    [{r['category']}] \"{r['command']}\" → None" + C["reset"])


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run(categories: list, save: bool = False):

    print_header(f"SEQUENCE INTERPRETER OBSERVATION RUN  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Model:      {os.getenv('ANTHROPIC_MODEL', 'claude-3-haiku-20240307')}")
    print(f"  Categories: {', '.join(categories)}")
    print(f"  Save log:   {'yes' if save else 'no'}")

    try:
        interpreter = SequenceInterpreter()
    except Exception as e:
        print(C["red"] + f"\n  Cannot initialise SequenceInterpreter: {e}" + C["reset"])
        sys.exit(1)

    all_results = []
    case_idx = 0

    for category in categories:
        cases = CASES.get(category, [])
        if not cases:
            print(C["yellow"] + f"\n  Warning: no cases found for category '{category}'" + C["reset"])
            continue

        print_section(category, len(cases))

        for command, note in cases:
            case_idx += 1
            t0 = time.time()
            result = interpreter.interpret(command)
            elapsed = time.time() - t0

            print_case(case_idx, command, note, result, elapsed)

            all_results.append({
                "category": category,
                "command":  command,
                "note":     note,
                "result":   result,
                "elapsed":  elapsed,
            })

            # Small delay to avoid rate limiting on fast runs
            time.sleep(0.3)

    print_summary(all_results)

    if save:
        save_log(all_results)

    print()


def save_log(results: list):
    """Save raw results to a JSON log file for later review."""
    log_dir = os.path.join(os.path.dirname(__file__), "observation_logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(log_dir, f"obs_{timestamp}.json")

    # Make serialisable
    serialisable = []
    for r in results:
        serialisable.append({
            "category": r["category"],
            "command":  r["command"],
            "note":     r["note"],
            "result":   r["result"],
            "elapsed":  round(r["elapsed"], 3),
        })

    with open(path, "w") as f:
        json.dump(serialisable, f, indent=2)

    print(C["dim"] + f"\n  Log saved → {path}" + C["reset"])


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

ALL_CATEGORIES = list(CASES.keys())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sequence interpreter observation runner")
    parser.add_argument(
        "--category", "-c",
        default="all",
        help=f"Category to run, or 'all'. Options: {', '.join(ALL_CATEGORIES)}"
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save results to observation_logs/ as JSON"
    )
    args = parser.parse_args()

    if args.category == "all":
        cats = ALL_CATEGORIES
    elif args.category in ALL_CATEGORIES:
        cats = [args.category]
    else:
        print(f"Unknown category '{args.category}'. Options: all, {', '.join(ALL_CATEGORIES)}")
        sys.exit(1)

    run(cats, save=args.save)
