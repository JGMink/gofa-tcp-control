using UnityEngine;
using System.IO;

/// <summary>
/// Mirrors the physical RG2-FT gripper state in Unity.
/// Reads gripper position from robot controller (via tcp_commands.json or robot state file)
/// and updates finger transforms to match the real gripper.
///
/// Just like mirroring joint positions from RobotStudio!
/// </summary>
public class RG2MirrorController : MonoBehaviour
{
    [Header("Gripper Part References")]
    [Tooltip("Assign from your grouped RG2_FT model")]
    public Transform mount;           // Static
    public Transform gripperBase;     // Static
    public Transform fingerLeft;      // Movable - main finger
    public Transform fingerRight;     // Movable - main finger
    public Transform fingerpadLeft;   // Movable - child of fingerLeft
    public Transform fingerpadRight;  // Movable - child of fingerRight

    [Header("Robot State Source")]
    [Tooltip("File containing robot state (gripper position)")]
    public string robotStateFile = "tcp_commands.json";
    public float pollInterval = 0.1f; // Poll every 100ms

    [Header("Gripper Specs (RG2-FT)")]
    public float maxStroke = 0.11f; // 110mm total
    [Tooltip("Scale multiplier to compensate for model scale (if gripper is scaled down, increase this)")]
    public float scaleCompensation = 1.0f; // Adjust if gripper is scaled

    [Header("Auto-Setup")]
    [Tooltip("Automatically find and parent fingerpads to fingers")]
    public bool autoParentPads = true;

    private float currentGripperPosition = 0.11f; // Current state (meters)
    private float lastPollTime;
    private Vector3 fingerLeftStartPos;
    private Vector3 fingerRightStartPos;
    private float lastLoggedPosition = -1f; // Track last logged position to avoid spam

    void Start()
    {
        ValidateReferences();

        // Store initial finger positions (this is the "fully open" position in the model)
        fingerLeftStartPos = fingerLeft.localPosition;
        fingerRightStartPos = fingerRight.localPosition;

        Debug.Log($"Finger start positions: Left={fingerLeftStartPos}, Right={fingerRightStartPos}");

        // Auto-parent fingerpads if enabled
        if (autoParentPads)
        {
            AutoParentFingerpads();
        }

        Debug.Log("════════════════════════════════════════");
        Debug.Log("RG2 MIRROR CONTROLLER INITIALIZED");
        Debug.Log("════════════════════════════════════════");
        Debug.Log("Mode: Mirror physical robot gripper state");
        Debug.Log($"Reading from: {robotStateFile}");
        Debug.Log($"Mirroring: finger_left, finger_right + pads");
        Debug.Log($"Start positions: L={fingerLeftStartPos.x:F4}, R={fingerRightStartPos.x:F4}");
        Debug.Log("════════════════════════════════════════\n");
    }

    void Update()
    {
        // Poll robot state
        if (Time.time - lastPollTime >= pollInterval)
        {
            ReadRobotState();
            lastPollTime = Time.time;
        }

        // Update finger positions to mirror robot
        UpdateFingerPositions();
    }

    void ValidateReferences()
    {
        if (fingerLeft == null || fingerRight == null)
        {
            Debug.LogError("❌ RG2MirrorController: finger_left and finger_right must be assigned!");
            enabled = false;
            return;
        }

        if (fingerpadLeft == null || fingerpadRight == null)
        {
            Debug.LogWarning("⚠️ Fingerpads not assigned - will only move main fingers");
        }
    }

    void AutoParentFingerpads()
    {
        // Make fingerpads children of fingers if they aren't already
        if (fingerpadLeft != null && fingerpadLeft.parent != fingerLeft)
        {
            Vector3 worldPos = fingerpadLeft.position;
            Quaternion worldRot = fingerpadLeft.rotation;

            fingerpadLeft.SetParent(fingerLeft);
            fingerpadLeft.position = worldPos;
            fingerpadLeft.rotation = worldRot;

            Debug.Log("✓ Parented fingerpad_left to finger_left");
        }

        if (fingerpadRight != null && fingerpadRight.parent != fingerRight)
        {
            Vector3 worldPos = fingerpadRight.position;
            Quaternion worldRot = fingerpadRight.rotation;

            fingerpadRight.SetParent(fingerRight);
            fingerpadRight.position = worldPos;
            fingerpadRight.rotation = worldRot;

            Debug.Log("✓ Parented fingerpad_right to finger_right");
        }
    }

