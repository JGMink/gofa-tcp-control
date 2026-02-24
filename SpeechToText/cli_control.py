"""
CLI Robot Control
=================
Type movement commands to control the robot via TCP.
Uses the same command parser as speech_control.py — no LLM, no gripper.

Usage:
  python cli_control.py

Commands:
  move right              -> moves 1.0 unit right
  move right 5            -> moves 5 units right
  move right a tiny bit   -> moves 0.3 units right
  move right and up       -> diagonal movement
  move right then up      -> sequential movements
  stop / halt / quit      -> exit
"""

import json
import os
import re
import threading
from datetime import datetime

import pathlib

# ── shared config ──────────────────────────────────────────────────────────────
COMMAND_QUEUE_FILE = "../UnityProject/tcp_commands.json"
DISTANCE_SCALE = 0.1

pathlib.Path(COMMAND_QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)

# ── global state ───────────────────────────────────────────────────────────────
command_queue = []
queue_lock = threading.Lock()
current_position = {"x": 0.0, "y": 0.567, "z": -0.24}
position_lock = threading.Lock()


# ── position persistence ───────────────────────────────────────────────────────
def load_current_position():
    global current_position
    try:
        if os.path.exists(COMMAND_QUEUE_FILE):
            with open(COMMAND_QUEUE_FILE, 'r') as f:
                pos = json.loads(f.read().strip())
                if 'x' in pos and 'y' in pos and 'z' in pos:
                    with position_lock:
                        current_position = {"x": round(pos["x"], 4), "y": round(pos["y"], 4), "z": round(pos["z"], 4)}
                    print(f"[OK] Loaded position: {current_position}")
                    return
    except Exception:
        pass
    try:
        ack_file = COMMAND_QUEUE_FILE.replace('tcp_commands.json', 'tcp_ack.json')
        if os.path.exists(ack_file):
            with open(ack_file, 'r') as f:
                ack = json.loads(f.read().strip())
                pos = ack.get('position', {})
                if 'x' in pos and 'y' in pos and 'z' in pos:
                    with position_lock:
                        current_position = {"x": round(pos["x"], 4), "y": round(pos["y"], 4), "z": round(pos["z"], 4)}
                    print(f"[OK] Loaded position from ack: {current_position}")
                    return
    except Exception:
        pass
    print(f"[INFO] Using default position: {current_position}")


def save_position():
    with position_lock:
        output = {
            "x": round(current_position["x"], 4),
            "y": round(current_position["y"], 4),
            "z": round(current_position["z"], 4),
        }
    with open(COMMAND_QUEUE_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"         Written to JSON: {output}")


# ── command parsing (mirrors speech_control.py) ────────────────────────────────
def split_into_commands(text: str):
    text = text.lower()
    for sep in [r'\s+and\s+then\s+', r'\s+then\s+', r',\s*then\s+',
                r'\s+after\s+that\s+', r'\s+next\s+']:
        text = re.sub(sep, '|THEN|', text)
    text = re.sub(r'\s+and\s+', '|AND|', text)
    text = re.sub(r',\s*', '|THEN|', text)

    parts = [p.strip() for p in text.split('|') if p.strip()]
    commands = []
    for i, part in enumerate(parts):
        if part in ('THEN', 'AND'):
            continue
        combine = i > 0 and parts[i - 1] == 'AND'
        commands.append((part, combine))
    return commands


