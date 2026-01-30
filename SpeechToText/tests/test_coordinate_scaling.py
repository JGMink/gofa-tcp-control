#!/usr/bin/env python3
"""
Coordinate Scaling Test Tool

Interactive CLI to test if speech commands translate correctly to real-world movement.
Use this to verify the scaling factor between:
  - Speech input (e.g., "move 20 cm right")
  - TCP command coordinates sent to Unity
  - Actual robot movement in real life

SCALING PIPELINE:
  Speech: "move X cm [direction]"
       ↓
  DISTANCE_SCALE = 0.01  (cm → Unity meters)
       ↓
  Unity receives: X * 0.01 meters
       ↓
  Robot moves: ??? (depends on Unity-to-robot calibration)

USAGE:
  python test_coordinate_scaling.py

Then type commands like:
  - move 20 cm right
  - move 5 cm forward
  - move 10 cm up
  - status         (shows current position)
  - reset          (reset to starting position)
  - quit           (exit)
"""

import json
import os
import sys
import re
from datetime import datetime

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.config import DISTANCE_SCALE, COMMAND_QUEUE_FILE


# Constants
STARTING_POSITION = {"x": 0.0, "y": 0.567, "z": -0.24}

DIRECTION_DELTAS = {
    "right":    {"x": 1,  "y": 0,  "z": 0},
    "left":     {"x": -1, "y": 0,  "z": 0},
    "up":       {"x": 0,  "y": 1,  "z": 0},
    "down":     {"x": 0,  "y": -1, "z": 0},
    "forward":  {"x": 0,  "y": 0,  "z": 1},
    "backward": {"x": 0,  "y": 0,  "z": -1},
}


