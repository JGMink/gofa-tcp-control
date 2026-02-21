using UnityEngine;

/// <summary>
/// Controls the OnRobot RG2 gripper with 4-bar parallelogram linkage arc motion.
///
/// ════════════════════════════════════════════════════════════════════════
/// OVERVIEW
/// ════════════════════════════════════════════════════════════════════════
///
/// The RG2 gripper has 5 mesh parts, all flat siblings under one parent:
///
///   R2_Gripper                          ← this script lives here
///     ├─ RG2_Scratch-Base              ← static housing, does not move
///     ├─ RG2_Scratch-FingerBase_Left   ← left arm: rotates around pivot pin
///     ├─ RG2_Scratch-FingerBase_Right  ← right arm: rotates (mirrored)
///     ├─ RG2_Scratch-FingerPad_Left    ← left pad: translates, stays parallel
///     └─ RG2_Scratch-FingerPad_Right   ← right pad: translates (mirrored)
///
/// All 5 parts are imported from OBJ files (FreeCAD export, mm units) with
/// globalScale=1. Each part sits at localPosition (0,0,0) — the mesh vertex
/// positions encode the actual geometry offsets.
///
/// ════════════════════════════════════════════════════════════════════════
/// HOW THE MECHANISM WORKS
/// ════════════════════════════════════════════════════════════════════════
///
/// The RG2 uses a 4-bar parallelogram linkage:
///
///   1. FINGER ARMS (FingerBase_Left/Right):
///      Each arm pivots around a pin embedded in the base housing.
///      The pin location is defined by armPivotLeft/Right in R2_Gripper
///      local coordinates. The arm mesh origin is at (0,0,0) but the
///      actual pivot is offset inside the mesh, so we use "rotate around"
///      logic — both position and orientation change together.
///
///   2. FINGER PADS (FingerPad_Left/Right):
///      Each pad connects to its arm via a thin parallelogram linkage bar.
///      The connection point on the arm is padLinkPointLeft/Right.
///      As the arm rotates, this point traces an arc. The pad translates
///      by the same displacement but does NOT rotate — the parallelogram
///      linkage constrains it to stay parallel to its starting orientation.
///      This is how the real RG2 keeps fingerpads parallel while the arms
///      swing in an arc.
///
///   3. ROTATION:
///      The rotation axis is Z (0,0,1) in R2_Gripper local space.
///      This rotates within the XY plane where all the mechanism geometry
///      lies (all pivot Z-coordinates are 0).
///      Left arm rotates by +angle, right arm by -angle (mirrored).
///
/// ════════════════════════════════════════════════════════════════════════
/// IPC / CONTROL FLOW
/// ════════════════════════════════════════════════════════════════════════
///
///   Python (cli_control.py / speech_control.py)
///     → writes gripper_position (0.0–0.11 meters) to tcp_commands.json
///     → TCPHotController.cs reads the JSON, calls SetGripperPosition()
///     → GripperController smoothly animates to the target position
///
///   gripper_position values:
///     0.0   = fully closed (arms rotated inward by maxFingerAngle)
///     0.055 = half open (55mm gap)
///     0.110 = fully open (arms at rest position)
///
///   Keyboard shortcuts (via GripperTest.cs):
///     P = close, O = open, H = half, T = test sequence, I = info
///
/// ════════════════════════════════════════════════════════════════════════
/// SETUP GUIDE
/// ════════════════════════════════════════════════════════════════════════
///
///   1. Import the 5 OBJ files into Unity under Assets/3D_Model/
///   2. Create an empty GameObject "R2_Gripper" and attach this script
///   3. Drag all 5 mesh objects as children of R2_Gripper
///      - All should be at localPosition (0,0,0) with no rotation
///      - Do NOT nest them — all are flat siblings
///   4. In the Inspector, assign the 5 transforms to the corresponding slots
///   5. Set R2_Gripper transform:
///      - Position: where you want the gripper in the scene
///      - Rotation: Z=90° (to orient the gripper correctly on the arm)
///      - Scale: (0.025, 0.025, 0.027) to convert mm to scene units
///   6. Hit Play and test with P/O keys or CLI commands
///
/// ════════════════════════════════════════════════════════════════════════
/// TUNING / DEBUGGING PIVOT POINTS
/// ════════════════════════════════════════════════════════════════════════
///
///   If the arm swing looks wrong (asymmetric, wrong center, etc.):
///
///   1. Set showDebugMarkers = true in the Inspector (under Debug header)
///   2. Hit Play — colored spheres appear at all key points:
///        RED    = arm pivot pins (where arms hinge on the base)
///        GREEN  = pad link points (where linkage bar connects arm to pad)
///        BLUE   = arm mesh origins (should overlap at 0,0,0)
///        CYAN   = pad mesh origins (should overlap at 0,0,0)
///   3. Select a debug sphere in the Hierarchy (e.g. DBG_ArmPivot_L)
///   4. Use the Move tool (W) to drag it to the correct position on the mesh
///      - RED spheres → center of the pin hole where arm meets base
///      - GREEN spheres → center of the pin hole where linkage bar meets arm
///   5. Read the new localPosition from the Inspector
///   6. Update armPivotLeft/Right and padLinkPointLeft/Right in the code
///   7. Reset the component (right-click → Reset) and re-wire transforms
///
///   Tip: The "forceZAxis" checkbox overrides any stale rotation axis
///   values that Unity may have serialized in the scene file.
///
/// ════════════════════════════════════════════════════════════════════════
/// CURRENT CALIBRATED VALUES (as of Feb 2025)
/// ════════════════════════════════════════════════════════════════════════
///
///   armPivotLeft:     (-64, 39, 0)   — left arm hinge pin
///   armPivotRight:    (-64, 10, 0)   — right arm hinge pin
///   padLinkPointLeft: (-103, 71, 0)  — left pad linkage connection
///   padLinkPointRight:(-103, -21, 0) — right pad linkage connection
///   maxFingerAngle:   45°            — full close rotation
///   rotationAxis:     (0, 0, 1)      — Z axis (XY plane rotation)
///
/// </summary>
public class GripperController : MonoBehaviour
{
    public enum GripperModel { RG2, RG6 }

