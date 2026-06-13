# MeshCore / HermesNET 整合備忘錄

更新時間：2026-06-11 17:02:00 +08:00

## 目前結論

HermesNET 2.0 適合採用「Base + Repeater + Client」分層架構。

```text
使用者 / 住戶 / 公寓
        ↓
社區 Repeater
        ↓
避難所 / 區域 Repeater
        ↓
Base Gateway
        ↓
Raspberry Pi Hermes Core
```

MeshCore 可以作為 LoRa mesh transport，但 HermesNET 的服務層仍應該由 Hermes Core / MeshBBS / MeshBridge 負責。

## 角色分工

### Base / Gateway

Base 是區域核心站，不是普通 repeater。

建議組成：

```text
Raspberry Pi 4B / Pi 5 / mini PC
+ Heltec Tracker KISS modem
+ Hermes Core
+ SQLite / API / Dashboard
+ 後續 MeshBBS / MeshBridge
```

Base 負責：

- 收集 LoRa mesh 傳來的事件。
- 將 MeshCore packet 轉成 Hermes event。
- 儲存 `SAFE`、`SOS`、`NEED`、`STATUS` 等事件。
- 提供 Web Dashboard / API。
- 後續對接 MeshBBS、MeshBridge、跨區同步。

Base 不適合只靠小電池長期運作，應該有穩定電源。

### Repeater

Repeater 是外部中繼點。

建議韌體：

```text
MeshCore Repeater firmware
```

Repeater 負責：

- 延伸 LoRa mesh 覆蓋範圍。
- 放在屋頂、山頭、公寓、社區、避難所。
- 低功耗、簡單、少維護。

Repeater 不負責：

- 跑 Hermes Core。
- 存資料庫。
- 提供 Web UI。
- 當 BBS server。

### Client

Client 是使用者端或現場操作端。

可能形式：

```text
MeshCore Companion BLE
MeshCore Companion USB
未來 Hermes App / Hermes Client
```

Client 負責：

- 讓使用者送出訊息或狀態。
- 例如 `SAFE`、`SOS`、`NEED`、`STATUS`。
- 可搭配手機 App 或現場裝置。

MeshCore client 預設不負責 repeater 功能。

## 韌體選擇

### KISS modem

用途：

```text
Base Gateway Radio
```

適合：

- Raspberry Pi / Linux gateway。
- 自製後端。
- Hermes Core。
- 需要程式直接控制 radio 的場景。

優點：

- Hermes Core 可以直接收發 MeshCore packet。
- 可用 KISS SetHardware 查詢裝置狀態。
- 可查詢 battery、RSSI、noise floor、stats、identity。
- 適合做正式 Base gateway。

缺點：

- 較底層。
- 需要自行設定 radio 參數。
- 不像官方 Companion firmware 那樣可直接給官方 App / Web App 使用。

### Companion USB

用途：

```text
官方 MeshCore Web App / 電腦端 companion
```

適合：

- 使用 MeshCore 官方 web client。
- 一般使用者操作。
- 非 Hermes Core 自製 gateway。

不適合：

- 直接給 Hermes Core 用 KISS protocol 控制。

### Companion BLE

用途：

```text
手機端 client
```

適合：

- 手機 App 連線。
- 現場使用者發送訊息。
- 手持或個人節點。

### Repeater

用途：

```text
中繼站
```

適合：

- 固定中繼。
- 山頭、屋頂、社區、避難所。
- 太陽能 + 電池部署。

## 為什麼 Base 建議用 KISS modem

HermesNET 2.0 的 Base 需要的不只是聊天，而是服務核心：

- API
- SQLite / database
- Dashboard
- 事件分類
- Store & Forward
- MeshBBS / MeshBridge integration
- 跨區同步
- 權限與驗證

因此 Base 需要讓 Raspberry Pi 直接控制 radio。

KISS modem 的角色就是：

```text
把 Heltec Tracker 變成 LoRa modem
讓 Raspberry Pi 透過 USB serial 控制它
```

目前 Hermes Core 已經能做到：

- 開啟 `/dev/ttyACM0`
- 送出 KISS SetHardware command
- 收到 radio 回應
- 查詢裝置名稱、identity、battery、RSSI、noise floor、stats
- Dashboard 顯示 radio 狀態

## 目前已完成狀態

目前 Base 原型：

```text
Raspberry Pi 4B 4GB
hostname: HermesBASEv1
user: oldways
radio: Heltec Wireless Tracker V1
firmware: MeshCore KISS modem
serial: /dev/ttyACM0
service: hermes-core
dashboard: http://HermesBASEv1.local:8000
```

目前驗證成功：

- Pi 可偵測 Tracker。
- Hermes Core 可開啟 serial。
- Hermes Core API 正常。
- SQLite 可寫入事件。
- Dashboard 可顯示事件。
- KISS modem 可回應 `Probe Radio`。
- 已取得：
  - identity
  - device name
  - battery
  - MCU temperature
  - RSSI
  - noise floor
  - stats
  - signal report 狀態

## 目前還沒完成

- 尚未完成 LoRa over-the-air 測試。
- 尚未有第二顆 MeshCore 節點送資料到 Base。
- Radio config 剛加入，需部署後測試 `Set AS923`。
- 尚未將 MeshCore raw packet 正式轉成 Hermes event schema。
- 尚未接 MeshBBS。
- 尚未接 MeshBridge。
- 尚未實作 Store & Forward。
- 尚未實作跨 Base 同步。
- 尚未實作權限、白名單、簽章。

