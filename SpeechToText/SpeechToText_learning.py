"""
Azure Speech-to-Text with Self-Learning Command System.
Uses phrase bank → fuzzy matching → LLM fallback architecture.
"""

import queue
import threading
import time
import sys
import json
from collections import deque
from datetime import datetime

import numpy as np
import sounddevice as sd
import webrtcvad
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
import os

from learning.command_processor import CommandProcessor
from intent_executor import IntentExecutor

load_dotenv()

#
# CONFIG
#
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
SILENCE_TIMEOUT_SECS = 0.8

# Phrase list for Azure Speech boost
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward", "go back",
    "go home", "open gripper", "close gripper", "save this"
]

# EMERGENCY halt words (checked in partial recognition)
EMERGENCY_WORDS = ["stop", "halt", "wait", "pause", "emergency"]

# Program termination words
EXIT_WORDS = ["exit program", "quit program", "shutdown", "terminate"]

# Command queue file
COMMAND_QUEUE_FILE = "../UnityProject/tcp_commands.json"
TCP_POSITION_FILE = "../UnityProject/tcp_current_position.json"
LOG_FILE = "asr_learning_log.jsonl"

# Global emergency state
emergency_halt = threading.Event()


def read_initial_tcp_position():
    """Read the current TCP position from Unity at startup."""
    try:
        if os.path.exists(TCP_POSITION_FILE):
            with open(TCP_POSITION_FILE, 'r') as f:
                position = json.load(f)
                print(f"✓ Loaded initial TCP position: {position}")
                return position
    except Exception as e:
        print(f"Warning: Could not read TCP position file: {e}")

    default_position = {"x": 0.0, "y": 0.0, "z": 0.0}
    print(f"Using default position: {default_position}")
    return default_position


