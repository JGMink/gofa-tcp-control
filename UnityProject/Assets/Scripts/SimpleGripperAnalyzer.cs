using UnityEngine;

/// <summary>
/// Simple auto-running gripper analyzer that prints hierarchy on Start
/// </summary>
public class SimpleGripperAnalyzer : MonoBehaviour
{
    [Header("Assign your gripper root GameObject")]
    public Transform gripperRoot;

    [Header("Auto-run on Start")]
    public bool autoAnalyze = true;

    void Start()
    {
        Debug.Log("========================================");
        Debug.Log("SIMPLE GRIPPER ANALYZER STARTED");
        Debug.Log("========================================");

        if (gripperRoot == null)
        {
            Debug.LogError("⚠️ NO GRIPPER ROOT ASSIGNED!");
            Debug.LogError("Please drag your RG2 model into the 'Gripper Root' field in the Inspector");
            return;
        }

        if (autoAnalyze)
        {
            AnalyzeGripper();
        }
        else
        {
            Debug.Log("Press SPACE to analyze gripper");
        }
    }

    void Update()
    {
        if (!autoAnalyze && Input.GetKeyDown(KeyCode.Space))
        {
            AnalyzeGripper();
        }
    }

    void AnalyzeGripper()
    {
        Debug.Log($"\n▶ ANALYZING: {gripperRoot.name}");
        Debug.Log("─────────────────────────────────────────\n");

        // Get all children
        Transform[] allTransforms = gripperRoot.GetComponentsInChildren<Transform>();
        Debug.Log($"Total objects in gripper: {allTransforms.Length}\n");

        // Print hierarchy
        Debug.Log("COMPLETE HIERARCHY:");
        Debug.Log("══════════════════\n");
        PrintHierarchy(gripperRoot, 0);

        // Analyze positions
        Debug.Log("\n\nPOSITION ANALYSIS:");
        Debug.Log("══════════════════\n");
        AnalyzePositions(allTransforms);

        // Look for symmetric pairs
        Debug.Log("\n\nSYMMETRIC PAIR SEARCH:");
        Debug.Log("══════════════════════\n");
        FindSymmetricPairs(allTransforms);

        Debug.Log("\n========================================");
        Debug.Log("ANALYSIS COMPLETE");
        Debug.Log("========================================\n");
    }

    void PrintHierarchy(Transform t, int level)
    {
        string indent = new string(' ', level * 3);
        string arrow = level > 0 ? "└─ " : "";

        MeshFilter mf = t.GetComponent<MeshFilter>();
        string meshInfo = mf != null && mf.sharedMesh != null
            ? $" [MESH: {mf.sharedMesh.vertexCount} verts]"
            : "";

        Vector3 localPos = t.localPosition;
        string posStr = $"({localPos.x:F4}, {localPos.y:F4}, {localPos.z:F4})";

        Debug.Log($"{indent}{arrow}{t.name} {posStr}{meshInfo}");

        foreach (Transform child in t)
        {
            PrintHierarchy(child, level + 1);
        }
    }

    void AnalyzePositions(Transform[] transforms)
    {
        int leftCount = 0, rightCount = 0, centerCount = 0;

        foreach (Transform t in transforms)
        {
            if (t == gripperRoot) continue;

            float x = t.localPosition.x;

            if (x < -0.001f)
            {
                leftCount++;
                Debug.Log($"LEFT:   {t.name,-30} at {t.localPosition}");
            }
            else if (x > 0.001f)
            {
                rightCount++;
                Debug.Log($"RIGHT:  {t.name,-30} at {t.localPosition}");
            }
            else
            {
                centerCount++;
                Debug.Log($"CENTER: {t.name,-30} at {t.localPosition}");
            }
        }

        Debug.Log($"\nSummary: {leftCount} left, {rightCount} right, {centerCount} center");
    }

    void FindSymmetricPairs(Transform[] transforms)
    {
        bool foundPair = false;

        for (int i = 0; i < transforms.Length; i++)
        {
            MeshFilter mf1 = transforms[i].GetComponent<MeshFilter>();
            if (mf1 == null || mf1.sharedMesh == null) continue;

            for (int j = i + 1; j < transforms.Length; j++)
            {
                MeshFilter mf2 = transforms[j].GetComponent<MeshFilter>();
                if (mf2 == null || mf2.sharedMesh == null) continue;

                int verts1 = mf1.sharedMesh.vertexCount;
                int verts2 = mf2.sharedMesh.vertexCount;

                // Similar vertex count
                if (Mathf.Abs(verts1 - verts2) < 100)
                {
                    Vector3 pos1 = transforms[i].localPosition;
                    Vector3 pos2 = transforms[j].localPosition;

                    // Check if mirrored on X axis
                    float xSum = Mathf.Abs(pos1.x + pos2.x);
                    float yDiff = Mathf.Abs(pos1.y - pos2.y);
                    float zDiff = Mathf.Abs(pos1.z - pos2.z);

                    if (xSum < 0.01f && yDiff < 0.01f && zDiff < 0.01f)
                    {
                        foundPair = true;
                        float distance = Mathf.Abs(pos1.x - pos2.x);

                        Debug.Log("┌─ SYMMETRIC PAIR FOUND! ─────────────────");
                        Debug.Log($"│ Left:     {transforms[i].name}");
                        Debug.Log($"│ Position: {pos1}");
                        Debug.Log($"│");
                        Debug.Log($"│ Right:    {transforms[j].name}");
                        Debug.Log($"│ Position: {pos2}");
                        Debug.Log($"│");
                        Debug.Log($"│ Vertices: {verts1} / {verts2}");
                        Debug.Log($"│ Distance: {distance * 1000:F2}mm");
                        Debug.Log($"│");
                        Debug.Log($"│ 👉 USE THESE AS YOUR FINGER TRANSFORMS!");
                        Debug.Log("└─────────────────────────────────────────");
                    }
                }
            }
        }

        if (!foundPair)
        {
            Debug.LogWarning("⚠️ No symmetric pairs found!");
            Debug.LogWarning("   This might mean:");
            Debug.LogWarning("   1. The fingers are combined into one mesh");
            Debug.LogWarning("   2. The STEP→OBJ conversion didn't preserve hierarchy");
            Debug.LogWarning("   3. The gripper needs to be rigged/separated manually");
        }
    }
}
