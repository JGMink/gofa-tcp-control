using UnityEngine;
using System.IO;

public class SceneObject : MonoBehaviour
{
    [Header("Scene Object Settings")]
    public string objectName = "table";
    public string objectType = "surface";  // "surface", "container", "obstacle", etc.
    public bool isPickupLocation = false;
    public bool isPlaceLocation = false;

    [Header("State Sync")]
    public string stateFilePath = "scene_objects.json";
    public float syncInterval = 2.0f;  // Sync every 2 seconds

    private float lastSyncTime;

    [System.Serializable]
    private class SceneObjectState
    {
        public string name;
        public string type;
        public float[] position;
        public float[] bounds;  // width, height, depth
        public bool is_pickup_location;
        public bool is_place_location;
    }

    [System.Serializable]
    private class SceneObjects
    {
        public SceneObjectState[] objects;
    }

    void Start()
    {
        // Initial sync
        SyncToFile();
        Debug.Log($"SceneObject '{objectName}' registered at {transform.position}");
    }

    void Update()
    {
        // Periodic sync (less frequent than grabbable objects)
        if (Time.time - lastSyncTime >= syncInterval)
        {
            SyncToFile();
            lastSyncTime = Time.time;
        }
    }

    void SyncToFile()
    {
        try
        {
            // Load existing states
            SceneObjects states = new SceneObjects();
            if (File.Exists(stateFilePath))
            {
                string json = File.ReadAllText(stateFilePath);
                states = JsonUtility.FromJson<SceneObjects>(json);
            }

            // Get bounds
            Bounds bounds = GetObjectBounds();

            // Create or update this object's state
            SceneObjectState myState = new SceneObjectState
            {
                name = objectName,
                type = objectType,
                position = new float[] { transform.position.x, transform.position.y, transform.position.z },
                bounds = new float[] { bounds.size.x, bounds.size.y, bounds.size.z },
                is_pickup_location = isPickupLocation,
                is_place_location = isPlaceLocation
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
                SceneObjectState[] newArray = new SceneObjectState[oldLength + 1];
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
            Debug.LogWarning($"Failed to sync scene object state: {e.Message}");
        }
    }

    Bounds GetObjectBounds()
    {
        // Get bounds from renderer or collider
        Renderer renderer = GetComponent<Renderer>();
        if (renderer != null)
        {
            return renderer.bounds;
        }

        Collider collider = GetComponent<Collider>();
        if (collider != null)
        {
            return collider.bounds;
        }

        // Default bounds
        return new Bounds(transform.position, Vector3.one * 0.1f);
    }

    // Visualize in editor
    void OnDrawGizmos()
    {
        Gizmos.color = isPickupLocation ? Color.green : (isPlaceLocation ? Color.blue : Color.gray);
        Bounds bounds = GetObjectBounds();
        Gizmos.DrawWireCube(bounds.center, bounds.size);

        // Draw label
        #if UNITY_EDITOR
        UnityEditor.Handles.Label(transform.position + Vector3.up * 0.1f, objectName);
        #endif
    }
}
