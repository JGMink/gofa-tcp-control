"""
Intent Executor - Converts structured intents into robot commands.
Handles position tracking, history, and command generation.
"""
import json
import threading
from typing import Dict, List, Optional
from collections import deque

from learning.config import DISTANCE_SCALE
from learning.phrase_bank import PhraseBank


class IntentExecutor:
    """
    Executes structured intents by generating robot movement commands.
    Tracks position history and named locations.
    """

    def __init__(self, command_queue_file: str, initial_position: Dict = None):
        """
        Initialize intent executor.

        Args:
            command_queue_file: Path to JSON file for Unity commands
            initial_position: Starting TCP position {x, y, z}
        """
        self.command_queue_file = command_queue_file
        self.current_position = initial_position or {"x": 0.0, "y": 0.0, "z": 0.0}
        self.position_lock = threading.Lock()

        # Position history for "go back" functionality
        self.position_history = deque(maxlen=10)  # Keep last 10 positions

        # Initialize phrase bank for named locations
        self.phrase_bank = PhraseBank(auto_save=True)

        # Command queue
        self.command_queue = []
        self.queue_lock = threading.Lock()

    def execute_intent(self, intent: str, params: Dict) -> bool:
        """
        Execute an intent and generate robot commands.

        Args:
            intent: Intent name (e.g., "move_relative", "move_to_previous")
            params: Intent parameters

        Returns:
            True if successful, False otherwise
        """
        try:
            if intent == "move_relative":
                return self._execute_move_relative(params)
            elif intent == "move_to_previous":
                return self._execute_move_to_previous(params)
            elif intent == "move_to_named":
                return self._execute_move_to_named(params)
            elif intent == "emergency_stop":
                return self._execute_emergency_stop(params)
            elif intent == "gripper_open":
                return self._execute_gripper_open(params)
            elif intent == "gripper_close":
                return self._execute_gripper_close(params)
            elif intent == "save_named_location":
                return self._execute_save_named_location(params)
            else:
                print(f"Unknown intent: {intent}")
                return False

        except Exception as e:
            print(f"Error executing intent '{intent}': {e}")
            return False

    def _execute_move_relative(self, params: Dict) -> bool:
        """Execute relative movement."""
        direction = params.get("direction", "").lower()
        distance = params.get("distance", 1.0)
        unit = params.get("unit", "cm")

        # Convert to centimeters if needed
        if unit == "mm":
            distance = distance / 10.0

        # Apply distance scale
        scaled_distance = distance * DISTANCE_SCALE

        # Calculate delta
        delta = {"x": 0.0, "y": 0.0, "z": 0.0}

        if direction == "right":
            delta["x"] = scaled_distance
        elif direction == "left":
            delta["x"] = -scaled_distance
        elif direction in ["up", "upward"]:
            delta["y"] = scaled_distance
        elif direction in ["down", "downward"]:
            delta["y"] = -scaled_distance
        elif direction in ["forward", "ahead"]:
            delta["z"] = scaled_distance
        elif direction in ["backward", "back"]:
            delta["z"] = -scaled_distance
        else:
            print(f"Unknown direction: {direction}")
            return False

        # Save current position to history before moving
        with self.position_lock:
            self.position_history.append(self.current_position.copy())

            # Apply delta to get new position
            new_position = {
                "x": self.current_position["x"] + delta["x"],
                "y": self.current_position["y"] + delta["y"],
                "z": self.current_position["z"] + delta["z"]
            }

            # Update current position
            self.current_position = new_position

        # Add to command queue
        self._add_to_queue([new_position])

        print(f"✓ Move {direction} {distance}{unit} → {new_position}")
        return True

    def _execute_move_to_previous(self, params: Dict) -> bool:
        """Return to previous position."""
        if not self.position_history:
            print("✗ No previous position in history")
            return False

        # Get last position from history
        previous_position = self.position_history.pop()

        with self.position_lock:
            # Save current before moving
            self.position_history.append(self.current_position.copy())
            self.current_position = previous_position.copy()

        self._add_to_queue([previous_position])

        print(f"✓ Returning to previous position: {previous_position}")
        return True

    def _execute_move_to_named(self, params: Dict) -> bool:
        """Move to a named location."""
        location_name = params.get("location", "")

        if not location_name:
            print("✗ No location name specified")
            return False

        # Get location from phrase bank
        location = self.phrase_bank.get_named_location(location_name)

        if not location:
            print(f"✗ Unknown location: '{location_name}'")
            return False

        # Save current position to history
        with self.position_lock:
            self.position_history.append(self.current_position.copy())
            self.current_position = location.copy()

        self._add_to_queue([location])

        print(f"✓ Moving to '{location_name}': {location}")
        return True

    def _execute_emergency_stop(self, params: Dict) -> bool:
        """Immediately halt all movement."""
        with self.queue_lock:
            self.command_queue = []

        self._write_queue()

        print("⚠️  EMERGENCY STOP - Queue cleared")
        return True

    def _execute_gripper_open(self, params: Dict) -> bool:
        """Open gripper (future hardware)."""
        print("⏳ Gripper open command (hardware not yet implemented)")
        # TODO: Add gripper control when hardware is available
        return True

    def _execute_gripper_close(self, params: Dict) -> bool:
        """Close gripper (future hardware)."""
        print("⏳ Gripper close command (hardware not yet implemented)")
        # TODO: Add gripper control when hardware is available
        return True

    def _execute_save_named_location(self, params: Dict) -> bool:
        """Save current position as a named location."""
        location_name = params.get("location", "")

        if not location_name:
            print("✗ No location name specified")
            return False

        # Save current position
        with self.position_lock:
            self.phrase_bank.save_named_location(location_name, self.current_position.copy())

        print(f"✓ Saved current position as '{location_name}': {self.current_position}")
        return True

    def _add_to_queue(self, positions: List[Dict]):
        """Add positions to command queue."""
        with self.queue_lock:
            self.command_queue.extend(positions)

        self._write_queue()

    def _write_queue(self):
        """Write command queue to JSON file for Unity."""
        with self.queue_lock:
            try:
                with open(self.command_queue_file, 'w') as f:
                    json.dump(self.command_queue, f, indent=2)
            except Exception as e:
                print(f"Error writing command queue: {e}")

    def update_position(self, position: Dict):
        """Update current position (called externally when Unity updates)."""
        with self.position_lock:
            self.current_position = position.copy()

    def get_position(self) -> Dict:
        """Get current position."""
        with self.position_lock:
            return self.current_position.copy()

    def clear_queue(self):
        """Clear command queue."""
        with self.queue_lock:
            self.command_queue = []
        self._write_queue()