class CoordinateScalingTester:
    def __init__(self):
        self.current_position = STARTING_POSITION.copy()
        self.move_history = []
        self.test_log = []

    def parse_command(self, text: str) -> dict:
        """Parse a movement command from natural text."""
        text = text.lower().strip()

        # Pattern: "move X cm/centimeters [direction]" or "[direction] X cm"
        patterns = [
            # "move 20 cm right" or "move 20 centimeters to the right"
            r"move\s+(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\s+(?:to\s+(?:the\s+)?)?(\w+)",
            # "move right 20 cm"
            r"move\s+(\w+)\s+(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)",
            # "right 20 cm" or "20 cm right"
            r"(\w+)\s+(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)",
            r"(\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\s+(?:to\s+(?:the\s+)?)?(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                # Determine which group is distance vs direction
                if groups[0].replace('.', '').isdigit():
                    distance = float(groups[0])
                    direction = groups[1]
                else:
                    direction = groups[0]
                    distance = float(groups[1])

                if direction in DIRECTION_DELTAS:
                    return {"direction": direction, "distance": distance}

        return None

    def execute_move(self, direction: str, distance_cm: float) -> dict:
        """Execute a move and return the result."""
        delta_unit = DIRECTION_DELTAS[direction]
        scaled_distance = distance_cm * DISTANCE_SCALE

        delta = {
            "x": delta_unit["x"] * scaled_distance,
            "y": delta_unit["y"] * scaled_distance,
            "z": delta_unit["z"] * scaled_distance,
        }

        old_position = self.current_position.copy()
        new_position = {
            "x": self.current_position["x"] + delta["x"],
            "y": self.current_position["y"] + delta["y"],
            "z": self.current_position["z"] + delta["z"],
        }

        self.current_position = new_position

        # Log the move
        move_record = {
            "timestamp": datetime.now().isoformat(),
            "command": f"move {distance_cm} cm {direction}",
            "distance_cm": distance_cm,
            "direction": direction,
            "scale_factor": DISTANCE_SCALE,
            "scaled_distance_unity": scaled_distance,
            "delta_unity": delta,
            "old_position": old_position,
            "new_position": new_position,
        }
        self.move_history.append(move_record)

        # Save to TCP command file
        self._save_to_tcp(new_position)

        return move_record

    def _save_to_tcp(self, position: dict):
        """Save position to the TCP commands file for Unity."""
        try:
            with open(COMMAND_QUEUE_FILE, 'w') as f:
                json.dump(position, f, indent=2)
            print(f"  [TCP] Saved to: {COMMAND_QUEUE_FILE}")
        except Exception as e:
            print(f"  [TCP] Error saving: {e}")

    def reset_position(self):
        """Reset to starting position."""
        self.current_position = STARTING_POSITION.copy()
        self._save_to_tcp(self.current_position)
        self.move_history = []
        print(f"Reset to starting position: {self.current_position}")

    def print_status(self):
        """Print current status."""
        print("\n" + "=" * 60)
        print("CURRENT STATUS")
        print("=" * 60)
        print(f"Position (Unity units): {self.current_position}")
        print(f"  X: {self.current_position['x']:.4f} (left/right)")
        print(f"  Y: {self.current_position['y']:.4f} (down/up)")
        print(f"  Z: {self.current_position['z']:.4f} (backward/forward)")
        print(f"\nScale factor: {DISTANCE_SCALE} (cm → Unity)")
        print(f"  1 cm  = {1 * DISTANCE_SCALE:.4f} Unity units")
        print(f"  10 cm = {10 * DISTANCE_SCALE:.4f} Unity units")
        print(f"  20 cm = {20 * DISTANCE_SCALE:.4f} Unity units")
        print(f"\nMoves in this session: {len(self.move_history)}")
        print("=" * 60 + "\n")

    def print_help(self):
        """Print help."""
        print("""
COMMANDS:
  move X cm [direction]  - Move X centimeters in direction
                           Directions: right, left, up, down, forward, backward

  Examples:
    move 20 cm right
    move 5 cm forward
    move 10 cm up
    right 15 cm
    20 cm left

  status   - Show current position and scale info
  reset    - Reset to starting position
  history  - Show move history
  export   - Export test log to file
  quit     - Exit
""")

    def print_history(self):
        """Print move history."""
        if not self.move_history:
            print("No moves recorded yet.")
            return

        print("\n" + "=" * 60)
        print("MOVE HISTORY")
        print("=" * 60)
        for i, move in enumerate(self.move_history, 1):
            print(f"\n[{i}] {move['command']}")
            print(f"    Input: {move['distance_cm']} cm {move['direction']}")
            print(f"    Scale: × {move['scale_factor']} = {move['scaled_distance_unity']:.4f} Unity units")
            print(f"    Delta: {move['delta_unity']}")
            print(f"    Result: {move['new_position']}")
        print("=" * 60 + "\n")

    def export_log(self):
        """Export test log to file."""
        filename = f"scaling_test_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(os.path.dirname(__file__), filename)

        log_data = {
            "test_date": datetime.now().isoformat(),
            "scale_factor": DISTANCE_SCALE,
            "starting_position": STARTING_POSITION,
            "final_position": self.current_position,
            "moves": self.move_history,
        }

        with open(filepath, 'w') as f:
            json.dump(log_data, f, indent=2)

        print(f"Exported to: {filepath}")

    def run(self):
        """Run the interactive CLI."""
        print("\n" + "=" * 60)
        print("COORDINATE SCALING TEST TOOL")
        print("=" * 60)
        print(f"Scale factor: {DISTANCE_SCALE} (cm → Unity units)")
        print(f"Starting position: {STARTING_POSITION}")
        print(f"TCP output file: {COMMAND_QUEUE_FILE}")
        print("\nType 'help' for commands, 'quit' to exit.")
        print("=" * 60 + "\n")

        while True:
            try:
                user_input = input(">>> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break

            if not user_input:
                continue

            cmd = user_input.lower()

            if cmd in ("quit", "exit", "q"):
                print("Exiting...")
                break
            elif cmd == "help":
                self.print_help()
            elif cmd == "status":
                self.print_status()
            elif cmd == "reset":
                self.reset_position()
            elif cmd == "history":
                self.print_history()
            elif cmd == "export":
                self.export_log()
            else:
                # Try to parse as movement command
                parsed = self.parse_command(user_input)
                if parsed:
                    result = self.execute_move(parsed["direction"], parsed["distance"])
                    print(f"\n  Command: move {result['distance_cm']} cm {result['direction']}")
                    print(f"  Scaled:  {result['distance_cm']} × {DISTANCE_SCALE} = {result['scaled_distance_unity']:.4f} Unity units")
                    print(f"  Delta:   {result['delta_unity']}")
                    print(f"  New pos: {result['new_position']}")
                    print(f"\n  >>> MEASURE THE ROBOT NOW <<<")
                    print(f"  Expected IRL movement: {result['distance_cm']} cm {result['direction']}")
                    print()
                else:
                    print(f"Unknown command: '{user_input}'")
                    print("Type 'help' for available commands.")


def run_predefined_tests():
    """Run predefined test sequence for systematic testing."""
    print("\n" + "=" * 60)
    print("PREDEFINED SCALING TESTS")
    print("=" * 60)
    print("""
These tests help verify coordinate scaling accuracy.
After each move, measure the robot's actual displacement.

RECOMMENDED TEST SEQUENCE:

TEST 1: Baseline X-axis (Right/Left)
  - Command: "move 20 cm right"
  - Expected: Robot moves 20 cm to its right
  - Measure: Distance from starting point

TEST 2: Small movement verification
  - Command: "move 5 cm right"
  - Expected: Total 25 cm from start (or 5 cm from TEST 1 position)
  - Measure: Verify 5 cm incremental movement

TEST 3: Y-axis (Up/Down)
  - Command: "move 10 cm up"
  - Expected: Robot gripper rises 10 cm
  - Measure: Vertical displacement

TEST 4: Z-axis (Forward/Backward)
  - Command: "move 15 cm forward"
  - Expected: Robot extends 15 cm forward
  - Measure: Forward displacement

TEST 5: Return verification
  - Command: "move 20 cm left" (reverse of TEST 1)
  - Expected: Returns close to original X position
  - Measure: Should be near starting X coordinate

RECORDING YOUR RESULTS:
After each test, note:
  - Commanded distance (cm)
  - Actual measured distance (cm)
  - Difference (commanded - actual)
  - Scaling error % = (difference / commanded) × 100

If you find consistent scaling errors, the DISTANCE_SCALE
constant in intent_executor.py may need adjustment.

Current DISTANCE_SCALE = {scale}
  - If robot moves MORE than commanded: decrease scale
  - If robot moves LESS than commanded: increase scale
""".format(scale=DISTANCE_SCALE))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--tests":
        run_predefined_tests()
    else:
        tester = CoordinateScalingTester()
        tester.run()
