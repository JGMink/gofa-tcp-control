"""
Azure Speech-to-Text with Learning System Integration.
Uses phrase bank for known commands, falls back to LLM for unknown phrases.
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
import sounddevice as sd
import webrtcvad
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv
import os

# Import the learning system
from learning import get_processor, get_phrase_bank, get_executor

load_dotenv()


# Try to import CLU SDK (optional - now secondary to phrase bank)
try:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.language.conversations import ConversationAnalysisClient
    CLU_SDK_AVAILABLE = True
except ImportError:
    CLU_SDK_AVAILABLE = False
    print("INFO: Azure CLU SDK not installed (optional). Install with: pip install azure-ai-language-conversations")


# 
# CONFIG
# 
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")

# CLU Configuration (optional, phrase bank is primary)
CLU_ENDPOINT = os.getenv("CLU_ENDPOINT")
CLU_KEY = os.getenv("CLU_KEY")
CLU_PROJECT = os.getenv("CLU_PROJECT")
CLU_DEPLOYMENT = os.getenv("CLU_DEPLOYMENT")
USE_CLU = os.getenv("USE_CLU", "false").lower() == "true"  # Default off now

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

# Phrase list for Azure STT boosting
PHRASE_LIST = [
    "GoFa", "pick", "place", "move to", "speed", "stop", "start",
    "move right", "move left", "move up", "move down",
    "move forward", "move backward", "centimeters", "millimeters",
    "halt", "wait", "pause", "emergency", "go right", "go left",
    "go up", "go down", "go forward", "go backward",
    "go back", "previous position", "grab", "release", "let go",
    "pick up", "put down", "home", "yes", "no"
]

# EMERGENCY halt words - checked in partial recognition for immediate response
EMERGENCY_WORDS = ["stop", "halt", "wait", "pause", "emergency", "freeze"]

# Program termination words
EXIT_WORDS = ["exit program", "quit program", "shutdown", "terminate"]

# Log file
LOG_FILE = "asr_learning_log.jsonl"


# 
# CLU call (optional, secondary to phrase bank)
# 
def call_clu_predict_sdk(text: str):
    """Call Azure CLU using the Python SDK."""
    if not USE_CLU:
        return None
    
    if not CLU_SDK_AVAILABLE:
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
        print(f"CLU Error: {e}")
        return None


def check_for_emergency_words(text: str) -> bool:
    """Check if text contains any emergency halt words."""
    text_lower = text.lower().strip()
    for word in EMERGENCY_WORDS:
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
# Audio stream handler
# 
class MicToAzureStream:
    def __init__(self, speech_key, region, stop_event):
        self.stop_event = stop_event
        self.processor = get_processor()
        self.executor = get_executor()
        
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
            print(f"Applied phrase list boosting ({len(PHRASE_LIST)} phrases)")
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
        """Handle partial recognition - check for emergency words immediately!"""
        text = evt.result.text
        print(f"[Partial] {text}", end='\r')
        
        # CRITICAL: Check for emergency words in partial recognition
        if check_for_emergency_words(text):
            print(f"\n🚨 [EMERGENCY DETECTED] '{text}' - HALTING NOW!")
            self.executor.execute("emergency_stop", {})

    def _on_recognized(self, evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = evt.result.text.strip()
            timestamp = time.time()
            
            if not text:
                return
                
            print(f"\n[Recognized] {text}")
            
            # Check for exit words FIRST (highest priority)
            if check_for_exit_words(text):
                print(f"\n🛑 Exit command detected: '{text}' - Shutting down...\n")
                self.stop()
                self.stop_event.set()
                return
            
            # Check for emergency words (in case partial didn't catch it)
            if check_for_emergency_words(text):
                print(f"🚨 [EMERGENCY HALT] '{text}'")
                self.executor.execute("emergency_stop", {})
                return
            
            # Process through the learning system
            clu_result = None
            if USE_CLU:
                clu_result = call_clu_predict_sdk(text)
            
            result = self.processor.process(text, clu_result=clu_result)
            
            # Handle the result
            if result["success"]:
                msg = f"✅ {result['message']}"
                if result.get("learned"):
                    msg += " 📚"
                print(msg)
            elif result.get("needs_confirmation"):
                print(f"❓ {result['confirmation_prompt']}")
            else:
                print(f"❌ {result['message']}")
            
            # Log to file
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                record = {
                    "timestamp": timestamp,
                    "text": text,
                    "result": result,
                    "state": self.executor.get_state()
                }
                fh.write(json.dumps(record) + "\n")
                
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            pass  # Silence, don't print

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

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE, 
        blocksize=FRAME_SIZE, 
        dtype='int16',
        channels=CHANNELS, 
        callback=callback
    ):
        print("Mic stream opened. Speak into the microphone.\n")
        
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
    print("Voice-Controlled Robot with Learning System")
    print("="*60)
    
    # Initialize components
    phrase_bank = get_phrase_bank()
    executor = get_executor()
    
    print(f"\nLoaded {len(phrase_bank.get_all_phrases())} phrases")
    print(f"Known intents: {list(phrase_bank.get_all_intents().keys())}")
    print(f"Known locations: {list(phrase_bank.get_all_locations().keys())}")
    
    if USE_CLU:
        print(f"\nCLU: Enabled (secondary to phrase bank)")
    else:
        print(f"\nCLU: Disabled (phrase bank + LLM only)")
    
    print(f"\nEmergency halt words: {EMERGENCY_WORDS}")
    print(f"Exit program words: {EXIT_WORDS}")
    print(f"Starting position: {executor.current_position}")
    print("\n" + "-"*60)
    print("Try saying:")
    print("  • 'move right 5 centimeters'")
    print("  • 'go up and then go left'")
    print("  • 'go back' (returns to previous position)")
    print("  • 'go home'")
    print("  • Or try something new - I'll learn it!")
    print("-"*60 + "\n")
    
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

        while not stop_event.is_set():
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received...")
    finally:
        if not stop_event.is_set():
            stop_event.set()
        if stream_writer:
            stream_writer.stop()
        time.sleep(0.3)
        
        # Final state
        state = executor.get_state()
        print("\n" + "="*60)
        print("Program stopped.")
        print(f"Final position: {state['current_position']}")
        print(f"Commands executed: {state['queue_length']}")
        print(f"Emergency halt: {state['emergency_halt']}")
        print(f"Phrases in bank: {len(phrase_bank.get_all_phrases())}")
        print("="*60)


if __name__ == "__main__":
    main()