def test_intent_executor():
    """Test intent executor."""
    print("\n=== Intent Executor Test ===\n")

    executor = IntentExecutor(
        command_queue_file="test_commands.json",
        initial_position={"x": 0.0, "y": 0.0, "z": 0.0}
    )

    # Test move_relative
    print("1. Testing move_relative:")
    executor.execute_intent("move_relative", {
        "direction": "right",
        "distance": 5.0,
        "unit": "cm"
    })

    # Test another move
    print("\n2. Testing another move:")
    executor.execute_intent("move_relative", {
        "direction": "up",
        "distance": 3.0,
        "unit": "cm"
    })

    # Test move_to_previous
    print("\n3. Testing move_to_previous:")
    executor.execute_intent("move_to_previous", {})

    # Test save_named_location
    print("\n4. Testing save_named_location:")
    executor.execute_intent("save_named_location", {
        "location": "test_position"
    })

    # Move somewhere else
    print("\n5. Moving away:")
    executor.execute_intent("move_relative", {
        "direction": "left",
        "distance": 10.0,
        "unit": "cm"
    })

    # Test move_to_named
    print("\n6. Testing move_to_named:")
    executor.execute_intent("move_to_named", {
        "location": "test_position"
    })

    print(f"\nFinal position: {executor.get_position()}")


if __name__ == "__main__":
    test_intent_executor()
