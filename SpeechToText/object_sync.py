#!/usr/bin/env python3
"""
Object Sync - Synchronizes Unity scene objects with Python speech control
Reads object_states.json from Unity and registers them with IntentExecutor
"""

import json
import time
from pathlib import Path
from typing import Dict, List

from learning.intent_executor import get_executor
from learning.config import VERBOSE_LOGGING


OBJECT_STATES_FILE = "../UnityProject/object_states.json"
POLL_INTERVAL = 1.0  # Check for updates every second


class ObjectSyncManager:
    """Manages synchronization of Unity objects with Python intent executor."""

    def __init__(self, object_states_file: str = OBJECT_STATES_FILE):
        self.object_states_file = Path(object_states_file)
        self.executor = get_executor()
        self.last_modified = 0
        self.known_objects = {}

    def load_objects_from_unity(self) -> Dict[str, dict]:
        """Load object states from Unity's JSON file."""
        if not self.object_states_file.exists():
            return {}

        try:
            with open(self.object_states_file, 'r') as f:
                data = json.load(f)

            objects = {}
            for obj in data.get("objects", []):
                name = obj["name"]
                position = {
                    "x": obj["position"][0],
                    "y": obj["position"][1],
                    "z": obj["position"][2]
                }
                properties = {
                    "color": obj.get("color", "white"),
                    "held": obj.get("held", False)
                }
                objects[name] = {"position": position, "properties": properties}

            return objects

        except json.JSONDecodeError as e:
            print(f"⚠️  Error parsing {self.object_states_file}: {e}")
            return {}
        except Exception as e:
            print(f"⚠️  Error reading {self.object_states_file}: {e}")
            return {}

    def sync_objects(self):
        """Sync objects from Unity to Python intent executor."""
        # Check if file was modified
        if not self.object_states_file.exists():
            return

        modified_time = self.object_states_file.stat().st_mtime
        if modified_time <= self.last_modified:
            return  # No changes

        self.last_modified = modified_time

        # Load objects
        unity_objects = self.load_objects_from_unity()

        if not unity_objects:
            return

        # Register/update objects
        for name, data in unity_objects.items():
            if name not in self.known_objects:
                # New object
                self.executor.register_object(name, data["position"], data["properties"])
                self.known_objects[name] = data
                print(f"✓ Registered new object: '{name}' at {data['position']}")
            else:
                # Check if position changed
                old_pos = self.known_objects[name]["position"]
                new_pos = data["position"]

                pos_changed = any(
                    abs(old_pos[k] - new_pos[k]) > 0.001
                    for k in ["x", "y", "z"]
                )

                if pos_changed:
                    self.executor.register_object(name, new_pos, data["properties"])
                    self.known_objects[name] = data
                    if VERBOSE_LOGGING:
                        print(f"↻ Updated '{name}' position: {new_pos}")

        # Remove objects that no longer exist in Unity
        for name in list(self.known_objects.keys()):
            if name not in unity_objects:
                self.executor.unregister_object(name)
                del self.known_objects[name]
                print(f"✗ Removed object: '{name}'")

    def run(self):
        """Main sync loop."""
        print("=== Object Sync Manager ===")
        print(f"Watching: {self.object_states_file.resolve()}")
        print()

        try:
            while True:
                self.sync_objects()
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nStopping object sync...")


def main():
    """Run object sync standalone."""
    sync_manager = ObjectSyncManager()
    sync_manager.run()


if __name__ == "__main__":
    main()
