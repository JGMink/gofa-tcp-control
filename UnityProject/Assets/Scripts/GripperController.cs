using UnityEngine;
using System.IO;

public class GripperController : MonoBehaviour
{
    [Header("Gripper Model Settings")]
    public enum GripperModel { RG2, RG6 }
    public GripperModel modelType = GripperModel.RG2;

    [Header("Finger Transforms")]
    public Transform fingerLeft;
    public Transform fingerRight;
    public Transform gripperBase;

    [Header("Stroke Settings - RG2")]
    [Tooltip("RG2: 110mm max stroke, RG6: 160mm max stroke")]
    public float maxStroke = 0.110f;  // RG2: 110mm = 0.11m
    public float minStroke = 0.0f;

    [Header("Grip Force Settings")]
    [Tooltip("RG2: 3-40N, RG6: 25-120N")]
    public float maxForce = 40f;  // RG2: 40N
    public float minForce = 3f;   // RG2: 3N

    [Header("Animation Settings")]
    [Tooltip("Speed at which fingers open/close (meters per second)")]
    public float gripSpeed = 0.05f;  // 50mm/sec

    [Header("Command File Settings")]
    public string commandFilePath = "tcp_commands.json";
    public float pollInterval = 0.1f;  // Check for commands every 100ms

    // Internal state
    private float currentGripPosition = 0.110f;  // Start fully open (RG2: 110mm)
    private float targetGripPosition = 0.110f;
    private Vector3 leftFingerStartPos;
    private Vector3 rightFingerStartPos;
    private float lastPollTime;

    [System.Serializable]
    private class TCPCommand
    {
        public float[] position;
        public float[] rotation;
        public float gripper_position;  // 0.0 = closed, 0.11 = open (RG2)
    }

    void Start()
    {
        // Validate references
        if (fingerLeft == null || fingerRight == null)
        {
            Debug.LogError("GripperController: Finger transforms not assigned!");
            enabled = false;
            return;
        }

        // Store initial finger positions
        leftFingerStartPos = fingerLeft.localPosition;
        rightFingerStartPos = fingerRight.localPosition;

        // Set stroke based on model type
        if (modelType == GripperModel.RG6)
        {
            maxStroke = 0.160f;  // RG6: 160mm
            maxForce = 120f;
            minForce = 25f;
        }

        // Start fully open
        currentGripPosition = maxStroke;
        targetGripPosition = maxStroke;
        UpdateFingerPositions();

        Debug.Log($"GripperController initialized: Model={modelType}, MaxStroke={maxStroke}m, Force={minForce}-{maxForce}N");
    }

    void Update()
    {
        // Poll for commands from file
        if (Time.time - lastPollTime >= pollInterval)
        {
            ReadGripperCommands();
            lastPollTime = Time.time;
        }

        // Smoothly animate to target position
        if (Mathf.Abs(currentGripPosition - targetGripPosition) > 0.0001f)
        {
            currentGripPosition = Mathf.MoveTowards(
                currentGripPosition,
                targetGripPosition,
                gripSpeed * Time.deltaTime
            );

            UpdateFingerPositions();
        }
    }

    void ReadGripperCommands()
    {
        if (!File.Exists(commandFilePath))
            return;

        try
        {
            string json = File.ReadAllText(commandFilePath);
            TCPCommand command = JsonUtility.FromJson<TCPCommand>(json);

            if (command != null && command.gripper_position >= 0)
            {
                // Clamp to valid range
                float newTarget = Mathf.Clamp(command.gripper_position, minStroke, maxStroke);

                if (Mathf.Abs(newTarget - targetGripPosition) > 0.001f)
                {
                    targetGripPosition = newTarget;
                    Debug.Log($"Gripper command received: {targetGripPosition * 1000:F1}mm");
                }
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to read gripper command: {e.Message}");
        }
    }

    void UpdateFingerPositions()
    {
        // OnRobot RG2/RG6 fingers move symmetrically from center
        // Each finger moves half the total stroke
        float halfStroke = currentGripPosition / 2.0f;

        // Update finger positions (adjust axis based on your model's orientation)
        // This assumes fingers move along the X-axis - adjust if needed
        if (fingerLeft != null)
        {
            fingerLeft.localPosition = leftFingerStartPos + new Vector3(-halfStroke, 0, 0);
        }

        if (fingerRight != null)
        {
            fingerRight.localPosition = rightFingerStartPos + new Vector3(halfStroke, 0, 0);
        }
    }

    // Public methods for external control
    public void SetGripperPosition(float position)
    {
        targetGripPosition = Mathf.Clamp(position, minStroke, maxStroke);
    }

    public void OpenGripper()
    {
        targetGripPosition = maxStroke;
    }

    public void CloseGripper()
    {
        targetGripPosition = minStroke;
    }

    public float GetCurrentPosition()
    {
        return currentGripPosition;
    }

    public float GetCurrentPositionPercent()
    {
        return (currentGripPosition / maxStroke) * 100f;
    }

    // Gizmos for debugging in Scene view
    void OnDrawGizmos()
    {
        if (fingerLeft != null && fingerRight != null)
        {
            // Draw line between fingers to visualize grip width
            Gizmos.color = Color.cyan;
            Gizmos.DrawLine(fingerLeft.position, fingerRight.position);
        }
    }
}
