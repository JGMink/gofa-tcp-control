using UnityEngine;
using System.IO;

public class KeyboardRobotControl : MonoBehaviour
{
    [Header("Movement Settings")]
    public float moveSpeed = 0.01f;  // 1cm per press
    public float fastMoveMultiplier = 5f;  // Hold Shift for faster movement
    public float rotationSpeed = 5f;  // 5 degrees per press

    [Header("Command File")]
    public string commandFilePath = "tcp_commands.json";

    [Header("References")]
    public GripperController gripperController;
    public Transform robotBase;  // Optional: The robot base to rotate

    // Current position and rotation
    private Vector3 currentPosition;
    private Vector3 currentRotation;  // Euler angles
    private float currentGripperPosition = 0.11f;  // Start open

    [System.Serializable]
    private class TCPCommand
    {
        public float x;
        public float y;
        public float z;
        public float rx;  // Rotation X (roll)
        public float ry;  // Rotation Y (pitch)
        public float rz;  // Rotation Z (yaw)
        public float gripper_position;
    }

    void Start()
    {
        // Load initial position from file if it exists
        LoadPosition();

        // Find gripper controller if not assigned
        if (gripperController == null)
        {
            gripperController = FindObjectOfType<GripperController>();
        }

        Debug.Log("=== Keyboard Robot Control ===");
        Debug.Log("MOVEMENT:");
        Debug.Log("  Arrow Keys: Move left/right/forward/backward");
        Debug.Log("  Page Up/Down: Move up/down (Y axis)");
        Debug.Log("  W/S: Move forward/backward (alternate)");
        Debug.Log("  A/D: Move left/right (alternate)");
        Debug.Log("");
        Debug.Log("ROTATION:");
        Debug.Log("  Z/X: Rotate left/right (yaw)");
        Debug.Log("  T/G: Tilt up/down (pitch)");
        Debug.Log("  F/H: Roll left/right");
        Debug.Log("");
        Debug.Log("GRIPPER:");
        Debug.Log("  Space: Open gripper");
        Debug.Log("  C: Close gripper");
        Debug.Log("  V: Half-close gripper");
        Debug.Log("");
        Debug.Log("OTHER:");
        Debug.Log("  Hold Shift: Move/rotate 5x faster");
        Debug.Log("  R: Reset to home position");
        Debug.Log("==============================");
    }

    void Update()
    {
        HandleMovementInput();
        HandleRotationInput();
        HandleGripperInput();
    }

    void HandleMovementInput()
    {
        Vector3 movement = Vector3.zero;
        float speed = moveSpeed;

        // Check for fast movement modifier
        if (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift))
        {
            speed *= fastMoveMultiplier;
        }

