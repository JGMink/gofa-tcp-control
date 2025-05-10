using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

/* EGM */
using Abb.Egm;
using System.IO;
using System.Net;
using System.Net.Sockets;
using Google.Protobuf;
using System.ComponentModel;
using System;
using TMPro;
using System.Threading;
// using System.Diagnostics; // Removed this line

/*
* THIS SHIT WAS MADE BY ME .... MILES POPIELA
*/

// TODO: Automatic move to home upon initiating connection

namespace communication
{
    public class UDPCOMM : MonoBehaviour
    {
        /* UDP port where EGM communication should happen (specified in RobotStudio) */
        public static int port = 6511;
        /* UDP client used to send messages from computer to robot */
        private UdpClient server = null;
        /* Endpoint used to store the network address of the ABB robot.
         * Make sure your robot is available on your local network. The easiest option
         * is to connect your computer to the management port of the robot controller
         * using a network cable. */
        private IPEndPoint robotAddress;

        public string robotIpAddress = "192.168.0.4";

        /* Variable used to count the number of messages sent */
        private uint sequenceNumber = 0;
        public GameObject cube;
        /* Robot cartesian position and rotation values */
        double x, y, z, rx, ry, rz;
        double xc, yc, zc;
        double cz; //initialize variables above
        double cx;
        double cy;
        double crx;
        double cry;
        double crz;
        Vector3 angles;

        public GameObject joint1;
        public GameObject joint2;
        public GameObject joint3;
        public GameObject joint4;
        public GameObject joint5;
        public GameObject joint6;

        /* Current state of EGM communication (disconnected, connected or running) */
        string egmState = "Undefined";

        /* Flag to track if we've logged the initial position */
        private bool initialPositionLogged = false;

        // ********************************************************************
        // ADD THIS: Reference to the JointDataSender script
        // ********************************************************************
        public JointDataSender jointDataSender;
        // ********************************************************************

        /* (Unity) Start is called before the first frame update */
        void Start()
        {
            /* Initializes EGM connection with robot */
            startcom();

            // ********************************************************************
            // Optionally, find the JointDataSender if not assigned in Inspector
            // ********************************************************************
            if (jointDataSender == null)
            {
                jointDataSender = FindObjectOfType<JointDataSender>();
                if (jointDataSender == null)
                {
                    Debug.LogError("UDPCOMM: JointDataSender script not found in the scene!");
                }
            }
            // ********************************************************************
        }

        /* (Unity) Update is called once per frame */
        void Update()
        {
            cz = -cube.transform.position.z; //initialize variables above
            cx = cube.transform.position.x;
            cy = cube.transform.position.y;

            cubeMove(cx, cy, cz, (-cube.transform.eulerAngles.z - 180), cube.transform.eulerAngles.x, (-cube.transform.eulerAngles.y - 180));
        }

        public void startcom()
        {
            Debug.Log("Connecting to robot EGM...");

            try
            {
                server = new UdpClient(port);
                Debug.Log("SERVER CREATED for EGM on port " + port);
                robotAddress = new IPEndPoint(IPAddress.Parse(robotIpAddress), port); // Using the class-level 'port' here for receiving
                // For sending to robot, EGM typically uses the same port it receives on,
                // but the robotAddress IPEndPoint is for who it's *receiving from* initially,
                // and who it will *send to*.

                // Start listening for messages from the robot (you'll likely want this in a separate thread or async)
                // For simplicity in this example, UpdateValues will be called, which blocks.
                // Consider using server.BeginReceive and EndReceive for non-blocking.
                UpdateValues(); // Initial call to get the ball rolling.
                                // In a real scenario, you'd continuously listen. This is simplified from your original.
                                // Your original `UpdateValues` and `UpdateJointsValues` methods are blocking calls.
                                // This means `cubeMove` will call `UpdateJointsValues` which blocks until a message is received.
            }
            catch (SocketException e)
            {
                Debug.LogError($"SocketException during EGM server creation: {e.ToString()}");
            }
            catch (System.Exception e)
            {
                Debug.LogError($"Error in startcom: {e.ToString()}");
            }
        }

