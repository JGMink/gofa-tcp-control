using UnityEngine;
using System.IO;

/// <summary>
/// Simple proxy gripper - uses basic cubes to show gripper state.
/// Visuals don't matter - just shows open/close for testing.
/// Physical robot gets exact same commands regardless.
/// </summary>
public class ProxyGripperVisualizer : MonoBehaviour
{
    [Header("Simple Visual Representation")]
    public GameObject leftFingerProxy;
    public GameObject rightFingerProxy;
    public GameObject baseProxy;

    [Header("Command File")]
    public string commandFilePath = "tcp_commands.json";
    public float pollInterval = 0.1f;

    [Header("Settings")]
    public float maxStroke = 0.11f; // 110mm

    [Header("Object Grabbing")]
    public bool enableGrabbing = true;
    public float grabDistance = 0.02f;
    public LayerMask grabbableLayer;

    private float currentPosition = 0.11f;
    private float targetPosition = 0.11f;
    private float lastPollTime;
    private GameObject heldObject;

    [ContextMenu("Create Simple Gripper Visuals")]
    void CreateSimpleVisuals()
    {
        // Create base
        if (baseProxy == null)
        {
            baseProxy = GameObject.CreatePrimitive(PrimitiveType.Cube);
            baseProxy.name = "Base_Proxy";
            baseProxy.transform.SetParent(transform);
            baseProxy.transform.localPosition = Vector3.zero;
            baseProxy.transform.localScale = new Vector3(0.05f, 0.05f, 0.1f); // 5cm x 5cm x 10cm

            // Color it blue
            Renderer r = baseProxy.GetComponent<Renderer>();
            Material mat = new Material(Shader.Find("Standard"));
            mat.color = Color.blue;
            r.material = mat;
        }

        // Create left finger
        if (leftFingerProxy == null)
        {
            leftFingerProxy = GameObject.CreatePrimitive(PrimitiveType.Cube);
            leftFingerProxy.name = "Finger_Left_Proxy";
            leftFingerProxy.transform.SetParent(transform);
            leftFingerProxy.transform.localPosition = new Vector3(-0.055f, 0, 0.05f);
            leftFingerProxy.transform.localScale = new Vector3(0.01f, 0.03f, 0.08f); // Finger shape

            // Color it green
            Renderer r = leftFingerProxy.GetComponent<Renderer>();
            Material mat = new Material(Shader.Find("Standard"));
            mat.color = Color.green;
            r.material = mat;
        }

        // Create right finger
        if (rightFingerProxy == null)
        {
            rightFingerProxy = GameObject.CreatePrimitive(PrimitiveType.Cube);
            rightFingerProxy.name = "Finger_Right_Proxy";
            rightFingerProxy.transform.SetParent(transform);
            rightFingerProxy.transform.localPosition = new Vector3(0.055f, 0, 0.05f);
            rightFingerProxy.transform.localScale = new Vector3(0.01f, 0.03f, 0.08f);

            // Color it red
            Renderer r = rightFingerProxy.GetComponent<Renderer>();
            Material mat = new Material(Shader.Find("Standard"));
            mat.color = Color.red;
            r.material = mat;
        }

        Debug.Log("✅ Created simple proxy gripper visuals!");
        Debug.Log("   Blue cube = base, Green/Red cubes = fingers");
    }

    void Start()
    {
        // Auto-create if not assigned
        if (leftFingerProxy == null || rightFingerProxy == null)
        {
            Debug.Log("Creating simple gripper visuals...");
            CreateSimpleVisuals();
        }

        Debug.Log("═══════════════════════════════════════");
        Debug.Log("PROXY GRIPPER VISUALIZER");
        Debug.Log("═══════════════════════════════════════");
        Debug.Log("This is a SIMPLE visual representation");
        Debug.Log("Physical robot gets exact same commands");
        Debug.Log("Appearance doesn't matter - function does!");
        Debug.Log("═══════════════════════════════════════\n");
    }

    void Update()
    {
        // Poll for commands
        if (Time.time - lastPollTime >= pollInterval)
        {
            ReadCommands();
            lastPollTime = Time.time;
        }

        // Smooth movement
        if (Mathf.Abs(currentPosition - targetPosition) > 0.0001f)
        {
            float oldPosition = currentPosition;
            currentPosition = Mathf.MoveTowards(currentPosition, targetPosition, 0.1f * Time.deltaTime);
            UpdateFingerPositions();

            // Try grab when closing
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

        // Update held object
        if (heldObject != null)
        {
            Vector3 gripCenter = (leftFingerProxy.transform.position + rightFingerProxy.transform.position) / 2f;
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

                    string state = targetPosition < 0.02f ? "CLOSED" :
                                   targetPosition > 0.09f ? "OPEN" :
                                   $"{targetPosition * 1000:F0}mm";

                    Debug.Log($"🤖 Gripper → {state}");
                }
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Error reading commands: {e.Message}");
        }
    }

    void UpdateFingerPositions()
    {
        float halfStroke = currentPosition / 2f;

        if (leftFingerProxy != null)
            leftFingerProxy.transform.localPosition = new Vector3(-halfStroke, 0, 0.05f);

        if (rightFingerProxy != null)
            rightFingerProxy.transform.localPosition = new Vector3(halfStroke, 0, 0.05f);
    }

    void TryGrabObject()
    {
        Vector3 gripCenter = (leftFingerProxy.transform.position + rightFingerProxy.transform.position) / 2f;

        Collider[] colliders = Physics.OverlapSphere(gripCenter, grabDistance, grabbableLayer);

        foreach (Collider col in colliders)
        {
            GrabbableObject grabbable = col.GetComponent<GrabbableObject>();
            if (grabbable != null && !grabbable.IsHeld())
            {
                heldObject = col.gameObject;
                grabbable.OnGrabbed(transform);
                Debug.Log($"✊ GRABBED: {heldObject.name}");
                break;
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
    public void SetPosition(float position) => targetPosition = Mathf.Clamp(position, 0f, maxStroke);
    public void Open() => SetPosition(maxStroke);
    public void Close() => SetPosition(0f);
    public float GetCurrentPosition() => currentPosition;
    public bool IsHoldingObject() => heldObject != null;
    public GameObject GetHeldObject() => heldObject;

    void OnDrawGizmos()
    {
        if (leftFingerProxy == null || rightFingerProxy == null) return;

        // Draw grip line
        Gizmos.color = heldObject != null ? Color.green : Color.cyan;
        Gizmos.DrawLine(leftFingerProxy.transform.position, rightFingerProxy.transform.position);

        // Draw grip center
        Vector3 center = (leftFingerProxy.transform.position + rightFingerProxy.transform.position) / 2f;
        Gizmos.color = Color.yellow;
        Gizmos.DrawWireSphere(center, 0.01f);

        // Draw grab zone
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
