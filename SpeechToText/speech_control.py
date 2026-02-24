"""
Unified Speech-to-Robot Control System
======================================

Central implementation combining:
- Low-latency partial recognition execution (from v2_baseline)
- Debounced execution with timer logic (from v2_baseline)
- "and"/"then" command combining/sequencing (from v2_baseline)
- Optional --precise mode for measurement prompting (from v3_experimental)
- Qualitative distance handling in normal mode (new)
- Duplicate execution prevention
- Position persistence with Unity

Usage:
  python speech_control.py              # Normal mode - assumes default measurements
  python speech_control.py --precise    # Precise mode - prompts for measurements if not given

Commands:
  "move right"           -> moves 1.0 unit right (or prompts in --precise mode)
  "move right a tiny bit" -> moves 0.3 units right
  "move right 5"         -> moves 5 units right
  "move right and up"    -> diagonal movement (combines into single move)
  "move right then up"   -> sequential movements (two separate moves)
  "stop" / "halt"        -> emergency shutdown

Note: gripper commands are not supported in this version.
"""

import argparse
import queue
import threading
import time
import sys
import json
import re
import os
from collections import deque
from datetime import datetime

# Global start time for relative timestamps
_start_time = None

def get_timestamp():
    """Get a relative timestamp in seconds since program start."""
    global _start_time
    if _start_time is None:
        _start_time = time.time()
    elapsed = time.time() - _start_time
    return f"[{elapsed:7.3f}s]"

import numpy as np
import sounddevice as sde
import webrtcvad
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()

# CONFIG
DISTANCE_SCALE = 0.1
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
    raise RuntimeError("Missing Azure Speech credentials. Check your .env file.")

# Audio params
SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
BYTES_PER_SAMPLE = 2

# VAD params
VAD_MODE = 2
PRE_SPEECH_FRAMES = 10
SILENCE_TIMEOUT_SECS = 0.6

# Partial recognition debounce (wait for more text before executing)
PARTIAL_DEBOUNCE_SECS = 0.5  # Wait 500ms to see if more text arrives

# Timeout for "and" commands - if we've been waiting this long, execute anyway
AND_COMMAND_TIMEOUT_SECS = 2.0  # Don't wait more than 2s for final recognition

# Phrase list for Azure boosting
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward",
    "tiny", "teensy", "little bit", "slightly", "large", "big",
]

# EMERGENCY halt words
EMERGENCY_WORDS = ["stop", "halt", "emergency", "quit", "exit"]

# Command queue file
COMMAND_QUEUE_FILE = "../UnityProject/tcp_commands.json"
LOG_FILE = "asr_log.jsonl"

import pathlib
pathlib.Path(COMMAND_QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)

# Global state
command_queue = []
queue_lock = threading.Lock()
emergency_halt = threading.Event()
current_position = {"x": 0.0, "y": 0.567, "z": -0.24}
position_lock = threading.Lock()

# Precise mode state (for --precise flag)
PRECISE_MODE = False
awaiting_measurement = threading.Event()
pending_command_direction = None
pending_command_lock = threading.Lock()