        // This method seems to be for getting cartesian feedback.
        private void UpdateValues()
        {
            if (server == null) return;

            byte[] bytes = null;
            try
            {
                Debug.Log("UpdateValues: Waiting for EGM message from robot...");
                bytes = server.Receive(ref robotAddress); // This is a blocking call
                //Debug.Log("Connected (received message for cartesian update)"); // More accurate log
            }
            catch (SocketException e)
            {
                Debug.LogWarning($"UpdateValues: SocketException: {e.Message}. Robot might not be sending EGM data or network issue.");
                return; // Exit if error
            }
            catch (System.Exception e)
            {
                Debug.LogError($"UpdateValues: General Exception: {e.Message}");
                return; // Exit if error
            }

            if (bytes != null && bytes.Length > 0)
            {
                EgmRobot message = EgmRobot.Parser.ParseFrom(bytes);
                ParseCurrentPositionFromMessage(message);
            }
            else
            {
                Debug.Log("UpdateValues: No bytes received.");
            }
        }

        // This method is called within cubeMove, meaning it's called every frame Update.
        private void UpdateJointsValues()
        {
            if (server == null)
            {
                Debug.LogWarning("UpdateJointsValues: EGM server is null. Cannot receive joint values.");
                return;
            }

            byte[] bytes = null;
            try
            {
                // Debug.Log("UpdateJointsValues: Waiting for EGM message from robot..."); // Can be spammy
                bytes = server.Receive(ref robotAddress); // This is a blocking call
                // Debug.Log("Connected (received message for joint update)"); // More accurate log
            }
            catch (SocketException e)
            {
                // This can happen frequently if EGM session stops or there are network issues.
                // Log less aggressively or handle state.
                // Debug.LogWarning($"UpdateJointsValues: SocketException: {e.Message}. Robot might not be sending EGM data or network issue.");
                return; // Exit if error
            }
            catch (System.Exception e)
            {
                Debug.LogError($"UpdateJointsValues: General Exception: {e.Message}");
                return; // Exit if error
            }


            if (bytes != null && bytes.Length > 0)
            {
                EgmRobot message = EgmRobot.Parser.ParseFrom(bytes);
                ParseCurrentJointsPositionFromMessage(message); // This will now also send data
            }
            else
            {
                // Debug.Log("UpdateJointsValues: No bytes received."); // Can be spammy
            }
        }

        private void ParseCurrentJointsPositionFromMessage(EgmRobot message)
        {
            if (message == null || message.FeedBack == null)
            {
                // Debug.LogWarning("ParseCurrentJointsPositionFromMessage: Invalid or incomplete joint data in EGM message.");
                return;
            }

            // Update local GameObjects (your existing logic)
            joint1.transform.localEulerAngles = new Vector3(0, 0, -(float)message.FeedBack.Joints.Joints[0]);
            joint2.transform.localEulerAngles = new Vector3(0, -(float)message.FeedBack.Joints.Joints[1], 0);
            joint3.transform.localEulerAngles = new Vector3(0, -(float)message.FeedBack.Joints.Joints[2], 0);
            joint4.transform.localEulerAngles = new Vector3(-(float)message.FeedBack.Joints.Joints[3], 0, 0);
            joint5.transform.localEulerAngles = new Vector3(0, -(float)message.FeedBack.Joints.Joints[4], 0);
            joint6.transform.localEulerAngles = new Vector3(-(float)message.FeedBack.Joints.Joints[5], 0, 0);

            // ********************************************************************
            // SEND JOINT DATA TO THE OTHER DEVICE
            // ********************************************************************
            if (jointDataSender != null)
            {
                float[] currentJointAngles = new float[6];
                for (int i = 0; i < 6; i++)
                {
                    currentJointAngles[i] = (float)message.FeedBack.Joints.Joints[i];
                }
                jointDataSender.SendJointAngles(currentJointAngles);
            }
            else
            {
                // Debug.LogWarning("UDPCOMM: JointDataSender reference not set. Cannot send joint data."); // Can be spammy
            }
            // ********************************************************************
        }

