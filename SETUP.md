# Setup

## Environment Variables

Create `SpeechToText/.env`:

```env
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=...
```

Only needed for `speech_control.py`. The CLI (`cli_control.py`) works with no keys.

---

## Network (Mac)

The Mac needs two simultaneous connections — robot WiFi for commands, internet (iPhone USB) for Azure.

1. **iPhone USB tethering** → Settings → Personal Hotspot → Allow Others to Join → plug into Mac
2. **Robot WiFi** → Connect to `Magnaforma-5G` (pw: `fuzzyowl457`)
   - System Settings → Network → WiFi → Details → TCP/IP
   - Set manually: IP `192.168.0.12`, Subnet `255.255.255.0`, Router **blank**
3. **Service order** → System Settings → Network → `...` → Set Service Order
   - iPhone USB on top, Wi-Fi second

Verify both work:
```bash
ping 192.168.0.1   # robot
ping 8.8.8.8       # internet
```

## Network (Windows)

Connect to `Magnaforma-5G`, set manual IP `192.168.0.12`, subnet `255.255.255.0`, gateway blank. Connect internet via Ethernet or second adapter. Windows routes automatically.

---

## Startup Order

1. Power on robot → set to **Automatic** mode on FlexPendant → load RAPID program → press Start
2. Open Unity → hit **Play**
3. Run Python (`cli_control.py` or `speech_control.py`)

> If the robot doesn't respond: restart in order — Controller first, then Unity, then Python.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ping 192.168.0.1` fails | Check WiFi is on Magnaforma-5G; Router field must be blank |
| `ping 8.8.8.8` fails | iPhone USB not connected or not in Personal Hotspot; check service order |
| Azure "Session stopped" immediately | No internet — verify iPhone USB; check `.env` keys |
| Unity not moving | Verify `tcp_commands.json` path in `TCPHotController.cs` matches Python output |
| Robot singularity (red light) | Switch to Manual on FlexPendant, jog out of singularity, return to Automatic |
| Movements wrong scale | `DISTANCE_SCALE = 0.1` in `speech_control.py` — 1 unit = 10 cm |
