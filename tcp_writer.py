import json
import time

# Define a sequence of TCP positions
positions = [
    {"x": 2.0, "y": 0.0, "z": 0.0},
    {"x": 2.0, "y": 2.0, "z": 0.0},
    {"x": 0.0, "y": 2.0, "z": 0.0},
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 1.0, "y": 1.0, "z": 1.0},
    {"x": -1.0, "y": 1.0, "z": 0.5},
    {"x": 0.0, "y": 0.0, "z": 2.0},
]

filepath = "tcp_commands.json"

print("Starting TCP command sequence...")
for i, pos in enumerate(positions):
    with open(filepath, 'w') as f:
        json.dump(pos, f, indent=2)
    
    print(f"Command {i+1}/{len(positions)}: x={pos['x']}, y={pos['y']}, z={pos['z']}")
    time.sleep(2)  # Wait 2 seconds between commands

print("Sequence complete!")