def log_recognition(text: str, result: dict):
    """Log recognition results to JSONL file."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "text": text,
        "emergency_halt": emergency_halt.is_set(),
        "result": result
    }

    try:
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"Warning: Could not write to log file: {e}")


#
# Audio stream handler
#
class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event, command_processor):
        self.stop_event = stop_event
        self.command_processor = command_processor

        # Azure stream setup
        self.push_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)

        # Add phrase list to boost recognition
        phrase_list_grammar = speechsdk.PhraseListGrammar.from_recognizer(
            speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        )
        for phrase in PHRASE_LIST:
            phrase_list_grammar.addPhrase(phrase)

        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config
        )

        # Connect callbacks
        self.recognizer.recognizing.connect(self._on_recognizing)
        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.session_started.connect(lambda evt: print("Azure session started"))
        self.recognizer.session_stopped.connect(lambda evt: print("Azure session stopped"))
        self.recognizer.canceled.connect(self._on_canceled)

        # Mic and VAD setup
        self.vad = webrtcvad.Vad(VAD_MODE)
        self.audio_queue = queue.Queue()
        self.is_speech_active = False
        self.silence_start = None
        self.pre_speech_buffer = deque(maxlen=PRE_SPEECH_FRAMES)

    def _on_recognizing(self, evt):
        """Called during partial recognition - check for emergency words."""
        partial_text = evt.result.text.lower()

        # Check for emergency halt words in partial recognition
        if any(word in partial_text for word in EMERGENCY_WORDS):
            print(f"\n⚠️  EMERGENCY HALT detected in partial: '{evt.result.text}'")
            emergency_halt.set()
            # Execute emergency stop through command processor
            self.command_processor.process_command("emergency stop")

    def _on_recognized(self, evt):
        """Called when final recognition result is available."""
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text
            text_lower = text.lower()

            print(f"\n🎤 Recognized: \"{text}\"")

            # Check for exit words
            if any(exit_word in text_lower for exit_word in EXIT_WORDS):
                print("Shutdown command detected. Exiting...")
                # Print final statistics
                self.command_processor.print_stats()
                self.stop_event.set()
                return

            # Check for emergency halt
            if any(word in text_lower for word in EMERGENCY_WORDS):
                print(f"⚠️  EMERGENCY HALT: '{text}'")
                emergency_halt.set()
                success = self.command_processor.process_command("emergency stop")
                log_recognition(text, {"action": "emergency_halt", "success": success})
                return

            # Process through learning system
            try:
                success = self.command_processor.process_command(text)
                log_recognition(text, {"success": success})

            except Exception as e:
                print(f"✗ Error processing command: {e}")
                log_recognition(text, {"success": False, "error": str(e)})

        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            print("No speech recognized")

    def _on_canceled(self, evt):
        """Called if recognition is canceled."""
        print(f"Recognition canceled: {evt}")
        if evt.reason == speechsdk.CancellationReason.Error:
            print(f"Error details: {evt.error_details}")
            self.stop_event.set()

    def mic_callback(self, indata, frames, time_info, status):
        """Sounddevice callback - receives raw audio from microphone."""
        if status:
            print(f"Mic status: {status}")

        audio_bytes = (indata * 32767).astype(np.int16).tobytes()
        self.audio_queue.put(audio_bytes)

    def process_audio(self):
        """Process audio from queue, apply VAD, and push to Azure."""
        while not self.stop_event.is_set():
            try:
                audio_chunk = self.audio_queue.get(timeout=0.1)

                # VAD check
                is_speech = self.vad.is_speech(audio_chunk, SAMPLE_RATE)

                if is_speech:
                    if not self.is_speech_active:
                        # Speech started - flush pre-speech buffer
                        self.is_speech_active = True
                        for buffered_chunk in self.pre_speech_buffer:
                            self.push_stream.write(buffered_chunk)
                        self.pre_speech_buffer.clear()

                    self.push_stream.write(audio_chunk)
                    self.silence_start = None

                else:
                    if self.is_speech_active:
                        # In speech, but this frame is silence
                        self.push_stream.write(audio_chunk)

                        if self.silence_start is None:
                            self.silence_start = time.time()
                        elif time.time() - self.silence_start > SILENCE_TIMEOUT_SECS:
                            # Silence timeout - speech ended
                            self.is_speech_active = False
                            self.silence_start = None
                    else:
                        # Not in speech - buffer for potential upcoming speech
                        self.pre_speech_buffer.append(audio_chunk)

            except queue.Empty:
                continue

    def start(self):
        """Start recognition."""
        print("Starting self-learning speech recognition...")

        # Start Azure recognizer
        self.recognizer.start_continuous_recognition()

        # Start audio processing thread
        audio_thread = threading.Thread(target=self.process_audio, daemon=True)
        audio_thread.start()

        # Start microphone stream
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='float32',
            blocksize=FRAME_SIZE,
            callback=self.mic_callback
        ):
            print("Listening... (Say 'exit program' to quit)")
            while not self.stop_event.is_set():
                time.sleep(0.1)

        # Cleanup
        self.recognizer.stop_continuous_recognition()
        print("Recognition stopped")


def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("Azure Speech-to-Text with Self-Learning System")
    print("="*60 + "\n")

    # Read initial TCP position
    initial_position = read_initial_tcp_position()

    # Initialize intent executor
    executor = IntentExecutor(
        command_queue_file=COMMAND_QUEUE_FILE,
        initial_position=initial_position
    )

    # Initialize command processor
    processor = CommandProcessor(executor, enable_llm=True)

    print("\n📚 Phrase Bank Loaded:")
    stats = processor.phrase_bank.get_stats()
    print(f"  Total phrases: {stats['total_phrases']}")
    print(f"  Named locations: {stats['named_locations']}")

    # Create stop event
    stop_event = threading.Event()

    # Create and start the stream
    stream = MicToAzureStream(AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, stop_event, processor)

    try:
        stream.start()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        stop_event.set()
        print("\nShutting down...")
        processor.print_stats()


if __name__ == "__main__":
    main()
