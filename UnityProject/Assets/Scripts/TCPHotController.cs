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
    
    void Start()
    {
        // Set path relative to project root
        if (!Path.IsPathRooted(configPath))
        {
            configPath = Path.Combine(Application.dataPath, "..", configPath);
        }
        
        Debug.Log($"Watching: {configPath}");
        StartCoroutine(WatchFile());
    }
    
    IEnumerator WatchFile()
    {
        while (true)
        {
            yield return new WaitForSeconds(pollInterval);
            
            if (File.Exists(configPath))
            {
                DateTime currentModified = File.GetLastWriteTime(configPath);
                
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
            string json = File.ReadAllText(configPath);
            TCPCommand cmd = JsonUtility.FromJson<TCPCommand>(json);
            
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
        catch (System.Exception e)
        {
            Debug.LogError($"Parse error: {e.Message}");
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