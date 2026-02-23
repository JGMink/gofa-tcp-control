"""
Speed Modifier Module
=====================
Detects speed-related keywords in speech commands and extracts them.

Usage:
    from speed_modifiers import extract_speed_mode, apply_speed_to_command
    
    text = "move right slowly"
    speed_mode, clean_text = extract_speed_mode(text)
    # speed_mode = "slowly", clean_text = "move right"
"""

import re

# Speed keywords and their normalized modes
SPEED_KEYWORDS = {
    "slowly": "slowly",
    "slow": "slowly",
    "very slowly": "slowly",
    
    "carefully": "carefully",
    "careful": "carefully",
    "gently": "carefully",
    "gentle": "carefully",
    "cautiously": "carefully",
    
    "quickly": "quickly",
    "quick": "quickly",
    "fast": "quickly",
    "faster": "quickly",
    "rapidly": "quickly",
    
    "messily": "messily",
    "messy": "messily",
    "roughly": "messily",
    "aggressively": "messily",
}


def extract_speed_mode(text):
    """
    Extract speed mode from text and return cleaned text.
    
    Args:
        text: The input command text (e.g., "move right slowly")
        
    Returns:
        Tuple of (speed_mode, cleaned_text)
        - speed_mode: One of "slowly", "carefully", "quickly", "messily", or "default"
        - cleaned_text: The text with speed keyword removed
    """
    detected_mode = "default"
    cleaned_text = text
    
    # Sort keywords by length (longest first) to avoid partial matches
    keywords_sorted = sorted(SPEED_KEYWORDS.keys(), key=len, reverse=True)
    
    # Check each keyword
    for keyword in keywords_sorted:
        # Create pattern with word boundaries
        pattern = r'\b' + re.escape(keyword) + r'\b'
        
        # Search case-insensitively
        if re.search(pattern, text, re.IGNORECASE):
            # Get normalized mode
            detected_mode = SPEED_KEYWORDS[keyword]
            
            # Remove the keyword from text (case-insensitive)
            cleaned_text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            
            # Clean up extra whitespace
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            
            # Remove trailing period if alone
            cleaned_text = re.sub(r'\s*\.\s*$', '', cleaned_text)
            
            break  # Use first match
    
    return detected_mode, cleaned_text


def apply_speed_to_command(command_dict, speed_mode):
    """
    Add speed_mode to a command dictionary (for JSON export).
    
    Args:
        command_dict: Dictionary with x, y, z keys
        speed_mode: Speed mode string
        
    Returns:
        Updated dictionary with speed_mode added
    """
    command_dict["speed_mode"] = speed_mode
    return command_dict


def get_speed_description(speed_mode):
    """
    Get a human-readable description of a speed mode.
    
    Args:
        speed_mode: The speed mode
        
    Returns:
        Description string
    """
    descriptions = {
        "slowly": "Moving slowly with gentle acceleration (30% speed)",
        "carefully": "Moving carefully with smooth motion (40% speed)",
        "default": "Moving at normal speed with balanced acceleration",
        "quickly": "Moving quickly with faster acceleration (200% speed)",
        "messily": "Moving rapidly with aggressive acceleration (300% speed)",
    }
    return descriptions.get(speed_mode, "Unknown speed mode")


# Self-test
if __name__ == "__main__":
    print("Speed Modifier Self-Test")
    print("=" * 70)
    
    tests = [
        ("move right slowly", "slowly"),
        ("move right slow", "slowly"),
        ("Move right slow.", "slowly"),
        ("go forward quickly", "quickly"),
        ("move up fast", "quickly"),
        ("turn right gently", "carefully"),
        ("move down carefully", "carefully"),
        ("move left", "default"),
    ]
    
    all_passed = True
    for text, expected in tests:
        speed, cleaned = extract_speed_mode(text)
        status = "✓" if speed == expected else "✗"
        print(f"{status} '{text}' -> speed='{speed}' (expected '{expected}')")
        if speed != expected:
            all_passed = False
    
    print("=" * 70)
    print("✓ PASSED" if all_passed else "✗ FAILED")