"""
Azure Speech-to-Text with multi-command parsing and cumulative position tracking.
Uses Python SDK for CLU.
"""

import queue
import threading
import time
import sys
import json
import re
from collections import deque
from datetime import datetime

import numpy as np
import sounddevice as sde
import webrtcvad
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
import os

load_dotenv()


# Try to import CLU SDK (optional)
try:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.language.conversations import ConversationAnalysisClient
    CLU_SDK_AVAILABLE = True
except ImportError:
    CLU_SDK_AVAILABLE = False
    print("WARNING: Azure CLU SDK not installed. Install with: pip install azure-ai-language-conversations")


# 
# CONFIG
# 

# Scale factor: converts centimeters to Unity units
DISTANCE_SCALE = 0.1  # 1 cm = 0.01 meters in Unity

# Azure Speech credentials
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

# Azure CLU credentials
CLU_ENDPOINT = os.getenv("CLU_ENDPOINT")
CLU_KEY = os.getenv("CLU_KEY")

# CLU config
CLU_PROJECT = "GofaVoiceBot"
CLU_DEPLOYMENT = "production"
USE_CLU = False  # Set to False to disable CLU calls for testing

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
SILENCE_TIMEOUT_SECS = 0.8

# Phrase list - added emergency words
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward"
]

# EMERGENCY halt words - checked in partial recognition for immediate response
EMERGENCY_WORDS = ["stop", "halt", "wait", "pause", "emergency"]

# Program termination words
EXIT_WORDS = ["exit program", "quit program", "shutdown", "terminate"]

# Command queue file
COMMAND_QUEUE_FILE = "../../UnityProject/tcp_commands.json"
LOG_FILE = "asr_luis_log.jsonl"

# Ensure the output directory exists
import pathlib
pathlib.Path(COMMAND_QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)

# Global command queue and emergency state
command_queue = []
queue_lock = threading.Lock()
emergency_halt = threading.Event()

# Current TCP position tracking
current_position = {"x": 0.0, "y": 0.567, "z": -0.24}
position_lock = threading.Lock()


# 
# Multi-command sentence splitter
# 
def split_into_commands(text: str):
    """
    Split a sentence into multiple movement commands.
    Examples:
    - "move up and go right 10 centimeters" -> ["move up", "go right 10 centimeters"]
    - "move right, then move down, then go left" -> ["move right", "move down", "go left"]
    """
    # Replace common separators with a delimiter
    text = text.lower()
    
    # Replace various connectors with a pipe delimiter
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
    
    # Split by pipe and clean up
    commands = [cmd.strip() for cmd in text.split('|') if cmd.strip()]
    
    return commands


