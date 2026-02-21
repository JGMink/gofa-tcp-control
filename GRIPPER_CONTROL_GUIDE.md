# RG2 Gripper Control Guide

## Overview

The OnRobot RG2 gripper is controlled through a JSON IPC pipeline. Python commands flow through a shared JSON file into Unity, where `GripperController.cs` animates a 5-part mesh gripper with realistic 4-bar parallelogram linkage motion.

```
Python (cli_control.py / speech_control.py)
    |
    v
intent_executor.py  -->  tcp_commands.json  { x, y, z, gripper_position }
                              |
                              v
                    TCPHotController.cs (reads JSON, calls SetGripperPosition)
                              |
                              v
                    GripperController.cs (animates 5 mesh parts)
```

---

## Unity Scene Setup

### 1. Hierarchy Structure

All 5 gripper mesh parts live as **flat siblings** under one parent. No nesting.

```
TCP
  └─ R2_Gripper                          ← GripperController.cs attached here
       ├─ RG2_Scratch-Base               ← static housing, never moves
       ├─ RG2_Scratch-FingerBase_Left    ← left arm, rotates around pivot pin
       ├─ RG2_Scratch-FingerBase_Right   ← right arm, rotates (mirrored)
       ├─ RG2_Scratch-FingerPad_Left     ← left pad, translates only
       └─ RG2_Scratch-FingerPad_Right    ← right pad, translates only
```

### 2. Import the Mesh Files

The 5 OBJ files are in `Assets/3D_Model/`:

| File | Part | Behavior |
|------|------|----------|
| `RG2_Scratch-Base.obj` | Base housing | Static, does not move |
| `RG2_Scratch-FingerBase_Left.obj` | Left finger arm | Rotates around pivot pin |
| `RG2_Scratch-FingerBase_Right.obj` | Right finger arm | Rotates (mirrored) |
| `RG2_Scratch-FingerPad_Left.obj` | Left finger pad | Translates, stays parallel |
| `RG2_Scratch-FingerPad_Right.obj` | Right finger pad | Translates, stays parallel |

These were exported from FreeCAD in **millimeters**. Unity import settings should have `globalScale = 1` and `useFileScale = 1`.

### 3. Parent Transform (R2_Gripper)

| Property | Value |
|----------|-------|
| Position | (0.63, -0.7, 0.229) — or wherever the gripper mounts on the arm |
| Rotation | Z = 90° |
| Scale | (0.025, 0.025, 0.027) — converts mm mesh coords to scene units |

### 4. Child Transforms (all 5 parts)

Every child should be at:
- **Local Position**: (0, 0, 0)
- **Local Rotation**: (0, 0, 0)
- **Local Scale**: (1, 1, 1)

The mesh vertex positions already encode the correct geometry offsets — don't move the transforms.

### 5. Wire Up the Inspector

Select **R2_Gripper** and in the **Gripper Controller** component:

| Inspector Field | Drag This Object |
|----------------|-----------------|
| Gripper Base | RG2_Scratch-Base |
| Finger Base Left | RG2_Scratch-FingerBase_Left |
| Finger Base Right | RG2_Scratch-FingerBase_Right |
| Finger Pad Left | RG2_Scratch-FingerPad_Left |
| Finger Pad Right | RG2_Scratch-FingerPad_Right |

### 6. Verify Settings

These should be the defaults after a Reset, but double-check:

| Setting | Value |
|---------|-------|
| Max Finger Angle | 45 |
| Rotation Axis | (0, 0, 1) |
| Arm Pivot Left | (-64, 39, 0) |
| Arm Pivot Right | (-64, 10, 0) |
| Pad Link Point Left | (-103, 71, 0) |
| Pad Link Point Right | (-103, -21, 0) |
| Force Z Axis | checked |
| Show Debug Markers | unchecked |

**Important**: If any values look wrong after wiring up, **right-click the component header > Reset** to pull fresh defaults from the code, then re-wire the 5 transforms. Unity serializes Inspector values into the scene file, so old values can persist even after code changes.

---

## How the Mechanism Works

The RG2 uses a **4-bar parallelogram linkage**:

1. **Finger arms** (FingerBase_Left/Right) pivot around pins embedded in the base housing. The pin locations are the `armPivotLeft/Right` coordinates.

2. **Finger pads** (FingerPad_Left/Right) are connected to the arms via thin linkage bars. As the arm rotates, the pad **translates** to follow the arm tip but **does not rotate** — the parallelogram linkage keeps the pads parallel to each other at all times.

3. The **rotation axis** is Z `(0,0,1)`, meaning the arms swing within the XY plane. Left arm rotates by `+angle`, right arm by `-angle`.

4. The `gripper_position` value (0.0 to 0.110 meters) maps to a rotation angle (0 to `maxFingerAngle` degrees). The animation smoothly interpolates at `gripSpeed` meters per second.

---

## Controlling the Gripper

### From CLI

```bash
cd SpeechToText
export ANTHROPIC_API_KEY='your-key'
python3 cli_control.py
```

```
robot> open gripper          # fully open (110mm)
robot> close gripper         # fully closed (0mm)
robot> close to 50mm         # partial close
robot> close halfway         # 55mm
```

