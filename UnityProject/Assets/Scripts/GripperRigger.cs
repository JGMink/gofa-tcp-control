using UnityEngine;

/// <summary>
/// Rigs the RG2 gripper by separating finger meshes into movable transforms.
/// Run this ONCE in the editor to set up your gripper properly.
/// </summary>
public class GripperRigger : MonoBehaviour
{
    [Header("Assign the imported RG2 model")]
    public GameObject importedGripperModel;

    [Header("Finger Mesh References")]
    public MeshFilter fingerLeftMesh;
    public MeshFilter fingerRightMesh;

    [Header("Rig Settings")]
    public float initialFingerSeparation = 0.055f; // 55mm starting position

    [Header("Output")]
    public Transform riggedGripperRoot;
    public Transform riggedFingerLeft;
    public Transform riggedFingerRight;

    [ContextMenu("Auto-Find Finger Meshes")]
    public void AutoFindFingerMeshes()
    {
        if (importedGripperModel == null)
        {
            Debug.LogError("Please assign the imported gripper model first!");
            return;
        }

        MeshFilter[] allMeshes = importedGripperModel.GetComponentsInChildren<MeshFilter>();

        foreach (MeshFilter mf in allMeshes)
        {
            string name = mf.gameObject.name.ToLower();

            if (name.Contains("finger") && name.Contains("left"))
            {
                fingerLeftMesh = mf;
                Debug.Log($"✓ Found left finger mesh: {mf.gameObject.name}");
            }
            else if (name.Contains("finger") && name.Contains("right"))
            {
                fingerRightMesh = mf;
                Debug.Log($"✓ Found right finger mesh: {mf.gameObject.name}");
            }
        }

        if (fingerLeftMesh == null || fingerRightMesh == null)
        {
            Debug.LogWarning("Could not find both finger meshes automatically.");
            Debug.LogWarning("Please assign them manually in the Inspector.");
        }
    }

    [ContextMenu("Rig Gripper (Create Movable Structure)")]
    public void RigGripper()
    {
        if (fingerLeftMesh == null || fingerRightMesh == null)
        {
            Debug.LogError("Both finger meshes must be assigned!");
            Debug.LogError("Use 'Auto-Find Finger Meshes' or assign manually.");
            return;
        }

        Debug.Log("========================================");
        Debug.Log("RIGGING GRIPPER");
        Debug.Log("========================================\n");

        // Create new rigged structure
        GameObject riggedRoot = new GameObject("RG2_Rigged");
        riggedRoot.transform.position = importedGripperModel.transform.position;
        riggedRoot.transform.rotation = importedGripperModel.transform.rotation;

        // Create base (non-moving parts)
        GameObject baseObj = new GameObject("Base");
        baseObj.transform.SetParent(riggedRoot.transform);
        baseObj.transform.localPosition = Vector3.zero;
        baseObj.transform.localRotation = Quaternion.identity;

        // Copy base mesh (everything except fingers)
        CopyNonFingerMeshes(importedGripperModel, baseObj);

        // Create left finger with proper transform
        GameObject leftFingerObj = new GameObject("Finger_Left");
        leftFingerObj.transform.SetParent(riggedRoot.transform);
        leftFingerObj.transform.localPosition = new Vector3(-initialFingerSeparation, 0, 0);
        leftFingerObj.transform.localRotation = Quaternion.identity;

        // Copy left finger mesh
        MeshFilter leftMF = leftFingerObj.AddComponent<MeshFilter>();
        MeshRenderer leftMR = leftFingerObj.AddComponent<MeshRenderer>();
        leftMF.sharedMesh = fingerLeftMesh.sharedMesh;
        leftMR.sharedMaterials = fingerLeftMesh.GetComponent<MeshRenderer>().sharedMaterials;

        // Create right finger with proper transform
        GameObject rightFingerObj = new GameObject("Finger_Right");
        rightFingerObj.transform.SetParent(riggedRoot.transform);
        rightFingerObj.transform.localPosition = new Vector3(initialFingerSeparation, 0, 0);
        rightFingerObj.transform.localRotation = Quaternion.identity;

        // Copy right finger mesh
        MeshFilter rightMF = rightFingerObj.AddComponent<MeshFilter>();
        MeshRenderer rightMR = rightFingerObj.AddComponent<MeshRenderer>();
        rightMF.sharedMesh = fingerRightMesh.sharedMesh;
        rightMR.sharedMaterials = fingerRightMesh.GetComponent<MeshRenderer>().sharedMaterials;

        // Store references
        riggedGripperRoot = riggedRoot.transform;
        riggedFingerLeft = leftFingerObj.transform;
        riggedFingerRight = rightFingerObj.transform;

        Debug.Log("✓ Created rigged gripper structure:");
        Debug.Log($"  Root: {riggedRoot.name}");
        Debug.Log($"  Base: {baseObj.name}");
        Debug.Log($"  Left Finger: {leftFingerObj.name} at {leftFingerObj.transform.localPosition}");
        Debug.Log($"  Right Finger: {rightFingerObj.name} at {rightFingerObj.transform.localPosition}");
        Debug.Log("\n========================================");
        Debug.Log("RIGGING COMPLETE!");
        Debug.Log("========================================");
        Debug.Log("\nNext steps:");
        Debug.Log("1. Disable or delete the original imported model");
        Debug.Log("2. Assign these transforms to your GripperController:");
        Debug.Log($"   - Left Finger: {riggedFingerLeft.name}");
        Debug.Log($"   - Right Finger: {riggedFingerRight.name}");
        Debug.Log("3. Test finger movement with GripperTest");
    }