    [Header("Gripper Model Settings")]
    public GripperModel modelType = GripperModel.RG2;

    [Header("Part Transforms (all flat under R2_Gripper)")]
    [Tooltip("The static base housing — does not move")]
    public Transform gripperBase;

    [Tooltip("Left finger arm — rotates around base pivot")]
    public Transform fingerBaseLeft;

    [Tooltip("Right finger arm — rotates around base pivot (mirrored)")]
    public Transform fingerBaseRight;

    [Tooltip("Left finger pad — follows arm tip, stays parallel via linkage")]
    public Transform fingerPadLeft;

    [Tooltip("Right finger pad — follows arm tip, stays parallel via linkage")]
    public Transform fingerPadRight;

    [Header("Stroke Settings")]
    [Tooltip("RG2: 110mm max stroke, RG6: 160mm max stroke")]
    public float maxStroke = 0.110f;
    public float minStroke = 0.0f;

    [Header("Animation Settings")]
    [Tooltip("Speed at which fingers open/close (meters per second)")]
    public float gripSpeed = 0.05f;

    [Header("Arc Motion Settings")]
    [Tooltip("Max rotation angle (degrees) when fully closed.")]
    public float maxFingerAngle = 45f;

    [Tooltip("Rotation axis in R2_Gripper local space. Z=(0,0,1) for XY plane rotation.")]
    public Vector3 rotationAxis = new Vector3(0, 0, 1);

    [Header("Arm Pivot (pin location in R2_Gripper local coords, mm)")]
    [Tooltip("Left arm pivot pin — center of the hinge hole where arm meets base.")]
    public Vector3 armPivotLeft = new Vector3(-64f, 39f, 0f);

    [Tooltip("Right arm pivot pin.")]
    public Vector3 armPivotRight = new Vector3(-64f, 10f, 0f);

    [Header("Pad Link Point (linkage connection in R2_Gripper local coords, mm)")]
    [Tooltip("Left pad linkage connection — where the parallelogram bar meets the arm.")]
    public Vector3 padLinkPointLeft = new Vector3(-103f, 71f, 0f);

    [Tooltip("Right pad linkage connection.")]
    public Vector3 padLinkPointRight = new Vector3(-103f, -21f, 0f);

    [Header("Debug")]
    [Tooltip("Create visible sphere GameObjects at pivot points on Play (see docs above for usage)")]
    public bool showDebugMarkers = false;