def load_current_position():
    """Load the current position from tcp_commands.json or tcp_ack.json."""
    global current_position

    # Try tcp_commands.json first
    try:
        if os.path.exists(COMMAND_QUEUE_FILE):
            with open(COMMAND_QUEUE_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    pos = json.loads(content)
                    if 'x' in pos and 'y' in pos and 'z' in pos:
                        with position_lock:
                            current_position = {"x": pos["x"], "y": pos["y"], "z": pos["z"]}
                        print(f"[OK] Loaded position from tcp_commands.json: {current_position}")
                        return True
    except Exception as e:
        print(f"[WARN] Could not load from tcp_commands.json: {e}")

    # Try tcp_ack.json as fallback
    ack_file = COMMAND_QUEUE_FILE.replace('tcp_commands.json', 'tcp_ack.json')
    try:
        if os.path.exists(ack_file):
            with open(ack_file, 'r') as f:
                content = f.read().strip()
                if content:
                    ack = json.loads(content)
                    if 'position' in ack:
                        pos = ack['position']
                        if 'x' in pos and 'y' in pos and 'z' in pos:
                            with position_lock:
                                current_position = {"x": pos["x"], "y": pos["y"], "z": pos["z"]}
                            print(f"[OK] Loaded position from tcp_ack.json: {current_position}")
                            return True
    except Exception as e:
        print(f"[WARN] Could not load from tcp_ack.json: {e}")

    print(f"[INFO] Using default position: {current_position}")
    return False


def split_into_commands(text: str):
    """
    Split a sentence into multiple movement commands.
    Returns a list of tuples: (command_text, combine_with_previous)
    - 'and' -> combine with previous (blend movements into diagonal)
    - 'then' -> execute sequentially (separate movements)
    """
    text = text.lower()

    # First, split by 'then' separators (sequential execution)
    sequential_separators = [
        r'\s+and\s+then\s+',
        r'\s+then\s+',
        r',\s*then\s+',
        r'\s+after\s+that\s+',
        r'\s+next\s+'
    ]

    for sep in sequential_separators:
        text = re.sub(sep, '|THEN|', text)

    # Split by 'and' (combine movements)
    text = re.sub(r'\s+and\s+', '|AND|', text)

    # Handle commas (treat as sequential by default)
    text = re.sub(r',\s*', '|THEN|', text)

    # Split and parse
    parts = [p.strip() for p in text.split('|') if p.strip()]
    commands = []

    for i, part in enumerate(parts):
        if part in ['THEN', 'AND']:
            continue

        combine = False
        if i > 0 and parts[i-1] == 'AND':
            combine = True

        commands.append((part, combine))

    return commands


def has_measurement(text: str) -> bool:
    """Check if the text contains a measurement (number or qualitative)."""
    text_lower = text.lower()

    # Check for explicit numbers
    if re.search(r'\d+(?:\.\d+)?', text_lower):
        return True

    # Check for qualitative measurements
    qualitative = ["little bit", "slightly", "bit", "tiny", "teensy", "small", "large", "big", "lot"]
    if any(word in text_lower for word in qualitative):
        return True

    return False


def get_direction_from_text(text: str) -> str:
    """Extract the direction from a movement command."""
    text_lower = text.lower()

    if "right" in text_lower:
        return "right"
    if "left" in text_lower:
        return "left"
    if "up" in text_lower or "upward" in text_lower:
        return "up"
    if "down" in text_lower or "downward" in text_lower:
        return "down"
    if "forward" in text_lower or "ahead" in text_lower:
        return "forward"
    if "backward" in text_lower or "back" in text_lower:
        return "backward"

    return None


def parse_movement_command(text: str):
    """Parse natural language movement commands and return delta values."""
    text_lower = text.lower()
    default_distance = 1.0

    number_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    distance = float(number_match.group(1)) if number_match else default_distance

    # Qualitative distances (only apply if no explicit number was given)
    if not number_match:
        if "tiny" in text_lower or "teensy" in text_lower or "small" in text_lower:
            distance = 0.3
        elif "little bit" in text_lower or "slightly" in text_lower or "bit" in text_lower:
            distance = 0.5
        elif "large" in text_lower or "big" in text_lower or "lot" in text_lower:
            distance = 2.0

    if "millimeter" in text_lower or "mm" in text_lower:
        distance = distance / 10.0

    delta = {"x": 0.0, "y": 0.0, "z": 0.0}
    scaled_distance = distance * DISTANCE_SCALE

    found_direction = False
    if "right" in text_lower:
        delta["x"] = scaled_distance
        found_direction = True
    if "left" in text_lower:
        delta["x"] = -scaled_distance
        found_direction = True
    if "up" in text_lower or "upward" in text_lower:
        delta["y"] = scaled_distance
        found_direction = True
    if "down" in text_lower or "downward" in text_lower:
        delta["y"] = -scaled_distance
        found_direction = True
    if "forward" in text_lower or "ahead" in text_lower:
        delta["z"] = scaled_distance
        found_direction = True
    if "backward" in text_lower or "back" in text_lower:
        delta["z"] = -scaled_distance
        found_direction = True

    if not found_direction:
        return None

    return delta


def apply_delta_to_position(position: dict, delta: dict) -> dict:
    """Apply a delta to a position and return the new position."""
    return {
        "x": position["x"] + delta["x"],
        "y": position["y"] + delta["y"],
        "z": position["z"] + delta["z"]
    }


def process_multi_command_sentence(text: str, skip_measurement_check: bool = False):
    """
    Process a sentence that may contain multiple movement commands.
    Handles 'and' (combine) and 'then' (sequential).
    In --precise mode, prompts for measurement if not given.
    """
    global pending_command_direction

    # Handle measurement response in precise mode
    if not skip_measurement_check and PRECISE_MODE:
        with pending_command_lock:
            if awaiting_measurement.is_set() and pending_command_direction:
                number_match = re.search(r'(\d+(?:\.\d+)?)', text.lower())
                if number_match:
                    distance = number_match.group(1)
                    new_command = f"move {pending_command_direction} {distance}"
                    print(f"{get_timestamp()} Applying measurement: {distance} to '{pending_command_direction}'")

                    awaiting_measurement.clear()
                    pending_command_direction = None

                    return process_multi_command_sentence(new_command, skip_measurement_check=True)
                else:
                    print(f"{get_timestamp()} [WARN] No number detected. Please say a number.")
                    return []

    commands = split_into_commands(text)
    positions = []

    with position_lock:
        temp_position = current_position.copy()
        accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
        accumulated_text = []

        for i, (cmd, combine) in enumerate(commands):
            # Check for missing measurement in precise mode
            if not skip_measurement_check and PRECISE_MODE and not has_measurement(cmd):
                direction = get_direction_from_text(cmd)
                if direction:
                    print(f"\n{get_timestamp()} Command '{cmd}' is missing a measurement.")
                    print(f"{get_timestamp()} How much? (Say a number like 5, 10, or 15)")

                    with pending_command_lock:
                        pending_command_direction = direction
                        awaiting_measurement.set()

                    return []

            delta = parse_movement_command(cmd)
            if not delta:
                continue

            if combine:
                # Combine with previous (diagonal movement)
                accumulated_delta["x"] += delta["x"]
                accumulated_delta["y"] += delta["y"]
                accumulated_delta["z"] += delta["z"]
                accumulated_text.append(cmd)
                print(f"  Combining: '{cmd}' -> delta{delta}")

                is_last = (i == len(commands) - 1)
                next_is_separate = not is_last and not commands[i+1][1]

                if is_last or next_is_separate:
                    temp_position = apply_delta_to_position(temp_position, accumulated_delta)
                    combined_text = " and ".join(accumulated_text)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": combined_text,
                        "delta": accumulated_delta.copy()
                    })
                    print(f"  [+] Combined movement: {accumulated_delta}")
                    print(f"     Position: x={temp_position['x']:.3f}, y={temp_position['y']:.3f}, z={temp_position['z']:.3f}")

                    accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    accumulated_text = []
            else:
                # Sequential command
                if accumulated_text:
                    temp_position = apply_delta_to_position(temp_position, accumulated_delta)
                    combined_text = " and ".join(accumulated_text)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": combined_text,
                        "delta": accumulated_delta.copy()
                    })
                    print(f"  [+] Combined movement: {accumulated_delta}")
                    accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    accumulated_text = []

                # Start new accumulator with this command
                accumulated_delta = delta.copy()
                accumulated_text = [cmd]

                # If this is the last command, flush it
                if i == len(commands) - 1:
                    temp_position = apply_delta_to_position(temp_position, accumulated_delta)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": cmd,
                        "delta": delta
                    })
                    print(f"  Sequential: '{cmd}' -> delta{delta}")
                    print(f"     Position: x={temp_position['x']:.3f}, y={temp_position['y']:.3f}, z={temp_position['z']:.3f}")

    return positions


