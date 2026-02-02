using UnityEngine;
using System.IO;
using System.Collections.Generic;

public class ObjectManager : MonoBehaviour
{
    [Header("Object Tracking")]
    public string objectStatesFile = "object_states.json";
    public string commandQueueFile = "command_queue.json";

    [Header("Prefabs")]
    public GameObject cubePrefab;
    public GameObject spherePrefab;

    [Header("Auto-spawn Settings")]
    public bool autoSpawnOnStart = true;
    public Vector3 spawnPosition = new Vector3(0.5f, 0.6f, -0.2f);
    public float objectSpacing = 0.15f;  // 15cm between objects

    private Dictionary<string, GameObject> trackedObjects = new Dictionary<string, GameObject>();

    [System.Serializable]
    private class ObjectState
    {
        public string name;
        public float[] position;
        public bool held;
        public string color;
    }

    [System.Serializable]
    private class ObjectStates
    {
        public ObjectState[] objects;
    }

    [System.Serializable]
    private class CommandQueueData
    {
        public ObjectCommand[] commands;
    }

    [System.Serializable]
    private class ObjectCommand
    {
        public string command_type;
        public string object_name;
        public float[] position;
    }

    void Start()
    {
        if (autoSpawnOnStart)
        {
            SpawnDefaultObjects();
        }

        // Load any existing objects from file
        LoadObjectsFromFile();

        Debug.Log("ObjectManager initialized");
    }

    void SpawnDefaultObjects()
    {
        // Create default grabbable objects for testing
        SpawnCube("red_cube", spawnPosition, Color.red);
        SpawnCube("blue_cube", spawnPosition + Vector3.right * objectSpacing, Color.blue);
        SpawnCube("green_cube", spawnPosition + Vector3.right * objectSpacing * 2, Color.green);
    }

    public GameObject SpawnCube(string objectName, Vector3 position, Color color)
    {
        GameObject cube;

        if (cubePrefab != null)
        {
            cube = Instantiate(cubePrefab, position, Quaternion.identity);
        }
        else
        {
            // Create primitive if no prefab
            cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.transform.position = position;
            cube.transform.localScale = Vector3.one * 0.05f;  // 5cm cube
        }

        cube.name = objectName;

        // Add GrabbableObject component
        GrabbableObject grabbable = cube.GetComponent<GrabbableObject>();
        if (grabbable == null)
        {
            grabbable = cube.AddComponent<GrabbableObject>();
        }
        grabbable.objectName = objectName;
        grabbable.objectColor = color;

        // Set color
        Renderer renderer = cube.GetComponent<Renderer>();
        if (renderer != null)
        {
            renderer.material.color = color;
        }

        // Track object
        trackedObjects[objectName] = cube;

        Debug.Log($"Spawned '{objectName}' at {position}");

        return cube;
    }

    public GameObject SpawnSphere(string objectName, Vector3 position, Color color)
    {
        GameObject sphere;

        if (spherePrefab != null)
        {
            sphere = Instantiate(spherePrefab, position, Quaternion.identity);
        }
        else
        {
            sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            sphere.transform.position = position;
            sphere.transform.localScale = Vector3.one * 0.05f;  // 5cm sphere
        }

        sphere.name = objectName;

        // Add GrabbableObject component
        GrabbableObject grabbable = sphere.GetComponent<GrabbableObject>();
        if (grabbable == null)
        {
            grabbable = sphere.AddComponent<GrabbableObject>();
        }
        grabbable.objectName = objectName;
        grabbable.objectColor = color;

        // Set color
        Renderer renderer = sphere.GetComponent<Renderer>();
        if (renderer != null)
        {
            renderer.material.color = color;
        }

        // Track object
        trackedObjects[objectName] = sphere;

        Debug.Log($"Spawned '{objectName}' at {position}");

        return sphere;
    }

    public void RemoveObject(string objectName)
    {
        if (trackedObjects.ContainsKey(objectName))
        {
            Destroy(trackedObjects[objectName]);
            trackedObjects.Remove(objectName);
            Debug.Log($"Removed object '{objectName}'");
        }
    }

    public GameObject GetObject(string objectName)
    {
        if (trackedObjects.ContainsKey(objectName))
        {
            return trackedObjects[objectName];
        }
        return null;
    }

    public List<string> GetObjectNames()
    {
        return new List<string>(trackedObjects.Keys);
    }

    void LoadObjectsFromFile()
    {
        if (!File.Exists(objectStatesFile))
            return;

        try
        {
            string json = File.ReadAllText(objectStatesFile);
            ObjectStates states = JsonUtility.FromJson<ObjectStates>(json);

            if (states?.objects != null)
            {
                foreach (ObjectState state in states.objects)
                {
                    // Only load if not already tracked
                    if (!trackedObjects.ContainsKey(state.name))
                    {
                        Vector3 pos = new Vector3(state.position[0], state.position[1], state.position[2]);
                        Color col = Color.white;

                        if (!string.IsNullOrEmpty(state.color))
                        {
                            ColorUtility.TryParseHtmlString("#" + state.color, out col);
                        }

                        SpawnCube(state.name, pos, col);
                    }
                }

                Debug.Log($"Loaded {states.objects.Length} objects from file");
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to load objects from file: {e.Message}");
        }
    }

    // Public method to sync all objects to Python
    public void SyncObjectsToPython()
    {
        ObjectStates states = new ObjectStates();
        List<ObjectState> stateList = new List<ObjectState>();

        foreach (var kvp in trackedObjects)
        {
            GameObject obj = kvp.Value;
            GrabbableObject grabbable = obj.GetComponent<GrabbableObject>();

            ObjectState state = new ObjectState
            {
                name = kvp.Key,
                position = new float[] { obj.transform.position.x, obj.transform.position.y, obj.transform.position.z },
                held = grabbable != null && grabbable.GetComponent<GrabbableObject>() != null,
                color = ColorUtility.ToHtmlStringRGB(obj.GetComponent<Renderer>()?.material.color ?? Color.white)
            };

            stateList.Add(state);
        }

        states.objects = stateList.ToArray();

        try
        {
            string json = JsonUtility.ToJson(states, true);
            File.WriteAllText(objectStatesFile, json);
            Debug.Log($"Synced {stateList.Count} objects to {objectStatesFile}");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Failed to sync objects: {e.Message}");
        }
    }

    void OnApplicationQuit()
    {
        SyncObjectsToPython();
    }
}