    [Tooltip("Force rotationAxis to (0,0,1) on Start — overrides stale scene serialization")]
    public bool forceZAxis = true;

    // ─── Internal State ────────────────────────────────────────────────
    private float currentGripPosition = 0.110f;
    private float targetGripPosition = 0.110f;

    // Captured at Start() — the open/rest position of each part
    private Vector3 armLeftStartPos, armRightStartPos;
    private Quaternion armLeftStartRot, armRightStartRot;
    private Vector3 padLeftStartPos, padRightStartPos;
    private Quaternion padLeftStartRot, padRightStartRot;

    // ─── Lifecycle ─────────────────────────────────────────────────────

    void Start()
    {
        if (forceZAxis)
            rotationAxis = new Vector3(0, 0, 1);

        if (fingerBaseLeft == null || fingerBaseRight == null)
        {
            Debug.LogError("GripperController: FingerBase L/R transforms not assigned!");
            enabled = false;
            return;
        }

        // Capture rest-position transforms (open position)
        armLeftStartPos  = fingerBaseLeft.localPosition;
        armRightStartPos = fingerBaseRight.localPosition;
        armLeftStartRot  = fingerBaseLeft.localRotation;
        armRightStartRot = fingerBaseRight.localRotation;

        if (fingerPadLeft != null)
        {
            padLeftStartPos = fingerPadLeft.localPosition;
            padLeftStartRot = fingerPadLeft.localRotation;
        }
        if (fingerPadRight != null)
        {
            padRightStartPos = fingerPadRight.localPosition;
            padRightStartRot = fingerPadRight.localRotation;
        }

        if (modelType == GripperModel.RG6)
            maxStroke = 0.160f;

        currentGripPosition = maxStroke;
        targetGripPosition = maxStroke;
        UpdateFingerPositions();

        Debug.Log($"GripperController ready: {modelType}, maxAngle={maxFingerAngle}°, axis={rotationAxis}");

        if (showDebugMarkers)
            CreateDebugMarkers();
    }

    void Update()
    {
        if (Mathf.Abs(currentGripPosition - targetGripPosition) > 0.0001f)
        {
            currentGripPosition = Mathf.MoveTowards(
                currentGripPosition,
                targetGripPosition,
                gripSpeed * Time.deltaTime
            );
            UpdateFingerPositions();
        }
    }

    // ─── Core Motion Logic ─────────────────────────────────────────────

    void UpdateFingerPositions()
    {
        // closeRatio: 0 = fully open, 1 = fully closed
        float closeRatio = 1f - (currentGripPosition / maxStroke);
        float angle = closeRatio * maxFingerAngle;

        // LEFT ARM — rotate around pivot
        {
            Quaternion rot = Quaternion.AngleAxis(angle, rotationAxis);
            Vector3 originRelPivot = armLeftStartPos - armPivotLeft;
            fingerBaseLeft.localPosition = armPivotLeft + rot * originRelPivot;
            fingerBaseLeft.localRotation = armLeftStartRot * rot;
        }

        // LEFT PAD — translate by linkage displacement, no rotation
        if (fingerPadLeft != null && padLinkPointLeft != Vector3.zero)
        {
            Quaternion rot = Quaternion.AngleAxis(angle, rotationAxis);
            Vector3 linkRelPivot = padLinkPointLeft - armPivotLeft;
            Vector3 linkPointNow = armPivotLeft + rot * linkRelPivot;
            Vector3 displacement = linkPointNow - padLinkPointLeft;
            fingerPadLeft.localPosition = padLeftStartPos + displacement;
            fingerPadLeft.localRotation = padLeftStartRot;
        }

        // RIGHT ARM — mirrored (-angle)
        {
            Quaternion rot = Quaternion.AngleAxis(-angle, rotationAxis);
            Vector3 originRelPivot = armRightStartPos - armPivotRight;
            fingerBaseRight.localPosition = armPivotRight + rot * originRelPivot;
            fingerBaseRight.localRotation = armRightStartRot * rot;
        }

        // RIGHT PAD — mirrored (-angle)
        if (fingerPadRight != null && padLinkPointRight != Vector3.zero)
        {
            Quaternion rot = Quaternion.AngleAxis(-angle, rotationAxis);
            Vector3 linkRelPivot = padLinkPointRight - armPivotRight;
            Vector3 linkPointNow = armPivotRight + rot * linkRelPivot;
            Vector3 displacement = linkPointNow - padLinkPointRight;
            fingerPadRight.localPosition = padRightStartPos + displacement;
            fingerPadRight.localRotation = padRightStartRot;
        }
    }