def add_positions_to_queue(positions: list):
    """Add multiple positions to the command queue and update current position."""
    global command_queue, current_position

    if not positions:
        return

    with queue_lock:
        with position_lock:
            for pos_data in positions:
                command = {
                    "timestamp": datetime.now().isoformat(),
                    "command_type": "move",
                    "position": pos_data["position"],
                    "delta": pos_data["delta"],
                    "text": pos_data["command_text"]
                }
                command_queue.append(command)

            current_position = positions[-1]["position"].copy()

        save_command_queue()
        print(f"{get_timestamp()} [OK] Added {len(positions)} command(s) | Queue total: {len(command_queue)}")


def save_command_queue():
    """Save only the latest command to JSON file (overwrites previous)."""
    with open(COMMAND_QUEUE_FILE, 'w') as f:
        if command_queue:
            latest_move = None
            for cmd in reversed(command_queue):
                if cmd["command_type"] == "move":
                    latest_move = cmd["position"]
                    break

            if latest_move:
                output = {
                    "x": latest_move["x"],
                    "y": latest_move["y"],
                    "z": latest_move["z"],
                }
                json.dump(output, f, indent=2)
                print(f"{get_timestamp()}    Written to JSON: {output}")
            else:
                output = {
                    "x": current_position["x"],
                    "y": current_position["y"],
                    "z": current_position["z"],
                }
                json.dump(output, f, indent=2)
                print(f"{get_timestamp()}    Written to JSON: {output}")
        else:
            json.dump({}, f)

    # Keep detailed log separately
    detailed_file = COMMAND_QUEUE_FILE.replace('.json', '_detailed.json')
    with open(detailed_file, 'w') as f:
        json.dump({
            "commands": command_queue,
            "total_commands": len(command_queue),
            "emergency_halt": emergency_halt.is_set(),
            "current_position": current_position
        }, f, indent=2)


