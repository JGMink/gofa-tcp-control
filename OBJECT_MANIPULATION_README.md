# Object Manipulation & Gripper Control

Complete integration of speech-controlled object manipulation with gripper control for the ABB GoFa robot.

## Features

### ✅ Compound Commands
- Say things like "move up and close gripper" to execute multiple actions
- Commands are parsed by Claude LLM and executed sequentially
- Examples:
  - "move right and grab it"
  - "open gripper and go back"
  - "pick up the cube and move left"

### ✅ Object Permanence
- Objects in Unity are tracked and synced with Python speech control
- Robot "remembers" where objects are located
- Objects maintain state (position, color, whether held, stacking info)

### ✅ Gripper Control
- Unity gripper visualization responds to commands
- Physical gripper control ready (via Modbus TCP when connected)
- Open/close with speech: "open gripper", "close gripper", "grab", "release"

### ✅ Object Stacking
- Detects when objects are stacked on top of each other
- Tracks stack height and relationships
- Visual feedback in Unity

## Setup

### Unity Scene Setup

1. **Add GripperController to your gripper**:
   - Attach `GripperController.cs` to your RG2 gripper GameObject
   - Assign left and right finger transforms in inspector
   - Set gripper model type (RG2 or RG6)

2. **Add ObjectManager to scene**:
   - Create empty GameObject named "ObjectManager"
   - Attach `ObjectManager.cs` script
   - It will auto-spawn 3 colored cubes on start
   - Objects: red_cube, blue_cube, green_cube

3. **Objects are auto-created** or manually add GrabbableObject:
   - Each object needs `GrabbableObject.cs` component
   - Set unique `objectName` for each
   - Optionally set color, physics settings

### Python Setup

1. **Run object sync** (in one terminal):
   ```bash
   cd SpeechToText
   python object_sync.py
   ```
   This syncs Unity objects with Python speech control.

2. **Run speech control** (in another terminal):
   ```bash
   cd SpeechToText
   python speech_control.py  # or speech_control_llm.py
   ```

3. **Optional: Run gripper controller** (for physical gripper):
   ```bash
   cd UnityProject
   python gripper_control.py
   ```

## Voice Commands

### Basic Movement
- "move up 5"
- "shift left a tiny bit"
- "go forward"

### Gripper Control
- "open gripper" / "close gripper"
- "grab" / "release"
- "pick up" / "drop it"

### Compound Commands
- "move up and close gripper"
- "grab it and move left"
- "open gripper and go back"

### Object Manipulation
- "go to the red cube"
- "pick up the blue cube"
- "move to the green cube"
- "place it here"
- "put it down"

### Stacking Objects
1. Pick up first object: "pick up the red cube"
2. Move to location: "move to the blue cube"
3. Stack on top: "move down a little" then "place it here"

## File Structure

### Unity Scripts (UnityProject/Assets/Scripts/)
- **GripperController.cs** - Controls gripper visualization and reads commands
- **GrabbableObject.cs** - Makes objects pickable with stacking detection
- **ObjectManager.cs** - Spawns and tracks all objects in scene

### Python Scripts (SpeechToText/)
- **object_sync.py** - Syncs Unity objects to Python (run continuously)
- **learning/intent_executor.py** - Executes robot commands and tracks objects
- **learning/llm_interpreter.py** - Parses speech into structured commands

### Gripper Control
- **UnityProject/gripper_control.py** - Physical RG2 gripper control via Modbus TCP

### Data Files
- **UnityProject/tcp_commands.json** - TCP position + gripper commands to Unity
- **UnityProject/object_states.json** - Object positions/states from Unity to Python
- **SpeechToText/learning/command_queue.json** - Command queue file

## How It Works

```
Speech → LLM Parser → Intent Executor → JSON Files → Unity/Robot
  ↓                                          ↓
Object Sync ←─── object_states.json ←──── Unity Objects
```

1. **Speech Input**: User says "pick up the red cube"
2. **LLM Parsing**: Claude interprets as `pick_object` intent with param `red_cube`
3. **Intent Execution**: Python finds object position, creates movement + gripper commands
4. **JSON Sync**: Commands written to `tcp_commands.json`
5. **Unity Reads**: GripperController and robot move to object and close gripper
6. **Object Update**: GrabbableObject detects grip, marks as held
7. **Sync Back**: object_sync.py updates Python with new object state

## Testing Compound Commands

Try these examples:

```bash
# Terminal 1: Object sync
cd SpeechToText && python object_sync.py

# Terminal 2: Speech control
cd SpeechToText && python speech_control_llm.py
```

Then say:
- "move up and close the gripper"
- "grab the red cube and move left"
- "open gripper and go to the blue cube"
- "pick up the green cube and move it up"

## Extending

### Add New Objects in Unity
```csharp
// In Unity, get ObjectManager reference
ObjectManager manager = FindObjectOfType<ObjectManager>();
manager.SpawnCube("my_cube", new Vector3(0.5f, 0.6f, 0f), Color.yellow);
```

### Add New Object Commands in Python
Edit `SpeechToText/learning/llm_interpreter.py` to add new intent types.
Edit `SpeechToText/learning/intent_executor.py` to add handlers.

### Physical Robot Integration
When robot is connected:
- TCP commands control robot position via EGM
- Gripper commands sent via `gripper_control.py`
- Robot IP: 192.168.0.12 (configured)

## Troubleshooting

**Objects not syncing?**
- Make sure `object_sync.py` is running
- Check `object_states.json` exists and updates
- Verify paths in config files

**Gripper not moving in Unity?**
- Check GripperController component is attached
- Verify finger transforms are assigned
- Check `tcp_commands.json` contains `gripper_position` field

**Speech commands not working?**
- Ensure ANTHROPIC_API_KEY is set
- Check console for LLM parsing errors
- Verify `command_queue.json` path matches

**Physical gripper timeout?**
- Verify robot IP (192.168.0.12)
- Check Modbus TCP port 502 is accessible
- May need different control method (I/O or RAPID)

## Next Steps

- [ ] Replace test cubes with EXPO objects
- [ ] Add more complex stacking logic
- [ ] Implement collision avoidance
- [ ] Add gripper force feedback
- [ ] Create predefined pick-and-place sequences
