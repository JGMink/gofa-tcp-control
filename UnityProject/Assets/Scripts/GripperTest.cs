using UnityEngine;

public class GripperTest : MonoBehaviour
{
    [Header("Test Settings")]
    public GripperController gripperController;
    public Transform leftFinger;
    public Transform rightFinger;
    public Transform gripperBase;

    [Header("Test Sequence")]
    public float testInterval = 2f;  // Time between test steps
    public bool runTestOnStart = false;

    private float testTimer = 0f;
    private int testStep = 0;
    private bool testRunning = false;

    void Start()
    {
        // Auto-find components if not assigned
        if (gripperController == null)
        {
            gripperController = FindObjectOfType<GripperController>();
            if (gripperController != null)
            {
                Debug.Log($"✓ Auto-found GripperController on: {gripperController.gameObject.name}");
            }
            else
            {
                Debug.LogError("✗ GripperController not found! Make sure it's attached to your gripper GameObject.");
            }
        }

        // Auto-find fingers if not assigned
        if (gripperController != null)
        {
            if (leftFinger == null)
            {
                leftFinger = gripperController.fingerBaseLeft;
                if (leftFinger != null) Debug.Log($"✓ Auto-found left finger arm: {leftFinger.name}");
            }

            if (rightFinger == null)
            {
                rightFinger = gripperController.fingerBaseRight;
                if (rightFinger != null) Debug.Log($"✓ Auto-found right finger arm: {rightFinger.name}");
            }

            if (gripperBase == null)
            {
                gripperBase = gripperController.gripperBase;
                if (gripperBase != null) Debug.Log($"✓ Auto-found gripper base: {gripperBase.name}");
            }
        }

        if (runTestOnStart)
        {
            StartTest();
        }

        Debug.Log("=== Gripper Test Ready ===");
        Debug.Log("Press T to run gripper test sequence");
        Debug.Log("Press O to open gripper");
        Debug.Log("Press P to close gripper");
        Debug.Log("Press H to half-close gripper");
        Debug.Log("Press I to print gripper info");
        Debug.Log("==========================");
    }

    void Update()
    {
        // Manual control keys
        if (Input.GetKeyDown(KeyCode.T))
        {
            StartTest();
        }

        if (Input.GetKeyDown(KeyCode.O))
        {
            TestOpen();
        }

        if (Input.GetKeyDown(KeyCode.P))
        {
            TestClose();
        }

        if (Input.GetKeyDown(KeyCode.H))
        {
            TestHalf();
        }

        if (Input.GetKeyDown(KeyCode.I))
        {
            PrintGripperInfo();
        }

        // Run test sequence
        if (testRunning)
        {
            testTimer += Time.deltaTime;

            if (testTimer >= testInterval)
            {
                testTimer = 0f;
                RunTestStep();
            }
        }
    }

    public void StartTest()
    {
        Debug.Log("\n=== STARTING GRIPPER TEST SEQUENCE ===");
        testStep = 0;
        testTimer = 0f;
        testRunning = true;
        RunTestStep();
    }

    void RunTestStep()
    {
        switch (testStep)
        {
            case 0:
                Debug.Log("\n[Test 1/5] Opening gripper to 110mm...");
                TestOpen();
                break;

            case 1:
                Debug.Log("\n[Test 2/5] Closing gripper to 0mm...");
                TestClose();
                break;

            case 2:
                Debug.Log("\n[Test 3/5] Half-closing to 55mm...");
                TestHalf();
                break;

            case 3:
                Debug.Log("\n[Test 4/5] Opening again to 110mm...");
                TestOpen();
                break;

            case 4:
                Debug.Log("\n[Test 5/5] Setting to 75mm...");
                TestCustom(0.075f);
                break;

            case 5:
                Debug.Log("\n=== TEST SEQUENCE COMPLETE ===");
                PrintGripperInfo();
                testRunning = false;
                break;
        }

        testStep++;
    }

    void TestOpen()
    {
        if (gripperController != null)
        {
            gripperController.OpenGripper();
            Debug.Log("✓ Sent OPEN command (110mm)");
            Invoke(nameof(PrintGripperInfo), 0.5f);
        }
        else
        {
            Debug.LogError("✗ GripperController not found!");
        }
    }

    void TestClose()
    {
        if (gripperController != null)
        {
            gripperController.CloseGripper();
            Debug.Log("✓ Sent CLOSE command (0mm)");
            Invoke(nameof(PrintGripperInfo), 0.5f);
        }
        else
        {
            Debug.LogError("✗ GripperController not found!");
        }
    }

    void TestHalf()
    {
        if (gripperController != null)
        {
            gripperController.SetGripperPosition(0.055f);  // 55mm
            Debug.Log("✓ Sent HALF command (55mm)");
            Invoke(nameof(PrintGripperInfo), 0.5f);
        }
        else
        {
            Debug.LogError("✗ GripperController not found!");
        }
    }

    void TestCustom(float position)
    {
        if (gripperController != null)
        {
            gripperController.SetGripperPosition(position);
            Debug.Log($"✓ Sent CUSTOM command ({position * 1000:F0}mm)");
            Invoke(nameof(PrintGripperInfo), 0.5f);
        }
        else
        {
            Debug.LogError("✗ GripperController not found!");
        }
    }

    void PrintGripperInfo()
    {
        if (gripperController == null)
        {
            Debug.LogError("✗ GripperController not found!");
            return;
        }

        Debug.Log("--- Gripper Status ---");
        Debug.Log($"Current Position: {gripperController.GetCurrentPosition() * 1000:F1}mm");
        Debug.Log($"Percent Open: {gripperController.GetCurrentPositionPercent():F1}%");

        // Get finger positions if assigned
        if (leftFinger != null && rightFinger != null)
        {
            float distance = Vector3.Distance(leftFinger.position, rightFinger.position);
            Debug.Log($"Finger Distance: {distance * 1000:F1}mm");
            Debug.Log($"Left Finger: {leftFinger.localPosition}");
            Debug.Log($"Right Finger: {rightFinger.localPosition}");
        }

        if (gripperBase != null)
        {
            Debug.Log($"Gripper Base Position: {gripperBase.position}");
        }

        Debug.Log("---------------------");
    }

    // Draw gizmos in scene view
    void OnDrawGizmos()
    {
        if (gripperController == null || leftFinger == null || rightFinger == null)
            return;

        // Draw line between fingers
        Gizmos.color = Color.cyan;
        Gizmos.DrawLine(leftFinger.position, rightFinger.position);

        // Draw labels
        #if UNITY_EDITOR
        float currentMM = gripperController.GetCurrentPosition() * 1000f;
        float percentOpen = gripperController.GetCurrentPositionPercent();
        string label = $"Gripper: {currentMM:F1}mm ({percentOpen:F0}% open)";

        Vector3 labelPos = (leftFinger.position + rightFinger.position) / 2f;
        labelPos += Vector3.up * 0.05f;

        UnityEditor.Handles.Label(labelPos, label);
        #endif
    }
}
