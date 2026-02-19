using UnityEngine;

/// <summary>
/// Simple gripper rig - creates movable finger transforms from the imported mesh.
/// Just separates left/right fingers for basic open/close movement.
/// Run this ONCE in Edit mode to set up your gripper.
/// </summary>
[ExecuteInEditMode]
public class SimpleGripperRig : MonoBehaviour
{
    [Header("Source Model")]
    [Tooltip("Drag your OnRobot_RG2_Organized model here")]
    public GameObject sourceGripperModel;

    [Header("Finger Meshes (Auto-find or assign manually)")]
    public MeshFilter fingerLeftMesh;
    public MeshFilter fingerRightMesh;
    public MeshFilter baseMesh;

    [Header("Output - Will be created")]
    public Transform riggedGripperRoot;
    public Transform leftFingerTransform;
    public Transform rightFingerTransform;

    [Header("Settings")]
    public float initialSeparation = 0.055f; // 55mm (half of 110mm open)

    [ContextMenu("1. Auto-Find Meshes")]
    public void AutoFindMeshes()
    {
        if (sourceGripperModel == null)
        {
            Debug.LogError("❌ Assign the source gripper model first!");
            return;
        }

        MeshFilter[] allMeshes = sourceGripperModel.GetComponentsInChildren<MeshFilter>();
        Debug.Log($"Found {allMeshes.Length} meshes in gripper model");

        foreach (MeshFilter mf in allMeshes)
        {
            string name = mf.gameObject.name.ToLower();
            Debug.Log($"  • {mf.gameObject.name} ({mf.sharedMesh?.vertexCount ?? 0} verts)");

            if (name.Contains("finger") && name.Contains("left"))
            {
                fingerLeftMesh = mf;
                Debug.Log($"    ✓ Assigned as LEFT finger");
            }
            else if (name.Contains("finger") && name.Contains("right"))
            {
                fingerRightMesh = mf;
                Debug.Log($"    ✓ Assigned as RIGHT finger");
            }
            else if (name.Contains("base"))
            {
                baseMesh = mf;
                Debug.Log($"    ✓ Assigned as BASE");
            }
        }

        if (fingerLeftMesh != null && fingerRightMesh != null)
        {
            Debug.Log("✅ Successfully found finger meshes!");
            Debug.Log("   Next: Run '2. Create Rigged Gripper'");
        }
        else
        {
            Debug.LogWarning("⚠️ Could not auto-find all meshes. Assign manually in Inspector.");
        }
    }

    [ContextMenu("2. Create Rigged Gripper")]
    public void CreateRiggedGripper()
    {
        if (fingerLeftMesh == null || fingerRightMesh == null)
        {
            Debug.LogError("❌ Both finger meshes must be assigned! Run 'Auto-Find Meshes' first.");
            return;
        }

        Debug.Log("════════════════════════════════════════");
        Debug.Log("CREATING RIGGED GRIPPER");
        Debug.Log("════════════════════════════════════════");

        // Create root
        GameObject root = new GameObject("RG2_Rigged");
        root.transform.position = sourceGripperModel.transform.position;
        root.transform.rotation = sourceGripperModel.transform.rotation;
        root.transform.SetParent(sourceGripperModel.transform.parent);

        // Create base (static parts)
        GameObject baseObj = new GameObject("Base");
        baseObj.transform.SetParent(root.transform);
        baseObj.transform.localPosition = Vector3.zero;
        baseObj.transform.localRotation = Quaternion.identity;

        if (baseMesh != null)
        {
            CopyMesh(baseMesh, baseObj);
            Debug.Log("✓ Copied base mesh");
        }
        else
        {
            Debug.LogWarning("⚠️ No base mesh assigned - only fingers will be rigged");
        }

        // Create LEFT finger
        GameObject leftObj = new GameObject("Finger_Left");
        leftObj.transform.SetParent(root.transform);
        leftObj.transform.localPosition = new Vector3(-initialSeparation, 0, 0);
        leftObj.transform.localRotation = Quaternion.identity;
        CopyMesh(fingerLeftMesh, leftObj);
        Debug.Log($"✓ Created left finger at ({-initialSeparation:F3}, 0, 0)");

        // Create RIGHT finger
        GameObject rightObj = new GameObject("Finger_Right");
        rightObj.transform.SetParent(root.transform);
        rightObj.transform.localPosition = new Vector3(initialSeparation, 0, 0);
        rightObj.transform.localRotation = Quaternion.identity;
        CopyMesh(fingerRightMesh, rightObj);
        Debug.Log($"✓ Created right finger at ({initialSeparation:F3}, 0, 0)");

        // Store references
        riggedGripperRoot = root.transform;
        leftFingerTransform = leftObj.transform;
        rightFingerTransform = rightObj.transform;

        Debug.Log("════════════════════════════════════════");
        Debug.Log("✅ RIGGING COMPLETE!");
        Debug.Log("════════════════════════════════════════");
        Debug.Log("\nCreated hierarchy:");
        Debug.Log($"  {root.name}");
        Debug.Log($"  ├─ {baseObj.name} (static)");
        Debug.Log($"  ├─ {leftObj.name} (movable)");
        Debug.Log($"  └─ {rightObj.name} (movable)");
        Debug.Log("\nNext steps:");
        Debug.Log("1. Disable the original source model");
        Debug.Log("2. Add GripperController to RG2_Rigged");
        Debug.Log("3. Assign Finger_Left and Finger_Right transforms");
        Debug.Log("4. Test with keyboard controls!");
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
            Debug.LogError("❌ Rigged gripper not found! Run 'Create Rigged Gripper' first.");
            return;
        }

        // Close to 20mm separation (10mm each side)
        leftFingerTransform.localPosition = new Vector3(-0.01f, 0, 0);
        rightFingerTransform.localPosition = new Vector3(0.01f, 0, 0);

        Debug.Log("✊ Gripper CLOSED (20mm separation)");
    }

    [ContextMenu("4. Test Movement (Open)")]
    public void TestOpen()
    {
        if (leftFingerTransform == null || rightFingerTransform == null)
        {
            Debug.LogError("❌ Rigged gripper not found!");
            return;
        }

        // Open to 110mm separation (55mm each side)
        leftFingerTransform.localPosition = new Vector3(-initialSeparation, 0, 0);
        rightFingerTransform.localPosition = new Vector3(initialSeparation, 0, 0);

        Debug.Log("✋ Gripper OPEN (110mm separation)");
    }
}
