using System;
using System.IO;
using System.Collections;
using System.Reflection;
using UnityEngine;

/// <summary>
/// TCPSpeedBridge — Motion Smoothing Companion for TCPHotController
/// -----------------------------------------------------------------
/// Keeps TCPHotController.cs completely untouched. Instead of letting
/// TCPHotController run its flat MoveTowards movement, this bridge:
///
///   1. Watches tcp_commands.json for the same file changes
///   2. Cancels TCPHotController's active coroutine before it moves
///   3. Runs its own SmoothMoveTo coroutine with ease-in/ease-out
///      and a speed profile matched to the speed_mode in the JSON
///
/// Setup:
///   - Attach to the SAME GameObject as TCPHotController
///   - No changes needed to TCPHotController, Python files, or any other script
/// </summary>
public class TCPSpeedBridge : MonoBehaviour
{
    [Header("File Settings — must match TCPHotController")]
    [SerializeField] private string configPath  = "tcp_commands.json";
    [SerializeField] private float pollInterval = 0.1f;

    [Header("Motion Settings")]
    [SerializeField] private float defaultMaxSpeed    = 0.5f;
    [SerializeField] private float defaultAcceleration = 1f; // units/s²
    [SerializeField] private float defaultDeceleration = 1f; // units/s²

    [Header("Speed Profiles (multipliers)")]
    [SerializeField] private SpeedProfile slowlyProfile    = new SpeedProfile(0.3f, 0.5f);
    [SerializeField] private SpeedProfile carefullyProfile = new SpeedProfile(0.4f, 0.6f);
    [SerializeField] private SpeedProfile quicklyProfile   = new SpeedProfile(2.0f, 3.0f);
    [SerializeField] private SpeedProfile messilyProfile   = new SpeedProfile(3.0f, 5.0f);

    [Header("Debug")]
    [SerializeField] private bool showDebugGizmos = true;

    private TCPHotController hotController;
    private FieldInfo activeMoveField;  // reflection handle to TCPHotController.activeMove
    private DateTime lastModified;
    private Coroutine smoothMove;
    private string fullPath;
    private Vector3 currentVelocity = Vector3.zero;

    void Start()
    {
        hotController = GetComponent<TCPHotController>();
        if (hotController == null)
        {
            Debug.LogError("TCPSpeedBridge: TCPHotController not found on this GameObject. " +
                           "Both scripts must be on the same object.");
            enabled = false;
            return;
        }

        // Grab the private 'activeMove' field from TCPHotController via reflection
        // so we can cancel its MoveTowards coroutine before it runs
        activeMoveField = typeof(TCPHotController).GetField(
            "activeMove",
            BindingFlags.NonPublic | BindingFlags.Instance
        );

        if (activeMoveField == null)
        {
            Debug.LogWarning("TCPSpeedBridge: Could not find 'activeMove' field on TCPHotController. " +
                             "Smooth motion will still work but the original coroutine may also run briefly.");
        }

        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        fullPath = Path.Combine(projectRoot, configPath);

        Debug.Log($"TCPSpeedBridge watching: {fullPath}");
        StartCoroutine(WatchFile());
    }

    IEnumerator WatchFile()
    {
        while (true)
        {
            yield return new WaitForSeconds(pollInterval);

            if (!File.Exists(fullPath))
                continue;

            DateTime currentModified = File.GetLastWriteTime(fullPath);
            if (currentModified == lastModified)
                continue;

            lastModified = currentModified;
            InterceptAndMove();
        }
    }

    void InterceptAndMove()
    {
        try
        {
            string json = File.ReadAllText(fullPath);
            if (string.IsNullOrWhiteSpace(json))
                return;

            // Read x, y, z, and speed_mode from the JSON.
            // JsonUtility ignores any fields not declared here (gripper_position etc.)
            BridgeCommand cmd = JsonUtility.FromJson<BridgeCommand>(json);
            if (cmd == null)
                return;

            // Cancel TCPHotController's own MoveTowards coroutine via reflection
            // so we don't get two coroutines fighting over transform.position
            if (activeMoveField != null)
            {
                Coroutine existingMove = activeMoveField.GetValue(hotController) as Coroutine;
                if (existingMove != null)
                {
                    hotController.StopCoroutine(existingMove);
                    activeMoveField.SetValue(hotController, null);
                }
            }

            // Cancel our own previous smooth move if still running
            if (smoothMove != null)
                StopCoroutine(smoothMove);

            SpeedProfile profile = GetSpeedProfile(cmd.speed_mode);
            Vector3 targetPos    = new Vector3(cmd.x, cmd.y, cmd.z);
            smoothMove           = StartCoroutine(SmoothMoveTo(targetPos, profile));

            Debug.Log($"TCPSpeedBridge: Moving to ({cmd.x:F3}, {cmd.y:F3}, {cmd.z:F3}) " +
                      $"[Mode: {cmd.speed_mode}]");
        }
        catch (IOException)
        {
            // File mid-write, will retry next poll
        }
        catch (Exception e)
        {
            Debug.LogWarning($"TCPSpeedBridge parse error: {e.Message}");
        }
    }