    void CopyNonFingerMeshes(GameObject source, GameObject destination)
    {
        MeshFilter[] allMeshes = source.GetComponentsInChildren<MeshFilter>();

        foreach (MeshFilter mf in allMeshes)
        {
            // Skip finger meshes
            if (mf == fingerLeftMesh || mf == fingerRightMesh)
                continue;

            // Create child object for this mesh
            GameObject meshObj = new GameObject(mf.gameObject.name);
            meshObj.transform.SetParent(destination.transform);
            meshObj.transform.localPosition = mf.transform.localPosition;
            meshObj.transform.localRotation = mf.transform.localRotation;
            meshObj.transform.localScale = mf.transform.localScale;

            // Copy mesh components
            MeshFilter newMF = meshObj.AddComponent<MeshFilter>();
            MeshRenderer newMR = meshObj.AddComponent<MeshRenderer>();
            newMF.sharedMesh = mf.sharedMesh;
            newMR.sharedMaterials = mf.GetComponent<MeshRenderer>().sharedMaterials;
        }
    }

    [ContextMenu("Test Finger Movement")]
    public void TestFingerMovement()
    {
        if (riggedFingerLeft == null || riggedFingerRight == null)
        {
            Debug.LogError("Rigged fingers not found! Run 'Rig Gripper' first.");
            return;
        }

        Debug.Log("Testing finger movement...");

        // Close gripper
        riggedFingerLeft.localPosition = new Vector3(-0.01f, 0, 0);
        riggedFingerRight.localPosition = new Vector3(0.01f, 0, 0);

        Debug.Log("Fingers closed to 20mm separation");
        Debug.Log("Check the Scene view to see if they moved!");
    }

    [ContextMenu("Reset Finger Positions")]
    public void ResetFingerPositions()
    {
        if (riggedFingerLeft == null || riggedFingerRight == null)
        {
            Debug.LogError("Rigged fingers not found!");
            return;
        }

        riggedFingerLeft.localPosition = new Vector3(-initialFingerSeparation, 0, 0);
        riggedFingerRight.localPosition = new Vector3(initialFingerSeparation, 0, 0);

        Debug.Log($"Fingers reset to {initialFingerSeparation * 1000}mm separation");
    }
}
