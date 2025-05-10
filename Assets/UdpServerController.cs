using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using Newtonsoft.Json; // Make sure Newtonsoft.Json is in your project
using System.Threading;
using System.Collections.Generic; 
using System.Numerics;

// --- Message Definitions ---
// Ideally, these classes would be in a separate shared file (e.g., Messages.cs)
// Duplicated here for example purposes.
public class BaseMessage { public string type; }

public class RequestControlMessage : BaseMessage
{
    public RequestControlMessage() { type = "requestControl"; }
}

public class ReleaseControlMessage : BaseMessage
{
    public ReleaseControlMessage() { type = "releaseControl"; }
}

public class DataMessage : BaseMessage
{
    public float[] payload; // posX, posY, posZ, rotX, rotY, rotZ
    public DataMessage(UnityEngine.Vector3 pos, UnityEngine.Vector3 rot)
    {
        type = "data";
        payload = new float[] { pos.x, pos.y, pos.z, rot.x, rot.y, rot.z };
    }
    public DataMessage() { type = "data"; } // For deserialization
}

public class ControlStatusMessage : BaseMessage
{
    public string controllerIp;
    public ControlStatusMessage(string ip)
    {
        type = "controlStatus";
        controllerIp = ip;
    }
    public ControlStatusMessage() { type = "controlStatus"; } // For deserialization
}
// --- End of Message Definitions ---

public class UdpServerController : MonoBehaviour
{
    [Header("Network Settings - Server Listener")]
    public int serverListenPort = 5005; // Port this server listens on for client messages

    [Header("Network Settings - Broadcast to Clients")]
    public int clientListenPortForBroadcasts = 5006; // Port clients are listening on for our broadcasts

    [Header("Control State")]
    private string _currentControllerIp = null;
    private readonly object _lockObject = new object(); // For thread safety around _currentControllerIp

    [Header("Target Object (Optional)")]
    public GameObject targetObjectToMove; // GameObject to move based on controlled client's data

    private UdpClient _udpListener;
    private Thread _listenerThread;
    private volatile bool _isListening = false;

    // For main thread processing of received data
    private volatile bool _newDataToProcess = false;
    private UnityEngine.Vector3 _receivedPosition;
    private UnityEngine.Vector3 _receivedRotation;


    void Start()
    {
        try
        {
            _udpListener = new UdpClient(serverListenPort);
            Debug.Log($"UDP Server Controller started. Listening on port {serverListenPort}. Broadcasting control status to port {clientListenPortForBroadcasts}.");

            _listenerThread = new Thread(new ThreadStart(ListenForClientMessages));
            _listenerThread.IsBackground = true;
            _isListening = true;
            _listenerThread.Start();
        }
        catch (SocketException e)
        {
            Debug.LogError($"SocketException in Start: {e.Message}. Ensure port {serverListenPort} is not in use.");
            enabled = false; // Disable script if listening can't start
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error starting UDP listener: {e.Message}");
            enabled = false;
        }
    }

    private void ListenForClientMessages()
    {
        IPEndPoint remoteEndPoint = new IPEndPoint(IPAddress.Any, 0); // Receives from any IP/port

        while (_isListening)
        {
            try
            {
                byte[] receivedBytes = _udpListener.Receive(ref remoteEndPoint); // Blocks
                string jsonMessage = Encoding.UTF8.GetString(receivedBytes);
                string senderIp = remoteEndPoint.Address.ToString();

                // Deserialize to check type first
                BaseMessage baseMsg = JsonConvert.DeserializeObject<BaseMessage>(jsonMessage);

                if (baseMsg == null)
                {
                    Debug.LogWarning($"Received null message from {senderIp}. Raw: {jsonMessage}");
                    continue;
                }

                // Debug.Log($"Received message of type '{baseMsg.type}' from {senderIp}");

                lock (_lockObject) // Ensure thread-safe access to _currentControllerIp
                {
                    switch (baseMsg.type)
                    {
                        case "requestControl":
                            Debug.Log($"Control request received from {senderIp}. Current controller: {_currentControllerIp ?? "NONE"}");
                            if (string.IsNullOrEmpty(_currentControllerIp) || _currentControllerIp == senderIp)
                            {
                                if (_currentControllerIp != senderIp)
                                {
                                    Debug.Log($"Assigning control to {senderIp}.");
                                }
                                else
                                {
                                    Debug.Log($"Re-confirming control for {senderIp}.");
                                }
                                _currentControllerIp = senderIp;
                                BroadcastControlStatus();
                            }
                            else
                            {
                                Debug.Log($"Control request from {senderIp} denied. {_currentControllerIp} already has control. Re-broadcasting current status.");
                                // Optionally, send a "denied" message back to senderIp (unicast)
                                // For now, just re-broadcast the current status, which will inform the requester.
                                BroadcastControlStatus();
                            }
                            break;

                        case "releaseControl":
                            Debug.Log($"Release control request received from {senderIp}. Current controller: {_currentControllerIp ?? "NONE"}");
                            if (_currentControllerIp == senderIp)
                            {
                                Debug.Log($"Controller {senderIp} released control.");
                                _currentControllerIp = null;
                                BroadcastControlStatus();
                            }
                            else
                            {
                                Debug.LogWarning($"Release request from {senderIp}, but current controller is {_currentControllerIp ?? "NONE"}. Ignoring.");
                            }
                            break;

                        case "data":
                            if (_currentControllerIp == senderIp)
                            {
                                DataMessage dataMsg = JsonConvert.DeserializeObject<DataMessage>(jsonMessage);
                                if (dataMsg != null && dataMsg.payload != null && dataMsg.payload.Length == 6)
                                {
                                    // Store data for processing in Update() on the main thread
                                    _receivedPosition = new UnityEngine.Vector3(dataMsg.payload[0], dataMsg.payload[1], dataMsg.payload[2]);
                                    _receivedRotation = new UnityEngine.Vector3(dataMsg.payload[3], dataMsg.payload[4], dataMsg.payload[5]);
                                    _newDataToProcess = true;
                                }
                                else
                                {
                                    Debug.LogWarning($"Received malformed data message from controller {senderIp}.");
                                }
                            }
                            else
                            {
                                // Debug.Log($"Data received from non-controller {senderIp}. Ignoring. Current controller: {_currentControllerIp ?? "NONE"}");
                            }
                            break;

                        default:
                            Debug.LogWarning($"Received unknown message type '{baseMsg.type}' from {senderIp}.");
                            break;
                    }
                }
            }
            catch (SocketException e)
            {
                if (_isListening) Debug.LogError($"SocketException in listener thread: {e.Message}");
            }
            catch (JsonException e)
            {
                // Attempt to get the raw string again for logging, but this might fail if Receive already moved on.
                // Consider logging the raw byte array or a portion of it if this becomes hard to debug.
                Debug.LogError($"JsonException: Could not deserialize message. {e.Message}.");
            }
            catch (System.Exception e)
            {
                if (_isListening) Debug.LogError($"Error in listener thread: {e.Message}");
            }
        }
        Debug.Log("Server listener thread finished.");
    }

