"""
Azure Speech-to-Text with PARTIAL RECOGNITION execution.
Key features:
- Commands execute on partial recognition (immediate response)
- Full transcription display
- Immediate emergency halt
- Measurement clarification for unspecified distances
- ISSUE: JSON is updated actively but robot doesn't move.
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

# ============================================================================
# NEW: Measurement clarification state
# ============================================================================
awaiting_measurement = threading.Event()
pending_command_direction = None
pending_command_lock = threading.Lock()


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


def has_measurement(text: str) -> bool:
    """Check if the text contains a measurement (number + optional unit)."""
    text_lower = text.lower()
    
    # Check for explicit numbers
    if re.search(r'\d+(?:\.\d+)?', text_lower):
        return True
    
    # Check for qualitative measurements
    if any(word in text_lower for word in ["little bit", "slightly", "bit"]):
        return True
    
    return False


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


def process_multi_command_sentence(text: str, skip_measurement_check: bool = False):
    """
    Process a sentence that may contain multiple movement commands.
    Handles:
    - 'and' → combine deltas into single movement
    - 'then' → separate sequential movements
    - Missing measurements → trigger clarification request
    """
    # ============================================================================
    # NEW: Check if we're responding to a measurement request
    # ============================================================================
    global pending_command_direction
    
    if not skip_measurement_check:
        with pending_command_lock:
            if awaiting_measurement.is_set() and pending_command_direction:
                # User is providing a measurement
                number_match = re.search(r'(\d+(?:\.\d+)?)', text.lower())
                if number_match:
                    distance = number_match.group(1)
                    # Reconstruct the command with the measurement
                    new_command = f"move {pending_command_direction} {distance}"
                    print(f"{get_timestamp()} 📏 Applying measurement: {distance} to '{pending_command_direction}' → '{new_command}'")
                    
                    # Clear the awaiting state FIRST
                    awaiting_measurement.clear()
                    temp_direction = pending_command_direction
                    pending_command_direction = None
                    
                    # Process the complete command with skip flag to prevent re-checking
                    return process_multi_command_sentence(new_command, skip_measurement_check=True)
                else:
                    print(f"{get_timestamp()} ⚠ No number detected in measurement response. Please say a number.")
                    return []
    
    # ============================================================================
    # Existing command processing logic
    # ============================================================================
    commands = split_into_commands(text)
    positions = []

    with position_lock:
        temp_position = current_position.copy()

    accumulated_delta = None
    last_was_combine = False

    for cmd_text, should_combine in commands:
        # ============================================================================
        # NEW: Check for missing measurement (only if not skipping check)
        # ============================================================================
        if not skip_measurement_check and not has_measurement(cmd_text):
            direction = get_direction_from_text(cmd_text)
            if direction:
                # This is a movement command without a measurement
                print(f"\n{get_timestamp()} ❓ Command '{cmd_text}' is missing a measurement.")
                print(f"{get_timestamp()} 📏 How much? (Suggested: 5cm, 10cm, or 15cm - or say any number)")
                
                with pending_command_lock:
                    pending_command_direction = direction
                    awaiting_measurement.set()
                
                # Return empty - wait for user's measurement response
                return []
        
        # ============================================================================
        # Original parsing logic continues unchanged
        # ============================================================================
        delta = parse_movement_command(cmd_text)
        if not delta:
            continue

        if should_combine:
            if accumulated_delta is None:
                accumulated_delta = delta
            else:
                accumulated_delta["x"] += delta["x"]
                accumulated_delta["y"] += delta["y"]
                accumulated_delta["z"] += delta["z"]
            last_was_combine = True
        else:
            if accumulated_delta is not None and last_was_combine:
                new_pos = apply_delta_to_position(temp_position, accumulated_delta)
                positions.append(new_pos)
                temp_position = new_pos
                accumulated_delta = None
                last_was_combine = False

            accumulated_delta = delta
            last_was_combine = False

    if accumulated_delta is not None:
        new_pos = apply_delta_to_position(temp_position, accumulated_delta)
        positions.append(new_pos)

    return positions


def add_positions_to_queue(positions: list):
    """Add positions to the command queue and save to file."""
    if not positions:
        return
    
    with queue_lock:
        command_queue.extend(positions)
        with open(COMMAND_QUEUE_FILE, "w", encoding="utf-8") as fh:
            json.dump(command_queue, fh, indent=2)
    
    with position_lock:
        global current_position
        current_position = positions[-1]


def load_current_position():
    """Load the current position from the command queue file."""
    global current_position
    if os.path.exists(COMMAND_QUEUE_FILE):
        try:
            with open(COMMAND_QUEUE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if data and isinstance(data, list) and len(data) > 0:
                    last_pos = data[-1]
                    if "x" in last_pos and "y" in last_pos and "z" in last_pos:
                        with position_lock:
                            current_position = last_pos
        except Exception as e:
            print(f"Could not load position from {COMMAND_QUEUE_FILE}: {e}")


def save_current_position():
    """Save the current position to the command queue file."""
    with position_lock:
        pos = current_position.copy()
    
    try:
        with open(COMMAND_QUEUE_FILE, "w", encoding="utf-8") as fh:
            json.dump([pos], fh, indent=2)
    except Exception as e:
        print(f"Could not save position to {COMMAND_QUEUE_FILE}: {e}")


def check_for_emergency_words(text: str) -> bool:
    """Check if text contains any emergency words."""
    text_lower = text.lower()
    for word in EMERGENCY_WORDS:
        if word in text_lower:
            return True
    return False


def emergency_shutdown():
    """Immediately terminate the program on emergency command."""
    print("\n" + "="*60)
    print("🚨 EMERGENCY SHUTDOWN INITIATED 🚨")
    print("="*60)
    save_current_position()
    emergency_halt.set()
    os._exit(0)


class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        self.stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self.stream)
        
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
        speech_config.speech_recognition_language = "en-US"
        
        phrase_list_grammar = speechsdk.PhraseListGrammar.from_recognizer(
            speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        )
        for phrase in PHRASE_LIST:
            phrase_list_grammar.addPhrase(phrase)
        
        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_config
        )
        
        self.recognizer.recognizing.connect(self._on_recognizing)
        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.canceled.connect(self._on_canceled)
        
        self.recognizer.start_continuous_recognition()
        
        self.partial_lock = threading.Lock()
        self.last_partial_text = ""
        self.executed_in_partial = ""
        self.pending_partial_timer = None
        self.pending_and_timer = None

    def write_audio(self, pcm_bytes):
        self.stream.write(pcm_bytes)

    def stop(self):
        self.recognizer.stop_continuous_recognition()
        self.stream.close()

    def _execute_partial_command(self, text: str):
        """Execute a partial recognition command after debounce."""
        with self.partial_lock:
            current_text = text.lower().strip().rstrip('.')
            executed = self.executed_in_partial.lower().strip() if self.executed_in_partial else ""
            
            if current_text == executed:
                return
            
            if executed and current_text.startswith(executed):
                remaining = current_text[len(executed):].strip()
                if not remaining or len(remaining) < 3:
                    return
            
            print(f"{get_timestamp()} ⚡ EXEC PARTIAL: '{text}'")
            positions = process_multi_command_sentence(text)
            
            if positions:
                add_positions_to_queue(positions)
                self.executed_in_partial = text
                print(f"{get_timestamp()} ➜ Partial commands sent!\n")
            else:
                print(f"{get_timestamp()}   └─ No executable commands found\n")

    def _on_recognizing(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
            text = evt.result.text
            if not text.strip():
                return
            
            print(f"{get_timestamp()} ⏳ [partial] {text}", end='\r')
            
            with self.partial_lock:
                if check_for_emergency_words(text):
                    print(f"\n🚨 [EMERGENCY HALT] Detected in partial: '{text}'")
                    emergency_shutdown()
                
                if self.pending_partial_timer:
                    self.pending_partial_timer.cancel()
                
                if self.pending_and_timer:
                    self.pending_and_timer.cancel()
                    self.pending_and_timer = None
                
                text_lower = text.lower()
                words = text_lower.split()
                
                if 'and' in words:
                    if self.pending_and_timer is None:
                        def execute_with_and():
                            self._execute_partial_command(self.last_partial_text)
                        
                        self.pending_and_timer = threading.Timer(
                            AND_COMMAND_TIMEOUT_SECS,
                            execute_with_and
                        )
                        self.pending_and_timer.start()
                else:
                    def execute_after_debounce():
                        self._execute_partial_command(self.last_partial_text)
                    
                    self.pending_partial_timer = threading.Timer(
                        PARTIAL_DEBOUNCE_SECS,
                        execute_after_debounce
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
    print(f"📏 NEW: Measurement clarification enabled")

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