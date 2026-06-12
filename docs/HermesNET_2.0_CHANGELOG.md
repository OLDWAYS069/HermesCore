# HermesNET 2.0 進度紀錄

## 2026-06-12 01:05:00 +08:00

### 已完成
- 將 HermesCore 主要 Web UI 中文化。
- 中文化範圍：
  - `/` HermesNET 儀表板
  - `/meshcore` MeshCore 管理頁
  - `/bbs` Hermes BBS
  - `/noteboard` 舊原型頁
- 保留系統代碼與通訊代碼原樣：
  - `SAFE`
  - `SOS`
  - `NEED`
  - `STATUS`
  - event type
  - API 欄位
  - HermesX / MeshCore protocol 內部名稱
- BBS 預設看板名稱改為中文：
  - 一般
  - 資源
  - 避難

### 驗證
```bash
python -m py_compile pi_payloads/hermes_core_app.py
```

## 2026-06-12 00:50:00 +08:00

### 已完成
- 收斂 MeshBBS / MeshBridge 的應用定位。
- 決定正式保留 `/bbs` 作為 HermesNET 上層訊息應用。
- 不再把 `/noteboard` 當成獨立正式產品，只保留為早期原型與相容 API。
- 將 Noteboard / MeshBridge 的關鍵欄位併入 BBS：
  - `kind`：文章類型，例如 post、notice、resource、shelter、request、status。
  - `priority`：優先級，例如 normal、high、urgent。
  - `location`：位置描述，例如社區、樓棟、避難所、座標或現場文字描述。
- 更新 `/bbs` UI：
  - 新增 Type / Priority / Location 欄位。
  - 文章列表顯示 type、priority、location。
  - 保留 board / title / body / author 的 MeshBBS 看板概念。
- 更新 BBS SQLite schema：
  - `bbs_posts.kind`
  - `bbs_posts.priority`
  - `bbs_posts.location`
- 更新 BBS HermesX data packet：
  - `data_type = 0xFF01`
  - `protocol = HX302.1`
  - payload 新增 `k`、`r`、`l` 欄位，分別代表 kind、priority、location。
- 從主要導覽移除 Noteboard 入口，避免後續操作混淆。
- 重寫 `docs/HermesCore_網站運作說明.md`，使文件符合目前「BBS 為主、Noteboard 概念併入」的架構。

### 架構決策
- MeshBBS 與 MeshBridge 的上層用途有重疊。
- MeshBBS 的 board/post 比較適合長期保留為主資料模型。
- MeshBridge / Noteboard 的 priority/location/kind 比較適合作為 BBS post 的 metadata。
- 因此不再維護兩套平行 UI，而是把 Noteboard 元素吸收到 BBS。

### 驗證
```bash
python -m py_compile pi_payloads/hermes_core_app.py
```

### 下一步
- 將新版 `pi_payloads/hermes_core_app.py` 部署到 Raspberry Pi。
- 在 `/bbs` 測試新增不同 kind / priority / location 的文章。
- 用第二顆 Tracker 驗證 BBS data packet 是否能跨 MeshCore channel 還原成 BBS post。

## 2026-06-11 17:51:25 +08:00

### 已完成

- Hermes Core 新增 radio profile 持久化設定。
- 新增本地設定檔：
  - `hermes_config.json`
- 預設 radio profile：
  - 名稱：`AS923-TW-TEST`
  - Frequency：`923200000`
  - Bandwidth：`125000`
  - Spreading Factor：`9`
  - Coding Rate：`5`
  - TX Power：`14 dBm`
- `hermes-core` 每次開啟 serial 後會自動套用目前 radio profile。
- 自動套用後會自動查詢：
  - Ping
  - Device name
  - Version
  - Radio config
  - TX power
  - RSSI
  - Noise floor
  - Stats
  - Battery
  - MCU temperature
  - Signal report
- Dashboard 新增顯示：
  - 目前 profile 名稱
  - 最後自動套用時間

### 原因

- KISS modem 的 `SetRadio` 在目前測試中不會跨重開機保存。
- 因此改由 Base 上的 Hermes Core 保存設定，並在服務啟動或 serial 重新連線時自動套用。

### 下一步部署指令

Windows PowerShell：

