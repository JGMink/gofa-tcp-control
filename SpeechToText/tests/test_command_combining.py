#!/usr/bin/env python3
"""Test the command combining logic without needing Azure Speech."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Import the parsing functions from Latency_fix_speech
import re

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


def test_commands():
    """Test various command combinations."""
    test_cases = [
        ("move right 5cm and up 3cm", "Should combine into single diagonal"),
        ("move right 5cm then up 3cm", "Should be two sequential movements"),
        ("go left 2cm and forward 4cm and up 1cm", "Should combine all three"),
        ("move right and then go up", "Should be sequential"),
        ("go forward, then left, then down", "Should be three sequential"),
    ]

    print("\n" + "="*60)
    print("COMMAND COMBINING TEST")
    print("="*60 + "\n")

    for text, description in test_cases:
        print(f"Input: '{text}'")
        print(f"Expected: {description}")
        result = split_into_commands(text)
        print(f"Result: {len(result)} command(s)")
        for i, (cmd, combine) in enumerate(result):
            mode = "COMBINE" if combine else "SEQUENTIAL"
            print(f"  {i+1}. '{cmd}' [{mode}]")
        print()


if __name__ == "__main__":
    test_commands()
