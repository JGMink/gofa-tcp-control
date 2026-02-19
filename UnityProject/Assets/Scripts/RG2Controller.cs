using UnityEngine;
using System.IO;

/// <summary>
/// Controls RG2 gripper in Unity - reads from tcp_commands.json
/// Physical robot mirrors this via RAPID scripts reading the same file
/// </summary>
public class RG2Controller : MonoBehaviour
{
    [Header("Finger Transforms")]
    [Tooltip("Assign the movable finger transforms from rigged gripper")]
    public Transform fingerLeft;
    public Transform fingerRight;

    [Header("Settings")]
    [Tooltip("RG2 max stroke: 110mm total (55mm per finger)")]
    public float maxStroke = 0.11f;
    public float gripSpeed = 0.1f; // Movement speed

    [Header("Command File")]
    public string commandFilePath = "tcp_commands.json";
    public float pollInterval = 0.1f;

    [Header("Object Grabbing")]
    public bool enableGrabbing = true;
    public float grabDistance = 0.02f; // 20mm threshold
    public LayerMask grabbableLayer;

    private float currentPosition = 0.11f; // Start open
    private float targetPosition = 0.11f;
    private float lastPollTime;
    private GameObject heldObject;

    void Start()
    {
        if (fingerLeft == null || fingerRight == null)
        {
            Debug.LogError("❌ RG2Controller: Finger transforms not assigned!");
            enabled = false;
            return;
        }

        Debug.Log("════════════════════════════════════════");
        Debug.Log("RG2 CONTROLLER INITIALIZED");
        Debug.Log("════════════════════════════════════════");
        Debug.Log($"Max Stroke: {maxStroke * 1000}mm");
        Debug.Log($"Command File: {commandFilePath}");
        Debug.Log($"Object Grabbing: {(enableGrabbing ? "Enabled" : "Disabled")}");
        Debug.Log("════════════════════════════════════════\n");

        // Set initial position
        UpdateFingerPositions();
    }

    void Update()
    {
        // Poll for commands
        if (Time.time - lastPollTime >= pollInterval)
        {
            ReadCommands();
            lastPollTime = Time.time;
        }

        // Smooth movement to target
        if (Mathf.Abs(currentPosition - targetPosition) > 0.0001f)
        {
            float oldPosition = currentPosition;
            currentPosition = Mathf.MoveTowards(currentPosition, targetPosition, gripSpeed * Time.deltaTime);
            UpdateFingerPositions();

            // Check for grabbing when closing
            if (enableGrabbing && currentPosition < oldPosition && heldObject == null)
            {
                TryGrabObject();
            }

            // Release when opening
            if (enableGrabbing && currentPosition > oldPosition && heldObject != null && currentPosition > 0.05f)
            {
                ReleaseObject();
            }
        }

        // Update held object position
        if (heldObject != null)
        {
            Vector3 gripCenter = (fingerLeft.position + fingerRight.position) / 2f;
            heldObject.transform.position = gripCenter;
        }
    }

    void ReadCommands()
    {
        if (!File.Exists(commandFilePath))
            return;

        try
        {
            string json = File.ReadAllText(commandFilePath);
            CommandData data = JsonUtility.FromJson<CommandData>(json);

            if (data.gripper_position >= 0)
            {
                float newTarget = Mathf.Clamp(data.gripper_position, 0f, maxStroke);

                if (Mathf.Abs(newTarget - targetPosition) > 0.001f)
                {
                    targetPosition = newTarget;

                    string state = targetPosition < 0.02f ? "CLOSE" :
                                   targetPosition > 0.09f ? "OPEN" :
                                   $"{targetPosition * 1000:F0}mm";

                    Debug.Log($"🤖 Gripper → {state}");
                }
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Error reading gripper commands: {e.Message}");
        }
    }

    void UpdateFingerPositions()
    {
        // Each finger moves half the stroke distance from center
        float halfStroke = currentPosition / 2f;

        fingerLeft.localPosition = new Vector3(-halfStroke, 0, 0);
        fingerRight.localPosition = new Vector3(halfStroke, 0, 0);
    }

    void TryGrabObject()
    {
        // Find objects between fingers
        Vector3 gripCenter = (fingerLeft.position + fingerRight.position) / 2f;
        float gripWidth = Vector3.Distance(fingerLeft.position, fingerRight.position);

        Collider[] colliders = Physics.OverlapSphere(gripCenter, grabDistance, grabbableLayer);

        foreach (Collider col in colliders)
        {
            GrabbableObject grabbable = col.GetComponent<GrabbableObject>();
            if (grabbable != null && !grabbable.IsHeld())
            {
                // Check if object fits between fingers
                Bounds bounds = col.bounds;
                float objectWidth = bounds.size.x; // Assuming X is the grip axis

                if (objectWidth <= gripWidth * 1.2f) // 20% tolerance
                {
                    heldObject = col.gameObject;
                    grabbable.OnGrabbed(transform);

                    Debug.Log($"✊ GRABBED: {heldObject.name}");
                    break;
                }
            }
        }
    }

    void ReleaseObject()
    {
        if (heldObject != null)
        {
            GrabbableObject grabbable = heldObject.GetComponent<GrabbableObject>();
            if (grabbable != null)
            {
                grabbable.OnReleased();
            }

            Debug.Log($"✋ RELEASED: {heldObject.name}");
            heldObject = null;
        }
    }

    // Public API
    public void SetPosition(float position)
    {
        targetPosition = Mathf.Clamp(position, 0f, maxStroke);
    }

    public void Open() => SetPosition(maxStroke);
    public void Close() => SetPosition(0f);
    public float GetCurrentPosition() => currentPosition;
    public bool IsHoldingObject() => heldObject != null;
    public GameObject GetHeldObject() => heldObject;

    void OnDrawGizmos()
    {
        if (fingerLeft == null || fingerRight == null) return;

        // Draw grip line
        Gizmos.color = heldObject != null ? Color.green : Color.cyan;
        Gizmos.DrawLine(fingerLeft.position, fingerRight.position);

        // Draw grip center
        Vector3 center = (fingerLeft.position + fingerRight.position) / 2f;
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(center, 0.01f);

        // Draw grab detection sphere
        if (enableGrabbing)
        {
            Gizmos.color = new Color(1, 0, 0, 0.3f);
            Gizmos.DrawWireSphere(center, grabDistance);
        }
    }

    [System.Serializable]
    public class CommandData
    {
        public float[] position;
        public float[] rotation;
        public float gripper_position;
    }
}
