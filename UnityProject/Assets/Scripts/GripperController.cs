using UnityEngine;
using System.IO;

public class GripperController : MonoBehaviour
{
    public enum GripperModel { RG2, RG6 }

    [Header("Gripper Model Settings")]
    public GripperModel modelType = GripperModel.RG2;

    [Header("Finger Transforms")]
    public Transform fingerLeft;
    public Transform fingerRight;
    public Transform gripperBase;

    [Header("Stroke Settings - RG2")]
    [Tooltip("RG2: 110mm max stroke, RG6: 160mm max stroke")]
    public float maxStroke = 0.110f;  // RG2: 110mm = 0.11m
    public float minStroke = 0.0f;

    [Header("Grip Force Settings")]
    [Tooltip("RG2: 3-40N, RG6: 25-120N")]
    public float maxForce = 40f;  // RG2: 40N
    public float minForce = 3f;   // RG2: 3N

    [Header("Animation Settings")]
    [Tooltip("Speed at which fingers open/close (meters per second)")]
    public float gripSpeed = 0.05f;  // 50mm/sec

    [Header("Command File Settings")]
    public string commandFilePath = "tcp_commands.json";
    public float pollInterval = 0.1f;  // Check for commands every 100ms

    [Header("Arc Motion Settings (RG2 4-bar linkage)")]
    [Tooltip("Max rotation angle in degrees when fully closed. RG2 fingers pivot ~46 degrees from open to closed.")]
    public float maxFingerAngle = 46f;

    [Tooltip("Pivot point offset in finger's local space (X). The OBJ pivot is at ~76mm along the finger length. " +
             "Adjust if mesh origin differs from pivot location.")]
    public Vector3 leftPivotOffset = Vector3.zero;

    [Tooltip("Pivot point offset for right finger (usually mirrored from left).")]
    public Vector3 rightPivotOffset = Vector3.zero;

    [Tooltip("Rotation axis in local space. For RG2, fingers rotate around local Z axis.")]
    public Vector3 rotationAxis = Vector3.forward;  // Local Z

    // Internal state
    private float currentGripPosition = 0.110f;  // Start fully open (RG2: 110mm)
    private float targetGripPosition = 0.110f;
    private Vector3 leftFingerStartPos;
    private Vector3 rightFingerStartPos;
    private Quaternion leftFingerStartRot;
    private Quaternion rightFingerStartRot;
    private float lastPollTime;

    [System.Serializable]
    private class TCPCommand
    {
        public float[] position;
        public float[] rotation;
        public float gripper_position;  // 0.0 = closed, 0.11 = open (RG2)
    }

    void Start()
    {
        // Validate references
        if (fingerLeft == null || fingerRight == null)
        {
            Debug.LogError("GripperController: Finger transforms not assigned!");
            enabled = false;
            return;
        }

        // Store initial finger positions AND rotations (open position)
        leftFingerStartPos = fingerLeft.localPosition;
        rightFingerStartPos = fingerRight.localPosition;
        leftFingerStartRot = fingerLeft.localRotation;
        rightFingerStartRot = fingerRight.localRotation;

        // Set stroke based on model type
        if (modelType == GripperModel.RG6)
        {
            maxStroke = 0.160f;  // RG6: 160mm
            maxForce = 120f;
            minForce = 25f;
        }

        // Start fully open
        currentGripPosition = maxStroke;
        targetGripPosition = maxStroke;
        UpdateFingerPositions();

        Debug.Log($"GripperController initialized: Model={modelType}, MaxStroke={maxStroke * 1000:F0}mm");
        Debug.Log($"  Finger start: L_pos={leftFingerStartPos}, R_pos={rightFingerStartPos}");
        Debug.Log($"  Finger start: L_rot={leftFingerStartRot.eulerAngles}, R_rot={rightFingerStartRot.eulerAngles}");
        Debug.Log($"  Arc motion: maxAngle={maxFingerAngle}deg, axis={rotationAxis}");
        Debug.Log($"  Pivot offsets: L={leftPivotOffset}, R={rightPivotOffset}");
    }

