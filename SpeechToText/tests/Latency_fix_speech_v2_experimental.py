"""
Azure Speech-to-Text with PARTIAL RECOGNITION execution.
Key features:
- Commands execute on partial recognition (immediate response)
- Full transcription display
- Immediate emergency halt
"""

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

# Try to import CLU SDK
try:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.language.conversations import ConversationAnalysisClient
    CLU_SDK_AVAILABLE = True
except ImportError:
    CLU_SDK_AVAILABLE = False
    print("WARNING: Azure CLU SDK not installed.")

# CONFIG
DISTANCE_SCALE = 0.1
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
CLU_ENDPOINT = os.getenv("CLU_ENDPOINT")
CLU_KEY = os.getenv("CLU_KEY")
CLU_PROJECT = "GofaVoiceBot"
CLU_DEPLOYMENT = "production"
USE_CLU = False

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
# Increased to 500ms to give more time for "and" to be recognized
PARTIAL_DEBOUNCE_SECS = 0.5  # Wait 500ms to see if more text arrives

# Timeout for "and" commands - if we've been waiting this long, execute anyway
AND_COMMAND_TIMEOUT_SECS = 2.0  # Don't wait more than 2s for final recognition

# Phrase list
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward"
]

# EMERGENCY halt words - these will IMMEDIATELY terminate the program
EMERGENCY_WORDS = ["stop", "halt", "emergency", "quit", "exit"]

# Command queue file
COMMAND_QUEUE_FILE = "../../UnityProject/tcp_commands.json"
LOG_FILE = "asr_luis_log.jsonl"

import pathlib
pathlib.Path(COMMAND_QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)

# Global state
command_queue = []
queue_lock = threading.Lock()
emergency_halt = threading.Event()
current_position = {"x": 0.0, "y": 0.567, "z": -0.24}
position_lock = threading.Lock()
last_processed_text = ""  # Track what we've already processed


