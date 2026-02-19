using UnityEngine;

/// <summary>
/// Analyzes and rigs the RG2_FT_Complete.obj model.
/// Similar to what we did with the original RG2, but for the FT version.
/// </summary>
[ExecuteInEditMode]
public class RG2FTRigger : MonoBehaviour
{
    [Header("Source Model")]
    [Tooltip("Drag RG2_FT_Complete from your scene here")]
    public GameObject sourceModel;

    [Header("Settings")]
    public float initialFingerSeparation = 0.055f; // 55mm per finger

    [Header("Output - Will be created")]
    public Transform riggedGripperRoot;
    public Transform leftFingerTransform;
    public Transform rightFingerTransform;

    [ContextMenu("1. Analyze Model Structure")]
    public void AnalyzeModel()
    {
        if (sourceModel == null)
        {
            Debug.LogError("❌ Assign the RG2_FT_Complete model first!");
            return;
        }

        Debug.Log("════════════════════════════════════════");
        Debug.Log("RG2-FT MODEL ANALYSIS");
        Debug.Log("════════════════════════════════════════\n");

        // Get all mesh filters
        MeshFilter[] meshes = sourceModel.GetComponentsInChildren<MeshFilter>();
        Debug.Log($"Found {meshes.Length} mesh objects\n");

        Debug.Log("MESH BREAKDOWN:");
        foreach (MeshFilter mf in meshes)
        {
            string name = mf.gameObject.name;
            int verts = mf.sharedMesh != null ? mf.sharedMesh.vertexCount : 0;
            Vector3 localPos = mf.transform.localPosition;

            Debug.Log($"• {name}");
            Debug.Log($"  Vertices: {verts:N0}");
            Debug.Log($"  Position: {localPos}");
            Debug.Log($"  Full Path: {GetPath(mf.transform)}");
            Debug.Log("");
        }

        Debug.Log("\nNEXT STEP:");
        Debug.Log("Look at the mesh names above and identify:");
        Debug.Log("  - Base/Body parts (largest vertex count, static)");
        Debug.Log("  - Left finger (medium vertex count)");
        Debug.Log("  - Right finger (medium vertex count)");
        Debug.Log("\nThen run '2. Create Rigged Gripper'");
        Debug.Log("════════════════════════════════════════\n");
    }

    [ContextMenu("2. Create Rigged Gripper (Auto)")]
    public void CreateRiggedGripper()
    {
        if (sourceModel == null)
        {
            Debug.LogError("❌ Assign source model first!");
            return;
        }

        Debug.Log("════════════════════════════════════════");
        Debug.Log("CREATING RIGGED GRIPPER");
        Debug.Log("════════════════════════════════════════\n");

        // Get all meshes
        MeshFilter[] allMeshes = sourceModel.GetComponentsInChildren<MeshFilter>();

        // Try to identify parts by name and vertex count
        MeshFilter baseMesh = null;
        MeshFilter leftFingerMesh = null;
        MeshFilter rightFingerMesh = null;

        // Sort by vertex count (largest = base, medium = fingers)
        System.Array.Sort(allMeshes, (a, b) =>
            (b.sharedMesh?.vertexCount ?? 0).CompareTo(a.sharedMesh?.vertexCount ?? 0));

        foreach (MeshFilter mf in allMeshes)
        {
            if (mf.sharedMesh == null) continue;

            string name = mf.gameObject.name.ToLower();
            int verts = mf.sharedMesh.vertexCount;

            // Base is usually the largest
            if (baseMesh == null && verts > 100000)
            {
                baseMesh = mf;
                Debug.Log($"✓ Base: {mf.gameObject.name} ({verts:N0} verts)");
                continue;
            }

            // Look for finger keywords
            if (name.Contains("finger") || name.Contains("jaw") || name.Contains("grip"))
            {
                if ((name.Contains("left") || name.Contains("_l") || name.Contains("1")) && leftFingerMesh == null)
                {
                    leftFingerMesh = mf;
                    Debug.Log($"✓ Left Finger: {mf.gameObject.name} ({verts:N0} verts)");
                }
                else if ((name.Contains("right") || name.Contains("_r") || name.Contains("2")) && rightFingerMesh == null)
                {
                    rightFingerMesh = mf;
                    Debug.Log($"✓ Right Finger: {mf.gameObject.name} ({verts:N0} verts)");
                }
            }
        }

        // If we didn't find fingers by name, use vertex count similarity
        if (leftFingerMesh == null || rightFingerMesh == null)
        {
            Debug.LogWarning("⚠️ Couldn't find fingers by name, trying by vertex count...");

            // Find two meshes with similar vertex counts (fingers should be similar)
            for (int i = 1; i < allMeshes.Length; i++)
            {
                if (allMeshes[i].sharedMesh == null) continue;
                if (allMeshes[i] == baseMesh) continue;

                for (int j = i + 1; j < allMeshes.Length; j++)
                {
                    if (allMeshes[j].sharedMesh == null) continue;
                    if (allMeshes[j] == baseMesh) continue;

                    int verts1 = allMeshes[i].sharedMesh.vertexCount;
                    int verts2 = allMeshes[j].sharedMesh.vertexCount;

                    // Similar vertex counts = likely finger pair
                    if (Mathf.Abs(verts1 - verts2) < verts1 * 0.1f) // Within 10%
                    {
                        leftFingerMesh = allMeshes[i];
                        rightFingerMesh = allMeshes[j];
                        Debug.Log($"✓ Left Finger (by count): {allMeshes[i].gameObject.name} ({verts1:N0} verts)");
                        Debug.Log($"✓ Right Finger (by count): {allMeshes[j].gameObject.name} ({verts2:N0} verts)");
                        break;
                    }
                }
                if (leftFingerMesh != null) break;
            }
        }

        if (leftFingerMesh == null || rightFingerMesh == null)
        {
            Debug.LogError("❌ Could not identify finger meshes!");
            Debug.LogError("Please assign them manually or check model structure.");
            return;
        }

        // Create rigged hierarchy
        CreateRiggedHierarchy(baseMesh, leftFingerMesh, rightFingerMesh);
    }

