# HermesCORE

HermesCORE 是 HermesNET 2.0 的 Raspberry Pi Base Gateway 層。

它負責透過 MeshCore 的 USB companion 模式連接 Base Tracker，將收到的事件寫入 SQLite，並提供本地瀏覽器介面給現場人員操作。

目前功能包含：

- HermesNET 事件儀表板
- MeshCore Gateway 管理介面
- Hermes BBS / MeshBBS 風格看板文章
- HermesX 302.1 data packet 實驗

## 目前運作環境

目標設備：

```text
Raspberry Pi 4B
Hostname: HermesBASEv1
Service: hermes-core
Port: 8000
Serial: /dev/ttyACM0
Baud: 115200
MeshCore firmware role: companion_radio_usb
```

本地網址：

```text
http://HermesBASEv1.local:8000
```

## 專案結構

```text
docs/         專案文件、changelog、整合計畫與技術備忘
pi_payloads/  部署到 Raspberry Pi 的 HermesCore FastAPI 應用程式
```

相關 upstream 專案：

```text
MeshCore    https://github.com/meshcore-dev/MeshCore
MeshBBS     https://github.com/JASON085/MeshBBS
MeshBridge  https://github.com/SCWhite/MeshBridge
HermesX     https://github.com/OLDWAYS069/HermesX
```

HermesCORE 目前只保存 Base Gateway 應用程式與專案文件；MeshCore firmware、MeshBBS、MeshBridge、HermesX 等來源專案請依需求從各自 upstream 取得。

## 部署到 Raspberry Pi

從 Windows PowerShell 執行：

```powershell
scp "G:\geek_guys_oldways\hermesbase\pi_payloads\hermes_core_app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

在 Raspberry Pi 上執行：

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

## 快速檢查

在 Raspberry Pi 上：

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/radio
```

從 Windows PowerShell：

```powershell
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/health"
```

## 目前設計重點

- BBS post 使用 HermesX protocol code：`HX302.1`
- BBS datagram 使用 data type：`0xFF01`
- 舊的 Noteboard 頁面目前保留為 prototype，但主要上層應用已收斂到 `/bbs`
- `SAFE`、`SOS`、`NEED`、`STATUS` 是 protocol-facing event code，即使 UI 中文化也會保留原代碼
