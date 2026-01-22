using System.IO;
using UnityEngine;
using Newtonsoft.Json;

/// <summary>
/// Unity script to write the current TCP position to a JSON file
/// that Python can read at startup.
/// 
/// Usage:
/// 1. Attach this script to your robot GameObject or a manager object
/// 2. Assign the TCP Transform in the inspector
/// 3. The script will automatically write the position on Start()
/// 4. It can also be called manually via WriteCurrentPosition()
/// </summary>
public class TCPPositionWriter : MonoBehaviour
{
    [Header("TCP Reference")]
    [Tooltip("Reference to the TCP (Tool Center Point) Transform")]
    public Transform tcpTransform;

    [Header("File Settings")]
    [Tooltip("Path relative to the Unity project folder")]
    public string outputFilePath = "tcp_current_position.json";

    [System.Serializable]
    public class Position
    {
        public float x;
        public float y;
        public float z;
    }

    void Start()
    {
        // Write the initial position when the program starts
        WriteCurrentPosition();
    }

    /// <summary>
    /// Write the current TCP position to the JSON file.
    /// Call this method whenever you need to update the position file.
    /// </summary>
    public void WriteCurrentPosition()
    {
        if (tcpTransform == null)
        {
            Debug.LogError("TCP Transform is not assigned!");
            return;
        }

        try
        {
            // Get the current position
            Vector3 pos = tcpTransform.position;
            
            // Create position object
            Position position = new Position
            {
                x = pos.x,
                y = pos.y,
                z = pos.z
            };

            // Convert to JSON
            string json = JsonConvert.SerializeObject(position, Formatting.Indented);

            // Get the full file path
            string fullPath = Path.Combine(Application.dataPath, "..", outputFilePath);
            
            // Write to file
            File.WriteAllText(fullPath, json);

            Debug.Log($"✅ TCP position written to: {fullPath}");
            Debug.Log($"   Position: x={position.x:F3}, y={position.y:F3}, z={position.z:F3}");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Failed to write TCP position: {e.Message}");
        }
    }

    /// <summary>
    /// Optional: Update the position file periodically or on demand
    /// </summary>
    public void UpdatePositionFile()
    {
        WriteCurrentPosition();
    }

    // Optional: Write position when the application quits
    void OnApplicationQuit()
    {
        WriteCurrentPosition();
    }
}