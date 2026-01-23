"""
Configuration for the learning system.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Claude API (for LLM interpretation)
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-20250514"  # Fast + capable

# Confidence thresholds (tune these as needed)
FUZZY_MATCH_THRESHOLD = 0.75       # Minimum similarity for phrase bank match
FUZZY_CONFIRM_THRESHOLD = 0.60    # Below this, ask for confirmation
CLU_CONFIDENCE_THRESHOLD = 0.70    # Minimum CLU confidence to trust
LLM_CONFIDENCE_THRESHOLD = 0.80    # LLM confidence to auto-learn (vs confirm)

# Paths
PHRASE_BANK_PATH = os.path.join(os.path.dirname(__file__), "phrase_bank.json")
COMMAND_QUEUE_FILE = os.path.join(os.path.dirname(__file__), "../../UnityProject/tcp_commands.json")

# Feature flags
ENABLE_FUZZY_MATCHING = True
ENABLE_LLM_FALLBACK = True
SILENT_LEARNING = True  # Learn without confirmation if confident
VERBOSE_LOGGING = True