def parse_movement_command(text: str):
    text_lower = text.lower()
    number_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    distance = float(number_match.group(1)) if number_match else 1.0

    if not number_match:
        if any(w in text_lower for w in ("tiny", "teensy", "small")):
            distance = 0.3
        elif any(w in text_lower for w in ("little bit", "slightly", "bit")):
            distance = 0.5
        elif any(w in text_lower for w in ("large", "big", "lot")):
            distance = 2.0

    # DISTANCE_SCALE=0.1 means raw units → metres (1 unit = 0.1m = 10cm)
    # cm: divide by 10 so 20cm → 2 units → 0.2m
    # mm: divide by 100 so 20mm → 0.2 units → 0.02m
    if "centimeter" in text_lower or "cm" in text_lower:
        distance /= 10.0
    elif "millimeter" in text_lower or "mm" in text_lower:
        distance /= 100.0

    delta = {"x": 0.0, "y": 0.0, "z": 0.0}
    scaled = round(distance * DISTANCE_SCALE, 4)
    found = False

    if "right"    in text_lower:                           delta["x"] =  scaled; found = True
    if "left"     in text_lower:                           delta["x"] = -scaled; found = True
    if "up"       in text_lower or "upward"   in text_lower: delta["y"] =  scaled; found = True
    if "down"     in text_lower or "downward" in text_lower: delta["y"] = -scaled; found = True
    if "forward"  in text_lower or "ahead"    in text_lower: delta["z"] =  scaled; found = True
    if "backward" in text_lower or "back"     in text_lower: delta["z"] = -scaled; found = True

    return delta if found else None


def apply_delta(position, delta):
    return {
        "x": position["x"] + delta["x"],
        "y": position["y"] + delta["y"],
        "z": position["z"] + delta["z"],
    }


def process_command(text: str):
    commands = split_into_commands(text)
    positions = []

    with position_lock:
        temp_pos = current_position.copy()
        acc_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
        acc_text = []

        for i, (cmd, combine) in enumerate(commands):
            delta = parse_movement_command(cmd)
            if not delta:
                print(f"  [?] Unrecognised: '{cmd}'")
                continue

            is_last = (i == len(commands) - 1)
            next_separate = not is_last and not commands[i + 1][1]

            if combine:
                acc_delta["x"] += delta["x"]
                acc_delta["y"] += delta["y"]
                acc_delta["z"] += delta["z"]
                acc_text.append(cmd)
                print(f"  Combining: '{cmd}' -> {delta}")

                if is_last or next_separate:
                    temp_pos = apply_delta(temp_pos, acc_delta)
                    positions.append({
                        "position": temp_pos.copy(),
                        "command_text": " and ".join(acc_text),
                        "delta": acc_delta.copy(),
                    })
                    print(f"  [+] Combined: {acc_delta} => {temp_pos}")
                    acc_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    acc_text = []
            else:
                if acc_text:
                    temp_pos = apply_delta(temp_pos, acc_delta)
                    positions.append({
                        "position": temp_pos.copy(),
                        "command_text": " and ".join(acc_text),
                        "delta": acc_delta.copy(),
                    })
                    acc_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    acc_text = []

                acc_delta = delta.copy()
                acc_text = [cmd]

                if is_last:
                    temp_pos = apply_delta(temp_pos, acc_delta)
                    positions.append({
                        "position": temp_pos.copy(),
                        "command_text": cmd,
                        "delta": delta,
                    })
                    print(f"  Sequential: '{cmd}' -> {delta} => {temp_pos}")

    return positions


def execute_positions(positions):
    global current_position, command_queue
    if not positions:
        return
    with queue_lock:
        with position_lock:
            for p in positions:
                command_queue.append({
                    "timestamp": datetime.now().isoformat(),
                    "command_type": "move",
                    "position": p["position"],
                    "delta": p["delta"],
                    "text": p["command_text"],
                })
            current_position = positions[-1]["position"].copy()
    save_position()
    print(f"  -> {len(positions)} command(s) sent. Position: {current_position}\n")


# ── main loop ──────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("CLI Robot Control  (no LLM, no gripper)")
    print("=" * 55)
    print("Type movement commands, e.g.:")
    print("  move right 5")
    print("  move up and forward")
    print("  move left then down 3")
    print("  stop / quit  ->  exit\n")

    load_current_position()
    print(f"Start position: {current_position}\n")

    STOP_WORDS = {"stop", "halt", "quit", "exit", "q"}

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not text:
            continue

        if text.lower() in STOP_WORDS:
            print("Exiting.")
            break

        positions = process_command(text)
        execute_positions(positions)


if __name__ == "__main__":
    main()