    private void BroadcastControlStatus()
    {
        // This method is called within a lock(_lockObject) block, so _currentControllerIp is safe to read.
        ControlStatusMessage statusMessage = new ControlStatusMessage(_currentControllerIp);
        string jsonMessage = JsonConvert.SerializeObject(statusMessage);
        byte[] data = Encoding.UTF8.GetBytes(jsonMessage);

        try
        {
            // Broadcast to all devices on the network on the specified client listen port
            // Note: IPAddress.Broadcast (255.255.255.255) might not work on all network configurations or platforms.
            // A subnet-specific broadcast (e.g., 192.168.1.255) can be more reliable if the subnet is known.
            // For simplicity, using IPAddress.Broadcast.
            // The UdpClient used for listening can also be used for sending.
            _udpListener.Send(data, data.Length, new IPEndPoint(IPAddress.Broadcast, clientListenPortForBroadcasts));
            Debug.Log($"Broadcasted control status: Controller is {_currentControllerIp ?? "NONE"} to port {clientListenPortForBroadcasts}");
        }
        catch (SocketException e)
        {
            Debug.LogError($"SocketException during broadcast: {e.Message}");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error broadcasting control status: {e.Message}");
        }
    }

    void Update()
    {
        if (_newDataToProcess)
        {
            if (targetObjectToMove != null)
            {
                targetObjectToMove.transform.position = _receivedPosition;
                targetObjectToMove.transform.eulerAngles = _receivedRotation;
            }
            // Debug.Log($"Processed data: Pos({_receivedPosition}), Rot({_receivedRotation})");
            _newDataToProcess = false; // Reset flag
        }
    }

    private void StopListening()
    {
        _isListening = false;

        if (_udpListener != null)
        {
            _udpListener.Close(); // This will cause the blocking Receive to throw a SocketException and exit loop
            _udpListener = null;
            Debug.Log("UDP Listener closed.");
        }

        if (_listenerThread != null && _listenerThread.IsAlive)
        {
            _listenerThread.Join(500); // Wait for the thread to finish
            if (_listenerThread.IsAlive)
            {
                Debug.LogWarning("Listener thread did not terminate gracefully.");
                // listenerThread.Abort(); // Generally not recommended
            }
            _listenerThread = null;
        }
    }

    private void OnApplicationQuit()
    {
        // Before quitting, broadcast that no one has control (if someone did)
        // This helps clients reset if the server just disappears.
        bool hadController;
        lock (_lockObject)
        {
            hadController = !string.IsNullOrEmpty(_currentControllerIp);
            _currentControllerIp = null; // Server is shutting down, no one controls via this server.
        }
        if (hadController)
        {
            Debug.Log("Server quitting. Broadcasting no controller status.");
            BroadcastControlStatus(); // Will broadcast with _currentControllerIp as null
        }

        StopListening();
        Debug.Log("UdpServerController resources cleaned up.");
    }

    private void OnDestroy()
    {
        // OnApplicationQuit is usually called first, but this is a good fallback.
        StopListening();
    }
}