    SpeedProfile GetSpeedProfile(string mode)
    {
        if (string.IsNullOrEmpty(mode) || mode == "default" || mode == "normal")
            return new SpeedProfile(1.0f, 1.0f);

        switch (mode.ToLower())
        {
            case "slowly":
            case "slow":
                return slowlyProfile;

            case "carefully":
            case "careful":
            case "gently":
            case "gentle":
            case "cautiously":
                return carefullyProfile;

            case "quickly":
            case "quick":
            case "fast":
            case "faster":
            case "rapidly":
                return quicklyProfile;

            case "messily":
            case "messy":
            case "roughly":
            case "aggressively":
                return messilyProfile;

            default:
                Debug.LogWarning($"TCPSpeedBridge: Unknown speed mode '{mode}', using default");
                return new SpeedProfile(1.0f, 1.0f);
        }
    }

    IEnumerator SmoothMoveTo(Vector3 target, SpeedProfile profile)
    {
        Vector3 startPos    = transform.position;
        float totalDistance = Vector3.Distance(startPos, target);

        if (totalDistance < 0.001f)
            yield break;

        // Scale speed and acceleration by profile multipliers
        float maxSpeed     = defaultMaxSpeed     * profile.speedMultiplier;
        float acceleration = defaultAcceleration * profile.accelerationMultiplier;
        float deceleration = defaultDeceleration * profile.accelerationMultiplier;

        // Calculate ramp-up and ramp-down distances
        float accelTime = maxSpeed / acceleration;
        float decelTime = maxSpeed / deceleration;
        float accelDist = 0.5f * acceleration * accelTime * accelTime;
        float decelDist = 0.5f * deceleration * decelTime * decelTime;

        // Short move — can't reach full speed, use triangular profile instead
        bool useTriangularProfile = (accelDist + decelDist) > totalDistance;
        if (useTriangularProfile)
        {
            float avgAccel = (acceleration + deceleration) / 2f;
            maxSpeed  = Mathf.Sqrt(avgAccel * totalDistance);
            accelDist = totalDistance / 2f;
            decelDist = totalDistance / 2f;
        }

        Debug.Log($"TCPSpeedBridge: Distance={totalDistance:F3}, MaxSpeed={maxSpeed:F3}, " +
                  $"AccelDist={accelDist:F3}, DecelDist={decelDist:F3}, " +
                  $"Triangular={useTriangularProfile}");

        float currentSpeed = 0f;

        while (Vector3.Distance(transform.position, target) > 0.001f)
        {
            float dt                = Time.deltaTime;
            float distanceTraveled  = Vector3.Distance(startPos, transform.position);
            float remainingDistance = totalDistance - distanceTraveled;

            if (distanceTraveled < accelDist)
            {
                // Ease-in — quadratic ramp up from rest
                float t  = distanceTraveled / accelDist;
                currentSpeed = EaseInQuad(t) * maxSpeed;
            }
            else if (remainingDistance > decelDist)
            {
                // Cruise — constant full speed
                currentSpeed = maxSpeed;
            }
            else
            {
                // Ease-out — quadratic ramp down to rest
                float t  = remainingDistance / decelDist;
                currentSpeed = EaseOutQuad(t) * maxSpeed;
            }

            Vector3 direction = (target - transform.position).normalized;
            Vector3 movement  = direction * currentSpeed * dt;

            // Prevent overshooting
            if (movement.magnitude > remainingDistance)
            {
                transform.position = target;
                break;
            }

            transform.position += movement;
            currentVelocity     = direction * currentSpeed;

            yield return null;
        }

        transform.position = target;
        currentVelocity    = Vector3.zero;

        Debug.Log("TCPSpeedBridge: Reached target");
    }

    // Quadratic ease-in: slow start → accelerates
    float EaseInQuad(float t)  => t * t;

    // Quadratic ease-out: decelerates → smooth stop
    float EaseOutQuad(float t) => t * (2f - t);

    void OnDrawGizmos()
    {
        if (!showDebugGizmos || !Application.isPlaying) return;

        Gizmos.color = Color.cyan;
        Gizmos.DrawRay(transform.position, currentVelocity.normalized * 0.1f);

        float speedIndicator = currentVelocity.magnitude / defaultMaxSpeed;
        Gizmos.color = Color.Lerp(Color.yellow, Color.red, speedIndicator);
        Gizmos.DrawWireSphere(transform.position, 0.02f);
    }
}

// Minimal JSON wrapper — only reads what TCPSpeedBridge needs.
// JsonUtility silently ignores gripper_position and any other fields,
// so all other scripts reading tcp_commands.json are completely unaffected.
[System.Serializable]
internal class BridgeCommand
{
    public float  x;
    public float  y;
    public float  z;
    public string speed_mode = "default";
}

[System.Serializable]
public class SpeedProfile
{
    [Tooltip("Multiplier for maximum speed (1.0 = default speed)")]
    public float speedMultiplier = 1.0f;

    [Tooltip("Multiplier for acceleration and deceleration (1.0 = default)")]
    public float accelerationMultiplier = 1.0f;

    public SpeedProfile(float speed, float accel)
    {
        speedMultiplier        = speed;
        accelerationMultiplier = accel;
    }
}