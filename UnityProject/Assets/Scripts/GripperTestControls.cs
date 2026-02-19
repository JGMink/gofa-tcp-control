using UnityEngine;
using System.IO;

/// <summary>
/// Keyboard controls for testing gripper WITHOUT the robot.
/// Press keys to control gripper and see it work in Unity.
/// Commands are written to tcp_commands.json for robot to mirror.
/// </summary>
public class GripperTestControls : MonoBehaviour
{
    [Header("References")]
    public RG2Controller gripperController;
    public Transform tcpTransform;

    [Header("Command File")]
    public string commandFilePath = "tcp_commands.json";

    [Header("Movement Settings")]
    public float moveSpeed = 0.1f; // m/s
    public float rotateSpeed = 30f; // deg/s

    private Vector3 currentPosition;
    private Vector3 currentRotation;
    private float currentGripperPos = 0.11f;

    void Start()
    {
        // Auto-find references
        if (gripperController == null)
        {
            gripperController = FindObjectOfType<RG2Controller>();
        }

        if (tcpTransform == null)
        {
            tcpTransform = transform;
        }

        currentPosition = tcpTransform.position;
        currentRotation = tcpTransform.eulerAngles;

        Debug.Log("════════════════════════════════════════");
        Debug.Log("GRIPPER TEST CONTROLS");
        Debug.Log("════════════════════════════════════════");
        Debug.Log("GRIPPER CONTROLS:");
        Debug.Log("  O - Open gripper");
        Debug.Log("  C - Close gripper");
        Debug.Log("  H - Half open (55mm)");
        Debug.Log("");
        Debug.Log("TCP MOVEMENT:");
        Debug.Log("  Arrow Keys - Move X/Z");
        Debug.Log("  Page Up/Down - Move Y");
        Debug.Log("  Q/E - Rotate Z");
        Debug.Log("  R/F - Rotate X");
        Debug.Log("");
        Debug.Log("SYSTEM:");
        Debug.Log("  I - Print info");
        Debug.Log("  Esc - Reset all");
        Debug.Log("════════════════════════════════════════\n");
    }

    void Update()
    {
        HandleGripperControls();
        HandleTCPMovement();
        HandleTCPRotation();
        HandleSystemControls();
    }

    void HandleGripperControls()
    {
        if (Input.GetKeyDown(KeyCode.O))
        {
            currentGripperPos = 0.11f; // Open
            SaveCommands();
            Debug.Log("✋ Gripper OPEN (110mm)");
        }

        if (Input.GetKeyDown(KeyCode.C))
        {
            currentGripperPos = 0.0f; // Closed
            SaveCommands();
            Debug.Log("✊ Gripper CLOSED (0mm)");
        }

        if (Input.GetKeyDown(KeyCode.H))
        {
            currentGripperPos = 0.055f; // Half
            SaveCommands();
            Debug.Log("🤏 Gripper HALF (55mm)");
        }
    }

    void HandleTCPMovement()
    {
        Vector3 movement = Vector3.zero;

        // Horizontal movement
        if (Input.GetKey(KeyCode.LeftArrow))
            movement.x -= moveSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.RightArrow))
            movement.x += moveSpeed * Time.deltaTime;

        // Forward/backward
        if (Input.GetKey(KeyCode.UpArrow))
            movement.z += moveSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.DownArrow))
            movement.z -= moveSpeed * Time.deltaTime;

        // Vertical movement
        if (Input.GetKey(KeyCode.PageUp))
            movement.y += moveSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.PageDown))
            movement.y -= moveSpeed * Time.deltaTime;

        if (movement != Vector3.zero)
        {
            currentPosition += movement;
            tcpTransform.position = currentPosition;
            SaveCommands();
        }
    }

    void HandleTCPRotation()
    {
        Vector3 rotation = Vector3.zero;

        // Rotate around Z axis
        if (Input.GetKey(KeyCode.Q))
            rotation.z += rotateSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.E))
            rotation.z -= rotateSpeed * Time.deltaTime;

        // Rotate around X axis
        if (Input.GetKey(KeyCode.R))
            rotation.x += rotateSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.F))
            rotation.x -= rotateSpeed * Time.deltaTime;

        // Rotate around Y axis
        if (Input.GetKey(KeyCode.T))
            rotation.y += rotateSpeed * Time.deltaTime;
        if (Input.GetKey(KeyCode.G))
            rotation.y -= rotateSpeed * Time.deltaTime;

        if (rotation != Vector3.zero)
        {
            currentRotation += rotation;
            tcpTransform.eulerAngles = currentRotation;
            SaveCommands();
        }
    }

    void HandleSystemControls()
    {
        if (Input.GetKeyDown(KeyCode.I))
        {
            PrintInfo();
        }

        if (Input.GetKeyDown(KeyCode.Escape))
        {
            ResetAll();
        }
    }

    void SaveCommands()
    {
        CommandData data = new CommandData
        {
            position = new float[] { currentPosition.x, currentPosition.y, currentPosition.z },
            rotation = new float[] { currentRotation.x, currentRotation.y, currentRotation.z },
            gripper_position = currentGripperPos
        };

        try
        {
            string json = JsonUtility.ToJson(data, true);
            File.WriteAllText(commandFilePath, json);
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to save commands: {e.Message}");
        }
    }

    void PrintInfo()
    {
        Debug.Log("════════════════════════════════════════");
        Debug.Log("CURRENT STATE");
        Debug.Log("════════════════════════════════════════");
        Debug.Log($"TCP Position: {currentPosition}");
        Debug.Log($"TCP Rotation: {currentRotation}");
        Debug.Log($"Gripper: {currentGripperPos * 1000:F1}mm");

        if (gripperController != null)
        {
            Debug.Log($"Actual Gripper Pos: {gripperController.GetCurrentPosition() * 1000:F1}mm");
            Debug.Log($"Holding Object: {gripperController.IsHoldingObject()}");

            if (gripperController.IsHoldingObject())
            {
                Debug.Log($"Held Object: {gripperController.GetHeldObject().name}");
            }
        }

        Debug.Log("════════════════════════════════════════");
    }

    void ResetAll()
    {
        currentPosition = Vector3.zero;
        currentRotation = Vector3.zero;
        currentGripperPos = 0.11f;

        tcpTransform.position = currentPosition;
        tcpTransform.eulerAngles = currentRotation;

        SaveCommands();

        Debug.Log("🔄 RESET - All values returned to zero/open");
    }

    void OnGUI()
    {
        // Simple on-screen display
        GUIStyle style = new GUIStyle();
        style.fontSize = 12;
        style.normal.textColor = Color.white;
        style.padding = new RectOffset(5, 5, 5, 5);

        GUI.BeginGroup(new Rect(10, Screen.height - 100, 300, 90));

        GUI.Label(new Rect(0, 0, 300, 20), $"TCP: {currentPosition:F2}", style);
        GUI.Label(new Rect(0, 20, 300, 20), $"Rot: {currentRotation:F1}°", style);
        GUI.Label(new Rect(0, 40, 300, 20), $"Gripper: {currentGripperPos * 1000:F0}mm", style);

        if (gripperController != null && gripperController.IsHoldingObject())
        {
            style.normal.textColor = Color.green;
            GUI.Label(new Rect(0, 60, 300, 20), $"✓ Holding: {gripperController.GetHeldObject().name}", style);
        }

        GUI.EndGroup();
    }

    [System.Serializable]
    public class CommandData
    {
        public float[] position;
        public float[] rotation;
        public float gripper_position;
    }
}