## Base 電源設計

Base 不是低功耗 repeater。

Base 建議供電：

```text
市電
+ UPS
+ 12V LiFePO4 / 車電備援
+ 5V 5A 或以上 DC-DC
```

最低測試配置：

```text
Pi 4B 官方 5V 3A 電源
+ Tracker 接 Pi USB
```

正式部署建議：

```text
12V battery / solar / vehicle power
        ↓
5V 5A or 5V 8A DC-DC
        ↓
Raspberry Pi + USB radio + WiFi/LTE equipment
```

Repeater 則應該走低功耗：

```text
Heltec / RAK / Tracker
+ battery
+ solar
```

## 建議拓樸

### 第一階段測試

```text
Client / second Tracker
        ↓ LoRa
Base Tracker KISS modem
        ↓ USB
Raspberry Pi Hermes Core
        ↓
Dashboard
```

### 第二階段社區部署

```text
住戶 Client
        ↓
公寓 Repeater
        ↓
社區 Repeater
        ↓
避難所 Repeater
        ↓
Base Gateway
        ↓
Hermes Core / MeshBBS / MeshBridge
```

### 第三階段跨區部署

```text
Base A
  ↕ LoRa / IP / LTE / MQTT
Base B
  ↕
Base C
```

跨區不應該傳大量自由聊天，而應該傳格式化狀態：

```text
NORMAL
DEGRADED
OFFLINE
POWER_LOW
SHELTER_OPEN
SOS_COUNT
SAFE_COUNT
FOOD_NEED
WATER_NEED
MEDICAL_NEED
```

## 下一步

### 1. 部署新版 Hermes Core

Windows PowerShell：

```powershell
scp "G:\geek_guys_oldways\hermesbase\src\hermes_core\app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

Pi SSH：

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

### 2. 設定 AS923 測試參數

Dashboard：

```text
http://HermesBASEv1.local:8000
```

按：

```text
Set AS923
Probe Radio
```

或用 API：

```powershell
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/config/as923"
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/probe"
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/radio"
```

### 3. 準備第二顆節點

至少需要第二顆 MeshCore 裝置才能測真正 LoRa 傳輸。

建議：

```text
第二顆 Tracker：Repeater 或 Companion BLE
Base Tracker：KISS modem
```

成功條件：

```text
第二顆節點送出訊息
        ↓
Base KISS modem 收到
        ↓
Hermes Core 寫入 SQLite
        ↓
Dashboard 顯示事件
```

## 判斷重點

目前不是 HermesNET 2.0 偏掉，而是正在建立 HermesNET 2.0 的 Base Gateway 原型。

已完成：

```text
Base service core
+ Gateway radio control path
```

下一個真正關鍵是：

```text
LoRa OTA event path
```

也就是讓第二顆 MeshCore 節點真的把事件送進 Hermes Core。
# 2026-06-11 補充：方案 B / Companion USB

## HermesCore 內建 MeshCore 管理頁

HermesCore 現在新增一個管理頁：
```text
http://HermesBASEv1.local:8000/meshcore
```

用途：
- 管理接在 Raspberry Pi 上的 Base Tracker。
- 查詢 Base Tracker 的 Companion USB 連線狀態。
- 查詢 Base Tracker 的 device/radio/channel 資訊。
- 寫入 HermesNET 測試 channel。
- 套用 AS923 radio profile。
- 發送 channel 測試訊息。

定位：
- `/` 是 HermesNET event dashboard。
- `/meshcore` 是 Base gateway radio 管理頁。
- `https://app.meshcore.nz` 仍適合用來管理一般 client Tracker。

這個頁面不是複製 MeshCore 官方 Web App，而是把 HermesNET 需要的 MeshCore 管理功能整合進 HermesCore。

目前 Hermes Core 已改成以 `companion_radio_usb` 作為 Base Tracker 的主要運作模式。

這個方案的重點是：
- Base Tracker 不再只是 KISS modem。
- Base Tracker 會以 MeshCore Companion 節點身分保存 channel 設定。
- Hermes Core 透過 USB serial companion protocol 寫入頻道、查詢裝置、輪詢訊息、送出 channel message。
- 第二顆 Tracker 只要加入同一個 MeshCore channel，就可以把訊息送到 Base，再由 Hermes Core 轉成 HermesNET event。

Base Tracker 必須刷：
```text
Heltec_Wireless_Tracker_companion_radio_usb-*.bin
```

不是：
```text
Heltec_Wireless_Tracker_kiss_modem
```

Hermes Core 目前使用的測試 channel：
```text
slot: 1
name: HermesNET-TW-TEST
secret: 已放在 PoC 設定中，正式部署前應移到 private config 或環境變數
```

部署後檢查順序：
```text
1. 重刷 Base Tracker 成 companion_radio_usb
2. 接回 Raspberry Pi
3. 重啟 hermes-core
4. 打開 http://HermesBASEv1.local:8000
5. 按 Probe Radio
6. 按 Join Channel
7. 第二顆 Tracker 加入同一 channel
8. 第二顆 Tracker 發 SAFE / SOS / NEED 測試
```
