using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Linq;

public class JointDataSender : MonoBehaviour
{
    [Header("Network Settings")]
    // The targetDeviceIpAddress is now automatically set to the broadcast address.
    // You only need to set the port.
    public int targetPort = 7000;            // Port to broadcast on

    private UdpClient udpClient;
    private IPEndPoint broadcastEndPoint;

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
            // Set the UdpClient to allow broadcast. This is crucial.
            udpClient.EnableBroadcast = true;

            // Use IPAddress.Broadcast for the broadcast address (typically 255.255.255.255)
            broadcastEndPoint = new IPEndPoint(IPAddress.Broadcast, targetPort);

            Debug.Log($"JointDataBroadcaster: Initialized. Ready to broadcast to port {targetPort}");
            isInitialized = true;
        }
        catch (System.Exception e)
        {
            Debug.LogError($"JointDataBroadcaster: Error initializing UdpClient or IPEndPoint: {e.Message}");
            isInitialized = false;
        }
    }

    /// <summary>
    /// Sends the joint angles to all devices on the network via broadcast.
    /// </summary>
    /// <param name="jointAngles">An array of 6 float values representing the robot's joint angles.</param>
    public void SendJointAngles(float[] jointAngles)
    {
        if (!isInitialized)
        {
            Debug.LogError("JointDataBroadcaster: Not initialized. Cannot send data.");
            // Optionally, you could try to re-initialize here if it makes sense for your application
            // InitializeSender();
            // if (!isInitialized) return;
            return;
        }

        if (jointAngles == null || jointAngles.Length != 6)
        {
            Debug.LogWarning("JointDataBroadcaster: Invalid joint angles data provided. Expected 6 values.");
            return;
        }

        try
        {
            // Format data as a comma-separated string (e.g., "angle1,angle2,angle3,angle4,angle5,angle6")
            // Using "F4" for 4 decimal places. Adjust as needed.
            string dataString = string.Join(",", jointAngles.Select(a => a.ToString("F4")));
            byte[] dataBytes = Encoding.UTF8.GetBytes(dataString);

            // Send the data to the broadcast endpoint
            udpClient.Send(dataBytes, dataBytes.Length, broadcastEndPoint);
            // Debug.Log($"JointDataBroadcaster: Sent data: {dataString} to broadcast port {broadcastEndPoint.Port}"); // Can be spammy
        }
        catch (SocketException e)
        {
            Debug.LogError($"JointDataBroadcaster: SocketException while sending data: {e.Message}");
            // Consider if re-initialization is needed or if the network is unavailable
        }
        catch (System.Exception e)
        {
            Debug.LogError($"JointDataBroadcaster: Error sending joint data: {e.Message}");
        }
    }

    void OnDestroy()
    {
        if (udpClient != null)
        {
            udpClient.Close();
            udpClient = null;
            Debug.Log("JointDataBroadcaster: UdpClient closed.");
        }
    }

    // Optional: If you want to test sending from the Inspector or another script
    [ContextMenu("Test Send Dummy Data (Broadcast)")]
    public void TestSend()
    {
        if (!Application.isPlaying)
        {
            Debug.LogWarning("JointDataBroadcaster: TestSend can only be used in Play Mode.");
            return;
        }
        // Ensure initialized for test. If Start() hasn't run yet, this will initialize.
        if (!isInitialized)
        {
            InitializeSender();
            if (!isInitialized)
            {
                Debug.LogError("JointDataBroadcaster: Failed to initialize for TestSend.");
                return;
            }
        }
        SendJointAngles(new float[] { 10.1234f, 20.2345f, 30.3456f, 40.4567f, 50.5678f, 60.6789f });
    }
}