```powershell
scp "G:\geek_guys_oldways\hermesbase\pi_payloads\hermes_core_app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

SSH 進 Raspberry Pi 後：

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

部署後測試：

```bash
curl http://localhost:8000/api/radio
sudo reboot
```

重開後再確認：

```powershell
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/radio"
```

成功條件：

```text
Radio 顯示 923200000 Hz SF9
Profile 顯示 AS923-TW-TEST
Applied 有時間
```

## 2026-06-11 16:49:18 +08:00

### 已完成

- Hermes Core 新增 MeshCore KISS modem 的 radio config API。
- 新增 API：
  - `POST /api/radio/config`
  - `POST /api/radio/config/as923`
- 新增 `SetRadio` 支援：
  - `freq_hz`
  - `bw_hz`
  - `sf`
  - `cr`
- 新增 `SetTxPower` 支援：
  - `tx_power`
- Dashboard 新增 `Set AS923` 按鈕。
- `Set AS923` 目前設定為測試 profile：
  - Frequency：`923200000`
  - Bandwidth：`125000`
  - Spreading Factor：`9`
  - Coding Rate：`5`
  - TX Power：`14 dBm`
- 本機 payload 已通過 Python syntax check。

### 說明

- MeshCore KISS modem 是較底層的 gateway 模式。
- 優點是 Raspberry Pi / Hermes Core 可以直接控制 radio。
- 代價是需要自行初始化 radio 參數，不能像 Companion firmware 一樣完全交給官方 App/Web App 管理。

### 下一步部署指令

Windows PowerShell：

```powershell
scp "G:\geek_guys_oldways\hermesbase\pi_payloads\hermes_core_app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

SSH 進 Raspberry Pi 後：

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

部署後測試：

```powershell
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/config/as923"
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/probe"
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/radio"
```

## 2026-06-11 16:12:32 +08:00

### 已完成

- Hermes Core 新增 MeshCore KISS SetHardware 查詢能力。
- 新增 KISS frame 送出功能：
  - 支援 KISS escape / unescape。
  - 支援將 SetHardware command 排入送出佇列。
  - 支援統計 TX / RX frame 數量。
- 新增 MeshCore radio response parser：
  - `Ping / Pong`
  - `GetDeviceName`
  - `GetVersion`
  - `GetIdentity`
  - `GetRadio`
  - `GetTxPower`
  - `GetCurrentRssi`
  - `GetNoiseFloor`
  - `GetStats`
  - `GetBattery`
  - `GetMCUTemp`
  - `GetSignalReport`
  - `TxDone`
  - `RxMeta`
  - `Error`
- 新增 Radio API：
  - `GET /api/radio`
  - `POST /api/radio/probe`
  - `POST /api/radio/query`
- Dashboard 新增 Radio 狀態區：
  - 顯示裝置名稱、版本、電池、溫度。
  - 顯示 serial 連線狀態、RSSI、noise floor、radio config。
  - 顯示 KISS frames RX / TX、stats、last pong。
  - 新增 `Probe Radio` 按鈕，可從 Dashboard 主動查詢 USB radio。

### 目前狀態

- 本機 payload 已完成並通過 Python syntax check。
- 尚未部署到 Raspberry Pi，因為 `scp` 需要互動式輸入 Pi 密碼。
- 下一步需由 Windows PowerShell 執行 `scp` 將新版 `app.py` 傳到 Pi，再重啟 `hermes-core`。

### 下一步部署指令

Windows PowerShell：

```powershell
scp "G:\geek_guys_oldways\hermesbase\pi_payloads\hermes_core_app.py" oldways@HermesBASEv1.local:~/HermesCore/app.py
```

SSH 進 Raspberry Pi 後：

```bash
cd ~/HermesCore
python -m py_compile app.py
sudo systemctl restart hermes-core
sudo systemctl status hermes-core --no-pager
```

部署後測試：

```powershell
Invoke-RestMethod "http://HermesBASEv1.local:8000/api/radio"
Invoke-RestMethod -Method Post "http://HermesBASEv1.local:8000/api/radio/probe"
```

## 2026-06-11 15:47:53 +08:00

### 已完成

- 確認第一台 Raspberry Pi Gateway 目標設備：
  - 裝置：Raspberry Pi 4B 4GB
  - 主機名稱：`HermesBASEv1`
  - 使用者：`oldways`
- 已將 MeshCore 韌體刷入 Heltec Wireless Tracker V1，作為 Gateway 用無線電模組。
- 已確認 Raspberry Pi 可以偵測到 MeshCore USB Companion Radio：
  - 裝置路徑：`/dev/ttyACM0`
  - Baud rate：`115200`
- 已在 Raspberry Pi 上建立第一版 Hermes Core MVP：
  - FastAPI 服務
  - SQLite 事件資料庫
  - MeshCore serial reader 雛形
  - KISS frame 捕捉路徑
  - 手動事件寫入 API
