"""
observation_app.py
──────────────────
Streamlit UI for the sequence interpreter observation runner.

Tabs:
  🏠 Home          — what this is, how to use it, quick-run buttons
  🟢 Baseline      — clean commands, should always work
  🌫️ Ambiguous     — underspecified, watch inference
  🔀 Modifiers     — double / no / swap / speed on recipes
  🗂️ Multi-Stack   — multiple assembly zones
  ↩️ Recovery      — undo, abort, cancel mid-build
  ⚠️ Edge          — empty input, unknown items, bad directions
  🎨 Creative      — wild inputs, professor-demo material
  🧠 Secondary     — explicit learning / composite-definition attempts
  📋 Log Viewer    — browse saved observation_logs/ JSON files

Run:
  streamlit run observation_app.py
"""

import os, sys, json, time, threading
from datetime import datetime
from typing import Optional

import streamlit as st

# ── path ──────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="GoFa Observation Runner",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── global ── */
html, body, [data-testid="stAppViewContainer"] {
    background: #0e0e12;
    color: #e0e0e0;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
[data-testid="stHeader"] { background: transparent; }

/* ── chat bubbles ── */
.bubble-user {
    background: #1a2744;
    border-left: 3px solid #4a9eff;
    border-radius: 4px 12px 12px 4px;
    padding: 10px 14px;
    margin: 8px 0 2px 60px;
    font-size: 0.95rem;
    color: #cce4ff;
}
.bubble-note {
    color: #6a7a8a;
    font-size: 0.78rem;
    margin: 0 0 4px 76px;
    font-style: italic;
}
.bubble-result {
    background: #141a1f;
    border-left: 3px solid #2a2a3a;
    border-radius: 4px 12px 12px 4px;
    padding: 10px 14px;
    margin: 2px 60px 14px 0;
    font-size: 0.88rem;
}
.bubble-result.high  { border-left-color: #3ecf6e; }
.bubble-result.med   { border-left-color: #f0b429; }
.bubble-result.low   { border-left-color: #e05252; }
.bubble-result.none  { border-left-color: #555; color: #666; }

/* confidence badge */
.badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: bold;
    margin-left: 8px;
}
.badge.high  { background: #1a4a2e; color: #3ecf6e; }
.badge.med   { background: #3d2f0a; color: #f0b429; }
.badge.low   { background: #3d0a0a; color: #e05252; }
.badge.none  { background: #2a2a2a; color: #888; }

/* step list */
.steps { margin: 6px 0 0 0; padding: 0; list-style: none; }
.steps li {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    color: #7ec8e3;
    padding: 1px 0;
}
.steps li::before { content: "→ "; color: #4a6a7a; }

/* composite pill */
.composite-pill {
    display: inline-block;
    background: #2a1a3a;
    color: #c084fc;
    border: 1px solid #6a3a9a;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.78rem;
    margin-top: 4px;
}

/* interpretation line */
.interp { color: #a0b4c0; font-size: 0.85rem; margin-top: 4px; }

/* elapsed */
.elapsed { color: #3a4a5a; font-size: 0.75rem; margin-top: 4px; }

/* section header */
.cat-header {
    font-size: 1.1rem;
    font-weight: bold;
    color: #4a9eff;
    margin: 18px 0 4px 0;
    border-bottom: 1px solid #1a2a3a;
    padding-bottom: 4px;
}

/* home cards */
.card {
    background: #12151e;
    border: 1px solid #1e2a3a;
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 12px;
}
.card h4 { color: #4a9eff; margin: 0 0 6px 0; }
.card p  { color: #8a9ab0; margin: 0; font-size: 0.88rem; }

/* instruction box */
.instruction {
    background: #0a1520;
    border: 1px solid #1e3a5a;
    border-radius: 6px;
    padding: 12px 16px;
    font-size: 0.85rem;
    color: #7a9ab0;
    margin-bottom: 10px;
}
.instruction code { color: #4a9eff; background: #0e1e2e; padding: 1px 5px; border-radius: 3px; }

/* running spinner area */
.running-msg { color: #f0b429; font-size: 0.9rem; margin: 8px 0; }

/* user feedback banner */
.feedback-banner {
    background: #1e1000;
    border: 1px solid #7a4a00;
    border-radius: 6px;
    padding: 8px 12px;
    margin-top: 6px;
    color: #f0b429;
    font-size: 0.82rem;
}

/* creative badge + reasoning */
.creative-badge {
    display: inline-block;
    background: #1a0a2e;
    color: #c084fc;
    border: 1px solid #6a3a9a;
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 0.72rem;
    margin-left: 6px;
}
.reasoning-block {
    background: #120a1e;
    border-left: 2px solid #6a3a9a;
    padding: 6px 10px;
    margin-top: 6px;
    color: #a070c0;
    font-size: 0.80rem;
    font-style: italic;
}

/* pass diff */
.pass-label { font-size: 0.70rem; color: #3a5a6a; margin: 5px 0 1px 0; text-transform: uppercase; letter-spacing: 0.07em; }
.pass-diff  { background: #1a1208; border-left: 2px solid #7a5a00; padding: 3px 8px; margin-bottom: 3px; }

/* summary row */
.sumrow { display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; }
.sumcard {
    background: #12151e;
    border: 1px solid #1e2a3a;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: center;
    min-width: 100px;
}
.sumcard .val { font-size: 1.5rem; font-weight: bold; }
.sumcard .lbl { font-size: 0.75rem; color: #5a6a7a; }
.val.green { color: #3ecf6e; }
.val.yellow { color: #f0b429; }
.val.red    { color: #e05252; }
.val.blue   { color: #4a9eff; }
.val.purple { color: #c084fc; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES (mirrored from run_observations.py)
# ══════════════════════════════════════════════════════════════════════════════

CASES = {
    "baseline": [
        ("pick up the cheese",
         "Simple pick. Should be pick_up(cheese). Confidence ≥0.9."),
        ("make a cheese sandwich",
         "3-layer: bread cheese bread. add_layer ×3 then go_home."),
        ("make a BLT",
         "Classic BLT layers. add_layer ×5. Meat stands in for bacon."),
        ("make a club sandwich",
         "6 layers. Longest standard recipe — watch token count."),
        ("go home",
         "Single composite. go_home(). Trivial."),
        ("move right a little",
         "Simple relative move. Might not need sequence interpreter at all."),
        ("add bread to the assembly",
         "Direct add_layer call. Should be add_layer(bread)."),
        ("start over",
         "Clear the assembly. Should be clear_assembly()."),
    ],
    "ambiguous": [
        ("make a sandwich",
         "No recipe named. Does it default to classic? Something else?"),
        ("put some bread down",
         "Colloquial for add_layer(bread). Does it get it?"),
        ("add the usual",
         "No prior context. Low confidence or asks for clarification?"),
        ("stack it up",
         "Totally vague. Does it hallucinate or admit it doesn't know?"),
        ("do the thing",
         "Maximally vague. Should be very low confidence."),
        ("give me something vegetarian",
         "Implicit recipe reference. Should map to veggie."),
        ("make two sandwiches",
         "Two stacks — does it know about multi-stack support?"),
        ("make a sandwich but make it interesting",
         "Open-ended creative modifier. What does it do?"),
    ],
    "modifiers": [
        ("make a BLT with double lettuce",
         "BLT + duplicate lettuce. Should produce 6 add_layer calls."),
        ("make a classic with no tomato",
         "Classic − tomato. Should produce 4 add_layer calls."),
        ("make a veggie sandwich, hold the cheese",
         "Veggie − cheese. Should produce 4 add_layer calls."),
        ("make a club sandwich with extra meat",
         "Club + duplicate meat. Should produce 7 add_layer calls."),
        ("swap the lettuce for cheese on a BLT",
         "BLT with lettuce replaced by cheese. Does it handle swap?"),
        ("make a BLT nice and slow",
         "Speed modifier on a recipe. Should prepend adjust_speed."),
        ("make a double cheese sandwich",
         "Ambiguous — two cheese layers, or two sandwiches?"),
        ("make a BLT with no bread",
         "Removing bread. Physically nonsensical — what does it do?"),
    ],
    "multi_stack": [
        ("make a cheese sandwich on the left and a BLT on the right",
         "Two simultaneous stacks. Does it know about multiple zones?"),
        ("start a BLT over there",
         "Vague target zone. Clarification or default?"),
        ("put bread on both stacks",
         "Broadcast add_layer to all active stacks. Novel."),
    ],
    "recovery": [
        ("put it back",
         "Return held item. Should be return_to_stack(). Context from state?"),
        ("never mind, start over",
         "Cancel current assembly. Should be clear_assembly()."),
        ("I made a mistake, undo that",
         "Undo last action — return_to_stack or clear_assembly?"),
        ("stop what you're doing and go home",
         "Mid-sequence abort + go_home. Watch for emergency_stop confusion."),
        ("that's wrong, take the tomato off",
         "Remove specific item from top of stack — partial undo?"),
    ],
    "edge": [
        ("",
         "Empty string. Should return None gracefully."),
        ("uhhh",
         "Filler only. Very low confidence expected."),
        ("pick up the avocado",
         "Unknown item. Should reject with unknown_item rule."),
        ("move the robot to the left side",
         "Vague relative move, no distance. Default or ask?"),
        ("place the cheese on the assembly",
         "Cheese not currently held. pick_up then add_layer, or just add_layer?"),
        ("make a sandwich with pickles",
         "Ingredient not in system. Substitute, skip, or flag?"),
        ("do it faster",
         "Speed modifier, no action. Just set_speed(fast)?"),
        ("make a BLT and also a cheese sandwich",
         "Two recipes in one command. Too long? Does it try?"),
        ("carefully pick up the lettuce",
         "Speed modifier + pick_up. Should it prepend adjust_speed?"),
        ("move diagonally",
         "Invalid direction. Reject or ask for clarification?"),
    ],
    "creative": [
        ("make something beautiful",
         "Maximally open-ended. Does it make a tall elaborate stack?"),
        ("impress me",
         "Creative directive. What does the robot think is impressive?"),
        ("surprise me with something delicious",
         "Does it pick a recipe? Invent a new one? Use everything?"),
        ("build a tower",
         "Non-food framing for stacking. Does it stack everything?"),
        ("make the best sandwich you can",
         "Superlative. Does it use all ingredients? Slow down to be careful?"),
        ("do something with the lettuce and tomato",
         "Partial ingredient list, open action. Does it invent a sequence?"),
        ("make me a work of art",
         "Completely abstract. What sequence does this produce?"),
        ("go wild",
         "Full creative latitude. The professor demo case."),
    ],
    "secondary": [
        ("make a BLT every time I say sandwich",
         "Meta-instruction — trying to define a new mapping."),
        ("remember this as my usual",
         "Learning directive without specifying what 'this' is."),
        ("from now on, careful means use slow speed and go home after",
         "Trying to define a new composite. Suggests a learned composite?"),
        ("that sequence where you do bread meat cheese bread, call it the classic plus",
         "Explicit composite definition. Should produce composite_name: classic_plus."),
        ("do the cheese sandwich but save it as a new sequence",
         "Explicit learning request. Should suggest composite_name."),
    ],
}

CATEGORY_META = {
    "baseline":    ("🟢", "Baseline",    "Clean commands the system should nail. High confidence expected across the board."),
    "ambiguous":   ("🌫️", "Ambiguous",   "Underspecified inputs. Watch how the LLM infers intent — and when it admits it doesn't know."),
    "modifiers":   ("🔀", "Modifiers",   "Recipe modifiers: double, no, swap, speed. The LLM must mutate a base recipe's layer list."),
    "multi_stack": ("🗂️", "Multi-Stack", "Commands referencing more than one assembly zone. Newer territory — system supports it, LLM might not fully."),
    "recovery":    ("↩️", "Recovery",    "Undo, abort, cancel mid-build. Critical for real operation."),
    "edge":        ("⚠️", "Edge",        "Empty input, unknown items, bad directions, compound requests. Designed to find breakage."),
    "creative":    ("🎨", "Creative",    "Wild, open-ended, abstract inputs. No 'correct' answer — observe what it does. Professor-demo material."),
    "secondary":   ("🧠", "Secondary",   "Explicit learning / composite-definition attempts. Seeds of the learning system."),
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def conf_class(conf: Optional[float]) -> str:
    if conf is None: return "none"
    if conf >= 0.90: return "high"
    if conf >= 0.75: return "med"
    return "low"

def conf_label(conf: Optional[float]) -> str:
    if conf is None: return "NONE"
    if conf >= 0.90: return "HIGH"
    if conf >= 0.75: return "MED"
    if conf >= 0.50: return "LOW"
    return "VERY LOW"

def _steps_html(sequence: list, dim: bool = False) -> str:
    """Render a sequence as an HTML step list."""
    if not sequence:
        return '<span style="color:#3a4a5a; font-size:0.82rem">(empty sequence)</span>'
    opacity = ' style="opacity:0.45"' if dim else ''
    items = ""
    for step in sequence:
        inst = step.get("instruction", "?")
        params = step.get("params", {})
        param_str = ", ".join(f"{k}={repr(v)}" for k, v in params.items()) if params else ""
        items += f"<li{opacity}>{inst}({param_str})</li>"
    return f'<ul class="steps">{items}</ul>'


def render_result_bubble(command: str, note: str, result: Optional[dict], elapsed: Optional[float]):
    cmd_display = f'"{command}"' if command else "(empty string)"

    # User bubble
    st.markdown(f'<div class="bubble-user">🎙️ {cmd_display}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="bubble-note">{note}</div>', unsafe_allow_html=True)

    if result is None:
        st.markdown('<div class="bubble-result none">No result returned — interpreter returned None.</div>',
                    unsafe_allow_html=True)
        return

    conf = result.get("confidence")
    interp = result.get("interpretation", "—")
    sequence = result.get("sequence", [])
    pass1_sequence = result.get("pass1_sequence", [])
    composite_name = result.get("composite_name")
    is_creative = result.get("is_creative", False)
    creative_reasoning = result.get("creative_reasoning")
    user_feedback = result.get("user_feedback")
    cc = conf_class(conf)
    cl = conf_label(conf)
    conf_display = f"{conf:.2f}" if conf is not None else "—"

    # Validation badge
    validated = result.get("validated", None)
    issues = result.get("validation_issues", [])
    if validated is True and not issues:
        val_html = '<span style="color:#3ecf6e; font-size:0.75rem">✓ validated</span>'
    elif issues:
        issue_str = " · ".join(issues)
        val_html = f'<span style="color:#f0b429; font-size:0.75rem">⚠ {issue_str}</span>'
    else:
        val_html = ""

    # Creative badge
    creative_html = '<span class="creative-badge">🎨 creative</span>' if is_creative else ""

    # Composite pill
    composite_html = ""
    if composite_name:
        composite_html = f'<div><span class="composite-pill">📎 suggests composite: "{composite_name}"</span></div>'

    # Pass 1 vs Pass 2 diff (only show if they differ)
    pass_diff_html = ""
    p1_insts = [s.get("instruction") for s in pass1_sequence]
    p2_insts = [s.get("instruction") for s in sequence]
    if pass1_sequence and p1_insts != p2_insts:
        p1_html = _steps_html(pass1_sequence, dim=True)
        pass_diff_html = f"""
        <div class="pass-label">Pass 1 (before validation)</div>
        <div class="pass-diff">{p1_html}</div>
        <div class="pass-label">Pass 2 (after validation)</div>
        """

    # Final sequence
    final_steps_html = _steps_html(sequence)

    # User feedback banner
    feedback_html = ""
    strict_mode = st.session_state.get("strict_mode", False)
    if user_feedback:
        escaped_fb = str(user_feedback).replace("<", "&lt;").replace(">", "&gt;")
        feedback_html = f'<div class="feedback-banner">💬 {escaped_fb}</div>'
    elif strict_mode and conf is not None and conf < 0.6 and not is_creative:
        feedback_html = f'<div class="feedback-banner">⚠ Strict mode: confidence {conf:.2f} — would request confirmation before executing</div>'

    # Creative reasoning block
    reasoning_html = ""
    if creative_reasoning:
        escaped_cr = str(creative_reasoning)[:500].replace("<", "&lt;").replace(">", "&gt;")
        reasoning_html = f'<div class="reasoning-block">💡 {escaped_cr}</div>'

    # Raw response (if JSON parse failed)
    raw_html = ""
    raw_response = result.get("raw_response")
    if raw_response:
        escaped = raw_response[:400].replace("<", "&lt;").replace(">", "&gt;")
        raw_html = f'<div style="margin-top:6px; color:#5a6a7a; font-size:0.78rem; font-style:italic;">Raw: {escaped}</div>'

    elapsed_html = f'<div class="elapsed">⏱ {elapsed:.2f}s</div>' if elapsed is not None else ""

    st.markdown(f"""
    <div class="bubble-result {cc}">
      <span style="color:#8a9ab0; font-size:0.8rem">🤖 Robot</span>
      <span class="badge {cc}">{cl} {conf_display}</span>
      {creative_html}
      &nbsp;{val_html}
      <div class="interp">"{interp}"</div>
      {pass_diff_html}
      {final_steps_html}
      {composite_html}
      {feedback_html}
      {reasoning_html}
      {raw_html}
      {elapsed_html}
    </div>
    """, unsafe_allow_html=True)


def run_category(interpreter, category: str) -> list:
    """Run all cases in a category and return results list."""
    results = []
    for command, note in CASES[category]:
        t0 = time.time()
        try:
            result = interpreter.interpret(command)
        except Exception as e:
            result = None
        elapsed = time.time() - t0
        results.append({"command": command, "note": note, "result": result, "elapsed": elapsed})
        time.sleep(0.2)
    return results


def render_summary(results: list):
    total = len(results)
    returned = sum(1 for r in results if r["result"] is not None)
    confs = [r["result"]["confidence"] for r in results if r["result"] and "confidence" in r["result"]]
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    high   = sum(1 for c in confs if c >= 0.90)
    med    = sum(1 for c in confs if 0.75 <= c < 0.90)
    low    = sum(1 for c in confs if c < 0.75)
    composites = [r for r in results if r["result"] and r["result"].get("composite_name")]

    st.markdown(f"""
    <div class="sumrow">
      <div class="sumcard"><div class="val blue">{total}</div><div class="lbl">Cases</div></div>
      <div class="sumcard"><div class="val blue">{returned}</div><div class="lbl">Returned</div></div>
      <div class="sumcard"><div class="val {'green' if avg_conf >= 0.85 else 'yellow' if avg_conf >= 0.7 else 'red'}">{avg_conf:.2f}</div><div class="lbl">Avg conf</div></div>
      <div class="sumcard"><div class="val green">{high}</div><div class="lbl">High</div></div>
      <div class="sumcard"><div class="val yellow">{med}</div><div class="lbl">Med</div></div>
      <div class="sumcard"><div class="val red">{low}</div><div class="lbl">Low</div></div>
      <div class="sumcard"><div class="val purple">{len(composites)}</div><div class="lbl">Composites</div></div>
    </div>
    """, unsafe_allow_html=True)

    if composites:
        st.markdown("**Composite names suggested:**")
        for r in composites:
            st.markdown(f'<span class="composite-pill">📎 "{r["result"]["composite_name"]}"</span> &nbsp; <span style="color:#5a6a7a; font-size:0.82rem">← "{r["command"]}"</span>', unsafe_allow_html=True)


def get_interpreter():
    """Lazy-load interpreter into session state."""
    if "interpreter" not in st.session_state:
        with st.spinner("Loading sequence interpreter…"):
            try:
                from learning.sequence_interpreter import SequenceInterpreter
                st.session_state["interpreter"] = SequenceInterpreter()
                st.session_state["interpreter_error"] = None
            except Exception as e:
                st.session_state["interpreter"] = None
                st.session_state["interpreter_error"] = str(e)
    return st.session_state.get("interpreter"), st.session_state.get("interpreter_error")


def get_cached_results(category: str) -> Optional[list]:
    return st.session_state.get(f"results_{category}")

def set_cached_results(category: str, results: list):
    st.session_state[f"results_{category}"] = results


# ══════════════════════════════════════════════════════════════════════════════
# PAGE RENDERERS
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
    st.markdown("""
    <div style="padding: 8px 0 24px 0;">
      <div style="font-size:2.2rem; font-weight:bold; color:#4a9eff; letter-spacing:-1px;">
        🤖 GoFa Observation Runner
      </div>
      <div style="color:#5a7a9a; font-size:1rem; margin-top:4px;">
        ABB GoFa Robot Arm · Sequence Interpreter · LLM Observation Tool
      </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### What is this?")
        st.markdown("""
        <div class="instruction">
        This tool feeds voice commands to the <b>sequence interpreter LLM</b> and shows
        you exactly what it generates — interpretation, confidence, and the sequence of
        robot instructions it would execute.
        <br><br>
        It's <b>not a test suite</b>. There are no pass/fail assertions.
        It's an <b>observation tool</b> — for finding surprising outputs, breaking things,
        and showing what the system does with wild inputs.
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### How to use it")
        st.markdown("""
        <div class="instruction">
        1. Pick a <b>category tab</b> at the top<br>
        2. Hit <code>Run this category</code> — the LLM processes each command in sequence<br>
        3. Results appear as a <b>chat log</b> — user command on the right, robot response on the left<br>
        4. Each response shows: interpretation · confidence · full instruction sequence · composite name if suggested<br>
        5. Results are <b>cached per session</b> — re-running overwrites<br>
        6. Use <code>Save log</code> to export a JSON snapshot to <code>observation_logs/</code>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### The instruction tiers")
        st.markdown("""
        <div class="instruction">
        <b>Primitives</b> (LLM never calls these directly):<br>
        &nbsp;&nbsp;<code>move_to</code> · <code>move_relative</code> · <code>gripper_set</code> · <code>wait</code> · <code>set_speed</code>
        <br><br>
        <b>Composites</b> (what the LLM generates):<br>
        &nbsp;&nbsp;<code>pick_up(item)</code> · <code>place_at(location)</code> · <code>transfer(item, dest)</code><br>
        &nbsp;&nbsp;<code>add_layer(item)</code> · <code>return_to_slot()</code> · <code>return_to_stack()</code><br>
        &nbsp;&nbsp;<code>clear_assembly()</code> · <code>go_home()</code> · <code>adjust_speed(modifier)</code>
        <br><br>
        <b>Learned composites</b> (LLM suggests, written to instruction_set.json):<br>
        &nbsp;&nbsp;Named sequences of composites — e.g. <code>make_blt</code>, <code>classic_plus</code>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("### Categories")
        for key, (icon, label, desc) in CATEGORY_META.items():
            n = len(CASES[key])
            cached = "✓" if get_cached_results(key) else ""
            st.markdown(f"""
            <div class="card">
              <h4>{icon} {label} &nbsp;<span style="color:#2a4a2a; font-size:0.8rem">{cached}</span></h4>
              <p>{desc}<br><span style="color:#3a5a3a; font-size:0.78rem">{n} cases</span></p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("### Confidence mode")
        st.markdown("""
        <div class="instruction" style="margin-bottom:8px;">
        <b>Strict</b>: physical/spatial violations at low confidence trigger a user feedback message
        rather than silently executing. Creative commands are exempt — they always run.<br>
        <b>Permissive</b>: always execute regardless of confidence. Good for demos.
        </div>
        """, unsafe_allow_html=True)
        mode = st.radio(
            "Confidence mode",
            ["Permissive — always execute", "Strict — flag low confidence spatial/physical violations"],
            index=0,
            key="conf_mode",
            label_visibility="collapsed",
        )
        st.session_state["strict_mode"] = ("Strict" in mode)

        st.markdown("### Quick run")
        interpreter, err = get_interpreter()
        if err:
            st.error(f"Interpreter unavailable: {err}")
        else:
            if st.button("▶ Run ALL categories", use_container_width=True, type="primary", key="run_all"):
                for cat in CASES:
                    with st.spinner(f"Running {cat}…"):
                        results = run_category(interpreter, cat)
                        set_cached_results(cat, results)
                st.success("All categories complete. Click each tab to view results.")
                st.rerun()


def page_category(category: str):
    icon, label, desc = CATEGORY_META[category]
    cases = CASES[category]

    st.markdown(f"""
    <div style="margin-bottom: 16px;">
      <div style="font-size:1.5rem; font-weight:bold; color:#4a9eff;">{icon} {label}</div>
      <div style="color:#5a7a9a; font-size:0.9rem; margin-top:2px;">{desc}</div>
    </div>
    """, unsafe_allow_html=True)

    interpreter, err = get_interpreter()

    col_run, col_save, col_clear, _ = st.columns([2, 2, 2, 6])

    with col_run:
        run_btn = st.button(f"▶ Run {label}", type="primary", use_container_width=True,
                            disabled=interpreter is None, key=f"run_{category}")
    with col_save:
        save_btn = st.button("💾 Save log", use_container_width=True,
                             disabled=get_cached_results(category) is None,
                             key=f"save_{category}")
    with col_clear:
        clear_btn = st.button("✕ Clear", use_container_width=True,
                              disabled=get_cached_results(category) is None,
                              key=f"clear_{category}")

    if err:
        st.error(f"Interpreter error: {err}")
        return

    if run_btn:
        progress = st.progress(0, text="Starting…")
        results = []
        for i, (command, note) in enumerate(cases):
            progress.progress((i) / len(cases), text=f"[{i+1}/{len(cases)}] \"{command[:40]}\"")
            t0 = time.time()
            try:
                result = interpreter.interpret(command)
            except Exception as e:
                result = None
            elapsed = time.time() - t0
            results.append({"command": command, "note": note, "result": result, "elapsed": elapsed})
            time.sleep(0.2)
        progress.progress(1.0, text="Done.")
        set_cached_results(category, results)
        st.rerun()

    if clear_btn:
        set_cached_results(category, None)
        st.rerun()

    results = get_cached_results(category)

    if results is None:
        # Show the cases as a preview without results
        st.markdown("---")
        st.markdown(f"**{len(cases)} cases queued.** Hit Run to send them to the LLM.")
        for i, (cmd, note) in enumerate(cases):
            cmd_display = f'"{cmd}"' if cmd else '(empty string)'
            st.markdown(f"""
            <div class="bubble-user" style="opacity:0.5;">🎙️ {cmd_display}</div>
            <div class="bubble-note">{note}</div>
            <div style="height:6px;"></div>
            """, unsafe_allow_html=True)
        return

    if save_btn and results:
        log_dir = os.path.join(os.path.dirname(__file__), "observation_logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(log_dir, f"obs_{category}_{ts}.json")
        with open(path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        st.success(f"Saved → `{path}`")

    # Summary
    st.markdown("---")
    render_summary(results)
    st.markdown("---")

    # Chat log
    for i, r in enumerate(results):
        render_result_bubble(r["command"], r["note"], r["result"], r["elapsed"])

        # Secondary commands: offer "Save to memory" if LLM flagged learning intent
        res = r.get("result")
        if res and res.get("composite_name"):
            fb = (res.get("user_feedback") or "").lower()
            if "mapping" in fb or "composite" in fb or "saved" in fb:
                save_key = f"mem_{category}_{i}"
                saved_key = f"mem_saved_{category}_{i}"
                if not st.session_state.get(saved_key):
                    if st.button(f"💾 Save '{res['composite_name']}' to memory",
                                 key=save_key, use_container_width=False):
                        try:
                            from learning.memory_writer import get_memory_writer
                            writer = get_memory_writer()
                            summary = writer.process(res, source_phrase=r["command"])
                            st.session_state[saved_key] = True
                            st.success(summary["message"])
                        except Exception as e:
                            st.error(f"Memory write failed: {e}")
                else:
                    st.markdown(
                        '<span style="color:#3ecf6e; font-size:0.8rem">✓ saved to memory</span>',
                        unsafe_allow_html=True)


def page_log_viewer():
    st.markdown("""
    <div style="font-size:1.5rem; font-weight:bold; color:#4a9eff; margin-bottom:16px;">
      📋 Log Viewer
    </div>
    """, unsafe_allow_html=True)

    log_dir = os.path.join(os.path.dirname(__file__), "observation_logs")
    if not os.path.exists(log_dir):
        st.info("No observation_logs/ directory yet. Run some categories and save them.")
        return

    logs = sorted(
        [f for f in os.listdir(log_dir) if f.endswith(".json")],
        reverse=True
    )

    if not logs:
        st.info("No saved logs yet. Run a category and hit 💾 Save log.")
        return

    selected = st.selectbox("Select a log file", logs)
    path = os.path.join(log_dir, selected)

    with open(path) as f:
        data = json.load(f)

    st.markdown(f"**{len(data)} cases** in `{selected}`")

    render_summary(data)
    st.markdown("---")

    for r in data:
        render_result_bubble(
            r.get("command", ""),
            r.get("note", ""),
            r.get("result"),
            r.get("elapsed")
        )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — TAB LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    tab_labels = ["🏠 Home"] + \
                 [f"{m[0]} {m[1]}" for m in CATEGORY_META.values()] + \
                 ["📋 Logs"]

    tabs = st.tabs(tab_labels)

    with tabs[0]:
        page_home()

    for i, category in enumerate(CATEGORY_META.keys()):
        with tabs[i + 1]:
            page_category(category)

    with tabs[-1]:
        page_log_viewer()


main()
