# HermesCORE

HermesCORE is the Raspberry Pi gateway layer for HermesNET 2.0.

It connects a MeshCore Base Tracker over USB companion mode, stores received events in SQLite, and exposes a local web UI for:

- HermesNET event dashboard
- MeshCore gateway management
- Hermes BBS / MeshBBS-style board posts
- HermesX 302.1 data packet experiments

## Current Runtime

Target device:

```text
Raspberry Pi 4B
Hostname: HermesBASEv1
Service: hermes-core
Port: 8000
Serial: /dev/ttyACM0
Baud: 115200
MeshCore firmware role: companion_radio_usb
```

Local URL:

```text
http://HermesBASEv1.local:8000
```

## Repository Layout

```text
docs/         Project notes, changelog, integration plans
pi_payloads/  HermesCore FastAPI application deployed to the Raspberry Pi
```

The workspace also references these upstream projects during development:

```text
MeshCore    https://github.com/meshcore-dev/MeshCore
MeshBBS     https://github.com/JASON085/MeshBBS
MeshBridge  https://github.com/SCWhite/MeshBridge
HermesX     https://github.com/OLDWAYS069/HermesX
```

Those upstream repos are intentionally not vendored into this repository. Keep local clones beside this project when development needs firmware or upstream reference code.

## Deploy To Raspberry Pi

From Windows PowerShell:

```powershell
scp "G:\geek_guys_oldways\hermesbase\pi_payloads\hermes_core_app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

On the Raspberry Pi:

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

## Quick Checks

On the Raspberry Pi:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/radio
```

From Windows PowerShell:

```powershell
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/health"
```

## Notes

- BBS posts use HermesX protocol code `HX302.1`.
- BBS datagrams use data type `0xFF01`.
- The old Noteboard page is kept as a prototype but the main upper-layer app is `/bbs`.
- `SAFE`, `SOS`, `NEED`, and `STATUS` are intentionally kept as protocol-facing event codes even when the UI is localized.