    void Update()
    {
        // NOTE: File polling is disabled - TCPHotController reads tcp_commands.json
        // and calls SetGripperPosition() on this component. This avoids double-reads
        // and format mismatches.

        // Smoothly animate to target position
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

    void UpdateFingerPositions()
    {
        // RG2 fingers pivot on pins (4-bar linkage mechanism).
        // The RG2 manual confirms: "circular movement of the finger arms"
        //
        // closeRatio: 0 = fully open (maxStroke), 1 = fully closed (0mm)
        // fingerAngle: rotation in degrees from open position
        //
        // Each finger rotates around a pivot point. As it rotates:
        //   - The fingertip moves inward (closing)
        //   - AND swings slightly forward (the arc effect the user noticed)
        //
        // Left finger rotates in POSITIVE direction around rotationAxis (e.g. +Z)
        // Right finger rotates in NEGATIVE direction around rotationAxis (mirrored)

        float closeRatio = 1f - (currentGripPosition / maxStroke);
        float fingerAngle = closeRatio * maxFingerAngle;

        if (fingerLeft != null)
        {
            // Apply rotation around the pivot point
            // 1. Start from the stored initial rotation
            // 2. Apply the closing rotation
            Quaternion closingRotation = Quaternion.AngleAxis(fingerAngle, rotationAxis);

            if (leftPivotOffset == Vector3.zero)
            {
                // Simple rotation around the finger's own origin
                fingerLeft.localRotation = leftFingerStartRot * closingRotation;
                fingerLeft.localPosition = leftFingerStartPos;
            }
            else
            {
                // Rotate around an offset pivot point
                // This moves the transform position as well as rotating it
                fingerLeft.localRotation = leftFingerStartRot * closingRotation;
                Vector3 pivotWorld = fingerLeft.parent.TransformPoint(leftFingerStartPos + leftPivotOffset);
                Vector3 startWorld = fingerLeft.parent.TransformPoint(leftFingerStartPos);
                Vector3 rotatedOffset = closingRotation * (-leftPivotOffset);
                fingerLeft.localPosition = leftFingerStartPos + leftPivotOffset + rotatedOffset;
            }
        }

        if (fingerRight != null)
        {
            // Right finger rotates in opposite direction (mirrored)
            Quaternion closingRotation = Quaternion.AngleAxis(-fingerAngle, rotationAxis);

            if (rightPivotOffset == Vector3.zero)
            {
                fingerRight.localRotation = rightFingerStartRot * closingRotation;
                fingerRight.localPosition = rightFingerStartPos;
            }
            else
            {
                fingerRight.localRotation = rightFingerStartRot * closingRotation;
                Vector3 rotatedOffset = closingRotation * (-rightPivotOffset);
                fingerRight.localPosition = rightFingerStartPos + rightPivotOffset + rotatedOffset;
            }
        }
    }

    // Public methods for external control
    public void SetGripperPosition(float position)
    {
        targetGripPosition = Mathf.Clamp(position, minStroke, maxStroke);
    }

    public void OpenGripper()
    {
        targetGripPosition = maxStroke;
    }

    public void CloseGripper()
    {
        targetGripPosition = minStroke;
    }

    public float GetCurrentPosition()
    {
        return currentGripPosition;
    }

    public float GetCurrentPositionPercent()
    {
        return (currentGripPosition / maxStroke) * 100f;
    }

    // Gizmos for debugging in Scene view
    void OnDrawGizmos()
    {
        if (fingerLeft != null && fingerRight != null)
        {
            // Draw line between fingers to visualize grip width
            Gizmos.color = Color.cyan;
            Gizmos.DrawLine(fingerLeft.position, fingerRight.position);

            // Draw pivot points if set
            if (leftPivotOffset != Vector3.zero)
            {
                Gizmos.color = Color.red;
                Vector3 leftPivotWorld = fingerLeft.TransformPoint(leftPivotOffset);
                Gizmos.DrawWireSphere(leftPivotWorld, 0.002f);
            }
            if (rightPivotOffset != Vector3.zero)
            {
                Gizmos.color = Color.red;
                Vector3 rightPivotWorld = fingerRight.TransformPoint(rightPivotOffset);
                Gizmos.DrawWireSphere(rightPivotWorld, 0.002f);
            }
        }

        // Draw rotation axis at gripper root
        if (gripperBase != null || transform != null)
        {
            Transform root = gripperBase != null ? gripperBase : transform;
            Gizmos.color = Color.yellow;
            Gizmos.DrawRay(root.position, root.TransformDirection(rotationAxis) * 0.03f);
        }
    }
}