def check_for_emergency_words(text: str) -> bool:
    """Check if text contains any emergency halt words."""
    text_lower = text.lower().strip()
    for word in EMERGENCY_WORDS:
        if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
            return True
    return False


def emergency_shutdown():
    """Immediately shutdown the entire program."""
    print("\n" + "="*60)
    print("*** EMERGENCY SHUTDOWN TRIGGERED ***")
    print("="*60)
    os._exit(0)


class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        self.last_partial_text = ""
        self.last_partial_time = 0
        self.pending_partial_timer = None
        self.pending_and_timer = None
        self.executed_in_partial = ""
        self.partial_lock = threading.Lock()

        self.push_stream = speechsdk.audio.PushAudioInputStream()
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=SAMPLE_RATE,
            bits_per_sample=16,
            channels=CHANNELS
        )
        audio_input = speechsdk.audio.AudioConfig(stream=self.push_stream)

        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
        speech_config.output_format = speechsdk.OutputFormat.Simple
        speech_config.speech_recognition_language = "en-US"

        # Balanced endpoint detection
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "500"
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "500"
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "3000"
        )

        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_input
        )

        self.recognizer.recognizing.connect(self._on_recognizing)
        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.canceled.connect(self._on_canceled)
        self.recognizer.session_started.connect(lambda evt: print("[Session started]"))
        self.recognizer.session_stopped.connect(lambda evt: print("[Session stopped]"))

        self._apply_phrase_list(self.recognizer)
        self.recognizer.start_continuous_recognition()
        print("Azure recognizer started (continuous).")

    def _apply_phrase_list(self, recognizer):
        try:
            plist = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
            for p in PHRASE_LIST:
                plist.addPhrase(p)
            print("Applied phrase list boosting:", PHRASE_LIST)
        except Exception as e:
            print("Could not apply phrase list:", e)

    def write_audio(self, pcm_bytes: bytes):
        try:
            self.push_stream.write(pcm_bytes)
        except Exception as e:
            print("Error writing audio:", e)

    def stop(self):
        try:
            self.recognizer.stop_continuous_recognition()
        except Exception:
            pass
        try:
            self.push_stream.close()
        except Exception:
            pass

    def _execute_and_timeout(self, captured_text):
        """Execute an 'and' command after timeout - we waited long enough for final."""
        with self.partial_lock:
            if self.executed_in_partial:
                return

            if not captured_text or len(captured_text.strip()) < 3:
                return

            print()
            print(f"{get_timestamp()} AND TIMEOUT: Executing after {AND_COMMAND_TIMEOUT_SECS}s wait")
            print(f"{get_timestamp()} EXEC (timeout): '{captured_text}'")

            positions = process_multi_command_sentence(captured_text)
            if positions:
                add_positions_to_queue(positions)
                print(f"{get_timestamp()} -> Robot executing (and-timeout)!\n")
                self.executed_in_partial = captured_text

    def _execute_partial_command(self, captured_text):
        """Execute a partial command after debounce delay."""
        with self.partial_lock:
            # Don't execute if text NOW contains connectors
            current_partial = self.last_partial_text.lower()
            has_connector_current = ' and ' in current_partial or ' then ' in current_partial
            if has_connector_current:
                return

            captured_lower = captured_text.lower()
            has_connector_captured = ' and ' in captured_lower or ' then ' in captured_lower
            if has_connector_captured:
                return

            if captured_text == self.executed_in_partial:
                return

            if self.executed_in_partial and captured_text.lower().strip() in self.executed_in_partial.lower():
                return

            positions = process_multi_command_sentence(captured_text)
            if positions:
                print()
                print(f"{get_timestamp()} EXEC PARTIAL: '{captured_text}'")
                add_positions_to_queue(positions)
                print(f"{get_timestamp()} -> Robot executing partial command!\n")
                self.executed_in_partial = captured_text

    def _on_recognizing(self, evt):
        """Handle partial recognition with debouncing to avoid duplicate execution."""
        text = evt.result.text

        if len(text) > 0:
            print(f"\r{get_timestamp()} [Partial] {text}", end='', flush=True)

        if check_for_emergency_words(text):
            print(f"\n*** [EMERGENCY HALT] - TERMINATING NOW! ***")
            emergency_shutdown()

        with self.partial_lock:
            if self.pending_partial_timer:
                self.pending_partial_timer.cancel()
                self.pending_partial_timer = None

            text_lower_check = text.lower()
            has_connector = ' and ' in text_lower_check or ' then ' in text_lower_check

            if has_connector:
                self.last_partial_text = text

                if self.pending_and_timer:
                    self.pending_and_timer.cancel()
                self.pending_and_timer = threading.Timer(
                    AND_COMMAND_TIMEOUT_SECS,
                    self._execute_and_timeout,
                    args=[text]
                )
                self.pending_and_timer.start()
                return

            # Skip if text ends with incomplete words
            text_lower = text.lower().strip()
            incomplete_endings = [' and', ' then', ' and then', ' to', ' the', ' a', ' move', ' go']
            for ending in incomplete_endings:
                if text_lower.endswith(ending):
                    self.last_partial_text = text
                    return

            # Skip partial execution if phrase ends with a direction word (wait for "and X")
            direction_words = ['right', 'left', 'up', 'down', 'forward', 'forwards',
                              'backward', 'backwards', 'back', 'upward', 'upwards',
                              'downward', 'downwards']
            words = text_lower.split()
            if words and words[-1] in direction_words:
                if len(words) <= 4:
                    self.last_partial_text = text
                    return

            # Process with debounce
            if text != self.last_partial_text and len(text) > 3:
                if text != self.executed_in_partial:
                    self.pending_partial_timer = threading.Timer(
                        PARTIAL_DEBOUNCE_SECS,
                        self._execute_partial_command,
                        args=[text]
                    )
                    self.pending_partial_timer.start()

            self.last_partial_text = text

    def _on_recognized(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            timestamp = time.time()
            print(f"\n\n{get_timestamp()} [FINAL] {text}")

            with self.partial_lock:
                if self.pending_partial_timer:
                    self.pending_partial_timer.cancel()
                    self.pending_partial_timer = None
                if self.pending_and_timer:
                    self.pending_and_timer.cancel()
                    self.pending_and_timer = None

                if check_for_emergency_words(text):
                    print(f"*** [EMERGENCY HALT] - TERMINATING! ***")
                    emergency_shutdown()

                executed = self.executed_in_partial.lower().strip() if self.executed_in_partial else ""
                final_text = text.lower().strip().rstrip('.')

                if executed:
                    executed_clean = executed.rstrip('.')
                    if final_text == executed_clean or final_text.startswith(executed_clean):
                        remaining = final_text[len(executed_clean):].strip()

                        was_and_command = remaining.startswith('and ')

                        for prefix in ['and ', 'then ', 'and to the ', 'to the ']:
                            if remaining.startswith(prefix):
                                remaining = remaining[len(prefix):]

                        if remaining and len(remaining) > 2:
                            if was_and_command:
                                print(f"{get_timestamp()}   Partial already executed: '{executed}'")
                                print(f"{get_timestamp()}   [WARN] Missed combination! Executing remaining separately: '{remaining}'")
                                positions = process_multi_command_sentence(remaining)
                                if positions:
                                    add_positions_to_queue(positions)
                                    print(f"{get_timestamp()} -> Final (remaining) commands sent!\n")
                            else:
                                print(f"{get_timestamp()}   Partial already executed: '{executed}'")
                                print(f"{get_timestamp()}   Processing remaining: '{remaining}'")
                                positions = process_multi_command_sentence(remaining)
                                if positions:
                                    add_positions_to_queue(positions)
                                    print(f"{get_timestamp()} -> Final (remaining) commands sent!\n")
                        else:
                            print(f"{get_timestamp()}   Skipping (already executed in partial)\n")
                    else:
                        print(f"{get_timestamp()} EXEC FINAL (different): '{text}'")
                        positions = process_multi_command_sentence(text)
                        if positions:
                            add_positions_to_queue(positions)
                            print(f"{get_timestamp()} -> Final commands sent!\n")
                else:
                    print(f"{get_timestamp()} EXEC FINAL: '{text}'")
                    positions = process_multi_command_sentence(text)
                    if positions:
                        add_positions_to_queue(positions)
                        print(f"{get_timestamp()} -> Final commands sent!\n")

                self.last_partial_text = ""
                self.executed_in_partial = ""

            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                record = {
                    "timestamp": timestamp,
                    "text": text,
                    "command_queue_length": len(command_queue)
                }
                fh.write(json.dumps(record) + "\n")

        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("\n[No speech recognized]\n")
            with self.partial_lock:
                self.last_partial_text = ""
                self.executed_in_partial = ""

    def _on_canceled(self, evt):
        print(f"[Canceled] Reason: {evt.reason}")
        if evt.result and evt.result.cancellation_details:
            print("Details:", evt.result.cancellation_details.error_details)


def mic_capture_thread(stream_writer: MicToAzureStream, stop_event):
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(status)
        q.put_nowait(bytes(indata))

    ring = deque(maxlen=PRE_SPEECH_FRAMES)
    vad = webrtcvad.Vad(VAD_MODE)
    voiced = False
    silence_since = None

    with sde.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SIZE,
        dtype='int16',
        channels=CHANNELS,
        callback=callback
    ):
        print("Mic stream opened. Speak into the microphone.")
        print(f"Say '{EMERGENCY_WORDS[0]}' to shutdown\n")

        try:
            while not stop_event.is_set():
                try:
                    pcm_bytes = q.get(timeout=0.1)
                except queue.Empty:
                    continue

                if len(pcm_bytes) != FRAME_SIZE * BYTES_PER_SAMPLE:
                    continue

                is_speech = vad.is_speech(pcm_bytes, SAMPLE_RATE)
                ring.append(pcm_bytes)

                if is_speech:
                    if not voiced:
                        for pre in ring:
                            stream_writer.write_audio(pre)
                        voiced = True
                        silence_since = None
                    stream_writer.write_audio(pcm_bytes)
                else:
                    if voiced:
                        if silence_since is None:
                            silence_since = time.time()
                        elif time.time() - silence_since > SILENCE_TIMEOUT_SECS:
                            voiced = False
                            silence_since = None

        except KeyboardInterrupt:
            print("Mic capture interrupted.")
        except Exception as e:
            print("Exception in mic thread:", e)


