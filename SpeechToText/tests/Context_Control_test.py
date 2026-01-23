"""
Azure Speech-to-Text with ADVANCED CONTEXTUAL UNDERSTANDING.
Features:
- Relative references (go back, return home)
- Compound movements (diagonally)
- Unit mixing (cm/mm/meters)
- Context-dependent commands (do that again, opposite)
- Natural variations (shift, nudge, slide)
- Sequential task memory
- User-oriented directions (right = robot's left)
- CLU-powered adaptive learning
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
from copy import deepcopy

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
DISTANCE_SCALE = 0.01  # 1 cm = 0.01 meters in Unity
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
CLU_ENDPOINT = os.getenv("CLU_ENDPOINT")
CLU_KEY = os.getenv("CLU_KEY")
CLU_PROJECT = "GofaVoiceBot"
CLU_DEPLOYMENT = "production"
USE_CLU = True  # Enable CLU for context understanding

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

# Enhanced phrase list with natural variations
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters", "meters",
    "shift", "nudge", "slide", "go", "travel", "head", "towards", "closer", "away",
    "diagonally", "diagonal", "back to", "return", "home", "start",
    "again", "repeat", "opposite", "reverse", "more", "less",
    "little", "bit", "tiny", "small", "large", "lot",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward"
]

# EMERGENCY halt words
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
max_queue_size = 5  # Prevent queue overflow
processing_commands = False  # Prevent simultaneous processing

# Starting position
HOME_POSITION = {"x": 0.0, "y": 0.567, "z": -0.24}
current_position = deepcopy(HOME_POSITION)
position_lock = threading.Lock()

# Context memory for adaptive commands
position_history = []  # List of all positions
last_command = None  # Last executed command for "do that again"
last_direction = None  # Last direction for "more", "opposite"
last_distance = 1.0  # Last distance for "more", "less"


def normalize_units(distance: float, text: str) -> float:
    """Convert all units to centimeters for consistency."""
    text_lower = text.lower()
    
    if "millimeter" in text_lower or "mm" in text_lower:
        return distance / 10.0  # mm to cm
    elif "meter" in text_lower and "centimeter" not in text_lower:
        return distance * 100.0  # m to cm
    else:
        return distance  # already in cm


def split_into_commands(text: str):
    """Split a sentence into multiple movement commands."""
    text = text.lower()
    separators = [
        r'\s+and\s+then\s+',
        r'\s+then\s+',
        r'\s+and\s+',
        r',\s*',
        r'\s+after\s+that\s+',
        r'\s+next\s+'
    ]
    for sep in separators:
        text = re.sub(sep, '|', text)
    commands = [cmd.strip() for cmd in text.split('|') if cmd.strip()]
    return commands


def parse_movement_command(text: str):
    """
    Parse natural language movement commands with advanced context.
    Handles:
    - Natural variations (shift, nudge, slide)
    - Compound movements (diagonally)
    - Relative references (back to start, home)
    - Context-dependent (more, less, opposite, again)
    - User-oriented directions (right = robot's left)
    """
    global last_command, last_direction, last_distance, current_position
    
    text_lower = text.lower()
    
    # Check for "go home" or "return to start"
    if any(word in text_lower for word in ["home", "start position", "go back to start", "return to start"]):
        with position_lock:
            delta = {
                "x": HOME_POSITION["x"] - current_position["x"],
                "y": HOME_POSITION["y"] - current_position["y"],
                "z": HOME_POSITION["z"] - current_position["z"]
            }
        return {"type": "absolute", "delta": delta, "description": "return home"}
    
    # Check for "go back" or "return to previous"
    if "go back" in text_lower or "previous position" in text_lower:
        if len(position_history) >= 2:
            prev_pos = position_history[-2]
            with position_lock:
                delta = {
                    "x": prev_pos["x"] - current_position["x"],
                    "y": prev_pos["y"] - current_position["y"],
                    "z": prev_pos["z"] - current_position["z"]
                }
            return {"type": "absolute", "delta": delta, "description": "go back"}
    
    # Check for "do that again" or "repeat"
    if ("again" in text_lower or "repeat" in text_lower) and last_command:
        return last_command  # Return exact same command
    
    # Check for "opposite" or "reverse"
    if ("opposite" in text_lower or "reverse" in text_lower) and last_command:
        reversed_cmd = deepcopy(last_command)
        reversed_cmd["delta"]["x"] *= -1
        reversed_cmd["delta"]["y"] *= -1
        reversed_cmd["delta"]["z"] *= -1
        return reversed_cmd
    
    # Check for contextual "more" or "less"
    if "more" in text_lower and last_direction:
        # Continue in the same direction
        modifier = 0.5  # default small increment
        if "little" in text_lower or "bit" in text_lower:
            modifier = 0.3
        elif "lot" in text_lower or "much" in text_lower:
            modifier = 2.0
        
        continued_cmd = deepcopy(last_direction)
        continued_cmd["delta"]["x"] *= modifier
        continued_cmd["delta"]["y"] *= modifier
        continued_cmd["delta"]["z"] *= modifier
        return continued_cmd
    
    if "less" in text_lower and last_direction:
        # Move back in opposite direction
        modifier = 0.5
        if "little" in text_lower or "bit" in text_lower:
            modifier = 0.3
        
        reversed_cmd = deepcopy(last_direction)
        reversed_cmd["delta"]["x"] *= -modifier
        reversed_cmd["delta"]["y"] *= -modifier
        reversed_cmd["delta"]["z"] *= -modifier
        return reversed_cmd
    
    # Extract distance with unit normalization
    default_distance = 1.0
    number_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    distance = float(number_match.group(1)) if number_match else default_distance
    distance = normalize_units(distance, text_lower)
    
    # Handle size modifiers
    if "little bit" in text_lower or "slightly" in text_lower or "tiny" in text_lower:
        distance = 0.5
    elif "small" in text_lower:
        distance = max(distance * 0.5, 0.5)
    elif "large" in text_lower or "lot" in text_lower:
        distance = distance * 2.0
    
    delta = {"x": 0.0, "y": 0.0, "z": 0.0}
    scaled_distance = distance * DISTANCE_SCALE
    
    # USER-ORIENTED DIRECTIONS (right = robot's left, etc.)
    found_direction = False
    
    # Check for diagonal movements first
    if "diagonal" in text_lower:
        if ("up" in text_lower or "upward" in text_lower) and ("right" in text_lower):
            delta["y"] = scaled_distance * 0.707
            delta["x"] = -scaled_distance * 0.707  # USER right = robot left
            found_direction = True
        elif ("up" in text_lower or "upward" in text_lower) and ("left" in text_lower):
            delta["y"] = scaled_distance * 0.707
            delta["x"] = scaled_distance * 0.707  # USER left = robot right
            found_direction = True
        elif ("down" in text_lower or "downward" in text_lower) and ("right" in text_lower):
            delta["y"] = -scaled_distance * 0.707
            delta["x"] = -scaled_distance * 0.707  # USER right = robot left
            found_direction = True
        elif ("down" in text_lower or "downward" in text_lower) and ("left" in text_lower):
            delta["y"] = -scaled_distance * 0.707
            delta["x"] = scaled_distance * 0.707  # USER left = robot right
            found_direction = True
    
    # Single direction movements (can be combined)
    if "right" in text_lower:
        delta["x"] = scaled_distance  # User/Robot orientation
        found_direction = True
    if "left" in text_lower:
        delta["x"] = -scaled_distance  # User/Robot orientation
        found_direction = True
    if "up" in text_lower or "upward" in text_lower:
        delta["y"] = scaled_distance  # Up is Y+
        found_direction = True
    if "down" in text_lower or "downward" in text_lower:
        delta["y"] = -scaled_distance  # Down is Y-
        found_direction = True
    if "forward" in text_lower or "ahead" in text_lower or "towards" in text_lower or "closer" in text_lower:
        delta["z"] = -scaled_distance  # USER forward (toward you) = robot Z-
        found_direction = True
    if "backward" in text_lower or ("back" in text_lower and "go back" not in text_lower) or "away" in text_lower:
        delta["z"] = scaled_distance  # USER backward (away from you) = robot Z+
        found_direction = True
    
    if not found_direction:
        return None
    
    # Store for context
    last_distance = distance
    result = {"type": "relative", "delta": delta, "description": text_lower}
    last_direction = deepcopy(result)
    
    return result


def apply_delta_to_position(position: dict, delta: dict) -> dict:
    """Apply a delta to a position and return the new position."""
    return {
        "x": position["x"] + delta["x"],
        "y": position["y"] + delta["y"],
        "z": position["z"] + delta["z"]
    }


def process_multi_command_sentence(text: str):
    """Process a sentence that may contain multiple movement commands."""
    global last_command, position_history, processing_commands
    
    # Prevent recursive/simultaneous processing
    if processing_commands:
        print("   ⚠ Still processing previous commands, skipping...")
        return []
    
    processing_commands = True
    
    try:
        commands = split_into_commands(text)
        
        # Limit to prevent overwhelming the system
        if len(commands) > 10:
            print(f"   ⚠ Too many commands ({len(commands)}), limiting to first 10")
            commands = commands[:10]
        
        positions = []
        
        with position_lock:
            temp_position = current_position.copy()
            
            for cmd in commands:
                parsed = parse_movement_command(cmd)
                if parsed:
                    delta = parsed["delta"]
                    temp_position = apply_delta_to_position(temp_position, delta)
                    positions.append({
                        "position": temp_position.copy(),
                        "command_text": cmd,
                        "delta": delta,
                        "type": parsed.get("type", "relative")
                    })
                    print(f"  └─ Parsed: '{cmd}' -> delta{delta}")
                    print(f"     Position: x={temp_position['x']:.3f}, y={temp_position['y']:.3f}, z={temp_position['z']:.3f}")
                    
                    # Store last successful command
                    last_command = parsed
        
        return positions
        
    finally:
        processing_commands = False


def add_positions_to_queue(positions: list):
    """Add multiple positions to the command queue and update current position."""
    global command_queue, current_position, position_history
    
    if not positions:
        return
    
    with queue_lock:
        # Check if queue is getting too full
        if len(command_queue) >= max_queue_size:
            print(f"   ⚠ Queue full ({len(command_queue)} commands), clearing oldest commands")
            # Keep only the most recent commands
            command_queue = command_queue[-(max_queue_size-len(positions)):]
        
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
                
                # Add to position history (keep last 20)
                position_history.append(pos_data["position"].copy())
                if len(position_history) > 20:
                    position_history = position_history[-20:]
            
            # Update current position to the last position in the sequence
            current_position = positions[-1]["position"].copy()
        
        save_command_queue()
        
        if len(command_queue) > max_queue_size * 0.8:
            print(f"⚠ Added {len(positions)} command(s) | Queue: {len(command_queue)}/{max_queue_size} (high)")
        else:
            print(f"✅ Added {len(positions)} command(s) | Queue: {len(command_queue)}/{max_queue_size}")


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
                print(f"   📤 Written to JSON: {latest_move}")
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
            "current_position": current_position,
            "position_history": position_history[-10:]  # Last 10 positions
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
    print("🚨 EMERGENCY SHUTDOWN TRIGGERED 🚨")
    print("="*60)
    os._exit(0)


def call_clu_predict_sdk(text: str):
    """Call Azure CLU for advanced intent understanding."""
    if not USE_CLU or not CLU_SDK_AVAILABLE:
        return None
    
    try:
        endpoint = CLU_ENDPOINT.rstrip('/')
        client = ConversationAnalysisClient(endpoint, AzureKeyCredential(CLU_KEY))
        
        task = {
            "kind": "Conversation",
            "analysisInput": {
                "conversationItem": {
                    "participantId": "1",
                    "id": "1",
                    "modality": "text",
                    "language": "en",
                    "text": text
                }
            },
            "parameters": {
                "projectName": CLU_PROJECT,
                "deploymentName": CLU_DEPLOYMENT,
                "verbose": True
            }
        }
        
        result = client.analyze_conversation(task)
        return result
        
    except Exception as e:
        print(f"   ⚠ CLU error: {str(e)}")
        return None


class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        self.last_partial_text = ""
        
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
            print("Applied phrase list boosting")
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

    def _on_recognizing(self, evt):
        """Handle partial recognition - execute commands immediately."""
        text = evt.result.text
        
        if len(text) > 0:
            print(f"\r[Partial] {text}", end='', flush=True)
        
        if check_for_emergency_words(text):
            print(f"\n🚨 [EMERGENCY HALT] - TERMINATING NOW!")
            emergency_shutdown()
        
        # Only process if text is substantially different (avoid re-processing)
        if text != self.last_partial_text and len(text) > 3:
            # Calculate how much text is new
            if text.startswith(self.last_partial_text):
                new_text = text[len(self.last_partial_text):].strip()
            else:
                new_text = text
            
            # Only process if we have meaningful new content (at least 5 chars or a complete word)
            if new_text and (len(new_text) >= 5 or ' ' in text):
                # Check if queue is manageable before adding more
                with queue_lock:
                    current_queue_size = len(command_queue)
                
                if current_queue_size < max_queue_size:
                    positions = process_multi_command_sentence(new_text)
                    if positions:
                        print()
                        add_positions_to_queue(positions)
                        print(f"➜ Robot executing!\n")
                else:
                    print(f"\n   ⚠ Queue full, waiting for robot to catch up...")
            
            self.last_partial_text = text

    def _on_recognized(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            timestamp = time.time()
            print(f"\n\n✓ [FINAL] {text}")
            
            self.last_partial_text = ""
            
            if check_for_emergency_words(text):
                print(f"🚨 [EMERGENCY HALT] - TERMINATING!")
                emergency_shutdown()
            
            # Call CLU for contextual understanding
            if USE_CLU and CLU_SDK_AVAILABLE:
                print("   🧠 Analyzing with CLU...")
                clu_result = call_clu_predict_sdk(text)
                if clu_result:
                    print(f"   ✓ CLU understanding complete")
            
            positions = process_multi_command_sentence(text)
            if positions:
                add_positions_to_queue(positions)
                print(f"➜ Final commands sent!\n")
            
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                record = {
                    "timestamp": timestamp,
                    "text": text,
                    "command_queue_length": len(command_queue),
                    "position": current_position
                }
                fh.write(json.dumps(record) + "\n")
                
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("\n⚠ [No speech recognized]\n")
            self.last_partial_text = ""

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
        print(f"🚨 Emergency: {EMERGENCY_WORDS[0]}")
        print(f"🏠 Say 'go home' to return to start")
        print(f"🔄 Say 'do that again' or 'opposite' for context")
        print(f"➕ Say 'more' or 'less' to continue direction\n")
        
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
    print("Advanced Contextual Speech-to-Robot Control")
    print("="*60)
    print(f"🚨 Emergency: {EMERGENCY_WORDS}")
    print(f"📁 Command file: {COMMAND_QUEUE_FILE}")
    print(f"📍 Home position: {HOME_POSITION}")
    print(f"🧠 CLU enabled: {USE_CLU and CLU_SDK_AVAILABLE}\n")
    
    with open(COMMAND_QUEUE_FILE, 'w') as f:
        json.dump({}, f, indent=2)
    
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

        print("🎤 Ready! Try advanced commands:")
        print("   - 'move right 5 centimeters'")
        print("   - 'go diagonally up and to the right'")
        print("   - 'move 50 millimeters left'")
        print("   - 'do that again'")
        print("   - 'opposite direction'")
        print("   - 'move a little more'")
        print("   - 'go home'\n")
        
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
        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Commands sent: {len(command_queue)}")
        print(f"Final position: {current_position}")
        print(f"Position history: {len(position_history)} moves")
        print("="*60)


if __name__ == "__main__":
    main()