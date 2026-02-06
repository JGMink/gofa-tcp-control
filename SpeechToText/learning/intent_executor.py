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

        # Object tracking
        self.known_objects: Dict[str, dict] = {}  # object_name -> {position, held, properties}
        self.held_object: Optional[str] = None  # Name of currently held object

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
            "compound_command": self._handle_compound_command,
            "move_to_object": self._handle_move_to_object,
            "pick_object": self._handle_pick_object,
            "place_object": self._handle_place_object,
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

    def _handle_compound_command(self, params: dict) -> Optional[dict]:
        """Execute a sequence of commands."""
        sequence = params.get("sequence", [])

        if not sequence:
            print("[IntentExecutor] Empty compound command sequence")
            return None

        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Compound command: {len(sequence)} steps")

        results = []
        for step in sequence:
            intent = step.get("intent")
            step_params = step.get("params", {})

            # Execute each step (but don't add to queue individually)
            result = self.execute(intent, step_params)
            if result:
                results.append(result)

        return {
            "command_type": "compound",
            "sequence": results,
            "steps_completed": len(results)
        }

    def _handle_move_to_object(self, params: dict) -> Optional[dict]:
        """Move to a known object's position."""
        object_name = params.get("object_name")
        if not object_name:
            print("[IntentExecutor] No object name provided")
            return None

        with self.lock:
            if object_name not in self.known_objects:
                print(f"[IntentExecutor] Unknown object: '{object_name}'")
                return {"command_type": "error", "message": f"I don't know where '{object_name}' is."}

            obj_info = self.known_objects[object_name]
            target_position = obj_info["position"].copy()

            # Move slightly above the object for safety
            target_position["y"] += 0.05  # 5cm above

            self._update_position(target_position)

        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Moving to object '{object_name}': {target_position}")

        return {
            "command_type": "move",
            "position": target_position,
            "target_object": object_name
        }

    def _handle_pick_object(self, params: dict) -> Optional[dict]:
        """Pick up an object (move to it, then close gripper)."""
        object_name = params.get("object_name")
        if not object_name:
            print("[IntentExecutor] No object name provided")
            return None

        with self.lock:
            if object_name not in self.known_objects:
                print(f"[IntentExecutor] Unknown object: '{object_name}'")
                return {"command_type": "error", "message": f"I don't know where '{object_name}' is."}

            obj_info = self.known_objects[object_name]
            target_position = obj_info["position"].copy()

            # Move to object
            self._update_position(target_position)

            # Close gripper and mark object as held
            self.gripper_state = "closed"
            self.held_object = object_name
            obj_info["held"] = True

        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Picking up '{object_name}'")

        return {
            "command_type": "pick",
            "position": target_position,
            "object_name": object_name,
            "gripper_action": "close"
        }

    def _handle_place_object(self, params: dict) -> Optional[dict]:
        """Place the held object at a location."""
        location = params.get("location", "here")

        with self.lock:
            if not self.held_object:
                print("[IntentExecutor] No object being held")
                return {"command_type": "error", "message": "I'm not holding anything."}

            place_position = self.current_position.copy()

            # If location specified, resolve it
            if location != "here":
                phrase_bank = get_phrase_bank()
                named_pos = phrase_bank.get_location(location)
                if named_pos:
                    place_position = named_pos.copy()

            # Update object position
            if self.held_object in self.known_objects:
                self.known_objects[self.held_object]["position"] = place_position.copy()
                self.known_objects[self.held_object]["held"] = False

            # Open gripper and release
            self.gripper_state = "open"
            placed_object = self.held_object
            self.held_object = None

        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Placing '{placed_object}' at {place_position}")

        return {
            "command_type": "place",
            "position": place_position,
            "object_name": placed_object,
            "gripper_action": "open"
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
            # Always save: current position + current gripper state
            output = self.current_position.copy()

            # Always include current gripper state
            gripper_pos = 0.11 if self.gripper_state == "open" else 0.0
            output["gripper_position"] = gripper_pos

            # Check for emergency halt
            if self.command_queue and self.command_queue[-1].get("command_type") == "emergency_halt":
                output["emergency_halt"] = True

            with open(self.command_queue_file, 'w') as f:
                json.dump(output, f, indent=2)

        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Saved to {self.command_queue_file}: pos={self.current_position}, gripper={self.gripper_state}")
    
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

    def register_object(self, name: str, position: dict, properties: dict = None):
        """Register an object in the scene."""
        with self.lock:
            self.known_objects[name] = {
                "position": position.copy(),
                "held": False,
                "properties": properties or {}
            }
        if VERBOSE_LOGGING:
            print(f"[IntentExecutor] Registered object '{name}' at {position}")

    def unregister_object(self, name: str):
        """Remove an object from tracking."""
        with self.lock:
            if name in self.known_objects:
                del self.known_objects[name]
                if self.held_object == name:
                    self.held_object = None

    def get_objects(self) -> Dict[str, dict]:
        """Get all known objects."""
        with self.lock:
            return self.known_objects.copy()


# Singleton instance
_executor_instance = None

def get_executor() -> IntentExecutor:
    """Get the singleton IntentExecutor instance."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = IntentExecutor()
    return _executor_instance