def main():
    global PRECISE_MODE

    parser = argparse.ArgumentParser(description='Speech-to-Robot Control System')
    parser.add_argument('--precise', action='store_true',
                       help='Enable precise mode - prompts for measurements if not given')
    args = parser.parse_args()

    PRECISE_MODE = args.precise

    print("="*60)
    print("Speech-to-Robot Control System")
    print("="*60)
    print(f"Emergency words: {EMERGENCY_WORDS}")
    print(f"Command file: {COMMAND_QUEUE_FILE}")
    if PRECISE_MODE:
        print("Mode: PRECISE (will prompt for measurements)")
    else:
        print("Mode: NORMAL (assumes default measurements)")
        print("  - 'tiny/teensy/small' = 0.3 units")
        print("  - 'little bit/slightly' = 0.5 units")
        print("  - 'large/big' = 2.0 units")
        print("  - No qualifier = 1.0 unit")

    load_current_position()
    print(f"Start position: {current_position}\n")

    stop_event = threading.Event()
    stream_writer = None

    try:
        stream_writer = MicToAzureStream(
            speech_key=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION,
            stop_event=stop_event
        )

        mic_thread = threading.Thread(
            target=mic_capture_thread,
            args=(stream_writer, stop_event),
            daemon=True
        )
        mic_thread.start()

        print("Ready! Speak your commands...\n")

        while not stop_event.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt...")
    finally:
        if not stop_event.is_set():
            stop_event.set()
        if stream_writer:
            stream_writer.stop()
        time.sleep(0.5)
        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Commands sent: {len(command_queue)}")
        print(f"Final position: {current_position}")
        print("="*60)


if __name__ == "__main__":
    main()
