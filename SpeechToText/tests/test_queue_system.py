#!/usr/bin/env python3
"""
Test script for queue system (simulates Unity acknowledgments).
Tests without requiring actual Unity or voice input.
"""
import json
import time
import os
import threading
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

COMMAND_FILE = "../../UnityProject/tcp_commands.json"
ACK_FILE = "../../UnityProject/tcp_ack.json"


class FakeUnity:
    """Simulates Unity: reads commands and writes acknowledgments."""

    def __init__(self, command_file, ack_file, delay=1.0):
        self.command_file = command_file
        self.ack_file = ack_file
        self.delay = delay  # Simulate movement time
        self.last_modified = None
        self.running = True

    def start(self):
        """Start watching for commands."""
        print("🎮 Fake Unity started (simulating robot movements)")
        while self.running:
            time.sleep(0.1)
            self._check_for_command()

    def _check_for_command(self):
        """Check if Python sent a new command."""
        try:
            if not os.path.exists(self.command_file):
                return

            current_modified = os.path.getmtime(self.command_file)

            if self.last_modified != current_modified:
                self.last_modified = current_modified
                self._process_command()

        except Exception as e:
            pass  # File might be mid-write

    def _process_command(self):
        """Read command, simulate movement, write ack."""
        try:
            with open(self.command_file, 'r') as f:
                cmd = json.load(f)

            if not cmd or not isinstance(cmd, dict):
                return

            print(f"  🤖 Unity received: x={cmd['x']:.3f}, y={cmd['y']:.3f}, z={cmd['z']:.3f}")
            print(f"  ⏱️  Moving (simulated {self.delay}s)...")

            # Simulate movement time
            time.sleep(self.delay)

            # Write acknowledgment
            ack = {
                "completed": True,
                "position": cmd,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
            }

            with open(self.ack_file, 'w') as f:
                json.dump(ack, f, indent=2)

            print(f"  ✅ Unity completed movement\n")

        except Exception as e:
            print(f"  ⚠️  Unity error: {e}")

    def stop(self):
        self.running = False


def test_queue_system():
    """Test the queue system with simulated commands."""
    print("\n" + "="*60)
    print("QUEUE SYSTEM TEST")
    print("="*60 + "\n")

    # Clean up old files
    for f in [COMMAND_FILE, ACK_FILE]:
        if os.path.exists(f):
            os.remove(f)

    # Import queue manager
    from Latency_fix_speech import CommandQueueManager, queue_processor_thread

    # Create queue manager
    queue_manager = CommandQueueManager(
        command_file=COMMAND_FILE,
        ack_file=ACK_FILE
    )

    # Start fake Unity in background
    fake_unity = FakeUnity(COMMAND_FILE, ACK_FILE, delay=0.5)
    unity_thread = threading.Thread(target=fake_unity.start, daemon=True)
    unity_thread.start()

    # Start queue processor
    stop_event = threading.Event()
    processor_thread = threading.Thread(
        target=queue_processor_thread,
        args=(queue_manager, stop_event),
        daemon=True
    )
    processor_thread.start()

    time.sleep(0.5)  # Let threads start

    # Test 1: Add single command
    print("TEST 1: Single command")
    queue_manager.add_commands([{"x": 1.0, "y": 0.0, "z": 0.0}])
    time.sleep(2)  # Wait for completion

    # Test 2: Add multiple commands
    print("\nTEST 2: Multiple commands (should execute sequentially)")
    commands = [
        {"x": 2.0, "y": 0.0, "z": 0.0},
        {"x": 2.0, "y": 1.0, "z": 0.0},
        {"x": 0.0, "y": 1.0, "z": 0.0}
    ]
    queue_manager.add_commands(commands)
    time.sleep(5)  # Wait for all to complete

    # Test 3: Add commands while others are executing
    print("\nTEST 3: Adding commands mid-execution")
    queue_manager.add_commands([
        {"x": 0.0, "y": 0.0, "z": 1.0},
        {"x": 1.0, "y": 1.0, "z": 1.0}
    ])
    time.sleep(3)

    # Print final stats
    stats = queue_manager.get_stats()
    print("\n" + "="*60)
    print("FINAL STATISTICS")
    print("="*60)
    print(f"Total sent: {stats['total_sent']}")
    print(f"Total completed: {stats['total_completed']}")
    print(f"Remaining in queue: {stats['queue_size']}")
    print(f"Pending: {stats['pending']}")
    print("\n✅ Test complete!")

    # Cleanup
    fake_unity.stop()
    stop_event.set()


if __name__ == "__main__":
    test_queue_system()
