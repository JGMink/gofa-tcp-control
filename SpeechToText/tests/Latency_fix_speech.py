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
    """Process a sentence that may contain multiple movement commands."""
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
                print(f"  └─ Parsed: '{cmd}' -> delta{delta}")
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
        print(f"✅ Added {len(positions)} command(s) | Queue total: {len(command_queue)}")


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
    print("🚨 EMERGENCY SHUTDOWN TRIGGERED 🚨")
    print("="*60)
    os._exit(0)  # Force immediate exit


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

    def _on_recognizing(self, evt):
        """Handle partial recognition - execute commands immediately and display full text."""
        text = evt.result.text
        
        # Display full transcription in real-time
        if len(text) > 0:
            print(f"\r[Partial] {text}", end='', flush=True)
        
        # Check for emergency words FIRST
        if check_for_emergency_words(text):
            print(f"\n🚨 [EMERGENCY HALT] - TERMINATING NOW!")
            emergency_shutdown()
        
        # Process commands on partial recognition if text is different from last time
        if text != self.last_partial_text and len(text) > 3:
            # Extract new portion of text that wasn't processed yet
            if text.startswith(self.last_partial_text):
                new_text = text[len(self.last_partial_text):].strip()
            else:
                new_text = text
            
            if new_text:
                # Try to process any complete commands in the new text
                positions = process_multi_command_sentence(new_text)
                if positions:
                    print()  # New line after partial text
                    add_positions_to_queue(positions)
                    print(f"➜ Robot executing partial command!\n")
            
            self.last_partial_text = text

    def _on_recognized(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            timestamp = time.time()
            print(f"\n\n✓ [FINAL] {text}")
            
            # Reset partial text tracker
            self.last_partial_text = ""
            
            # Double-check for emergency words
            if check_for_emergency_words(text):
                print(f"🚨 [EMERGENCY HALT] - TERMINATING!")
                emergency_shutdown()
            
            # Process any remaining commands in final text
            # (in case partial didn't catch everything)
            positions = process_multi_command_sentence(text)
            if positions:
                add_positions_to_queue(positions)
                print(f"➜ Final commands sent!\n")
            
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
    print(f"📍 Start position: {current_position}\n")
    
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
        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Commands sent: {len(command_queue)}")
        print(f"Final position: {current_position}")
        print("="*60)


if __name__ == "__main__":
    main()