### From Unity Keyboard (GripperTest.cs)

While in Play mode with Game view focused:

| Key | Action |
|-----|--------|
| **P** | Close gripper (0mm) |
| **O** | Open gripper (110mm) |
| **H** | Half-close (55mm) |
| **T** | Run full test sequence |
| **I** | Print gripper info to Console |

### From Code

```csharp
// Get reference
GripperController gripper = GetComponent<GripperController>();

// Set exact position in meters
gripper.SetGripperPosition(0.055f);  // 55mm

// Convenience methods
gripper.OpenGripper();   // 110mm
gripper.CloseGripper();  // 0mm

// Read state
float pos = gripper.GetCurrentPosition();         // meters
float pct = gripper.GetCurrentPositionPercent();   // 0-100%
```

---

## Debugging & Tuning Pivot Points

If the arm swing looks wrong (asymmetric, wrong center of rotation, arms detaching from base), the pivot point coordinates may need adjustment.

### Step 1: Enable Debug Markers

In the Inspector under **Debug**, check **Show Debug Markers**, then hit Play.

Colored spheres appear at key points:

| Color | Meaning | What to Look For |
|-------|---------|-----------------|
| **Red** | Arm pivot pins | Should sit on the pin holes where arms hinge on the base |
| **Green** | Pad link points | Should sit where the linkage bar connects arm to pad |
| **Blue** | Arm mesh origins | Should be at (0,0,0) — just for reference |
| **Cyan** | Pad mesh origins | Should be at (0,0,0) — just for reference |

### Step 2: Adjust Positions

1. In the Hierarchy (while in Play mode), select a debug sphere (e.g. `DBG_ArmPivot_L`)
2. Use the **Move tool (W)** to drag it to the correct location on the mesh
3. Read the new **local position** from the Inspector

### Step 3: Update the Code

Update the default values in `GripperController.cs`:

```csharp
public Vector3 armPivotLeft = new Vector3(-64f, 39f, 0f);     // your new values
public Vector3 armPivotRight = new Vector3(-64f, 10f, 0f);
public Vector3 padLinkPointLeft = new Vector3(-103f, 71f, 0f);
public Vector3 padLinkPointRight = new Vector3(-103f, -21f, 0f);
```

### Step 4: Apply

Stop Play, **Reset** the component (right-click > Reset), re-wire the 5 transforms, and test again.

### Where Each Sphere Belongs

- **Red (arm pivot)**: The **lower pin** on each finger arm — where the arm connects to the base housing. This is the hinge point the arm physically rotates around.

- **Green (pad link)**: The **upper pin** on each finger arm — where the thin linkage bar connects the arm to the finger pad. As the arm swings, this point traces an arc and drags the pad with it.

### Tips

- If one arm closes higher/lower than the other, adjust that arm's pivot **Y value**
- Both pivots should have the same **X value** (they're on the same bolt line)
- The `maxFingerAngle` controls how far the arms swing when fully closed
- If arms swing the wrong direction (outward instead of inward), negate the rotation axis: `(0, 0, -1)`

---

## Troubleshooting

### Fingers don't move at all
1. Check that all 5 transforms are assigned in the Inspector
2. Check the Console for `"GripperController: FingerBase L/R transforms not assigned!"`
3. Verify `tcp_commands.json` is being written: `cat UnityProject/tcp_commands.json`
4. Make sure the gripper_position value is changing in the JSON

### Motion is wild / arms fly off
1. The pivot coordinates are probably wrong — enable debug markers and verify
2. Make sure `Rotation Axis` is `(0, 0, 1)` and `Force Z Axis` is checked
3. Try reducing `Max Finger Angle` to 10 to see small controlled motion first

### Old values won't go away
Unity serializes Inspector values into the scene file. Even if you change code defaults, the scene overrides them. Fix: **right-click the component > Reset**, then re-wire transforms and save the scene.

### Pads don't move
Check that `padLinkPointLeft/Right` are not `(0, 0, 0)` — the code skips pad motion if the link point is zero.

### Gripper position values
| Value | Meaning |
|-------|---------|
| `0.110` | Fully open (110mm gap) |
| `0.055` | Half open (55mm gap) |
| `0.000` | Fully closed |

---

## File Reference

| File | Purpose |
|------|---------|
| `UnityProject/Assets/Scripts/GripperController.cs` | Main gripper animation logic |
| `UnityProject/Assets/Scripts/GripperTest.cs` | Keyboard test controls (P/O/H/T/I) |
| `UnityProject/Assets/Scripts/TCPHotController.cs` | Reads tcp_commands.json, calls SetGripperPosition |
| `UnityProject/Assets/3D_Model/RG2_Scratch-*.obj` | 5 gripper mesh files |
| `UnityProject/tcp_commands.json` | IPC file: Python writes, Unity reads |
| `UnityProject/tcp_ack.json` | IPC file: Unity writes acknowledgement |
| `SpeechToText/cli_control.py` | CLI interface for sending commands |
| `SpeechToText/learning/intent_executor.py` | Interprets commands, writes JSON |
