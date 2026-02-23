using UnityEngine;
using System.IO;

/// <summary>
/// Controls the robot TCP (Tool Center Point) based on commands from JSON file.
/// This mimics EGM-style control where TCP position dictates robot movement.
/// </summary>
public class TCPController : MonoBehaviour
{
    [Header("TCP Reference")]
    [Tooltip("The TCP GameObject - this is what moves based on commands")]
    public Transform tcpTransform;

    [Header("Gripper Reference")]
    public GripperController gripperController;

    [Header("Command File")]
    public string commandFilePath = "tcp_commands.json";
    public float pollInterval = 0.1f;  // 100ms

    [Header("Movement Settings")]
    public float moveSpeed = 1f;  // Speed multiplier for smooth movement
    public bool smoothMovement = true;

    private Vector3 targetPosition;
    private float targetGripperPosition;
    private float lastPollTime;

    [System.Serializable]
    private class TCPCommand
    {
        public float x;
        public float y;
        public float z;
        public float gripper_position;
    }

    void Start()
    {
        // Find TCP if not assigned
        if (tcpTransform == null)
        {
            // Look for GameObject named "TCP"
            GameObject tcpObj = GameObject.Find("TCP");
            if (tcpObj != null)
            {
                tcpTransform = tcpObj.transform;
                Debug.Log($"✓ Auto-found TCP: {tcpObj.name}");
            }
            else
            {
                Debug.LogWarning("⚠️ TCP not found! Using this GameObject as TCP");
                tcpTransform = transform;
            }
        }

        // Find gripper controller if not assigned
        if (gripperController == null)
        {
            gripperController = FindObjectOfType<GripperController>();
            if (gripperController != null)
            {
                Debug.Log($"✓ Auto-found GripperController on: {gripperController.gameObject.name}");
            }
        }

        // Initialize target to current position
        targetPosition = tcpTransform.position;
        targetGripperPosition = gripperController != null ? gripperController.GetCurrentPosition() : 0.11f;

        Debug.Log("=== TCP Controller Ready ===");
        Debug.Log($"TCP Position: {targetPosition}");
        Debug.Log($"Reading commands from: {commandFilePath}");
        Debug.Log("===========================");
    }

    void Update()
    {
        // Poll for new commands
        if (Time.time - lastPollTime >= pollInterval)
        {
            ReadCommands();
            lastPollTime = Time.time;
        }

        // Move TCP to target
        if (smoothMovement)
        {
            tcpTransform.position = Vector3.Lerp(tcpTransform.position, targetPosition, Time.deltaTime * moveSpeed * 10f);
        }
        else
        {
            tcpTransform.position = targetPosition;
        }

        // Update gripper
        if (gripperController != null)
        {
            gripperController.SetGripperPosition(targetGripperPosition);
        }
    }

    void ReadCommands()
    {
        if (!File.Exists(commandFilePath))
        {
            return;
        }

        try
        {
            string json = File.ReadAllText(commandFilePath);
            TCPCommand cmd = JsonUtility.FromJson<TCPCommand>(json);

            if (cmd != null)
            {
                Vector3 newPosition = new Vector3(cmd.x, cmd.y, cmd.z);
                float newGripper = cmd.gripper_position;

                bool posChanged = Vector3.Distance(newPosition, targetPosition) > 0.0001f;
                bool gripperChanged = Mathf.Abs(newGripper - targetGripperPosition) > 0.001f;

                if (posChanged)
                {
                    targetPosition = newPosition;
                    Debug.Log($"→ TCP move to: {targetPosition}");
                }

                if (gripperChanged)
                {
                    targetGripperPosition = newGripper;
                    Debug.Log($"✊ Gripper → {targetGripperPosition * 1000:F1}mm");
                }
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to read command: {e.Message}");
        }
    }

    // Visualize TCP in scene view
    void OnDrawGizmos()
    {
        if (tcpTransform == null) return;

        // Draw TCP coordinate frame
        Gizmos.color = Color.red;
        Gizmos.DrawRay(tcpTransform.position, tcpTransform.right * 0.05f);  // X axis

        Gizmos.color = Color.green;
        Gizmos.DrawRay(tcpTransform.position, tcpTransform.up * 0.05f);  // Y axis

        Gizmos.color = Color.blue;
        Gizmos.DrawRay(tcpTransform.position, tcpTransform.forward * 0.05f);  // Z axis

        // Draw sphere at TCP
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(tcpTransform.position, 0.01f);
    }
}
