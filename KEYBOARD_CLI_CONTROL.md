# Keyboard & CLI Control Guide

Two ways to test and control the robot interactively!

## 🎮 Keyboard Control (Unity)

Control the robot directly in Unity using keyboard shortcuts.

### Setup:
1. Create an empty GameObject in Unity
2. Attach `KeyboardRobotControl.cs` script
3. Assign the `GripperController` reference in inspector (optional)
4. Assign `robotBase` transform for rotation (optional)
5. Hit Play!

### Controls:

**MOVEMENT:**
- **Arrow Keys**: Move left/right/forward/backward
- **W/S**: Move forward/backward (alternate)
- **A/D**: Move left/right (alternate)
- **Page Up/Down**: Move up/down (Y axis)
- **Hold Shift**: Move 5x faster

**ROTATION:**
- **Z/X**: Rotate left/right (yaw)
- **T/G**: Tilt up/down (pitch)
- **F/H**: Roll left/right
- **Hold Shift**: Rotate 5x faster

**GRIPPER:**
- **Space**: Open gripper (110mm)
- **C**: Close gripper (0mm)
- **V**: Half-close gripper (55mm)

**OTHER:**
- **R**: Reset to home position

### On-Screen Display:
- Current position (X, Y, Z)
- Current rotation (pitch, yaw, roll)
- Gripper state (OPEN/CLOSED) with distance

### How It Works:
Keyboard inputs → Write to `tcp_commands.json` → Unity/Robot reads and executes

---

## 💻 CLI Control (Terminal)

Type natural language commands in your terminal to control the robot.

### Setup:
```bash
cd SpeechToText
export ANTHROPIC_API_KEY='your-key-here'
python cli_control.py
```

### Usage:

```
robot> move 10 left
robot> close gripper
robot> move up and grab it
robot> go to the red cube
robot> pick up the blue cube
robot> place it here
```

### Commands:

**Movement:**
```
move 10 left
go right 5cm
move up a little
shift down 2 centimeters
move forward
go back
```

**Gripper:**
```
open gripper
close gripper
grab
release
```

**Compound Commands:**
```
move up and close gripper
grab it and move left
open gripper and go back
```

**Object Manipulation:**
```
go to the red cube
pick up the blue cube
place it here
move to the green cube
```

**Navigation:**
```
go home
return to previous
save this as pickup_zone
```

**CLI Commands:**
- `help` - Show help message
- `status` - Show current robot state
- `objects` - List all known objects
- `clear` - Clear screen
- `quit` or `exit` - Exit CLI

### Features:
- ✅ Natural language parsing via Claude LLM
- ✅ Confidence scores (warns if < 70%)
- ✅ Compound command support
- ✅ Object tracking and manipulation
- ✅ Position history
- ✅ Real-time status display

### Example Session:

```bash
$ python cli_control.py
=== CLI Robot Control ===
Initializing...
✓ Ready!
Type 'help' for available commands

robot> status

--- Current Status ---
Position: (0.000, 0.567, -0.240)
Gripper: OPEN
Emergency Halt: False
Command Queue: 0 items
--------------------

robot> move 5 left
Interpreting: 'move 5 left'
  Intent: move_relative
  Params: {'direction': 'left', 'distance': 5.0}
  Confidence: 0.98
✓ Moved to (-0.050, 0.567, -0.240)

robot> close gripper
Interpreting: 'close gripper'
  Intent: gripper_close
  Params: {}
  Confidence: 1.00
✓ Gripper CLOSED

robot> objects

--- Known Objects ---
  • red_cube: (0.500, 0.600, -0.200) [red]
  • blue_cube: (0.650, 0.600, -0.200) [blue]
  • green_cube: (0.800, 0.600, -0.200) [green]
--------------------

robot> pick up the red cube
Interpreting: 'pick up the red cube'
  Intent: pick_object
  Params: {'object_name': 'red_cube'}
  Confidence: 0.95
✓ Picked up 'red_cube'

robot> quit
Goodbye!
```

---

## 🔄 Using Both Together

**Workflow:**
1. Run CLI in terminal for typed commands
2. Run Unity with keyboard control for visual feedback
3. Both write to same `tcp_commands.json` file
4. See robot move in real-time in Unity!

**Example:**
```bash
# Terminal 1: Object sync
cd SpeechToText && python object_sync.py

# Terminal 2: CLI control
cd SpeechToText && python cli_control.py

# Unity: Play scene with KeyboardRobotControl
```

Type commands in terminal, see results in Unity!

---

## 📁 Files

**Unity:**
- `KeyboardRobotControl.cs` - Keyboard input handler

**Python:**
- `cli_control.py` - CLI command interface
- `learning/llm_interpreter.py` - Natural language parser
- `learning/intent_executor.py` - Command executor

**Data:**
- `tcp_commands.json` - Shared command file
- `object_states.json` - Object positions from Unity

---

## 💡 Tips

**Keyboard Control:**
- Use Shift for precise positioning (5x faster)
- Reset to home (R) if you get lost
- Watch on-screen display for exact coordinates

**CLI Control:**
- Type naturally - LLM understands variations
- Use `status` to check where you are
- Use `objects` to see what's available
- Low confidence? Check your command syntax

**Testing Objects:**
- Use keyboard to position robot above cube
- Use CLI to "close gripper"
- Check Unity to see if cube is picked up
- Use "open gripper" to release

**Troubleshooting:**
- No response? Check `tcp_commands.json` is updating
- Unity not moving? Ensure GripperController is attached
- CLI not working? Check ANTHROPIC_API_KEY is set
- Objects not found? Run `object_sync.py` first
