using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using Newtonsoft.Json;
using System.Threading;
using System.Collections.Generic;
using System.IO; // For StreamReader/Writer
using System.Linq; // For client list management

using TMPro; // Assuming you still want TextMeshPro for server-side display

// --- Message Definitions ---
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
    [Header("Network Settings - TCP for Control")]
    public int serverTcpControlPort = 5007; // Port for TCP control messages

    [Header("Network Settings - UDP for Data")]
    public int serverUdpDataPort = 5005; // Port this server listens on for client data messages

    [Header("Network Settings - UDP Broadcast to Clients")]
    public int clientListenPortForUdpBroadcasts = 5006; // Port clients listen on for our status broadcasts

    [Header("Control State")]
    private string _currentControllerIp = null; // IP of the client with control
    private TcpClient _currentControllerTcpClient = null; // TCP client instance that has control
    private readonly object _controlLock = new object();

    [Header("Target Object (Optional)")]
    public GameObject targetObjectToMove;

    [Header("UI Display (Optional)")]
    public TextMeshProUGUI controllerStatusText;
    public TextMeshProUGUI connectedClientsText; // To show TCP connected clients

    private TcpListener _tcpListener;
    private Thread _tcpListenerThread;
    private volatile bool _isTcpListening = false;
    private List<ClientHandler> _connectedTcpClients = new List<ClientHandler>();
    private readonly object _tcpClientsLock = new object();

    private UdpClient _udpDataListener;
    private Thread _udpDataListenerThread;
    private volatile bool _isUdpListening = false;

    // For main thread processing of received data
    private volatile bool _newDataToProcess = false;
    private UnityEngine.Vector3 _receivedPosition;
    private UnityEngine.Vector3 _receivedRotation;

    // For UI updates from other threads
    private volatile bool _uiNeedsUpdate = false;
    private volatile string _lastActivityLog = "";


    void Start()
    {
        Application.runInBackground = true; // Keep server running even if window loses focus
        UpdateUIText(); // Initial UI

        // Start TCP Control Listener
        try
        {
            _tcpListener = new TcpListener(IPAddress.Any, serverTcpControlPort);
            _tcpListenerThread = new Thread(new ThreadStart(ListenForTcpConnections));
            _tcpListenerThread.IsBackground = true;
            _isTcpListening = true;
            _tcpListenerThread.Start();
            Debug.Log($"TCP Control Server started on port {serverTcpControlPort}");
            LogActivity($"TCP Control Server started on port {serverTcpControlPort}");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error starting TCP listener: {e.Message}");
            LogActivity($"Error starting TCP listener: {e.Message}");
            enabled = false;
            return;
        }

        // Start UDP Data Listener
        try
        {
            _udpDataListener = new UdpClient(serverUdpDataPort);
            _udpDataListenerThread = new Thread(new ThreadStart(ListenForUdpData));
            _udpDataListenerThread.IsBackground = true;
            _isUdpListening = true;
            _udpDataListenerThread.Start();
            Debug.Log($"UDP Data Listener started on port {serverUdpDataPort}");
            LogActivity($"UDP Data Listener started on port {serverUdpDataPort}");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error starting UDP data listener: {e.Message}");
            LogActivity($"Error starting UDP data listener: {e.Message}");
            enabled = false;
        }
    }

    void Update()
    {
        if (_uiNeedsUpdate)
        {
            UpdateUIText();
            _uiNeedsUpdate = false;
        }

        if (_newDataToProcess)
        {
            if (targetObjectToMove != null)
            {
                targetObjectToMove.transform.position = _receivedPosition;
                targetObjectToMove.transform.eulerAngles = _receivedRotation;
            }
            _newDataToProcess = false;
        }
    }

    private void LogActivity(string message)
    {
        _lastActivityLog = message;
        _uiNeedsUpdate = true;
    }

    private void ListenForTcpConnections()
    {
        _tcpListener.Start();
        while (_isTcpListening)
        {
            try
            {
                TcpClient client = _tcpListener.AcceptTcpClient(); // Blocks
                ClientHandler clientHandler = new ClientHandler(client, this);
                lock (_tcpClientsLock)
                {
                    _connectedTcpClients.Add(clientHandler);
                }
                Thread clientThread = new Thread(new ThreadStart(clientHandler.HandleClientComm));
                clientThread.IsBackground = true;
                clientThread.Start();
                LogActivity($"TCP Client connected: {((IPEndPoint)client.Client.RemoteEndPoint).Address}");
            }
            catch (SocketException ex)
            {
                if (_isTcpListening) Debug.LogWarning($"SocketException in TCP Listener (expected on close): {ex.Message}");
                else break; // Exit loop if not listening anymore
            }
            catch (System.Exception e)
            {
                if (_isTcpListening) Debug.LogError($"Error accepting TCP client: {e.Message}");
                break; // Exit on other critical errors
            }
        }
        _tcpListener.Stop();
        Debug.Log("TCP Listener thread finished.");
    }

    public void RemoveTcpClient(ClientHandler clientHandler)
    {
        lock (_tcpClientsLock)
        {
            _connectedTcpClients.Remove(clientHandler);
        }
        // If the disconnecting client had control, release it
        lock (_controlLock)
        {
            if (_currentControllerTcpClient == clientHandler.TcpClient)
            {
                Debug.Log($"Controller {clientHandler.ClientIp} (TCP) disconnected. Releasing control.");
                LogActivity($"Controller {clientHandler.ClientIp} disconnected. Releasing control.");
                _currentControllerIp = null;
                _currentControllerTcpClient = null;
                BroadcastControlStatus();
            }
        }
        LogActivity($"TCP Client disconnected: {clientHandler.ClientIp}");
    }

    // This method will be called by ClientHandler instances
    public void ProcessTcpMessage(BaseMessage message, ClientHandler sender)
    {
        lock (_controlLock)
        {
            string senderIp = sender.ClientIp;
            switch (message.type)
            {
                case "requestControl":
                    Debug.Log($"Control request received via TCP from {senderIp}. Current controller: {_currentControllerIp ?? "NONE"}");
                    LogActivity($"TCP Control Req from {senderIp}. Controller: {_currentControllerIp ?? "NONE"}");
                    if (string.IsNullOrEmpty(_currentControllerIp) || _currentControllerTcpClient == sender.TcpClient)
                    {
                        _currentControllerIp = senderIp;
                        _currentControllerTcpClient = sender.TcpClient;
                        Debug.Log($"Assigning/Confirming control (TCP) to {senderIp}.");
                        LogActivity($"Control granted to {senderIp} (TCP).");
                        BroadcastControlStatus(); // Inform all clients (UDP)
                    }
                    else
                    {
                        Debug.Log($"Control request from {senderIp} (TCP) denied. {_currentControllerIp} already has control.");
                        LogActivity($"Control Req from {senderIp} denied. {_currentControllerIp} in control.");
                        // Optionally send a "denied" message back via TCP to sender (not implemented here for brevity)
                        BroadcastControlStatus(); // Re-broadcast current status
                    }
                    break;

                case "releaseControl":
                    Debug.Log($"Release control request via TCP from {senderIp}. Current controller: {_currentControllerIp ?? "NONE"}");
                    LogActivity($"TCP Release Req from {senderIp}. Controller: {_currentControllerIp ?? "NONE"}");
                    if (_currentControllerTcpClient == sender.TcpClient)
                    {
                        Debug.Log($"Controller {senderIp} (TCP) released control.");
                        LogActivity($"Control released by {senderIp} (TCP).");
                        _currentControllerIp = null;
                        _currentControllerTcpClient = null;
                        BroadcastControlStatus();
                    }
                    else
                    {
                        Debug.LogWarning($"Release request (TCP) from {senderIp}, but current controller is {_currentControllerIp ?? "NONE"} or different client. Ignoring.");
                    }
                    break;
                default:
                    Debug.LogWarning($"Received unknown TCP message type '{message.type}' from {senderIp}.");
                    break;
            }
        }
        _uiNeedsUpdate = true; // For controller status text update
    }


    private void ListenForUdpData()
    {
        IPEndPoint remoteEndPoint = new IPEndPoint(IPAddress.Any, 0);
        while (_isUdpListening)
        {
            try
            {
                byte[] receivedBytes = _udpDataListener.Receive(ref remoteEndPoint); // Blocks
                string jsonMessage = Encoding.UTF8.GetString(receivedBytes);
                string senderIp = remoteEndPoint.Address.ToString();

                BaseMessage baseMsg = JsonConvert.DeserializeObject<BaseMessage>(jsonMessage);
                if (baseMsg == null || baseMsg.type != "data") continue;

                lock (_controlLock) // Check against current controller
                {
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
                            Debug.LogWarning($"Received malformed UDP data message from controller {senderIp}.");
                        }
                    }
                    // else: Data from non-controller, ignore silently
                }
            }
            catch (SocketException e)
            {
                if (_isUdpListening) Debug.LogWarning($"SocketException in UDP Data listener (expected on close): {e.Message}");
            }
            catch (JsonException e)
            {
                //Debug.LogError($"JsonException in UDP Data listener: {e.Message}. Raw: {Encoding.UTF8.GetString(receivedBytes)}"); // receivedBytes might be out of scope here if error is after new Receive
            }
            catch (System.Exception e)
            {
                if (_isUdpListening) Debug.LogError($"Error in UDP Data listener: {e.Message}");
            }
        }
        Debug.Log("UDP Data Listener thread finished.");
    }

    private void BroadcastControlStatus()
    {
        // This method might be called from different threads, _currentControllerIp is protected by _controlLock when set
        string controllerIpForBroadcast;
        lock(_controlLock) // Ensure reading consistent state
        {
            controllerIpForBroadcast = _currentControllerIp;
        }

        ControlStatusMessage statusMessage = new ControlStatusMessage(controllerIpForBroadcast);
        string jsonMessage = JsonConvert.SerializeObject(statusMessage);
        byte[] data = Encoding.UTF8.GetBytes(jsonMessage);

        try
        {
            // Use the _udpDataListener to send broadcasts. Ensure it's capable of sending.
            // Or, create a separate UdpClient for broadcasting if preferred.
            // For simplicity, re-using _udpDataListener. It needs to be able to send to broadcast address.
            // This requires the UdpClient not to be "connected" to a single endpoint if it's also used for general sending.
            // If _udpDataListener was new UdpClient(port), it's fine. If it was new UdpClient() then Connect(), it's an issue for broadcast.
            // Our _udpDataListener = new UdpClient(serverUdpDataPort) is fine.

            using (UdpClient broadcaster = new UdpClient()) // Temporary client for broadcast to avoid issues with listener
            {
                broadcaster.EnableBroadcast = true;
                IPEndPoint broadcastEp = new IPEndPoint(IPAddress.Broadcast, clientListenPortForUdpBroadcasts);
                broadcaster.Send(data, data.Length, broadcastEp);
                Debug.Log($"Broadcasted control status: Controller is {controllerIpForBroadcast ?? "NONE"} to port {clientListenPortForUdpBroadcasts}");
                LogActivity($"Broadcasted: Controller is {controllerIpForBroadcast ?? "NONE"}");
            }
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Error broadcasting control status: {e.Message}");
            LogActivity($"Error broadcasting: {e.Message}");
        }
        _uiNeedsUpdate = true;
    }

    private void UpdateUIText()
    {
        if (controllerStatusText != null)
        {
            lock (_controlLock)
            {
                controllerStatusText.text = $"Controller: {_currentControllerIp ?? "NONE"}";
            }
        }
        if (connectedClientsText != null)
        {
            int count;
            List<string> ips = new List<string>();
            lock (_tcpClientsLock)
            {
                count = _connectedTcpClients.Count;
                foreach(var ch in _connectedTcpClients)
                {
                    ips.Add(ch.ClientIp);
                }
            }
            connectedClientsText.text = $"TCP Clients ({count}): {string.Join(", ", ips)}\nLast: {_lastActivityLog}";
        }
    }

    private void StopListeners()
    {
        _isTcpListening = false;
        if (_tcpListener != null)
        {
            _tcpListener.Stop(); // This should cause AcceptTcpClient to throw an exception
            _tcpListener = null;
        }
        if (_tcpListenerThread != null && _tcpListenerThread.IsAlive)
        {
            _tcpListenerThread.Join(500);
        }

        lock (_tcpClientsLock)
        {
            foreach (var clientHandler in _connectedTcpClients.ToList()) // ToList to avoid modification issues
            {
                clientHandler.Stop();
            }
            _connectedTcpClients.Clear();
        }


        _isUdpListening = false;
        if (_udpDataListener != null)
        {
            _udpDataListener.Close();
            _udpDataListener = null;
        }
        if (_udpDataListenerThread != null && _udpDataListenerThread.IsAlive)
        {
            _udpDataListenerThread.Join(500);
        }
    }

    private void OnApplicationQuit()
    {
        Debug.Log("Server quitting...");
        LogActivity("Server shutting down...");
        lock (_controlLock)
        {
            _currentControllerIp = null; // Server is down, no one has control via it
            _currentControllerTcpClient = null;
        }
        BroadcastControlStatus(); // Broadcast one last time that no one has control
        StopListeners();
        Debug.Log("HybridCommServer resources cleaned up.");
    }

    private void OnDestroy()
    {
        StopListeners(); // Fallback
    }
}

