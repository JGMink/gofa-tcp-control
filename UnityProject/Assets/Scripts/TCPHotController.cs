using System;
using System.IO;
using System.Collections;
using UnityEngine;

public class TCPHotController : MonoBehaviour
{
    [SerializeField] private string configPath = "tcp_commands.json";
    [SerializeField] private float pollInterval = 0.1f;
    [SerializeField] private float moveSpeed = 2f;
    
    private DateTime lastModified;
    private Coroutine activeMove;
    private string fullPath;
    
    void Start()
    {
        // Build path relative to project root
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        fullPath = Path.Combine(projectRoot, configPath);

        Debug.Log($"Watching: {fullPath}");

        // Write current position to file on startup
        WriteCurrentPosition();

        StartCoroutine(WatchFile());
    }

    void OnApplicationQuit()
    {
        // Write current position to file on shutdown
        WriteCurrentPosition();
        Debug.Log("Saved TCP position on shutdown");
    }

    void WriteCurrentPosition()
    {
        try
        {
            TCPCommand cmd = new TCPCommand
            {
                x = transform.position.x,
                y = transform.position.y,
                z = transform.position.z
            };

            string json = JsonUtility.ToJson(cmd, true);
            File.WriteAllText(fullPath, json);

            Debug.Log($"Wrote current position to file: ({cmd.x:F3}, {cmd.y:F3}, {cmd.z:F3})");
        }
        catch (Exception e)
        {
            Debug.LogWarning($"Failed to write current position: {e.Message}");
        }
    }
    
    IEnumerator WatchFile()
    {
        while (true)
        {
            yield return new WaitForSeconds(pollInterval);
            
            if (File.Exists(fullPath))
            {
                DateTime currentModified = File.GetLastWriteTime(fullPath);
                
                if (currentModified != lastModified)
                {
                    lastModified = currentModified;
                    LoadAndMove();
                }
            }
        }
    }
    
    void LoadAndMove()
    {
        try
        {
            string json = File.ReadAllText(fullPath);
            
            // Skip empty files
            if (string.IsNullOrWhiteSpace(json))
            {
                return;
            }
            
            TCPCommand cmd = JsonUtility.FromJson<TCPCommand>(json);
            
            // Validate the command
            if (cmd == null)
            {
                Debug.LogWarning("Failed to parse TCP command - file may be incomplete");
                return;
            }
            
            // Cancel current movement
            if (activeMove != null)
            {
                StopCoroutine(activeMove);
            }
            
            // Start new movement
            Vector3 targetPos = new Vector3(cmd.x, cmd.y, cmd.z);
            activeMove = StartCoroutine(MoveTo(targetPos));
            
            Debug.Log($"Moving TCP to: ({cmd.x}, {cmd.y}, {cmd.z})");
        }
        catch (IOException)
        {
            // File is being written to, try again next poll
            Debug.LogWarning("File is locked, will retry");
        }
        catch (Exception e)
        {
            Debug.LogWarning($"Parse error (will retry): {e.Message}");
        }
    }
    
    IEnumerator MoveTo(Vector3 target)
    {
        while (Vector3.Distance(transform.position, target) > 0.01f)
        {
            transform.position = Vector3.MoveTowards(
                transform.position,
                target,
                moveSpeed * Time.deltaTime
            );
            yield return null;
        }

        transform.position = target;
        Debug.Log("TCP reached target");

        // Write acknowledgment for queue system
        WriteAcknowledgment(target);
    }

    void WriteAcknowledgment(Vector3 position)
    {
        try
        {
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            string ackPath = Path.Combine(projectRoot, "tcp_ack.json");

            TCPAck ack = new TCPAck
            {
                completed = true,
                position = new TCPCommand { x = position.x, y = position.y, z = position.z },
                timestamp = System.DateTime.Now.ToString("o")
            };

            string ackJson = JsonUtility.ToJson(ack, true);
            File.WriteAllText(ackPath, ackJson);

            Debug.Log($"Acknowledgment written: ({position.x:F3}, {position.y:F3}, {position.z:F3})");
        }
        catch (Exception e)
        {
            Debug.LogWarning($"Failed to write acknowledgment: {e.Message}");
        }
    }
}

[System.Serializable]
public class TCPCommand
{
    public float x;
    public float y;
    public float z;
}

[System.Serializable]
public class TCPAck
{
    public bool completed;
    public TCPCommand position;
    public string timestamp;
}

