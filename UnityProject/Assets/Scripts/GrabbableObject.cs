using UnityEngine;
using System.IO;
using System.Collections.Generic;

public class GrabbableObject : MonoBehaviour
{
    [Header("Object Settings")]
    public string objectName = "cube";
    public Color objectColor = Color.white;

    [Header("Physics Settings")]
    public bool useGravity = true;
    public bool isKinematic = false;

    [Header("Grip Detection")]
    public float gripDetectionRadius = 0.05f;  // 5cm radius to detect gripper
    public LayerMask gripperLayer;

    [Header("State Sync")]
    public string stateFilePath = "object_states.json";
    public float syncInterval = 0.5f;  // Sync position every 500ms

    [Header("Stacking")]
    public bool enableStacking = true;
    public float stackDetectionDistance = 0.06f;  // 6cm to detect stacking

    // Internal state
    private Rigidbody rb;
    private bool isHeld = false;
    private Transform gripper;
    private Vector3 lastSyncedPosition;
    private float lastSyncTime;
    private MeshRenderer meshRenderer;
    private GrabbableObject objectBelow;  // Object this is stacked on
    private List<GrabbableObject> objectsAbove = new List<GrabbableObject>();  // Objects stacked on this

    [System.Serializable]
    private class ObjectState
    {
        public string name;
        public float[] position;
        public bool held;
        public string color;
        public string object_below;  // Name of object this is stacked on
        public int stack_height;     // How many objects are stacked on this
    }

    [System.Serializable]
    private class ObjectStates
    {
        public ObjectState[] objects;
    }

    void Start()
    {
        // Setup rigidbody
        rb = GetComponent<Rigidbody>();
        if (rb == null)
        {
            rb = gameObject.AddComponent<Rigidbody>();
        }
        rb.useGravity = useGravity;
        rb.isKinematic = isKinematic;

        // Setup renderer
        meshRenderer = GetComponent<MeshRenderer>();
        if (meshRenderer != null && objectColor != Color.white)
        {
            meshRenderer.material.color = objectColor;
        }

        // Initial sync
        lastSyncedPosition = transform.position;
        SyncToFile();

        Debug.Log($"GrabbableObject '{objectName}' initialized at {transform.position}");
    }

    void Update()
    {
        // Check if gripper is nearby
        CheckGripperProximity();

        // Check stacking
        if (enableStacking && !isHeld)
        {
            CheckStacking();
        }

        // Sync position periodically
        if (Time.time - lastSyncTime >= syncInterval)
        {
            if (Vector3.Distance(transform.position, lastSyncedPosition) > 0.001f)
            {
                SyncToFile();
            }
            lastSyncTime = Time.time;
        }

        // If held, follow gripper
        if (isHeld && gripper != null)
        {
            transform.position = gripper.position;
        }
    }

    void CheckStacking()
    {
        // Cast ray downward to detect objects below
        RaycastHit hit;
        Vector3 checkOrigin = transform.position;

        if (Physics.Raycast(checkOrigin, Vector3.down, out hit, stackDetectionDistance))
        {
            GrabbableObject objBelow = hit.collider.GetComponent<GrabbableObject>();
            if (objBelow != null && objBelow != this)
            {
                if (objectBelow != objBelow)
                {
                    // New object detected below
                    objectBelow = objBelow;
                    if (!objBelow.objectsAbove.Contains(this))
                    {
                        objBelow.objectsAbove.Add(this);
                    }
                    Debug.Log($"[Stack] '{objectName}' is now on top of '{objBelow.objectName}'");
                }
            }
        }
        else
        {
            // No object below
            if (objectBelow != null)
            {
                objectBelow.objectsAbove.Remove(this);
                Debug.Log($"[Stack] '{objectName}' is no longer on top of '{objectBelow.objectName}'");
                objectBelow = null;
            }
        }
    }

    void CheckGripperProximity()
    {
        // Find gripper by tag or name
        if (gripper == null)
        {
            GameObject gripperObj = GameObject.FindWithTag("Gripper");
            if (gripperObj == null)
            {
                gripperObj = GameObject.Find("GripperBase");
            }
            if (gripperObj != null)
            {
                gripper = gripperObj.transform;
            }
            else
            {
                return;  // No gripper found
            }
        }

        float distance = Vector3.Distance(transform.position, gripper.position);

        // Check if gripper is closed (you'll need a reference to GripperController)
        GripperController gripperController = gripper.GetComponent<GripperController>();
        if (gripperController == null)
        {
            gripperController = gripper.GetComponentInParent<GripperController>();
        }

        if (gripperController != null)
        {
            float gripperOpenPercent = gripperController.GetCurrentPositionPercent();
            bool gripperClosed = gripperOpenPercent < 30f;  // Less than 30% open = closed

            // Pick up if gripper is nearby and closed
            if (distance < gripDetectionRadius && gripperClosed && !isHeld)
            {
                PickUp();
            }
            // Release if gripper opened while holding
            else if (isHeld && !gripperClosed)
            {
                Release();
            }
        }
    }

    public void PickUp()
    {
        isHeld = true;
        if (rb != null)
        {
            rb.isKinematic = true;  // Disable physics while held
        }
        Debug.Log($"[GrabbableObject] '{objectName}' picked up");
        SyncToFile();
    }

    public void Release()
    {
        isHeld = false;
        if (rb != null)
        {
            rb.isKinematic = isKinematic;  // Restore original physics setting
        }
        Debug.Log($"[GrabbableObject] '{objectName}' released at {transform.position}");
        SyncToFile();
    }

    void SyncToFile()
    {
        lastSyncedPosition = transform.position;

        try
        {
            // Load existing states
            ObjectStates states = new ObjectStates();
            if (File.Exists(stateFilePath))
            {
                string json = File.ReadAllText(stateFilePath);
                states = JsonUtility.FromJson<ObjectStates>(json);
            }

            // Create or update this object's state
            ObjectState myState = new ObjectState
            {
                name = objectName,
                position = new float[] { transform.position.x, transform.position.y, transform.position.z },
                held = isHeld,
                color = ColorUtility.ToHtmlStringRGB(objectColor),
                object_below = objectBelow != null ? objectBelow.objectName : null,
                stack_height = objectsAbove.Count
            };

            // Find and update or append
            bool found = false;
            if (states.objects != null)
            {
                for (int i = 0; i < states.objects.Length; i++)
                {
                    if (states.objects[i].name == objectName)
                    {
                        states.objects[i] = myState;
                        found = true;
                        break;
                    }
                }
            }

            if (!found)
            {
                // Append to array
                int oldLength = states.objects?.Length ?? 0;
                ObjectState[] newArray = new ObjectState[oldLength + 1];
                if (states.objects != null)
                {
                    System.Array.Copy(states.objects, newArray, oldLength);
                }
                newArray[oldLength] = myState;
                states.objects = newArray;
            }

            // Write back
            string output = JsonUtility.ToJson(states, true);
            File.WriteAllText(stateFilePath, output);
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to sync object state: {e.Message}");
        }
    }

    // Visualize grip detection radius in editor
    void OnDrawGizmosSelected()
    {
        Gizmos.color = isHeld ? Color.green : Color.yellow;
        Gizmos.DrawWireSphere(transform.position, gripDetectionRadius);
    }
}
