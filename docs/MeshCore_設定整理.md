# MeshCore 設定整理

更新時間：2026-06-11 17:15:00 +08:00

## 這份文件在講什麼

這份文件整理 HermesNET 2.0 目前使用 MeshCore 時，需要知道與設定的項目。

目前架構分三種角色：

```text
Base Gateway：Raspberry Pi + KISS modem Tracker
Repeater：外部中繼節點
Client：手機 / 現場使用者節點
```

三種角色要設定的東西不一樣。

## 重要結論

MeshCore 要互通，至少要確保這些 radio 設定一致：

```text
frequency
bandwidth
spreading factor
coding rate
```

也就是：

```text
freq / bw / sf / cr
```

MeshCore 官方 CLI 的 radio 設定格式是：

```text
set radio <freq>,<bw>,<sf>,<cr>
```

官方文件說明：

```text
freq：MHz
bw：kHz
sf：5-12
cr：5-8
```

KISS modem protocol 則使用底層格式：

```text
freq_hz：Hz
bw_hz：Hz
sf：5-12
cr：5-8
```

所以同一組設定在兩邊會長這樣：

```text
MeshCore CLI:
set radio 923.2,125,9,5

Hermes Core KISS API:
freq_hz = 923200000
bw_hz   = 125000
sf      = 9
cr      = 5
```

## 目前建議的測試設定

先用以下設定作為 HermesNET 台灣測試 profile：

```text
Profile name：AS923-TW-TEST
Frequency：923.2 MHz
Bandwidth：125 kHz
Spreading Factor：SF9
Coding Rate：CR 4/5
TX Power：14 dBm
```

Hermes Core 內的對應值：

```json
{
  "freq_hz": 923200000,
  "bw_hz": 125000,
  "sf": 9,
  "cr": 5,
  "tx_power": 14
}
```

### 為什麼先用 923.2 MHz

AS923 / LoRaWAN 常見資料中，`923.2 MHz` 與 `923.4 MHz` 是常見共通頻點。

這不代表 HermesNET 必須永遠固定在 923.2 MHz，而是先用它作為測試起點，方便跟 AS923 常見設定對齊。

正式部署前仍需要確認：

- 台灣 NCC 相關規範。
- 實際天線增益。
- EIRP 是否超標。
- duty cycle / airtime 使用量。
- 現場是否有既有 MeshCore 社群頻點。

## Base Gateway 設定

Base Gateway 目前是：

```text
Raspberry Pi 4B
+ Heltec Wireless Tracker V1
+ MeshCore KISS modem firmware
+ Hermes Core
```

Base 需要設定：

```text
radio profile
tx power
device identity
Hermes Core API / dashboard
systemd service
```

目前 Hermes Core 已經支援：

```text
Probe Radio
Set AS923
```

Dashboard 操作：

```text
http://HermesBASEv1.local:8000
```

按：

```text
Set AS923
Probe Radio
```

API 操作：

```powershell
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/config/as923"
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/probe"
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/radio"
```

設定成功後，`/api/radio` 應該看到類似：

```json
{
  "radio": {
    "radio": {
      "freq_hz": 923200000,
      "bw_hz": 125000,
      "sf": 9,
      "cr": 5
    },
    "tx_power_dbm": 14
  }
}
```

## Repeater 設定

Repeater 是外部中繼點。

建議韌體：

```text
MeshCore Repeater firmware
```

Repeater 需要設定：

```text
frequency
bandwidth
spreading factor
coding rate
tx power
node name
location
region / scope
admin password / ACL
```

### Radio 設定

官方 CLI：

```text
get radio
set radio 923.2,125,9,5
```

注意：官方 CLI 文件說 `set radio` 需要 reboot 後生效。

也可以單獨設定 frequency：

```text
get freq
set freq 923.2
```

官方 FAQ 也提到 repeater 刷完後，應該透過 USB serial console 設定所在地區/國家的頻率。

### TX Power

官方 CLI：

```text
get tx
set tx 14
```

MeshCore 官方文件提醒：這個值只控制 LoRa 晶片輸出功率。有些硬體有額外 PA，總輸出可能更高，設定太高可能違反當地法規。

### Repeater region / scope

MeshCore 有 region management。

常見指令：

```text
region
region put <name> [parent_name]
region home <name>
region default <name>
region allowf <name>
region denyf <name>
region save
```

HermesNET 建議先不要做太複雜。

第一版可以先用簡單命名：

```text
tw
tw-hualien
tw-hualien-city
```

