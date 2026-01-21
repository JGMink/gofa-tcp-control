# ABB GoFa Voice Control System - Setup Documentation

## Overview
This system enables voice control of the ABB GoFa CRB 15000 robot using Azure Speech-to-Text, with commands sent via Unity to the robot over WiFi.

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Network Configuration](#network-configuration)
3. [Robot Setup](#robot-setup)
4. [Running the System](#running-the-system)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Hardware Required
- ABB GoFa CRB 15000 robot
- Computer (Mac or Windows)
- USB cable for iPhone tethering (Mac users)
- Microphone (built-in or external)

### Software Required
- Unity project (download from shared drive)
- Python 3.7+
- Azure Speech Services credentials
- Azure CLU credentials (optional)

### Python Dependencies
```bash
pip install --break-system-packages azure-cognitiveservices-speech
pip install --break-system-packages azure-ai-language-conversations
pip install --break-system-packages python-dotenv
pip install --break-system-packages sounddevice
pip install --break-system-packages webrtcvad
pip install --break-system-packages numpy
```

### Environment Setup
Create a `.env` file in the Python script directory with:
```env
AZURE_SPEECH_KEY=your_speech_key_here
AZURE_SPEECH_REGION=your_region_here
CLU_ENDPOINT=your_clu_endpoint_here
CLU_KEY=your_clu_key_here
CLU_PROJECT=GofaVoiceBot
CLU_DEPLOYMENT=production
USE_CLU=true
```

---

## Network Configuration

### For Mac Users (Dual Network Setup Required)

The Mac needs simultaneous connections:
- **Robot WiFi**: For sending commands to the robot (192.168.0.x network)
- **Internet**: For Azure API calls (via iPhone USB tethering)

#### Step 1: Configure iPhone USB Tethering

1. **On iPhone:**
   - Go to **Settings → Personal Hotspot**
   - Turn ON **"Allow Others to Join"**
   - Turn ON **"Maximize Compatibility"**
   - Connect iPhone to Mac via USB cable

2. **On Mac:**
   - When prompted on iPhone, tap **"Trust This Computer"**
   - Enter iPhone passcode if requested
   - Verify connection: **System Settings → Network** should show **"iPhone USB"** as **Connected**

#### Step 2: Configure Robot WiFi Connection

1. **Connect to robot WiFi:**
   - Network Name: `Magnaforma-5G`
   - Password: `fuzzyowl457`

2. **Configure WiFi settings manually:**
   - **System Settings → Network → WiFi**
   - Click **"Details..."** next to Magnaforma-5G
   - Select **TCP/IP** tab
   - Set the following:
     ```
     Configure IPv4: Manually
     IP Address: 192.168.0.12
     Subnet Mask: 255.255.255.0
     Router: [LEAVE COMPLETELY BLANK - CRITICAL!]
     ```
   - Click **OK**

#### Step 3: Set Network Service Order

This ensures iPhone provides internet while WiFi connects to robot:

1. **System Settings → Network**
2. Click **"..." (three dots)** at the bottom left
3. Select **"Set Service Order..."**
4. Drag services into this priority order:
   ```
   1. iPhone USB          (highest priority - for internet)
   2. Wi-Fi               (for robot communication only)
   3. Everything else...
   ```
5. Click **OK** and **Apply**

#### Step 4: Verify Dual Connection

Open Terminal and test both connections:
```bash
# Test robot connection (via WiFi)
ping 192.168.0.1

# Test internet connection (via iPhone USB)
ping 8.8.8.8

# Test Azure API access
curl -I https://api.cognitive.microsoft.com
```

All three should succeed. If not, see [Troubleshooting](#troubleshooting).

---

### For Windows Users

Windows handles dual networks automatically - simply:
1. Connect to robot WiFi (`Magnaforma-5G`, password: `fuzzyowl457`)
2. Set manual IP: `192.168.0.12`, Subnet: `255.255.255.0`, Gateway: blank
3. Connect to internet via Ethernet or another WiFi adapter
4. Windows will automatically route traffic correctly

---

## Robot Setup

### Step 1: Power On Robot
1. Power on the ABB GoFa robot controller
2. Wait for the system to fully boot
3. Check that FlexPendant (teach pendant) is responsive

### Step 2: Set Robot Mode
1. On the FlexPendant, set the robot to **Automatic** mode
2. Ensure no emergency stops are active
3. Verify robot is in a safe starting position

### Step 3: Load RAPID Program
1. Ensure the appropriate RAPID program is loaded
2. The program should include TCP server functionality to receive commands
3. Verify the program is configured to listen on the correct network interface

### Step 4: Robot Network Verification
From your computer, verify you can reach the robot:
```bash
ping 192.168.0.1
```

Optionally, try accessing the robot web interface:
```bash
open http://192.168.0.1  # Mac
# OR
start http://192.168.0.1  # Windows
```

---

## Running the System

### File Structure
Your project should be organized as:
```
project-root/
├── SpeechToText/
│   ├── test_improved.py          # Main voice control script
│   ├── SpeechToText.py           # Original script
│   ├── .env                      # Azure credentials
│   └── requirements.txt
├── UnityProject/
│   ├── tcp_commands.json         # Auto-generated command queue
│   ├── Assets/
│   │   └── Scripts/
│   │       └── TCPHotController.cs
│   └── ...
```

### Step 1: Start the Voice Recognition System

Navigate to your Python script directory:
```bash
cd /path/to/SpeechToText
```

Run the improved script with connectivity checking:
```bash
python test_improved.py
```

You should see:
```
============================================================
Multi-Command Speech-to-Robot Position Queue System
============================================================

🔍 Checking network connectivity...

✅ Robot connection OK (192.168.0.1)
✅ Azure Speech service reachable

Emergency halt words: ['stop', 'halt', 'wait', 'pause', 'emergency']
Exit program words: ['exit program', 'quit program', 'shutdown', 'terminate']
Command queue file: ../UnityProject/tcp_commands.json
Starting position: {'x': 0.0, 'y': 0.567, 'z': -0.24}

Applied phrase list boosting: [...]
Azure recognizer started (continuous).
[Session started]
Mic stream opened. Speak into the microphone.
Emergency halt words: ['stop', 'halt', 'wait', 'pause', 'emergency']
Exit program words: ['exit program', 'quit program', 'shutdown', 'terminate']

Running. Try saying: 'move up and go right 10 centimeters'
```

### Step 2: Start Unity

1. Open Unity Hub
2. Open the GoFa Unity project
3. Press **Play** in the Unity editor
4. Verify the console shows the TCP controller is watching for commands

### Step 3: Start Robot Execution

1. On the robot controller/FlexPendant, press **Start** or **Play**
2. The robot should now be ready to receive commands

**Important:** According to your documentation:
> "Hit play Unity, then hit play on the controller."

If you encounter issues, try: Controller → Unity → Commands sequence.

### Step 4: Issue Voice Commands

Speak naturally into your microphone. The system recognizes:

**Single Commands:**
- "Move right 10 centimeters"
- "Go up 5 centimeters"
- "Move forward"
- "Go down a bit"

**Multi-Command Sentences:**
- "Move up and go right 10 centimeters"
- "Go forward, then move left, then go down"
- "Move right 5 centimeters, then up 3 centimeters"

**Emergency Commands:**
- "Stop" / "Halt" / "Wait" / "Pause" / "Emergency" - Immediately halt all commands

**Exit Commands:**
- "Exit program" / "Quit program" / "Shutdown" / "Terminate" - Stop the Python script

### Step 5: Monitor Execution

**Python Console:**
```
[Partial] move right
[Final] Move right 10 centimeters.
[PARSING] Splitting sentence into commands...
  └─ Parsed: 'move right 10 centimeters' -> {'x': 0.1, 'y': 0.0, 'z': 0.0} -> Position: {'x': 0.1, 'y': 0.567, 'z': -0.24}
✅ [ADDED 1 COMMANDS] Total in queue: 1
```

**Unity Console:**
- Should show commands being received and sent to robot
- Watch for "SendPoseMessageToRobot" messages

**Robot:**
- Should execute movements in sequence
- Watch for singularity warnings (red light)

---

## Understanding the System

### Command Flow
1. **Voice Input** → Microphone captures speech
2. **Azure Speech** → Converts speech to text (via iPhone/internet)
3. **Python Parser** → Extracts movement commands and calculates positions
4. **JSON File** → Writes positions to `tcp_commands.json`
5. **Unity Watcher** → Detects file changes and reads commands
6. **TCP Transmission** → Unity sends commands to robot (via WiFi)
7. **Robot Execution** → GoFa executes movements

### Position Tracking
The system maintains cumulative position tracking:
- Starting position: `{"x": 0.0, "y": 0.567, "z": -0.24}`
- Each command adds a delta to the current position
- Multi-command sentences are queued in sequence

### Distance Scaling
Commands are scaled for Unity units:
- `DISTANCE_SCALE = 0.1` (in `test_improved.py`)
- "10 centimeters" becomes 1.0 Unity units
- Adjust this value if robot movements don't match expectations

---

## Troubleshooting

### Network Issues (Mac)

**Problem:** `ping 8.8.8.8` fails (no internet)
**Solution:**
- Verify iPhone USB shows "Connected" in Network settings
- Check Personal Hotspot is ON on iPhone
- Try unplugging and reconnecting iPhone
- Check service order has iPhone USB at top
- Try a different USB cable (some are charge-only)

**Problem:** `ping 192.168.0.1` fails (no robot connection)
**Solution:**
- Verify WiFi is connected to Magnaforma-5G
- Check IP is set to 192.168.0.12
- **Critical:** Verify Router field is BLANK
- Try forgetting and reconnecting to WiFi network

**Problem:** One works but not both
**Solution:**
- Check service order (iPhone USB should be #1)
- Verify WiFi Router field is empty
- Run: `netstat -nr | grep default` - should show default route through iPhone interface, not WiFi

### Azure Speech Issues

**Problem:** "[Session stopped]" immediately after starting
**Solution:**
- Verify internet connection: `ping 8.8.8.8`
- Check Azure credentials in `.env` file
- The improved script has auto-reconnect - wait 2 seconds for retry
- Run connectivity check: Script will show which connection failed

**Problem:** Speech not recognized
**Solution:**
- Check microphone permissions (System Settings → Privacy → Microphone)
- Test microphone: `python -c "import sounddevice; print(sounddevice.query_devices())"`
- Speak clearly and wait for partial recognition to appear
- Check phrase list is being applied

### Unity Issues

**Problem:** "Parse error: Object reference not set"
**Solution:**
- Verify `tcp_commands.json` exists and is valid JSON
- Check file path in Unity matches Python output path
- Stop and restart Unity Play mode
- Manually create test file: `echo '{"x": 0.1, "y": 0.567, "z": -0.24}' > ../UnityProject/tcp_commands.json`

**Problem:** "SocketException: Host is down"
**Solution:**
- Verify robot is powered on and reachable: `ping 192.168.0.1`
- Check robot is in Automatic mode
- Ensure RAPID program is loaded and running
- Verify Unity IP settings match robot network (192.168.0.x)

### Robot Issues

**Problem:** "Start failed - no response from controller"
**Solution:**
- Set robot to Automatic mode (not Manual)
- Verify RAPID program is loaded
- Check robot is not in emergency stop state
- Restart robot controller
- Follow startup sequence: Controller → Unity → Commands

**Problem:** Robot enters singularity (red light)
**Solution:**
- Switch to Manual mode on FlexPendant
- Manually move robot out of singularity position
- Light should turn green
- Return to Automatic mode
- Resume commands

**Problem:** Movements are too large or too small
**Solution:**
- Adjust `DISTANCE_SCALE` in `test_improved.py`
- Current: `0.1` (10cm = 1.0 Unity unit)
- Increase for larger movements, decrease for smaller
- Test with "move right 10 centimeters" and measure actual movement

---

## System Shutdown

### Proper Shutdown Sequence

1. **Stop voice commands:**
   - Say "exit program" OR
   - Press `Ctrl+C` in Python terminal

2. **Stop Unity:**
   - Click Stop button in Unity editor

3. **Stop robot:**
   - Press Stop on robot controller/FlexPendant
   - **Important:** Restart controller for next run (per documentation)

4. **Disconnect networks (Mac):**
   - Can leave iPhone USB connected
   - Disconnect from robot WiFi if needed

---

## Quick Reference Card

### Voice Commands
| Command | Example | Effect |
|---------|---------|--------|
| Directional | "move right 10 centimeters" | Moves robot in specified direction |
| Multiple | "go up, then right, then down" | Executes sequence of movements |
| Emergency | "stop" / "halt" | Immediately halts all commands |
| Exit | "exit program" | Shuts down voice control system |

### Network Quick Check (Mac)
```bash
# All should succeed:
ping 192.168.0.1    # Robot
ping 8.8.8.8        # Internet
curl -I https://api.cognitive.microsoft.com  # Azure
```

### File Locations
- Python script: `/path/to/SpeechToText/test_improved.py`
- Command queue: `../UnityProject/tcp_commands.json`
- Unity project: `/path/to/UnityProject/`
- Logs: `asr_luis_log.jsonl` (in Python script directory)

### Common Error Codes
- "No route to host" → Network configuration issue
- "Session stopped" → Azure connection lost
- "Parse error" → JSON file issue
- "Host is down" → Robot not reachable

---

## Additional Resources

### Documentation Links
- **Previous Capstone Team Docs:** https://drive.google.com/file/d/1OK2gSxbwA_l32ghTyrsXg2cihH0YTcNR/view?usp=sharing
- **EGM for ABB Robots:** https://github.com/riseatlsu/egm-for-abb-robots
- **Unity Project Download:** https://drive.google.com/file/d/18j8NqUYFQP9UiXW3FZnc_M1z6dZIw75l/view?usp=drive_link

### Support Contacts
- For network issues: Check with lab IT
- For Azure issues: Verify subscription status
- For robot issues: Consult ABB documentation or FlexPendant help

---

## Appendix: Mac vs Windows Networking Differences

### Why Mac Requires Special Setup

**macOS behavior:**
- Prioritizes single "primary" network interface
- Ignores secondary interfaces unless manually configured
- Requires service order and route configuration for dual networks

**Windows behavior:**
- Automatically handles multiple network interfaces
- Uses metric-based routing without manual configuration
- Dual network setup "just works"

### Mac-Only Configuration Summary
1. iPhone USB tethering for internet
2. Service order with iPhone USB on top
3. Manual IP configuration

### Windows-Only Configuration Summary
1. Connect to robot WiFi
2. Connect to internet (any method)
3. Done - Windows routes automatically

---

**Document Version:** 1.0  
**Last Updated:** January 2026  
**System:** ABB GoFa CRB 15000 Voice Control