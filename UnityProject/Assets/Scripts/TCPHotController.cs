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
        StartCoroutine(WatchFile());
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
    }
}

[System.Serializable]
public class TCPCommand
{
    public float x;
    public float y;
    public float z;
}