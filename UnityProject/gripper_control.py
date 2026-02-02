#!/usr/bin/env python3
"""
RG2 Gripper Controller - Sends gripper commands to physical OnRobot RG2
Reads from tcp_commands.json and sends commands to robot via Modbus TCP or IO signals
"""

import json
import time
import socket
from typing import Optional

# Configuration
TCP_COMMANDS_FILE = "tcp_commands.json"
ROBOT_IP = "192.168.0.12"  # ABB robot IP
GRIPPER_PORT = 502  # Standard Modbus TCP port for OnRobot
POLL_INTERVAL = 0.1  # Poll every 100ms

# RG2 Gripper specifications
RG2_MAX_STROKE_MM = 110  # 110mm max stroke
RG2_MIN_STROKE_MM = 0    # Fully closed


class RG2GripperController:
    """Controls physical OnRobot RG2 gripper via Modbus TCP."""

    def __init__(self, robot_ip: str, port: int = 502):
        self.robot_ip = robot_ip
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.current_position_mm = RG2_MAX_STROKE_MM  # Start open
        self.connected = False

    def connect(self):
        """Establish connection to the gripper."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.robot_ip, self.port))
            self.connected = True
            print(f"✓ Connected to RG2 gripper at {self.robot_ip}:{self.port}")
            return True
        except Exception as e:
            print(f"✗ Failed to connect to gripper: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Close connection to the gripper."""
        if self.sock:
            self.sock.close()
            self.sock = None
        self.connected = False
        print("Disconnected from gripper")

    def set_gripper_position(self, position_meters: float, force: float = 40.0):
        """
        Set gripper position via Modbus TCP.

        Args:
            position_meters: Gripper width in meters (0.0 = closed, 0.11 = open for RG2)
            force: Grip force in Newtons (3-40N for RG2)
        """
        if not self.connected:
            print("⚠️  Not connected to gripper")
            return False

        # Convert meters to millimeters
        position_mm = position_meters * 1000.0
        position_mm = max(RG2_MIN_STROKE_MM, min(RG2_MAX_STROKE_MM, position_mm))

        # Clamp force to RG2 specs
        force = max(3.0, min(40.0, force))

        try:
            # OnRobot RG2 Modbus registers:
            # Register 0: Target width (0.1mm units)
            # Register 1: Target force (0.1N units)
            # Register 2: Control word

            width_units = int(position_mm * 10)  # Convert mm to 0.1mm units
            force_units = int(force * 10)        # Convert N to 0.1N units

            # Build Modbus TCP frame
            # Function code 0x10 (Write Multiple Registers)
            # Starting address: 0x0000
            # Number of registers: 3
            transaction_id = 0x0001
            protocol_id = 0x0000
            unit_id = 0x01
            function_code = 0x10
            start_address = 0x0000
            num_registers = 0x0003
            byte_count = 0x06
            control_word = 0x0001  # Move gripper

            # Modbus TCP header
            frame = bytearray()
            frame.extend(transaction_id.to_bytes(2, 'big'))
            frame.extend(protocol_id.to_bytes(2, 'big'))
            frame.extend((byte_count + 7).to_bytes(2, 'big'))  # Length
            frame.append(unit_id)
            frame.append(function_code)
            frame.extend(start_address.to_bytes(2, 'big'))
            frame.extend(num_registers.to_bytes(2, 'big'))
            frame.append(byte_count)

            # Register data
            frame.extend(width_units.to_bytes(2, 'big'))
            frame.extend(force_units.to_bytes(2, 'big'))
            frame.extend(control_word.to_bytes(2, 'big'))

            # Send command
            self.sock.sendall(frame)

            # Read response
            response = self.sock.recv(1024)

            if len(response) >= 8:
                self.current_position_mm = position_mm
                print(f"→ Gripper set to {position_mm:.1f}mm ({force:.1f}N)")
                return True
            else:
                print(f"⚠️  Invalid response from gripper: {response.hex()}")
                return False

        except Exception as e:
            print(f"✗ Error sending gripper command: {e}")
            self.connected = False
            return False

    def open_gripper(self, force: float = 40.0):
        """Fully open the gripper."""
        return self.set_gripper_position(RG2_MAX_STROKE_MM / 1000.0, force)

    def close_gripper(self, force: float = 40.0):
        """Fully close the gripper."""
        return self.set_gripper_position(RG2_MIN_STROKE_MM / 1000.0, force)


def read_tcp_commands(filepath: str) -> Optional[dict]:
    """Read TCP commands from JSON file."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(f"⚠️  Invalid JSON in {filepath}: {e}")
        return None
    except Exception as e:
        print(f"✗ Error reading {filepath}: {e}")
        return None


def main():
    """Main control loop."""
    print("=== OnRobot RG2 Gripper Controller ===")
    print(f"Reading commands from: {TCP_COMMANDS_FILE}")
    print(f"Robot IP: {ROBOT_IP}")
    print()

    gripper = RG2GripperController(ROBOT_IP, GRIPPER_PORT)

    # Connect to gripper
    if not gripper.connect():
        print("\n⚠️  Running in simulation mode (no physical gripper connected)")
        print("Commands will be displayed but not executed.\n")

    last_gripper_position = None

    try:
        print("Polling for commands... (Ctrl+C to stop)")
        while True:
            # Read command file
            commands = read_tcp_commands(TCP_COMMANDS_FILE)

            if commands and "gripper_position" in commands:
                gripper_pos = commands["gripper_position"]

                # Only send command if position changed
                if gripper_pos != last_gripper_position:
                    print(f"\n[{time.strftime('%H:%M:%S')}] New gripper command: {gripper_pos*1000:.1f}mm")

                    if gripper.connected:
                        gripper.set_gripper_position(gripper_pos)
                    else:
                        print(f"  [SIM] Would set gripper to {gripper_pos*1000:.1f}mm")

                    last_gripper_position = gripper_pos

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        gripper.disconnect()
        print("Gripper controller stopped")


if __name__ == "__main__":
    main()