# 
# Movement command parser
# 
def parse_movement_command(text: str):
    """
    Parse natural language movement commands and return delta values.
    Now handles compound directions like "up and to the left".
    Examples:
    - "move right 5 centimeters" -> {"x": 5.0, "y": 0.0, "z": 0.0}
    - "go up" -> {"x": 0.0, "y": 1.0, "z": 0.0}
    - "move up and to the left" -> {"x": -1.0, "y": 1.0, "z": 0.0}
    """
    text_lower = text.lower()
    
    # Default small movement if no number specified
    default_distance = 1.0
    
    # Extract number if present
    number_match = re.search(r'(\d+(?:\.\d+)?)', text_lower)
    distance = float(number_match.group(1)) if number_match else default_distance
    
    # Handle "a little bit" or "slightly" as small movements
    if "little bit" in text_lower or "slightly" in text_lower or "bit" in text_lower:
        distance = 0.5
    
    # Convert millimeters to centimeters for consistency
    if "millimeter" in text_lower or "mm" in text_lower:
        distance = distance / 10.0
    
    delta = {"x": 0.0, "y": 0.0, "z": 0.0}

    # Scale to Unity units (centimeters to meters)
    scaled_distance = distance * DISTANCE_SCALE
    
    # Check ALL directions (not elif - allows compound like "up and left")
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
        return None  # Not a recognized movement command
    
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
    Returns a list of positions to execute in order.
    """
    commands = split_into_commands(text)
    positions = []
    
    with position_lock:
        temp_position = current_position.copy()
        
        for cmd in commands:
            delta = parse_movement_command(cmd)
            if delta:
                temp_position = apply_delta_to_position(temp_position, delta)
                positions.append({
                    "position": temp_position.copy(),
                    "command_text": cmd,
                    "delta": delta
                })
                print(f"  â””â”€ Parsed: '{cmd}' -> {delta} -> Position: {temp_position}")
    
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
            
            # Update current position to the last position in the sequence
            current_position = positions[-1]["position"].copy()
        
        # Write positions to JSON file
        save_command_queue()
        
        print(f"âœ… [ADDED {len(positions)} COMMANDS] Total in queue: {len(command_queue)}")


def add_emergency_halt():
    """Add emergency halt to the queue."""
    global command_queue
    
    with queue_lock:
        command = {
            "timestamp": datetime.now().isoformat(),
            "command_type": "emergency_halt",
            "reason": "voice_command"
        }
        command_queue.append(command)
        save_command_queue()
        print(f"ðŸ›‘ [EMERGENCY HALT ADDED] Total commands: {len(command_queue)}")

# Multiple Command Version: save full command queue to JSON
# def save_command_queue():
#     """Save the command queue to JSON file."""
#     # Create two formats: detailed queue and simple position list
#     with open(COMMAND_QUEUE_FILE, 'w') as f:
#         # Just save the positions in simple format for robot execution
#         positions_only = [
#             cmd["position"] for cmd in command_queue 
#             if cmd["command_type"] == "move"
#         ]
#         json.dump(positions_only, f, indent=2)
    
#     # Save detailed log separately
#     detailed_file = COMMAND_QUEUE_FILE.replace('.json', '_detailed.json')
#     with open(detailed_file, 'w') as f:
#         json.dump({
#             "commands": command_queue,
#             "total_commands": len(command_queue),
#             "emergency_halt": emergency_halt.is_set(),
#             "current_position": current_position
#         }, f, indent=2)

# Single Command Version: overwrite JSON with only latest command
def save_command_queue():
    """Save only the latest command to JSON file (overwrites previous)."""
    with open(COMMAND_QUEUE_FILE, 'w') as f:
        if command_queue:
            # Get the last move command's position
            latest_move = None
            for cmd in reversed(command_queue):
                if cmd["command_type"] == "move":
                    latest_move = cmd["position"]
                    break
            
            if latest_move:
                json.dump(latest_move, f, indent=2)
            else:
                json.dump({}, f)
        else:
            json.dump({}, f)
    
    # Keep detailed log separately if you still want history
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
    
    # Check for standalone emergency words or as part of phrases
    for word in EMERGENCY_WORDS:
        # Match whole word or word with punctuation
        if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
            return True
    return False


def check_for_exit_words(text: str) -> bool:
    """Check if text contains program exit words."""
    text_lower = text.lower()
    for word in EXIT_WORDS:
        if word in text_lower:
            return True
    return False


# 
# CLU call
# 
def call_clu_predict_sdk(text: str):
    """Call Azure CLU using the Python SDK."""
    if not USE_CLU:
        return {"status": "CLU disabled in config"}
    
    if not CLU_SDK_AVAILABLE:
        return {"error": "CLU SDK not installed"}
    
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
        return {"error": f"CLU SDK error: {str(e)}"}


# 
# Audio stream handler
# 
class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        
        # Azure stream setup
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
        
        # Faster endpoint detection for short, direct commands
        # 500ms silence timeout - balance between responsive and not cutting off
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "500"
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "500"
        )

        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_input
        )

        # Attach callbacks
        self.recognizer.recognizing.connect(self._on_recognizing)
        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.canceled.connect(self._on_canceled)
        self.recognizer.session_started.connect(lambda evt: print("[Session started]"))
        self.recognizer.session_stopped.connect(lambda evt: print("[Session stopped]"))

        # Apply phrase list
        self._apply_phrase_list(self.recognizer)

        # Start recognition
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

    def _on_recognizing(self, evt):
        """Handle partial recognition - check for emergency words."""
        text = evt.result.text
        print(f"[Partial] {text}", end='\r')
        
        # Check for emergency words in partial recognition
        if check_for_emergency_words(text):
            print(f"\n[EMERGENCY DETECTED IN PARTIAL] '{text}' - HALTING NOW!")
            emergency_halt.set()
            add_emergency_halt()

    def _on_recognized(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            timestamp = time.time()
            print(f"\n[Final] {text}")
            
            # Check for exit words FIRST (highest priority)
            if check_for_exit_words(text):
                print(f"\n[EXIT] Exit command detected: '{text}' - Shutting down program...\n")
                self.stop()
                self.stop_event.set()
                return
            
            # Check for emergency words (in case partial didn't catch it)
            if check_for_emergency_words(text) and not emergency_halt.is_set():
                print(f"[EMERGENCY HALT] '{text}' - Stopping all commands!")
                emergency_halt.set()
                add_emergency_halt()
                return
            
            # Parse multi-command sentence (only if not in emergency halt)
            if not emergency_halt.is_set():
                print(f"[PARSING] Splitting sentence into commands...")
                positions = process_multi_command_sentence(text)
                if positions:
                    add_positions_to_queue(positions)
                else:
                    print(f"[INFO] No movement commands detected in: '{text}'")
            
            
            # Call CLU if enabled
            clu_out = None
            if USE_CLU:
                clu_out = call_clu_predict_sdk(text)
                if clu_out and "error" not in clu_out:
                    print("CLU Result:")
                    try:
                        print(json.dumps(dict(clu_out), indent=2))
                    except:
                        print(clu_out)
                elif clu_out and "error" in clu_out:
                    print(f"CLU Error: {clu_out['error']}")
            
            # Log to file
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                record = {
                    "timestamp": timestamp,
                    "text": text,
                    "emergency_halt": emergency_halt.is_set(),
                    "command_queue_length": len(command_queue),
                    "clu": str(clu_out) if clu_out else None
                }
                fh.write(json.dumps(record) + "\n")
                
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("[NoMatch] Speech not recognized")

    def _on_canceled(self, evt):
        print(f"[Canceled] Reason: {evt.reason}")
        if evt.result and evt.result.cancellation_details:
            print("Details:", evt.result.cancellation_details.error_details)


# 
# Microphone capture + VAD
# 
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
        print(f"Emergency halt words: {EMERGENCY_WORDS}")
        print(f"Exit program words: {EXIT_WORDS}\n")
        
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


# 
# Main
# 
def main():
    print("="*60)
    print("Multi-Command Speech-to-Robot Position Queue System")
    print("="*60)
    
    if not USE_CLU:
        print("\nâš ï¸  CLU is DISABLED - only speech recognition active\n")
    elif not CLU_SDK_AVAILABLE:
        print("\nâš ï¸  CLU SDK not installed")
        print("    To enable CLU: pip install azure-ai-language-conversations\n")
    
    print(f"Emergency halt words: {EMERGENCY_WORDS}")
    print(f"Exit program words: {EXIT_WORDS}")
    print(f"Command queue file: {COMMAND_QUEUE_FILE}")
    print(f"Absolute path: {os.path.abspath(COMMAND_QUEUE_FILE)}")
    print(f"Starting position: {current_position}\n")
    
    # Initialize empty command queue file
    with open(COMMAND_QUEUE_FILE, 'w') as f:
        json.dump([], f, indent=2)
    
    stop_event = threading.Event()
    stream_writer = None

    try:
        stream_writer = MicToAzureStream(
            speech_key=AZURE_SPEECH_KEY, 
            region=AZURE_SPEECH_REGION,
            stop_event=stop_event
        )

        # Start mic capture thread
        mic_thread = threading.Thread(
            target=mic_capture_thread, 
            args=(stream_writer, stop_event), 
            daemon=True
        )
        mic_thread.start()

        print("Running. Try saying: 'move up and go right 10 centimeters'\n")
        
        
        while not stop_event.is_set():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received...")
    finally:
        if not stop_event.is_set():
            stop_event.set()
        if stream_writer:
            stream_writer.stop()
        time.sleep(0.5)
        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Total commands in queue: {len(command_queue)}")
        print(f"Final position: {current_position}")
        print(f"Emergency halt triggered: {emergency_halt.is_set()}")
        print(f"Command queue saved to: {COMMAND_QUEUE_FILE}")
        print("="*60)


if __name__ == "__main__":
    main()