- 已加入 API 端點：
  - `GET /api/health`
  - `GET /api/events`
  - `POST /api/events`
  - `GET /api/summary`
- 已從 Windows 端驗證 API 運作：
  - Health check 正常回應。
  - 可手動寫入 `SAFE` 事件。
  - 可查詢事件列表。
  - 可查詢事件統計。
- 已將 Hermes Core 設定為 `systemd` 常駐服務：
  - 服務名稱：`hermes-core`
  - 已確認服務可啟動並監聽 `8000` port。
- 已加入簡易 Web Dashboard：
  - 網址：`http://HermesBASEv1.local:8000`
  - 可顯示事件統計與最近事件。
  - 可手動新增測試事件：`SAFE`、`SOS`、`NEED`、`STATUS`。

### 與 HermesNET 2.0 架構的對應

- 本次完成的是 HermesNET 2.0 的第一個服務核心 MVP。
- 目前對應到原計畫架構的位置：
  - Physical Layer：Heltec Tracker + MeshCore USB Companion Radio 已接上 Raspberry Pi。
  - Routing Layer：已能開啟 MeshCore serial interface，但尚未完整解析 MeshCore 封包。
  - Service Layer：Hermes Core API、SQLite 儲存、事件統計、Dashboard 已可運作。
  - Application Layer：目前只有開發測試用 Dashboard，尚不是正式 Hermes Web Portal。

### 目前缺口

- 尚未完整解析 MeshCore KISS payload 成正式 Hermes Event。
- 尚未完成第二顆 MeshCore 節點透過 LoRa 傳事件到 Raspberry Pi 的實測。
- Event schema 仍是暫定格式。
- MeshBBS 尚未接入 Hermes Core。
- MeshBridge 尚未接入 Hermes Core。
- 尚未實作 Store & Forward。
- 尚未實作跨區同步。
- 尚未實作權限、白名單、簽章或驗證機制。
- 尚未整合 captive portal。

### 下一個里程碑

建立第一條真正的 LoRa 資料鏈：

```text
MeshCore client/repeater node
        -> MeshCore USB companion radio
        -> Raspberry Pi Hermes Core
        -> SQLite event table
        -> Web Dashboard
```

下一步的成功條件：

```text
遠端 MeshCore 節點送出 SAFE / SOS / STATUS
並且事件出現在 http://HermesBASEv1.local:8000
```
# HermesNET 2.0 更新紀錄

## 2026-06-11 21:02:00 +08:00

### 已完成
- BBS mesh sync 從一般 channel text message 改成 MeshCore channel data datagram。
- 新增 HermesX protocol code：
  - `HX302.1`
- 新增 BBS experimental data type：
  - `0xFF01`
- BBS post payload 改為精簡 JSON：
  - `{"p":"HX302.1","t":"BBS_POST","b":"general","s":"title","m":"body","a":"author"}`
- `/bbs` UI 文案改為：
  - `Send as HermesX data packet`
- HermesCore 收到 `data_type = 0xFF01` 時，會解析為 BBS post 並寫入 `bbs_posts`。

### 架構意義
- BBS post 不再顯示於一般 MeshCore 聊天室。
- 一般聊天室只看 channel text message。
- Hermes BBS 使用 channel data datagram，只有 HermesCore 會解析。
- 這比較接近 HermesX 302.1 protocol code 的設計方向。

## 2026-06-11 20:43:00 +08:00

### 已完成
- HermesCore 新增 `/bbs` 頁面，開始接入 MeshBBS 應用層。
- 新增 BBS SQLite tables：
  - `bbs_boards`
  - `bbs_posts`
- 新增預設 boards：
  - `general`
  - `resources`
  - `shelter`
- 新增 BBS API：
  - `GET /api/bbs/boards`
  - `POST /api/bbs/boards`
  - `GET /api/bbs/posts`
  - `POST /api/bbs/posts`
- `/bbs` 支援：
  - 看 boards
  - 看 posts
  - 新增 post
  - 選擇是否送到 MeshCore channel
- 發文若勾選 `Send to MeshCore channel`，會送出文字格式：
  - 此格式已在 2026-06-11 21:02:00 +08:00 改為 HermesX data packet。
- 發文同時會寫入 HermesCore event：
  - `event_type = BBS_POST`

### 說明
- 這是 MeshBBS 的第一階段整合，不是完整 MeshBBS 移植。
- 目前目標是讓 HermesCore 網站上開始有 BBS 應用層，而不是只停留在 MeshCore gateway console。