// Helper class to handle individual TCP client communication
public class ClientHandler
{
    public TcpClient TcpClient { get; private set; }
    private UdpServerController _server;
    private NetworkStream _stream;
    private StreamReader _reader;
    private StreamWriter _writer;
    private volatile bool _isRunning = false;
    public string ClientIp {get; private set;}

    public ClientHandler(TcpClient client, UdpServerController server)
    {
        TcpClient = client;
        _server = server;
        _stream = client.GetStream();
        _reader = new StreamReader(_stream, Encoding.UTF8);
        _writer = new StreamWriter(_stream, Encoding.UTF8) { AutoFlush = true }; // AutoFlush for sending immediately
        ClientIp = ((IPEndPoint)client.Client.RemoteEndPoint).Address.ToString();
    }

    public void HandleClientComm()
    {
        _isRunning = true;
        Debug.Log($"Started handling TCP client: {ClientIp}");
        try
        {
            while (_isRunning && TcpClient.Connected)
            {
                string jsonMessage = _reader.ReadLine(); // Blocks until a line is received or connection breaks
                if (jsonMessage == null) // Client disconnected gracefully
                {
                    Debug.Log($"TCP Client {ClientIp} disconnected (ReadLine returned null).");
                    break;
                }

                // Debug.Log($"Received TCP from {ClientIp}: {jsonMessage}");
                try
                {
                    BaseMessage baseMsg = JsonConvert.DeserializeObject<BaseMessage>(jsonMessage);
                    if (baseMsg != null)
                    {
                        _server.ProcessTcpMessage(baseMsg, this);
                    }
                    else
                    {
                         Debug.LogWarning($"Failed to deserialize TCP message from {ClientIp}: {jsonMessage}");
                    }
                }
                catch (JsonException jsonEx)
                {
                    Debug.LogError($"JsonException deserializing TCP message from {ClientIp}: {jsonEx.Message}. Raw: {jsonMessage}");
                }
            }
        }
        catch (IOException ioEx)
        {
            // Often happens when client disconnects abruptly or network issue
            Debug.LogWarning($"IOException for TCP client {ClientIp} (likely disconnect): {ioEx.Message}");
        }
        catch (System.Exception e)
        {
            // Catch other exceptions to prevent thread from crashing server if possible
            Debug.LogError($"Error handling TCP client {ClientIp}: {e.Message}\n{e.StackTrace}");
        }
        finally
        {
            Stop();
            _server.RemoveTcpClient(this);
            Debug.Log($"Finished handling TCP client: {ClientIp}");
        }
    }

    // Call this to send a message to this specific client (not used in current design, server broadcasts via UDP)
    // public void SendMessage(BaseMessage message)
    // {
    //     if (TcpClient.Connected && _writer != null)
    //     {
    //         string json = JsonConvert.SerializeObject(message);
    //         _writer.WriteLine(json);
    //     }
    // }

    public void Stop()
    {
        _isRunning = false;
        if (_reader != null) _reader.Close(); // Close reader/writer before client
        if (_writer != null) _writer.Close();
        if (TcpClient != null) TcpClient.Close();
    }
}