    void CreateRiggedHierarchy(MeshFilter baseMesh, MeshFilter leftMesh, MeshFilter rightMesh)
    {
        // Create root
        GameObject root = new GameObject("RG2_FT_Rigged");
        root.transform.position = sourceModel.transform.position;
        root.transform.rotation = sourceModel.transform.rotation;
        root.transform.SetParent(sourceModel.transform.parent);

        // Create base
        GameObject baseObj = new GameObject("Base");
        baseObj.transform.SetParent(root.transform);
        baseObj.transform.localPosition = Vector3.zero;
        baseObj.transform.localRotation = Quaternion.identity;

        if (baseMesh != null)
        {
            CopyMesh(baseMesh, baseObj);
            Debug.Log("✓ Created Base");
        }

        // Create left finger at -55mm
        GameObject leftObj = new GameObject("Finger_Left");
        leftObj.transform.SetParent(root.transform);
        leftObj.transform.localPosition = new Vector3(-initialFingerSeparation, 0, 0);
        leftObj.transform.localRotation = Quaternion.identity;
        CopyMesh(leftMesh, leftObj);
        Debug.Log($"✓ Created Left Finger at ({-initialFingerSeparation:F3}, 0, 0)");

        // Create right finger at +55mm
        GameObject rightObj = new GameObject("Finger_Right");
        rightObj.transform.SetParent(root.transform);
        rightObj.transform.localPosition = new Vector3(initialFingerSeparation, 0, 0);
        rightObj.transform.localRotation = Quaternion.identity;
        CopyMesh(rightMesh, rightObj);
        Debug.Log($"✓ Created Right Finger at ({initialFingerSeparation:F3}, 0, 0)");

        // Store references
        riggedGripperRoot = root.transform;
        leftFingerTransform = leftObj.transform;
        rightFingerTransform = rightObj.transform;

        Debug.Log("\n════════════════════════════════════════");
        Debug.Log("✅ RIGGING COMPLETE!");
        Debug.Log("════════════════════════════════════════");
        Debug.Log("\nCreated hierarchy:");
        Debug.Log($"  {root.name}");
        Debug.Log($"  ├─ {baseObj.name}");
        Debug.Log($"  ├─ {leftObj.name}");
        Debug.Log($"  └─ {rightObj.name}");
        Debug.Log("\nNext steps:");
        Debug.Log("1. Disable the original RG2_FT_Complete model");
        Debug.Log("2. Run '3. Test Movement' to verify");
        Debug.Log("3. Add ProxyGripperVisualizer or RG2Controller script");
    }

    void CopyMesh(MeshFilter source, GameObject destination)
    {
        MeshFilter mf = destination.AddComponent<MeshFilter>();
        MeshRenderer mr = destination.AddComponent<MeshRenderer>();

        mf.sharedMesh = source.sharedMesh;

        MeshRenderer sourceMR = source.GetComponent<MeshRenderer>();
        if (sourceMR != null)
        {
            mr.sharedMaterials = sourceMR.sharedMaterials;
        }
    }

    [ContextMenu("3. Test Movement (Close)")]
    public void TestClose()
    {
        if (leftFingerTransform == null || rightFingerTransform == null)
        {
            Debug.LogError("❌ Run 'Create Rigged Gripper' first!");
            return;
        }

        leftFingerTransform.localPosition = new Vector3(-0.01f, 0, 0);
        rightFingerTransform.localPosition = new Vector3(0.01f, 0, 0);
        Debug.Log("✊ Gripper CLOSED (20mm)");
    }

    [ContextMenu("4. Test Movement (Open)")]
    public void TestOpen()
    {
        if (leftFingerTransform == null || rightFingerTransform == null)
        {
            Debug.LogError("❌ Run 'Create Rigged Gripper' first!");
            return;
        }

        leftFingerTransform.localPosition = new Vector3(-initialFingerSeparation, 0, 0);
        rightFingerTransform.localPosition = new Vector3(initialFingerSeparation, 0, 0);
        Debug.Log("✋ Gripper OPEN (110mm)");
    }

    string GetPath(Transform t)
    {
        string path = t.name;
        Transform parent = t.parent;

        while (parent != null)
        {
            path = parent.name + "/" + path;
            parent = parent.parent;
        }

        return path;
    }
}