範例：

```text
region put tw
region put tw-hualien tw
region home tw-hualien
region default tw-hualien
region save
```

正式跨區前，再設計完整 region tree。

## Client 設定

Client 是使用者端。

建議韌體：

```text
Companion BLE
```

用途：

- 手機連線。
- 現場人員發送訊息。
- 測試 `SAFE`、`SOS`、`NEED`、`STATUS`。

Client 需要跟 Base / Repeater 使用相同 radio settings：

```text
923.2 MHz
125 kHz
SF9
CR 4/5
```

如果 client 和 repeater / base 的 radio setting 不一致，就算距離很近也不會互通。

## HermesNET 建議 profile

目前先定義一個測試 profile：

```text
Name：HERMES-TW-AS923-TEST
Frequency：923.2 MHz
Bandwidth：125 kHz
SF：9
CR：5
TX Power：14 dBm
用途：短距離 / 社區測試
```

後續可以再定義：

```text
HERMES-TW-AS923-LONG
Frequency：923.2 MHz
Bandwidth：125 kHz
SF：11 或 12
CR：5 或 8
TX Power：依合法值調整
用途：跨區 / 山頭 / 長距離測試
```

但注意：

```text
SF 越高，距離可能越遠，但 airtime 越長，容量越低。
```

HermesNET 的原則應該是：

```text
不要把 LoRa 當聊天室
只送格式化事件與必要狀態
```

## 目前 Hermes Core 已支援的設定能力

目前程式已加入：

```text
POST /api/radio/config
POST /api/radio/config/as923
GET  /api/radio
POST /api/radio/probe
```

也就是 Hermes Core 可以：

- 查 radio 狀態。
- 查 battery / RSSI / noise floor。
- 設定 radio profile。
- 設定 TX power。

## 還需要補的設定能力

### 1. 持久化設定

目前 KISS `SetRadio` 是否會永久保存，需要再實測。

如果重開 Tracker 後設定歸零，就需要：

- Hermes Core 開機後自動送一次 radio config。
- 或改 firmware build flag 預設值。

### 2. 多 profile

目前只有：

```text
AS923-TW-TEST
```

後續應加入：

```text
AS923-TW-LONG
AS923-TW-LOCAL
AS923-TW-BASE
```

### 3. Repeater CLI 管理

KISS modem 不等於 repeater console。

Repeater 設定仍要透過：

- MeshCore Web Flasher console
- USB serial CLI
- 官方 App / 管理工具
- 或未來 Hermes Core 增加 repeater admin flow

### 4. Region 設計

HermesNET 應該要設計自己的 region tree。

暫定方向：

```text
tw
tw-north
tw-central
tw-south
tw-east
tw-hualien
tw-taitung
```

第一版不要過度複雜，先以實際測試區域為主。

## 設定檢查表

### Base KISS modem

- [ ] 刷 KISS modem firmware
- [ ] Pi 偵測到 `/dev/ttyACM0`
- [ ] Hermes Core `Probe Radio` 有回應
- [ ] `Set AS923` 後 `Radio` 顯示 `923200000 Hz SF9`
- [ ] `tx_power_dbm` 顯示 `14`

### Repeater

- [ ] 刷 Repeater firmware
- [ ] 設定 `set radio 923.2,125,9,5`
- [ ] 設定 `set tx 14`
- [ ] 設定 name
- [ ] 設定 region
- [ ] 設定位置
- [ ] 重開機後確認設定仍存在

### Client

- [ ] 刷 Companion BLE 或 USB
- [ ] 設定同一組 radio profile
- [ ] 可送訊息到 repeater / base
- [ ] 測試 `SAFE` / `SOS` / `STATUS`

## 參考資料

- MeshCore FAQ：說明 repeater、companion、frequency 設定與 USB serial console。
  - https://docs.meshcore.io/faq/
- MeshCore CLI Commands：`set radio`、`set tx`、region management。
  - https://docs.meshcore.io/cli_commands/
- MeshCore KISS Modem Protocol：KISS SetHardware、SetRadio / Radio response 格式。
  - https://docs.meshcore.io/kiss_modem_protocol/
- The Things Network Frequency Plans：AS923 常見頻點包含 `923.2 MHz`、`923.4 MHz`。
  - https://www.thethingsnetwork.org/docs/lorawan/frequency-plans/
- LoRaWAN Regional Parameters：AS923 / Taiwan 相關頻段參考。
  - https://lora-alliance.org/resource_hub/lorawan-regional-parameters/