## 2026-06-11 20:24:00 +08:00

### 已完成
- 新增文件：`docs/MeshBridge_MeshBBS_整合定位.md`
- 釐清 MeshBridge / MeshBBS 在 HermesNET 2.0 的位置。
- 確認目前 HermesCore 只完成 MeshCore transport 與 core event pipeline，尚未把 MeshBridge / MeshBBS 的應用層搬進網站。

### 架構判斷
- MeshBridge 與 MeshBBS 原本都偏 Meshtastic 生態。
- HermesNET 目前改走 MeshCore，因此不能讓 MeshBridge / MeshBBS 直接控制 serial radio。
- 正確整合方式是：
  - HermesCore 控制 MeshCore Base Tracker。
  - MeshBridge / MeshBBS 改成 HermesCore 上層應用。
  - 透過 HermesCore API 收送訊息。

### 下一步建議
- 先做 `/bbs`，讓 MeshBBS 的看板、文章、回覆開始出現在 HermesCore。
- 再做 `/noteboard`，把 MeshBridge 的公告板與社區留言功能搬進 HermesCore。
- 最後才處理 MeshBridge 的 Wi-Fi AP、offline map、e-paper。

## 2026-06-11 19:43:00 +08:00

### 修正
- `/meshcore` Logs 改成由舊到新顯示，新訊息在底部，符合 terminal 閱讀習慣。
- Logs 改用 `GET /api/logs`，預設過濾 `poll sync next message` 與 `poll battery` 這類高頻噪音。
- terminal log 會自動捲到底部。
- `Save + Join` 文案改為明確區分：
  - local config saved
  - write command queued
  - radio confirmed
- Known Channels 不再空白誤導；若 radio 尚未回覆，會顯示「Configured locally, not confirmed by radio yet」。
- MeshCore 管理按鈕加上簡單防連點，避免 log 被重複 `manual app start` 洗版。

### 說明
- Known Channels 代表「Base Tracker 回傳的 channel slot」，不是 HermesCore 本機設定檔。
- 目前若 `Protocol RX: no`，Known Channels 只能顯示本機 configured 狀態，不能顯示 confirmed。

## 2026-06-11 19:31:00 +08:00

### 已完成
- 重新整理 `/meshcore` 管理頁。
- 新增分頁：
  - `Overview`
  - `Channels`
  - `Logs`
- `Channels` 分頁現在集中管理：
  - Channel slot
  - Channel name
  - Channel secret
  - `Save + Join`
  - Known channels
  - 測試訊息發送
- `Save + Join` 現在會在頁面上直接顯示結果，不再只有右上角狀態文字。
- `Logs` 分頁新增黑底 terminal-style log 視窗。
- terminal log 顯示：
  - timestamp
  - event id
  - event type
  - source
  - raw message

### 說明
- `/meshcore` 會保留成 MeshCore gateway console。
- 未來若要把 MeshCore 官方 Web App 的功能整合進來，會以這個 console 作為入口。

## 2026-06-11 19:12:00 +08:00

### 修正
- 修正 MeshCore Companion USB serial framing 方向。
- 正確方向：
  - HermesCore 主機送到 Base Tracker：`<` + 2-byte little-endian length + payload
  - Base Tracker 回到 HermesCore：`>` + 2-byte little-endian length + payload
- 修正前 HermesCore 會一直送出 command，但收不到 radio response：
  - `Frames TX` 持續增加
  - `Frames RX` 維持 `0`
  - Dashboard 的 device name / radio / battery 都是 `-`

### 影響
- 修正後重啟 `hermes-core`，`Frames RX` 應開始增加。
- `Probe Radio` 後應能看到 Base Tracker 的 device info、battery、channel info。
- 第二顆 Tracker 發送的 channel message 才有機會被 HermesCore 正確同步與解析。

## 2026-06-11 18:42:00 +08:00

### 已完成
- 調整 Hermes Core Dashboard 資訊分層。
- 主頁 `/` 改為偏向 HermesNET 事件監控：
  - 保留 `SAFE`、`SOS`、`NEED`、`STATUS` 快速發送。
  - 移除第一層的 `Probe Radio`、`Set AS923`、`Join Channel`。
  - 新增 `Manage MeshCore` 入口。
- `/api/events` 與 `/api/summary` 預設不再顯示 MeshCore system events。
- 新增 `include_system=true` 查詢參數：
  - `GET /api/events?include_system=true`
  - `GET /api/summary?include_system=true`
