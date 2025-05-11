using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using Newtonsoft.Json; // Make sure Newtonsoft.Json is in your project
using System.Threading;
using System.Collections.Generic;
// using System.Numerics; // UnityEngine.Vector3 is used, System.Numerics.Vector3 is not needed unless for other purposes.

// TMP CHANGE: Add TextMeshPro namespace
using TMPro;

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

    // TMP CHANGE: Add TextMeshPro UI references
    [Header("UI Display")]
    public TextMeshProUGUI controllerStatusText; // Assign in Inspector
    public TextMeshProUGUI lastClientActivityText; // Assign in Inspector

    private UdpClient _udpListener;
    private Thread _listenerThread;
    private volatile bool _isListening = false;

    // For main thread processing of received data
    private volatile bool _newDataToProcess = false;
    private UnityEngine.Vector3 _receivedPosition;
    private UnityEngine.Vector3 _receivedRotation;

    // TMP CHANGE: Variables to store data for UI update on the main thread
    private volatile string _uiControllerIpUpdate = null;
    private volatile string _uiLastSenderIpUpdate = null;
    private volatile bool _uiNeedsUpdate = false;


    void Start()
    {
        // TMP CHANGE: Initial UI Update
        UpdateUIText();

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
            if (controllerStatusText) controllerStatusText.text = $"Error: Port {serverListenPort} in use.";
            enabled = false; // Disable script if listening can't start
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error starting UDP listener: {e.Message}");
            if (controllerStatusText) controllerStatusText.text = "Error starting listener.";
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

                // TMP CHANGE: Mark for UI update with the last sender
                _uiLastSenderIpUpdate = senderIp;
                _uiNeedsUpdate = true;


                BaseMessage baseMsg = JsonConvert.DeserializeObject<BaseMessage>(jsonMessage);

                if (baseMsg == null)
                {
                    Debug.LogWarning($"Received null message from {senderIp}. Raw: {jsonMessage}");
                    continue;
                }

                // Debug.Log($"Received message of type '{baseMsg.type}' from {senderIp}");

                lock (_lockObject) // Ensure thread-safe access to _currentControllerIp
                {
                    string previousControllerIp = _currentControllerIp; // Store previous for comparison

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
                                BroadcastControlStatus(); // This will also trigger UI update via _uiControllerIpUpdate
                            }
                            else
                            {
                                Debug.Log($"Control request from {senderIp} denied. {_currentControllerIp} already has control. Re-broadcasting current status.");
                                BroadcastControlStatus(); // Re-broadcast to inform the requester
                            }
                            break;

                        case "releaseControl":
                            Debug.Log($"Release control request received from {senderIp}. Current controller: {_currentControllerIp ?? "NONE"}");
                            if (_currentControllerIp == senderIp)
                            {
                                Debug.Log($"Controller {senderIp} released control.");
                                _currentControllerIp = null;
                                BroadcastControlStatus(); // This will also trigger UI update
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
                                    _receivedPosition = new UnityEngine.Vector3(dataMsg.payload[0], dataMsg.payload[1], dataMsg.payload[2]);
                                    _receivedRotation = new UnityEngine.Vector3(dataMsg.payload[3], dataMsg.payload[4], dataMsg.payload[5]);
                                    _newDataToProcess = true;
                                }
                                else
                                {
                                    Debug.LogWarning($"Received malformed data message from controller {senderIp}.");
                                }
                            }
                            // No need to log if data is from non-controller, can be noisy
                            break;

                        default:
                            Debug.LogWarning($"Received unknown message type '{baseMsg.type}' from {senderIp}.");
                            break;
                    }

                    // TMP CHANGE: If controller changed, mark for UI update
                    if (previousControllerIp != _currentControllerIp)
                    {
                        _uiControllerIpUpdate = _currentControllerIp;
                        _uiNeedsUpdate = true;
                    }
                }
            }
            catch (SocketException e)
            {
                if (_isListening) Debug.LogError($"SocketException in listener thread: {e.Message}");
            }
            catch (JsonException e)
            {
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
        // This method is called within a lock(_lockObject) block.
        ControlStatusMessage statusMessage = new ControlStatusMessage(_currentControllerIp);
        string jsonMessage = JsonConvert.SerializeObject(statusMessage);
        byte[] data = Encoding.UTF8.GetBytes(jsonMessage);

        try
        {
            _udpListener.Send(data, data.Length, new IPEndPoint(IPAddress.Broadcast, clientListenPortForBroadcasts));
            Debug.Log($"Broadcasted control status: Controller is {_currentControllerIp ?? "NONE"} to port {clientListenPortForBroadcasts}");

            // TMP CHANGE: Set controller IP for UI update on main thread
            _uiControllerIpUpdate = _currentControllerIp;
            _uiNeedsUpdate = true;
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
        // TMP CHANGE: Process UI updates on the main thread
        if (_uiNeedsUpdate)
        {
            UpdateUIText();
            _uiNeedsUpdate = false; // Reset flag
        }

        if (_newDataToProcess)
        {
            if (targetObjectToMove != null)
            {
                targetObjectToMove.transform.position = _receivedPosition;
                targetObjectToMove.transform.eulerAngles = _receivedRotation;
            }
            _newDataToProcess = false; // Reset flag
        }
    }

    // TMP CHANGE: Method to update TextMeshPro UI elements
    private void UpdateUIText()
    {
        if (controllerStatusText != null)
        {
            // Use the main-thread-safe _uiControllerIpUpdate if available, otherwise use the locked _currentControllerIp
            string controllerDisplay = "Controller: " + (_uiControllerIpUpdate ?? _currentControllerIp ?? "NONE");
            controllerStatusText.text = controllerDisplay;
        }

        if (lastClientActivityText != null)
        {
            // UDP is connectionless, so "connected" is tricky.
            // We'll show the last client that sent any message.
            string activityDisplay = "Last Message From: " + (_uiLastSenderIpUpdate ?? "N/A");
            lastClientActivityText.text = activityDisplay;
        }
    }


    private void StopListening()
    {
        _isListening = false;

        if (_udpListener != null)
        {
            _udpListener.Close();
            _udpListener = null;
            Debug.Log("UDP Listener closed.");
        }

        if (_listenerThread != null && _listenerThread.IsAlive)
        {
            _listenerThread.Join(500);
            if (_listenerThread.IsAlive)
            {
                Debug.LogWarning("Listener thread did not terminate gracefully.");
            }
            _listenerThread = null;
        }
    }

    private void OnApplicationQuit()
    {
        bool hadController;
        lock (_lockObject)
        {
            hadController = !string.IsNullOrEmpty(_currentControllerIp);
            _currentControllerIp = null;
        }
        if (hadController)
        {
            Debug.Log("Server quitting. Broadcasting no controller status.");
            BroadcastControlStatus(); // Will broadcast with _currentControllerIp as null
        }

        StopListening();
        Debug.Log("UdpServerController resources cleaned up.");

        // TMP CHANGE: Clear UI on quit
        _uiControllerIpUpdate = null;
        _uiLastSenderIpUpdate = "Server shutting down...";
        UpdateUIText(); // Update one last time
    }

    private void OnDestroy()
    {
        StopListening();
        // TMP CHANGE: Optional: Clear UI if destroyed not during quit
        // if (Application.isPlaying) // Only if destroyed while game is running
        // {
        // _uiControllerIpUpdate = null;
        // _uiLastSenderIpUpdate = "Server stopped.";
        // UpdateUIText();
        // }
    }
}