    void ReadRobotState()
    {
        if (!File.Exists(robotStateFile))
            return;

        try
        {
            string json = File.ReadAllText(robotStateFile);
            RobotState state = JsonUtility.FromJson<RobotState>(json);

            if (state.gripper_position >= 0)
            {
                float newPosition = Mathf.Clamp(state.gripper_position, 0f, maxStroke);

                // Only log if position changed significantly
                if (Mathf.Abs(newPosition - currentGripperPosition) > 0.001f)
                {
                    currentGripperPosition = newPosition;

                    string stateStr = currentGripperPosition < 0.02f ? "CLOSED" :
                                      currentGripperPosition > 0.09f ? "OPEN" :
                                      $"{currentGripperPosition * 1000:F0}mm";

                    Debug.Log($"🔄 Mirroring gripper: {stateStr}");
                }
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Error reading robot state: {e.Message}");
        }
    }

    void UpdateFingerPositions()
    {
        // currentGripperPosition: 0.11 = fully open, 0.0 = fully closed
        //
        // In this model:
        //   - Fingers start at local (0,0,0) which is the OPEN position
        //   - Movement axis is Y (local left-right in the gripper's frame)
        //   - Closing moves fingers inward along Y
        //   - Parent scale is ~0.025, so local coordinates must be large
        //     to produce small world-space movement
        //
        // openingOffset: how far apart fingers should be from center
        //   At 0.11 (open):  openingOffset = maxStroke/2 = 0.055 (each finger 55mm from center)
        //   At 0.0 (closed): openingOffset = 0 (fingers at center)
        //
        // Since start pos (0,0,0) = open, we need to move INWARD as gripper closes.
        // closingOffset = how much to move from start toward center
        float closingOffset = (maxStroke - currentGripperPosition) / 2f;

        // Compensate for parent scale: local units are divided by parent scale
        // With parent scale 0.025, moving 0.055 local = 0.001375 world
        // We need to move in local space, so divide by the parent's lossy scale
        float parentScale = transform.lossyScale.y; // Use Y since that's our movement axis
        float localOffset = closingOffset;
        if (parentScale > 0.0001f)
        {
            localOffset = closingOffset / parentScale;
        }

        localOffset *= scaleCompensation;

        // Move fingers along local Y axis from their starting positions
        // Left finger: moves positive Y (inward) as gripper closes
        // Right finger: moves negative Y (inward) as gripper closes
        Vector3 leftPos = fingerLeftStartPos;
        leftPos.y += localOffset;

        Vector3 rightPos = fingerRightStartPos;
        rightPos.y -= localOffset;

        fingerLeft.localPosition = leftPos;
        fingerRight.localPosition = rightPos;

        // Only log when position actually changes
        if (Mathf.Abs(currentGripperPosition - lastLoggedPosition) > 0.001f)
        {
            Debug.Log($"[Fingers] Gripper={currentGripperPosition * 1000:F1}mm | localOffset={localOffset:F4} | L.y={leftPos.y:F4}, R.y={rightPos.y:F4}");
            lastLoggedPosition = currentGripperPosition;
        }

        // Fingerpads move with fingers since they're children
    }

    // Public API for debugging/testing
    public float GetCurrentPosition() => currentGripperPosition;
    public string GetGripperState()
    {
        if (currentGripperPosition < 0.02f) return "CLOSED";
        if (currentGripperPosition > 0.09f) return "OPEN";
        return $"{currentGripperPosition * 1000:F0}mm";
    }

    void OnGUI()
    {
        // Simple status display
        GUIStyle style = new GUIStyle();
        style.fontSize = 14;
        style.normal.textColor = Color.white;
        style.padding = new RectOffset(5, 5, 5, 5);

        GUI.BeginGroup(new Rect(10, Screen.height - 80, 300, 70));

        GUI.Label(new Rect(0, 0, 300, 25), "🔄 MIRRORING ROBOT GRIPPER", style);
        GUI.Label(new Rect(0, 25, 300, 25), $"State: {GetGripperState()}", style);
        GUI.Label(new Rect(0, 45, 300, 25), $"Position: {currentGripperPosition * 1000:F1}mm", style);

        GUI.EndGroup();
    }

    void OnDrawGizmos()
    {
        if (fingerLeft == null || fingerRight == null) return;

        // Draw line between fingers
        Gizmos.color = Color.cyan;
        Gizmos.DrawLine(fingerLeft.position, fingerRight.position);

        // Draw grip center
        Vector3 center = (fingerLeft.position + fingerRight.position) / 2f;
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(center, 0.01f);

        // Draw coordinate axes at gripper root
        Gizmos.color = Color.red;
        Gizmos.DrawRay(transform.position, transform.right * 0.05f);

        Gizmos.color = Color.green;
        Gizmos.DrawRay(transform.position, transform.up * 0.05f);

        Gizmos.color = Color.blue;
        Gizmos.DrawRay(transform.position, transform.forward * 0.05f);
    }

    [System.Serializable]
    public class RobotState
    {
        // Support both formats
        public float x;
        public float y;
        public float z;
        public float[] position;        // TCP position (alternative format)
        public float[] rotation;        // TCP rotation
        public float gripper_position;  // 0.0 = closed, 0.11 = open
        public float[] joint_angles;    // Optional: joint positions
    }
}
