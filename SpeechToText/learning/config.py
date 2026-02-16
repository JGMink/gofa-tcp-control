"""
Configuration for LLM-based intent interpretation.
"""
import os
from dotenv import load_dotenv

# Load .env from SpeechToText/ regardless of working directory
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=_env_path, override=True)

# Anthropic Claude API configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")  # Haiku is fast and cheap

# Distance scale (should match main config)
DISTANCE_SCALE = 0.01  # Centimeters to Unity units

# Emergency and exit words
EMERGENCY_WORDS = ["stop", "halt", "wait", "pause", "emergency"]
EXIT_WORDS = ["exit program", "quit program", "shutdown", "terminate"]

# Default movement distance when not specified
DEFAULT_DISTANCE_CM = 1.0

# Fuzzy matching threshold (0.0-1.0)
# Higher = more strict, Lower = more lenient
# Lowered to 0.6 to catch more variations like "move up into the left"
FUZZY_MATCH_THRESHOLD = float(os.getenv("FUZZY_MATCH_THRESHOLD", "0.6"))

# LLM confidence threshold for auto-learning
# Only save phrases if LLM is this confident
# Lowered to 0.8 since we have a more detailed prompt now
LLM_CONFIDENCE_THRESHOLD = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.80"))

# Command queue file path (relative to SpeechToText directory)
COMMAND_QUEUE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "UnityProject", "tcp_commands.json")

# Verbose logging for debugging
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "false").lower() == "true"
