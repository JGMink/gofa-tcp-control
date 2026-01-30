"""
Intent Executor - Maps intents to robot commands.
Contains the actual logic for what each intent does.
"""

import json
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

from .config import COMMAND_QUEUE_FILE, VERBOSE_LOGGING
from .phrase_bank import get_phrase_bank


# Scale factor: converts centimeters to Unity units
DISTANCE_SCALE = 0.01  # Adjust as needed


class IntentExecutor:
    """
    Executes intents and produces robot commands.
    Maintains state like position history.
    """

    def __init__(self, command_queue_file: str = None, write_to_file: bool = True):
        self.command_queue_file = command_queue_file or COMMAND_QUEUE_FILE
        self.write_to_file = write_to_file  # Whether to write to JSON (disable if main script handles it)

        # Position tracking
        self.current_position = {"x": 0.0, "y": 0.567, "z": -0.24}  # Starting position
        self.position_history: List[dict] = [self.current_position.copy()]
        self.max_history = 50
        
        # Gripper state
        self.gripper_state = "open"  # "open", "closed", "unknown"
        
        # Command queue
        self.command_queue: List[dict] = []
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Emergency halt flag
        self.emergency_halt = threading.Event()
        
        # Direction to delta mapping
        self.direction_deltas = {
            "right":    {"x": 1, "y": 0, "z": 0},
            "left":     {"x": -1, "y": 0, "z": 0},
            "up":       {"x": 0, "y": 1, "z": 0},
            "down":     {"x": 0, "y": -1, "z": 0},
            "forward":  {"x": 0, "y": 0, "z": 1},
            "backward": {"x": 0, "y": 0, "z": -1},
        }

        # Don't initialize/overwrite command file on startup
        # This preserves existing position from Unity
    
    def execute_intent(self, intent: str, parameters: dict = None) -> bool:
        """
        Execute an intent (alias for CommandProcessor compatibility).
        Returns True if successful.
        """
        result = self.execute(intent, parameters)
        return result is not None and result.get("command_type") != "not_implemented"

    def execute(self, intent: str, parameters: dict = None) -> Optional[Dict[str, Any]]:
        """
        Execute an intent and return the command to send to the robot.

        Returns:
            Command dict to add to queue, or None if no command needed.
        """
        parameters = parameters or {}
        phrase_bank = get_phrase_bank()
        
        # Check if intent is implemented
        if not phrase_bank.is_intent_implemented(intent):
            message = phrase_bank.get_not_implemented_message(intent)
            print(f"[IntentExecutor] ⚠️ {message}")
            return {"command_type": "not_implemented", "message": message, "intent": intent}
        
        # Check emergency halt
        if self.emergency_halt.is_set() and intent != "resume":
            print("[IntentExecutor] ⚠️ Emergency halt active - ignoring command")
            return None
        
        # Route to handler
        handler_map = {
            "move_relative": self._handle_move_relative,
            "move_to_previous": self._handle_move_to_previous,
            "move_to_named": self._handle_move_to_named,
            "save_named_location": self._handle_save_location,
            "gripper_open": self._handle_gripper_open,
            "gripper_close": self._handle_gripper_close,
            "emergency_stop": self._handle_emergency_stop,
            "resume": self._handle_resume,
        }
        
        handler = handler_map.get(intent)
        if handler:
            command = handler(parameters)
            if command:
                self._add_to_queue(command)
            return command
        else:
            print(f"[IntentExecutor] Unknown intent: {intent}")
            return None
    
    def _handle_move_relative(self, params: dict) -> Optional[dict]:
        """Handle relative movement in a direction."""
        direction = params.get("direction")
        distance = params.get("distance", 1.0)  # Default 1 cm
        
        if direction not in self.direction_deltas:
            print(f"[IntentExecutor] Unknown direction: {direction}")
            return None
        
        delta_unit = self.direction_deltas[direction]
        scaled_distance = distance * DISTANCE_SCALE
        
        delta = {
            "x": delta_unit["x"] * scaled_distance,
            "y": delta_unit["y"] * scaled_distance,
            "z": delta_unit["z"] * scaled_distance,
        }
        
        with self.lock:
            new_position = {
                "x": self.current_position["x"] + delta["x"],
                "y": self.current_position["y"] + delta["y"],
                "z": self.current_position["z"] + delta["z"],
            }
            self._update_position(new_position)
        
        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Move {direction} {distance}cm → {new_position}")
        
        return {
            "command_type": "move",
            "position": new_position,
            "delta": delta,
            "direction": direction,
            "distance": distance
        }
    
    def _handle_move_to_previous(self, params: dict) -> Optional[dict]:
        """Move to the previous position."""
        with self.lock:
            if len(self.position_history) < 2:
                print("[IntentExecutor] No previous position to return to")
                return None
            
            # -1 is current, -2 is previous
            previous = self.position_history[-2].copy()
            self._update_position(previous)
        
        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Move to previous: {previous}")
        
        return {
            "command_type": "move",
            "position": previous,
            "reason": "return_to_previous"
        }
    
    def _handle_move_to_named(self, params: dict) -> Optional[dict]:
        """Move to a named location."""
        location_name = params.get("location_name")
        if not location_name:
            print("[IntentExecutor] No location name provided")
            return None
        
        phrase_bank = get_phrase_bank()
        position = phrase_bank.get_location(location_name)
        
        if position is None:
            print(f"[IntentExecutor] Unknown location: '{location_name}'")
            return {"command_type": "error", "message": f"I don't know where '{location_name}' is."}
        
        with self.lock:
            self._update_position(position.copy())
        
        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Move to '{location_name}': {position}")
        
        return {
            "command_type": "move",
            "position": position,
            "location_name": location_name
        }
    
    def _handle_save_location(self, params: dict) -> Optional[dict]:
        """Save current position as a named location."""
        location_name = params.get("location_name")
        if not location_name:
            print("[IntentExecutor] No location name provided")
            return None
        
        phrase_bank = get_phrase_bank()
        with self.lock:
            phrase_bank.add_location(location_name, self.current_position.copy())
        
        return {
            "command_type": "location_saved",
            "location_name": location_name,
            "position": self.current_position.copy()
        }
    
    def _handle_gripper_open(self, params: dict) -> Optional[dict]:
        """Open the gripper."""
        with self.lock:
            self.gripper_state = "open"
        
        if VERBOSE_LOGGING:
            print("[IntentExecutor] Gripper: OPEN")
        
        return {
            "command_type": "gripper",
            "action": "open"
        }
    
    def _handle_gripper_close(self, params: dict) -> Optional[dict]:
        """Close the gripper."""
        with self.lock:
            self.gripper_state = "closed"
        
        if VERBOSE_LOGGING:
            print("[IntentExecutor] Gripper: CLOSE")
        
        return {
            "command_type": "gripper",
            "action": "close"
        }
    
    def _handle_emergency_stop(self, params: dict) -> Optional[dict]:
        """Emergency stop - halt all movement."""
        self.emergency_halt.set()
        
        print("[IntentExecutor] 🛑 EMERGENCY STOP")
        
        return {
            "command_type": "emergency_halt",
            "timestamp": datetime.now().isoformat()
        }
    
    def _handle_resume(self, params: dict) -> Optional[dict]:
        """Resume after emergency stop."""
        self.emergency_halt.clear()
        
        print("[IntentExecutor] ▶️ RESUMED")
        
        return {
            "command_type": "resume",
            "timestamp": datetime.now().isoformat()
        }
    
    def _update_position(self, new_position: dict):
        """Update current position and add to history (must be called with lock held)."""
        self.position_history.append(new_position.copy())
        if len(self.position_history) > self.max_history:
            self.position_history.pop(0)
        self.current_position = new_position
    
    def _add_to_queue(self, command: dict):
        """Add a command to the queue and optionally save to file."""
        command["timestamp"] = datetime.now().isoformat()

        with self.lock:
            self.command_queue.append(command)

        if self.write_to_file:
            self._save_commands()
    
    def _save_commands(self):
        """Save current command to the JSON file (single command mode)."""
        with self.lock:
            # Single command mode: just save the latest position
            output = {}
            if self.command_queue:
                latest = self.command_queue[-1]
                if latest.get("command_type") == "move" and "position" in latest:
                    output = latest["position"]
                elif latest.get("command_type") == "gripper":
                    output = {"gripper_action": latest["action"]}
                elif latest.get("command_type") == "emergency_halt":
                    output = {"emergency_halt": True}
            
            with open(self.command_queue_file, 'w') as f:
                json.dump(output, f, indent=2)
        
        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Saved to {self.command_queue_file}")
    
    def get_state(self) -> dict:
        """Get current state for LLM context."""
        with self.lock:
            return {
                "current_position": self.current_position.copy(),
                "previous_position": self.position_history[-2].copy() if len(self.position_history) >= 2 else None,
                "gripper_state": self.gripper_state,
                "emergency_halt": self.emergency_halt.is_set(),
                "queue_length": len(self.command_queue)
            }
    
    def set_position(self, position: dict):
        """Manually set the current position (e.g., for sync with robot)."""
        with self.lock:
            self._update_position(position)


# Singleton instance
_executor_instance = None

def get_executor() -> IntentExecutor:
    """Get the singleton IntentExecutor instance."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = IntentExecutor()
    return _executor_instance