- MeshCore 管理頁 `/meshcore` 新增 `Recent MeshCore Log`，用來查看：
  - `COMPANION_TX`
  - `RADIO_RESPONSE`
  - `RADIO_ERROR`
  - `NO_MORE_MESSAGES`
  - 其他底層 gateway log

### 說明
- 原本主頁的 Total 會被 `COMPANION_TX`、poll、radio query 等底層事件灌高。
- 調整後主頁只看「人或節點傳來的 HermesNET 事件」。
- MeshCore 管理與 debug 資訊集中到 `/meshcore`。

## 2026-06-11 18:28:00 +08:00

### 已完成
- 新增 HermesCore 內建 MeshCore 管理頁：
  - 路徑：`/meshcore`
  - 主 Dashboard 增加 `MeshCore Manager` 入口。
- 管理頁功能：
  - 顯示 Base Tracker 裝置資訊。
  - 顯示 Companion USB serial 狀態。
  - 顯示目前 radio profile 與實際 radio 設定。
  - 顯示 MeshCore channel slot 資訊。
  - 可執行 `Probe Radio`。
  - 可執行 `Set AS923`。
  - 可執行 `Join Channel`。
  - 可修改 channel slot、channel name、channel secret。
  - 可送出 MeshCore channel 測試訊息。
- 新增 API：
  - `POST /api/radio/channel`

### 說明
- 這不是直接複製 MeshCore 官方 Web App。
- 目前採用「搬功能概念，不搬官方前端」的方式，讓 HermesCore 自己管理 Base gateway radio。
- 官方 MeshCore Web App 仍適合用來管理一般 client 節點；HermesCore 的 `/meshcore` 頁面則專注於 Base gateway。

## 2026-06-11 18:18:00 +08:00

### 已完成
- 將 Hermes Core 的預設 radio transport 從 `meshcore-kiss` 改為 `meshcore-companion-usb`。
- 新增 MeshCore Companion USB framing：
  - 主機送出：`>` + 2-byte little-endian length + payload
  - radio 回傳：`<` + 2-byte little-endian length + payload
- Hermes Core 啟動時會自動執行 Companion 初始化流程：
  - `CMD_APP_START`
  - `CMD_DEVICE_QUERY`
  - `CMD_SET_DEVICE_TIME`
  - `CMD_SET_RADIO_PARAMS`
  - `CMD_SET_RADIO_TX_POWER`
  - `CMD_SET_CHANNEL`
  - `CMD_GET_CHANNEL`
  - `CMD_GET_BATT_AND_STORAGE`
  - `CMD_SYNC_NEXT_MESSAGE`
- 新增 HermesNET 測試頻道設定：
  - Channel slot：`1`
  - Channel name：`HermesNET-TW-TEST`
  - Channel secret：已寫入 PoC 設定，正式部署前建議改成 Pi 本機 private config 或環境變數。
- 新增 API：
  - `POST /api/radio/channel/apply`
  - `POST /api/mesh/send`
- Dashboard 新增 `Join Channel` 按鈕。
- Dashboard 的 `SAFE`、`SOS`、`NEED`、`STATUS` 現在會透過 MeshCore channel 發送，不再只是寫入本機 SQLite。
- Hermes Core 會解析 Companion 回傳：
  - Self info
  - Device info
  - Channel info
  - Battery/storage
  - Channel text message
  - Channel datagram
  - Messages waiting
  - Message sent / error

### 架構變更
- 方案 B 代表 Base Tracker 需要刷 `companion_radio_usb` 韌體。
- KISS modem 路徑仍保留在程式中，但目前不是預設模式。
- 這樣 Base radio 才能真正「加入 MeshCore 頻道」，而不是像 KISS modem 只看到較底層的 radio frame。

### 下一步
- 將新的 `pi_payloads/hermes_core_app.py` 部署到 Raspberry Pi。
- Base Tracker 從 KISS modem 改刷 MeshCore `companion_radio_usb`。
- 重啟 `hermes-core` 後按 `Probe Radio` 與 `Join Channel`，確認 `/api/radio` 顯示 channel slot 1。
- 用第二顆 Tracker 在同一個 MeshCore channel 發訊息，確認 Hermes Core 收到 `SAFE`、`SOS`、`NEED` 或一般 channel message。
# HermesNET 2.0 更新紀錄

## 2026-06-11 20:12:00 +08:00