    // ─── Public API (called by TCPHotController) ───────────────────────

    /// <summary>Set target grip position in meters (0.0 = closed, 0.11 = open).</summary>
    public void SetGripperPosition(float position)
    {
        targetGripPosition = Mathf.Clamp(position, minStroke, maxStroke);
    }

    /// <summary>Fully open the gripper (110mm for RG2).</summary>
    public void OpenGripper() { targetGripPosition = maxStroke; }

    /// <summary>Fully close the gripper (0mm).</summary>
    public void CloseGripper() { targetGripPosition = minStroke; }

    /// <summary>Current grip position in meters.</summary>
    public float GetCurrentPosition() { return currentGripPosition; }

    /// <summary>Current grip position as percentage (0–100%).</summary>
    public float GetCurrentPositionPercent() { return (currentGripPosition / maxStroke) * 100f; }

    // ─── Debug Marker System ───────────────────────────────────────────
    // Set showDebugMarkers = true in Inspector, then hit Play.
    // Colored spheres appear at pivot/link points for visual verification.
    // Drag them to correct positions, read local coords, update code defaults.
    // See class documentation above for full debugging workflow.

    /*
    void CreateDebugMarkers()
    {
        float markerRadius = 10f;

        // Arm pivots — RED (2x size to poke through gripper body)
        CreateMarkerSphere("DBG_ArmPivot_L", armPivotLeft, Color.red, markerRadius * 2f);
        CreateMarkerSphere("DBG_ArmPivot_R", armPivotRight, Color.red, markerRadius * 2f);

        // Pad link points — GREEN
        CreateMarkerSphere("DBG_PadLink_L", padLinkPointLeft, Color.green, markerRadius);
        CreateMarkerSphere("DBG_PadLink_R", padLinkPointRight, Color.green, markerRadius);

        // Arm mesh origins — BLUE (should be at 0,0,0)
        CreateMarkerSphere("DBG_ArmOrigin_L", armLeftStartPos, Color.blue, markerRadius);
        CreateMarkerSphere("DBG_ArmOrigin_R", armRightStartPos, Color.blue, markerRadius);

        // Pad mesh origins — CYAN (should be at 0,0,0)
        if (fingerPadLeft != null)
            CreateMarkerSphere("DBG_PadOrigin_L", padLeftStartPos, Color.cyan, markerRadius);
        if (fingerPadRight != null)
            CreateMarkerSphere("DBG_PadOrigin_R", padRightStartPos, Color.cyan, markerRadius);

        Debug.Log("GripperController: Debug markers created " +
                  "(RED=arm pivots, GREEN=pad links, BLUE=arm origins, CYAN=pad origins)");
    }

    void CreateMarkerSphere(string name, Vector3 localPos, Color color, float radiusLocal)
    {
        GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        marker.name = name;
        marker.transform.SetParent(transform, false);
        marker.transform.localPosition = localPos;

        float diameter = radiusLocal * 2f;
        marker.transform.localScale = new Vector3(diameter, diameter, diameter);

        Collider col = marker.GetComponent<Collider>();
        if (col != null) Destroy(col);

        Renderer rend = marker.GetComponent<Renderer>();
        if (rend != null)
        {
            Shader shader = Shader.Find("Unlit/Color")
                         ?? Shader.Find("Standard")
                         ?? Shader.Find("Universal Render Pipeline/Lit");
            Material mat = new Material(shader);
            mat.color = color;
            if (mat.HasProperty("_EmissionColor"))
            {
                mat.EnableKeyword("_EMISSION");
                mat.SetColor("_EmissionColor", color);
            }
            rend.material = mat;
        }

        Debug.Log($"  {name}: local={localPos}, world={marker.transform.position}");
    }
    */

    // Uncomment CreateDebugMarkers() above and the call in Start() to re-enable.
    void CreateDebugMarkers() { /* commented out — see block above */ }
}