        // Arrow keys for XZ movement
        if (Input.GetKeyDown(KeyCode.RightArrow))
        {
            movement.x += speed;
            Debug.Log($"→ Move RIGHT {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.LeftArrow))
        {
            movement.x -= speed;
            Debug.Log($"← Move LEFT {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.UpArrow))
        {
            movement.z += speed;
            Debug.Log($"↑ Move FORWARD {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.DownArrow))
        {
            movement.z -= speed;
            Debug.Log($"↓ Move BACKWARD {speed * 100:F1}cm");
        }

        // Page Up/Down for Y movement
        if (Input.GetKeyDown(KeyCode.PageUp))
        {
            movement.y += speed;
            Debug.Log($"⬆ Move UP {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.PageDown))
        {
            movement.y -= speed;
            Debug.Log($"⬇ Move DOWN {speed * 100:F1}cm");
        }

        // W/S for forward/backward
        if (Input.GetKeyDown(KeyCode.W))
        {
            movement.z += speed;
            Debug.Log($"W: Move FORWARD {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.S))
        {
            movement.z -= speed;
            Debug.Log($"S: Move BACKWARD {speed * 100:F1}cm");
        }

        // A/D for left/right
        if (Input.GetKeyDown(KeyCode.A))
        {
            movement.x -= speed;
            Debug.Log($"A: Move LEFT {speed * 100:F1}cm");
        }
        if (Input.GetKeyDown(KeyCode.D))
        {
            movement.x += speed;
            Debug.Log($"D: Move RIGHT {speed * 100:F1}cm");
        }

        // Reset to home
        if (Input.GetKeyDown(KeyCode.R))
        {
            currentPosition = new Vector3(0.0f, 0.567f, -0.24f);
            currentRotation = Vector3.zero;
            Debug.Log("🏠 Reset to HOME position");
            SavePosition();
        }

        // Apply movement
        if (movement.magnitude > 0.0001f)
        {
            currentPosition += movement;
            SavePosition();
        }
    }

    void HandleRotationInput()
    {
        Vector3 rotation = Vector3.zero;
        float speed = rotationSpeed;

        // Check for fast rotation modifier
        if (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift))
        {
            speed *= fastMoveMultiplier;
        }

        // Z/X for yaw (rotation around Y axis)
        if (Input.GetKeyDown(KeyCode.Z))
        {
            rotation.y -= speed;
            Debug.Log($"↺ Rotate LEFT {speed}°");
        }
        if (Input.GetKeyDown(KeyCode.X))
        {
            rotation.y += speed;
            Debug.Log($"↻ Rotate RIGHT {speed}°");
        }

        // T/G for pitch (rotation around X axis)
        if (Input.GetKeyDown(KeyCode.T))
        {
            rotation.x -= speed;
            Debug.Log($"⤴ Tilt UP {speed}°");
        }
        if (Input.GetKeyDown(KeyCode.G))
        {
            rotation.x += speed;
            Debug.Log($"⤵ Tilt DOWN {speed}°");
        }

        // F/H for roll (rotation around Z axis)
        if (Input.GetKeyDown(KeyCode.F))
        {
            rotation.z -= speed;
            Debug.Log($"⟲ Roll LEFT {speed}°");
        }
        if (Input.GetKeyDown(KeyCode.H))
        {
            rotation.z += speed;
            Debug.Log($"⟳ Roll RIGHT {speed}°");
        }

        // Apply rotation
        if (rotation.magnitude > 0.0001f)
        {
            currentRotation += rotation;
            SavePosition();
        }
    }

    void HandleGripperInput()
    {
        bool gripperChanged = false;

        // Space to open
        if (Input.GetKeyDown(KeyCode.Space))
        {
            currentGripperPosition = 0.11f;  // Fully open
            gripperChanged = true;
            Debug.Log("👐 OPEN gripper");
        }

        // C to close
        if (Input.GetKeyDown(KeyCode.C))
        {
            currentGripperPosition = 0.0f;  // Fully closed
            gripperChanged = true;
            Debug.Log("✊ CLOSE gripper");
        }

        // V for half-closed (for testing)
        if (Input.GetKeyDown(KeyCode.V))
        {
            currentGripperPosition = 0.055f;  // Half
            gripperChanged = true;
            Debug.Log("🤏 HALF gripper (55mm)");
        }

        if (gripperChanged)
        {
            SavePosition();
        }
    }

    void LoadPosition()
    {
        if (!File.Exists(commandFilePath))
        {
            // Default position
            currentPosition = new Vector3(0.0f, 0.567f, -0.24f);
            return;
        }

        try
        {
            string json = File.ReadAllText(commandFilePath);
            TCPCommand cmd = JsonUtility.FromJson<TCPCommand>(json);

            currentPosition = new Vector3(cmd.x, cmd.y, cmd.z);
            currentRotation = new Vector3(cmd.rx, cmd.ry, cmd.rz);
            currentGripperPosition = cmd.gripper_position;

            Debug.Log($"Loaded position: {currentPosition}, rotation: {currentRotation}, gripper: {currentGripperPosition * 1000:F1}mm");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to load position: {e.Message}");
            currentPosition = new Vector3(0.0f, 0.567f, -0.24f);
        }
    }

    void SavePosition()
    {
        try
        {
            TCPCommand cmd = new TCPCommand
            {
                x = currentPosition.x,
                y = currentPosition.y,
                z = currentPosition.z,
                rx = currentRotation.x,
                ry = currentRotation.y,
                rz = currentRotation.z,
                gripper_position = currentGripperPosition
            };

            string json = JsonUtility.ToJson(cmd, true);
            File.WriteAllText(commandFilePath, json);

            // Also update the visual robot/gripper if in Unity
            if (transform != null)
            {
                transform.position = currentPosition;
            }

            if (robotBase != null)
            {
                robotBase.rotation = Quaternion.Euler(currentRotation);
            }

            if (gripperController != null)
            {
                gripperController.SetGripperPosition(currentGripperPosition);
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to save position: {e.Message}");
        }
    }

    // Display current position on screen
    void OnGUI()
    {
        GUIStyle style = new GUIStyle();
        style.fontSize = 16;
        style.normal.textColor = Color.white;
        style.padding = new RectOffset(10, 10, 10, 10);

        string posText = $"Position: ({currentPosition.x:F3}, {currentPosition.y:F3}, {currentPosition.z:F3})\n";
        posText += $"Rotation: ({currentRotation.x:F1}°, {currentRotation.y:F1}°, {currentRotation.z:F1}°)\n";
        posText += $"Gripper: {currentGripperPosition * 1000:F1}mm ({(currentGripperPosition > 0.05f ? "OPEN" : "CLOSED")})";

        GUI.Label(new Rect(10, 10, 400, 80), posText, style);
    }
}
