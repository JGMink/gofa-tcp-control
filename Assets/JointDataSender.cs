using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Linq;

public class JointDataSender : MonoBehaviour
{
    [Header("Target Device Network Settings")]
    public string targetDeviceIpAddress = "10.0.0.199"; // TODO: Change to your target device's IP
    public int targetDevicePort = 7000;                 // TODO: Choose a port for the target device

    private UdpClient udpClient;
    private IPEndPoint targetEndPoint;

    private bool isInitialized = false;

    void Start()
    {
        InitializeSender();
    }

    void InitializeSender()
    {
        try
        {
            udpClient = new UdpClient();
            targetEndPoint = new IPEndPoint(IPAddress.Parse(targetDeviceIpAddress), targetDevicePort);
            Debug.Log($"JointDataSender: Initialized. Ready to send to {targetDeviceIpAddress}:{targetDevicePort}");
            isInitialized = true;
        }
        catch (System.Exception e)
        {
            Debug.LogError($"JointDataSender: Error initializing UdpClient or IPEndPoint: {e.Message}");
            isInitialized = false;
        }
    }

    /// <summary>
    /// Sends the joint angles to the configured target device.
    /// </summary>
    /// <param name="jointAngles">An array of 6 float values representing the robot's joint angles.</param>
    public void SendJointAngles(float[] jointAngles)
    {
        if (!isInitialized)
        {
            // Debug.LogWarning("JointDataSender: Not initialized. Attempting to re-initialize.");
            // InitializeSender(); // Optionally try to re-initialize
            // if (!isInitialized) return;
            Debug.LogError("JointDataSender: Not initialized. Cannot send data.");
            return;
        }

        if (jointAngles == null || jointAngles.Length != 6)
        {
            Debug.LogWarning("JointDataSender: Invalid joint angles data provided. Expected 6 values.");
            return;
        }

        try
        {
            // Format data as a comma-separated string (e.g., "angle1,angle2,angle3,angle4,angle5,angle6")
            // Using "F4" for 4 decimal places. Adjust as needed.
            string dataString = string.Join(",", jointAngles.Select(a => a.ToString("F4")));
            byte[] dataBytes = Encoding.UTF8.GetBytes(dataString);

            // Send the data
            udpClient.Send(dataBytes, dataBytes.Length, targetEndPoint);
            // Debug.Log($"JointDataSender: Sent data: {dataString} to {targetEndPoint.Address}:{targetEndPoint.Port}"); // Can be spammy
        }
        catch (SocketException e)
        {
            Debug.LogError($"JointDataSender: SocketException while sending data: {e.Message}");
            // Consider if re-initialization is needed or if the target is unavailable
        }
        catch (System.Exception e)
        {
            Debug.LogError($"JointDataSender: Error sending joint data: {e.Message}");
        }
    }

    void OnDestroy()
    {
        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
            Debug.Log("JointDataSender: UdpClient closed.");
        }
    }

    // Optional: If you want to test sending from the Inspector or another script
    [ContextMenu("Test Send Dummy Data")]
    public void TestSend()
    {
        if (!Application.isPlaying)
        {
            Debug.LogWarning("JointDataSender: TestSend can only be used in Play Mode.");
            return;
        }
        if (!isInitialized) InitializeSender(); // Ensure initialized for test
        SendJointAngles(new float[] { 10.1f, 20.2f, 30.3f, 40.4f, 50.5f, 60.6f });
    }
}