        private void ParseCurrentPositionFromMessage(EgmRobot message)
        {
            if (message == null) return;

            if (message.Header != null && message.Header.HasSeqno && message.Header.HasTm)
            {
                if (message.FeedBack != null)
                {
                    x = message.FeedBack.Cartesian.Pos.X;
                    y = message.FeedBack.Cartesian.Pos.Y;
                    z = message.FeedBack.Cartesian.Pos.Z;
                    xc = x; // Why are these duplicated? xc,yc,zc seem to be assigned then immediately overwritten by cubeMove
                    yc = y;
                    zc = z;
                    rx = message.FeedBack.Cartesian.Euler.X;
                    ry = message.FeedBack.Cartesian.Euler.Y;
                    rz = message.FeedBack.Cartesian.Euler.Z;

                    // Update cube position based on robot feedback
                    cube.transform.position = new Vector3((float)y / 1000, (float)z / 1000, (float)-x / 1000);
                    // Note: Robot rotation (rx,ry,rz) is read but not applied to the cube's rotation here.
                    // The cube's rotation is set in Update() based on its own eulerAngles.

                    if (!initialPositionLogged)
                    {
                        initialPositionLogged = true;
                        Debug.Log("Initial robot cartesian position - X:" + x + ", Y:" + y + ", Z:" + z +
                                  ", RX:" + rx + ", RY:" + ry + ", RZ:" + rz);
                    }
                }
            }
            else
            {
                Debug.LogWarning("The EGM message received from robot has an invalid header.");
            }
        }

        private void SendPoseMessageToRobot(double zx, double zy, double zz, double zrx, double zry, double zrz)
        {
            if (server == null || robotAddress == null) // Ensure robotAddress is not null
            {
                Debug.LogWarning("SendPoseMessageToRobot: EGM server or robotAddress not initialized.");
                return;
            }

            using (MemoryStream memoryStream = new MemoryStream())
            {
                EgmSensor sensorMessage = new EgmSensor(); // Renamed to avoid conflict with 'message' variable if used in same scope
                CreatePoseMessage(sensorMessage, zx, zy, zz, zrx, zry, zrz);

                sensorMessage.WriteTo(memoryStream);

                try
                {
                    int bytesSent = server.Send(memoryStream.ToArray(), (int)memoryStream.Length, robotAddress);
                    if (bytesSent <= 0) // Check for non-positive return value
                    {
                        Debug.LogWarning("No message or an error occurred while sending pose to robot.");
                    }
                }
                catch (SocketException e)
                {
                    Debug.LogError($"SendPoseMessageToRobot: SocketException: {e.Message}");
                }
                catch (System.Exception e)
                {
                    Debug.LogError($"SendPoseMessageToRobot: General Exception: {e.Message}");
                }
            }
        }

        private void CreatePoseMessage(EgmSensor sensorMessage, double zx, double zy, double zz, double zrx, double zry, double zrz)
        {
            EgmHeader hdr = new EgmHeader();
            hdr.Seqno = sequenceNumber++;
            hdr.Tm = (uint)DateTime.Now.Ticks; // Using DateTime.Now.Ticks is fine, but it's a large number. System time.
                                               // Some EGM examples use a continuously incrementing timestamp or a robot provided one.
            hdr.Mtype = EgmHeader.Types.MessageType.MsgtypeCorrection;

            sensorMessage.Header = hdr;

            EgmPlanned planned_trajectory = new EgmPlanned();
            EgmPose cartesian_pos = new EgmPose();
            EgmCartesian tcp_p = new EgmCartesian();
            EgmEuler ea_p = new EgmEuler();

            tcp_p.X = zx;
            tcp_p.Y = zy;
            tcp_p.Z = zz;

            ea_p.X = zrx;
            ea_p.Y = zry;
            ea_p.Z = zrz;

            cartesian_pos.Pos = tcp_p;
            cartesian_pos.Euler = ea_p;

            planned_trajectory.Cartesian = cartesian_pos;
            sensorMessage.Planned = planned_trajectory;
        }

        public void cubeMove(double xx, double yy, double zz, double rrx, double rry, double rrz)
        {
            // Mapping cube coordinates/rotations to robot coordinates/rotations
            // These seem to be your specific coordinate system transformations
            y = (xx * 1000);  // Unity X maps to Robot Y
            x = (zz * 1000);  // Unity Z (negated in Update) maps to Robot X
            z = (yy * 1000);  // Unity Y maps to Robot Z

            rx = rrx;
            ry = rry;
            rz = rrz;

            SendPoseMessageToRobot(x, y, z, rx, ry, rz);
            UpdateJointsValues(); // This will block until a message is received, then parse and send joint data
        }

        void OnApplicationQuit() // Or OnDestroy
        {
            if (server != null)
            {
                server.Close();
                server = null;
                Debug.Log("UDPCOMM: EGM server UdpClient closed.");
            }
        }
    }
}