### 已完成
- 驗證 MeshCore Companion USB gateway 收訊鏈路成功。
- 第二顆 Tracker `F807BA14` 在 MeshCore channel 發送 `SAFE`。
- Base Tracker 收到 MeshCore channel message。
- HermesCore 透過 Companion USB `SYNC_NEXT_MESSAGE` 取回訊息。
- HermesCore 成功將訊息解析成 HermesNET event：
  - event type：`SAFE`
  - source：`meshcore-radio`
  - message：`F807BA14: SAFE`

### 驗證紀錄
```text
[2026-06-11 12:08:58.327142Z] #2105 MESSAGES_WAITING meshcore-radio messages waiting
[2026-06-11 12:08:58.451330Z] #2106 SAFE meshcore-radio F807BA14: SAFE
```

### 架構意義
- HermesCore 已不只是本機 dashboard。
- 目前已完成第一條可用的 MeshCore -> HermesCore -> HermesNET event pipeline。
- 這代表後續可以開始設計：
  - 節點命名規則
  - event schema
  - 災情分類
  - shelter/base dashboard
  - store-and-forward
  - 多 Base gateway 匯流

### 待處理
- `RADIO_LOG` 目前可能包含 binary/debug payload，應改成 hex 顯示或預設隱藏。
- `/meshcore` 的 log terminal 需持續保留，作為 gateway debug console。
- Known Channels 需在 radio 回覆 `CHANNEL_INFO` 後才標示為 confirmed。
# HermesNET 2.0 更新紀錄

## 2026-06-12 00:30:00 +08:00

### 已完成
- HermesCore 新增 `/noteboard` 頁面，開始接入 MeshBridge 公告板應用層。
- 新增 Noteboard SQLite table：
  - `noteboard_notes`
- 新增 Noteboard API：
  - `GET /api/noteboard/notes`
  - `POST /api/noteboard/notes`
- `/noteboard` 支援：
  - 看 notes
  - 新增 note
  - category
  - priority
  - location
  - 選擇是否送成 HermesX data packet
- 新增 HermesX data type：
  - `0xFF02`
- Noteboard note payload：
  - `{"p":"HX302.1","t":"NOTE","c":"notice","s":"title","m":"body","a":"author","r":"normal","l":"location"}`
- Noteboard note 使用 MeshCore channel data datagram，不會顯示在一般 MeshCore 聊天室。

### 架構意義
- `/bbs` 是 MeshBBS 的第一個可見整合點。
- `/noteboard` 是 MeshBridge 的第一個可見整合點。
- HermesCore 現在開始具備「gateway + BBS + public noteboard」的 Base 站雛形。

### 尚未處理
- MeshBridge Wi-Fi AP / captive portal 尚未移植。
- MeshBridge offline map 尚未移植。
- MeshBridge e-paper output 尚未移植。

## 2026-06-12 00:00:00 +08:00

### 狀態
- 目前 HermesCore / MeshCore gateway / BBS MVP 整體看起來沒有重大阻塞。
- 已確認 MeshCore Companion USB gateway 可正常收訊。
- 已確認第二顆 Tracker 可透過 MeshCore channel 傳送 `SAFE`，並由 HermesCore 解析成 HermesNET event。

### 已完成
- HermesCore 已具備三個主要入口：
  - `/`：HermesNET event dashboard
  - `/meshcore`：MeshCore gateway 管理與 log console
  - `/bbs`：Hermes BBS / MeshBBS MVP
- `/meshcore` 保留 terminal-style log，並區分 gateway debug 與一般事件 dashboard。
- `/bbs` 已能：
  - 顯示 boards
  - 顯示 posts
  - 新增 post
  - 選擇是否送出 HermesX data packet
- BBS mesh sync 已由一般 channel text message 改為 MeshCore channel data datagram。
- BBS data packet 目前使用：
  - protocol code：`HX302.1`
  - data type：`0xFF01`
  - payload type：`BBS_POST`
- 一般 MeshCore 聊天室不會顯示 BBS post；只有 HermesCore 會解析這類 datagram。

### 驗證
- `pi_payloads/hermes_core_app.py` 已通過 Python syntax check：

```bash
python -m py_compile pi_payloads/hermes_core_app.py
```

### 待處理
- 測試 BBS datagram 在另一個 HermesCore 節點上的接收與匯入。
- 將 channel secret 移出程式碼，改放 Pi 本機 private config 或環境變數。
- 整理 `RADIO_LOG` binary/debug payload 顯示方式。
- 下一階段開始做 `/noteboard`，把 MeshBridge 的公告板功能接進 HermesCore。