def split_into_commands(text: str):
    """
    Split a sentence into multiple movement commands.
    Returns a list of tuples: (command_text, combine_with_previous)
    - 'and' → combine with previous (blend movements)
    - 'then' → execute sequentially (separate movements)
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

    # Replace sequential separators with '|THEN|'
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

        # Determine if this should be combined with previous
        combine = False
        if i > 0 and parts[i-1] == 'AND':
            combine = True

        commands.append((part, combine))

    return commands


def parse_movement_command(text: str):
    """Parse natural language movement commands and return delta values."""
    text_lower = text.lower()
    default_distance = 1.0
    
    number_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    distance = float(number_match.group(1)) if number_match else default_distance
    
    if "little bit" in text_lower or "slightly" in text_lower or "bit" in text_lower:
        distance = 0.5
    
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


def process_multi_command_sentence(text: str):
    """
    Process a sentence that may contain multiple movement commands.
    Handles:
    - 'and' → combine deltas into single movement
    - 'then' → separate sequential movements
    """
    commands = split_into_commands(text)
    positions = []

    with position_lock:
        temp_position = current_position.copy()
        accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
        accumulated_text = []

        for i, (cmd, combine) in enumerate(commands):
            delta = parse_movement_command(cmd)
            if not delta:
                continue

            if combine:
                # Combine with previous command (add deltas together)
                accumulated_delta["x"] += delta["x"]
                accumulated_delta["y"] += delta["y"]
                accumulated_delta["z"] += delta["z"]
                accumulated_text.append(cmd)
                print(f"  └─ Combining: '{cmd}' -> delta{delta}")

                # If this is the last command or next is not combined, execute accumulated
                is_last = (i == len(commands) - 1)
                next_is_separate = not is_last and not commands[i+1][1]

                if is_last or next_is_separate:
                    # Apply accumulated delta
                    temp_position = apply_delta_to_position(temp_position, accumulated_delta)
                    combined_text = " and ".join(accumulated_text)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": combined_text,
                        "delta": accumulated_delta.copy()
                    })
                    print(f"  ✓ Combined movement: {accumulated_delta}")
                    print(f"     Position: x={temp_position['x']:.3f}, y={temp_position['y']:.3f}, z={temp_position['z']:.3f}")

                    # Reset accumulator
                    accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    accumulated_text = []

            else:
                # Sequential command (separate movement)
                # First, flush any accumulated combined commands
                if accumulated_text:
                    temp_position = apply_delta_to_position(temp_position, accumulated_delta)
                    combined_text = " and ".join(accumulated_text)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": combined_text,
                        "delta": accumulated_delta.copy()
                    })
                    print(f"  ✓ Combined movement: {accumulated_delta}")
                    print(f"     Position: x={temp_position['x']:.3f}, y={temp_position['y']:.3f}, z={temp_position['z']:.3f}")

                    # Reset accumulator
                    accumulated_delta = {"x": 0.0, "y": 0.0, "z": 0.0}
                    accumulated_text = []

                # Now process this sequential command
                temp_position = apply_delta_to_position(temp_position, delta)
                positions.append({
                    "position": temp_position.copy(),
                    "command_text": cmd,
                    "delta": delta
                })
                print(f"  └─ Sequential: '{cmd}' -> delta{delta}")
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
        print(f"{get_timestamp()} ✅ Added {len(positions)} command(s) | Queue total: {len(command_queue)}")


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
                json.dump(latest_move, f, indent=2)
                print(f"{get_timestamp()}    📤 Written to JSON: {latest_move}")
            else:
                json.dump({}, f)
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


def load_current_position():
    """Load the current TCP position from tcp_commands.json."""
    global current_position
    try:
        if os.path.exists(COMMAND_QUEUE_FILE):
            with open(COMMAND_QUEUE_FILE, 'r') as f:
                content = f.read().strip()
                if content:  # Only load if file has content
                    unity_pos = json.loads(content)
                    # Validate it has x, y, z keys
                    if 'x' in unity_pos and 'y' in unity_pos and 'z' in unity_pos:
                        with position_lock:
                            current_position = unity_pos
                        print(f"✓ Loaded position from tcp_commands.json: {current_position}")
                        return True
    except Exception as e:
        print(f"⚠ Could not load position from tcp_commands.json ({e}), using default")
    return False


def save_current_position():
    """Save the current position to tcp_commands.json (for Unity to read on next start)."""
    try:
        with position_lock:
            pos = current_position.copy()
        with open(COMMAND_QUEUE_FILE, 'w') as f:
            json.dump(pos, f, indent=2)
        print(f"✓ Saved final position to tcp_commands.json: {pos}")
    except Exception as e:
        print(f"⚠ Could not save position: {e}")


def emergency_shutdown():
    """Immediately shutdown the entire program."""
    print("\n" + "="*60)
    print("🚨 EMERGENCY SHUTDOWN TRIGGERED 🚨")
    print("="*60)
    os._exit(0)  # Force immediate exit


class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        self.last_partial_text = ""
        self.last_partial_time = 0  # Track when last partial text arrived
        self.pending_partial_timer = None  # Timer for debounced execution
        self.pending_and_timer = None  # Timer for "and" command timeout
        self.executed_in_partial = ""  # Track what we already executed during partial
        self.partial_lock = threading.Lock()  # Protect shared state

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
            # Don't execute if we already executed something
            if self.executed_in_partial:
                return

            # Don't execute empty text
            if not captured_text or len(captured_text.strip()) < 3:
                return

            print()
            print(f"{get_timestamp()} ⏱️ AND TIMEOUT: Executing after {AND_COMMAND_TIMEOUT_SECS}s wait")
            print(f"{get_timestamp()} ⚡ EXEC (timeout): '{captured_text}'")

            positions = process_multi_command_sentence(captured_text)
            if positions:
                add_positions_to_queue(positions)
                print(f"{get_timestamp()} ➜ Robot executing (and-timeout)!\n")
                self.executed_in_partial = captured_text

    def _execute_partial_command(self, captured_text):
        """Execute a partial command after debounce delay."""
        with self.partial_lock:
            # Double-check: don't execute if text NOW contains connectors
            # (in case "and"/"then" was added after timer started)
            current_partial = self.last_partial_text.lower()
            has_connector_current = ' and ' in current_partial or ' then ' in current_partial
            if has_connector_current:
                return

            # Also check the captured text we're about to execute
            captured_lower = captured_text.lower()
            has_connector_captured = ' and ' in captured_lower or ' then ' in captured_lower
            if has_connector_captured:
                return

            # Only execute if this text hasn't been executed yet
            if captured_text == self.executed_in_partial:
                return

            # Check if captured_text is a prefix/subset of what we already executed
            if self.executed_in_partial and captured_text.lower().strip() in self.executed_in_partial.lower():
                return

            # Process the command
            positions = process_multi_command_sentence(captured_text)
            if positions:
                print()  # New line after partial text
                print(f"{get_timestamp()} ⚡ EXEC PARTIAL: '{captured_text}'")
                add_positions_to_queue(positions)
                print(f"{get_timestamp()} ➜ Robot executing partial command!\n")
                # Track what we executed
                self.executed_in_partial = captured_text

    def _on_recognizing(self, evt):
        """Handle partial recognition with debouncing to avoid duplicate execution."""
        text = evt.result.text

        # Display full transcription in real-time
        if len(text) > 0:
            print(f"\r{get_timestamp()} [Partial] {text}", end='', flush=True)

        # Check for emergency words FIRST
        if check_for_emergency_words(text):
            print(f"\n🚨 [EMERGENCY HALT] - TERMINATING NOW!")
            emergency_shutdown()

        with self.partial_lock:
            # Cancel any pending partial execution when new text arrives
            if self.pending_partial_timer:
                self.pending_partial_timer.cancel()
                self.pending_partial_timer = None

            # Skip partial processing if text contains "and" or "then" - wait for final
            # This prevents partial execution of combined commands
            # Note: "and" = combine into diagonal, "then" = sequential separate movements
            text_lower_check = text.lower()
            has_connector = ' and ' in text_lower_check or ' then ' in text_lower_check

            if has_connector:
                self.last_partial_text = text

                # Start a timeout timer - if final doesn't arrive in time, execute anyway
                if self.pending_and_timer:
                    self.pending_and_timer.cancel()
                self.pending_and_timer = threading.Timer(
                    AND_COMMAND_TIMEOUT_SECS,
                    self._execute_and_timeout,
                    args=[text]
                )
                self.pending_and_timer.start()
                return

            # Skip if text ends with incomplete words that suggest more is coming
            text_lower = text.lower().strip()
            incomplete_endings = [' and', ' then', ' and then', ' to', ' the', ' a', ' move', ' go']
            for ending in incomplete_endings:
                if text_lower.endswith(ending):
                    self.last_partial_text = text
                    return

            # IMPORTANT: Skip partial execution if phrase ends with a direction word
            # These commonly precede "and" (e.g., "move right and up")
            # We want to wait for the full phrase to preserve combining behavior
            direction_words = ['right', 'left', 'up', 'down', 'forward', 'forwards',
                              'backward', 'backwards', 'back', 'upward', 'upwards',
                              'downward', 'downwards']
            words = text_lower.split()
            if words and words[-1] in direction_words:
                # Check if this is a short phrase that likely has more coming
                # e.g., "move right" (2 words) vs "move to the right please" (5 words)
                if len(words) <= 4:
                    # Don't execute yet - wait for potential "and X"
                    self.last_partial_text = text
                    return

            # Process commands on partial recognition if text is different from last time
            # AND we haven't already executed this exact text
            if text != self.last_partial_text and len(text) > 3:
                if text != self.executed_in_partial:
                    # Start new debounce timer
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
            print(f"\n\n{get_timestamp()} ✓ [FINAL] {text}")

            with self.partial_lock:
                # Cancel any pending timers - we have final text now
                if self.pending_partial_timer:
                    self.pending_partial_timer.cancel()
                    self.pending_partial_timer = None
                if self.pending_and_timer:
                    self.pending_and_timer.cancel()
                    self.pending_and_timer = None

                # Double-check for emergency words
                if check_for_emergency_words(text):
                    print(f"🚨 [EMERGENCY HALT] - TERMINATING!")
                    emergency_shutdown()

                # Check if we already executed this (or essentially the same thing) in partial
                executed = self.executed_in_partial.lower().strip() if self.executed_in_partial else ""
                final_text = text.lower().strip().rstrip('.')

                # If partial already executed something, we need to figure out what's new
                if executed:
                    executed_clean = executed.rstrip('.')
                    # Case 1: Final is same as what we executed (just with punctuation)
                    if final_text == executed_clean or final_text.startswith(executed_clean):
                        # Check if there's genuinely new content after what we executed
                        remaining = final_text[len(executed_clean):].strip()

                        # Check if this was supposed to be a combined "and" command
                        # If so, we should NOT execute the remaining part separately
                        # because it was meant to be combined with what partial executed
                        was_and_command = remaining.startswith('and ')

                        # Remove common connectors from the beginning
                        for prefix in ['and ', 'then ', 'and to the ', 'to the ']:
                            if remaining.startswith(prefix):
                                remaining = remaining[len(prefix):]

                        if remaining and len(remaining) > 2:
                            if was_and_command:
                                # This was meant to be combined but partial executed early
                                # Execute remaining as separate movement (better than nothing)
                                # but warn about the missed combination
                                print(f"{get_timestamp()}   └─ Partial already executed: '{executed}'")
                                print(f"{get_timestamp()}   ⚠ Missed combination! Executing remaining separately: '{remaining}'")
                                positions = process_multi_command_sentence(remaining)
                                if positions:
                                    add_positions_to_queue(positions)
                                    print(f"{get_timestamp()} ➜ Final (remaining) commands sent!\n")
                            else:
                                # Sequential command ("then") - execute remaining
                                print(f"{get_timestamp()}   └─ Partial already executed: '{executed}'")
                                print(f"{get_timestamp()}   └─ Processing remaining: '{remaining}'")
                                positions = process_multi_command_sentence(remaining)
                                if positions:
                                    add_positions_to_queue(positions)
                                    print(f"{get_timestamp()} ➜ Final (remaining) commands sent!\n")
                        else:
                            print(f"{get_timestamp()}   └─ Skipping (already executed in partial)\n")
                    else:
                        # Final text is different - process the whole thing
                        # but this shouldn't happen often
                        print(f"{get_timestamp()} ⚡ EXEC FINAL (different): '{text}'")
                        positions = process_multi_command_sentence(text)
                        if positions:
                            add_positions_to_queue(positions)
                            print(f"{get_timestamp()} ➜ Final commands sent!\n")
                else:
                    # Nothing was executed in partial - process everything
                    print(f"{get_timestamp()} ⚡ EXEC FINAL: '{text}'")
                    positions = process_multi_command_sentence(text)
                    if positions:
                        add_positions_to_queue(positions)
                        print(f"{get_timestamp()} ➜ Final commands sent!\n")

                # Reset trackers for next utterance
                self.last_partial_text = ""
                self.executed_in_partial = ""

            # Log to file
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                record = {
                    "timestamp": timestamp,
                    "text": text,
                    "command_queue_length": len(command_queue)
                }
                fh.write(json.dumps(record) + "\n")

        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("\n⚠ [No speech recognized]\n")
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
        print(f"🚨 Say '{EMERGENCY_WORDS[0]}' to shutdown\n")
        
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
    print("="*60)
    print("Speech-to-Robot Control System")
    print("="*60)
    print(f"🚨 Emergency words: {EMERGENCY_WORDS}")
    print(f"📁 Command file: {COMMAND_QUEUE_FILE}")

    # Load current position from tcp_commands.json (Unity's last position)
    load_current_position()
    print(f"📍 Start position: {current_position}\n")
    
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

        print("🎤 Ready! Speak your commands...\n")
        
        while not stop_event.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n⚠ Keyboard interrupt...")
    finally:
        if not stop_event.is_set():
            stop_event.set()
        if stream_writer:
            stream_writer.stop()
        time.sleep(0.5)

        # Save final position back to tcp_commands.json
        save_current_position()

        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Commands sent: {len(command_queue)}")
        print(f"Final position: {current_position}")
        print("="*60)


if __name__ == "__main__":
    main()