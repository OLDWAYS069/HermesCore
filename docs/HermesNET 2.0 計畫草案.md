# HermesNET / HermesBASE 2.0 計畫草案

## 一、計畫背景

台灣現行通訊系統高度依賴：

- 行動基地台
- 電力系統
- 光纖骨幹
- 核心機房

當大型地震、颱風、戰時或長時間停電發生時，區域性通訊能力可能迅速下降。

現有防災 APP 雖能提升資訊發布效率，但仍依賴行動網路與雲端服務，無法作為真正的離網通訊系統。

因此，本計畫提出 HermesNET 架構，建立一套面向民眾與政府的韌性備援通訊系統。

## 二、計畫目標

建立一套：

- 低成本
- 可大規模部署
- 可離網運作
- 可跨區域協同
- 適用於政府與民眾

的韌性通訊架構。

本計畫不以「聊天軟體」為目標，而以：

- 災情回報
- 報平安
- 資源需求
- 政府公告
- 避難所資訊

作為核心用途。

## 三、系統定位

HermesNET 並非 Meshtastic 或 MeshCore 的延伸產品。

Meshtastic、MeshCore 僅作為可支援之傳輸協議之一。

HermesNET 將提供：

- 統一服務層
- 統一管理層
- 統一應用層

使底層傳輸技術可以自由替換。

## 四、系統架構

### 第一層：Physical Layer

可支援：

- LoRa
- WiFi HaLow
- WiFi Mesh
- LTE
- 衛星鏈路
- 光纖

### 第二層：Routing Layer

負責：

- 路由決策
- Store & Forward
- 協議轉換
- 跨區域同步

支援：

- MeshCore
- Meshtastic
- MQTT
- TAK
- 未來協議

### 第三層：Service Layer

由 Hermes 系統提供：

- MeshBridge
- MeshBBS
- 災害事件管理
- 報平安系統
- 資源需求系統
- 政府公告系統

### 第四層：Application Layer

終端應用：

- Hermes APP
- Web Portal
- 政府指揮平台
- TAK 系統

## 五、HermesBASE 2.0

### 平台變更

由 ESP32 平台升級至 Raspberry Pi 平台。

原因：

- 運算能力提升
- 可運行 Linux
- 可整合資料庫
- 可執行 Web Service
- 可執行 MeshBridge

### 雙核心架構

#### ARM-A

通訊核心。

負責：

- LoRa
- MeshCore
- Meshtastic
- Gateway

#### ARM-B

服務核心。

負責：

- 資料庫
- API
- WebUI
- MeshBridge
- MeshBBS

## 六、MeshBridge

### 定位

MeshBridge 為 HermesNET 核心服務。

並非單純 Gateway。

其職責：

- 訊息分類
- 路由決策
- 區域同步
- 狀態聚合
- 權限控管

### 功能

#### 本地交換

處理：

- 報平安
- 需求回報
- 公告

#### 區域同步

彙整：

- 避難所資訊
- 節點狀態
- 電力狀態

#### 跨區域交換

僅允許格式化資料。

不允許自由聊天訊息。

## 七、MeshBBS

### 定位

區域訊息服務系統。

作為一般民眾主要互動介面。

### 提供功能

#### 報平安

- `SAFE`

#### 求救

- `SOS`

#### 資源需求

- `FOOD`
- `WATER`
- `MEDICAL`
- `POWER`

#### 公告

- 鄉鎮公告
- 避難所公告
- 政府公告

#### 家庭群組

限定小規模家庭成員使用。

## 八、跨縣市訊息策略

### 問題

LoRa Mesh 不適合大量自由文字傳輸。

跨縣市聊天將迅速耗盡 Airtime。

### 解法

跨縣市只傳輸格式化狀態資訊。

例如：

- `NORMAL`
- `DEGRADED`
- `OFFLINE`
- `POWER_LOW`
- `POWER_CRITICAL`
- `SHELTER_OPEN`
- `SHELTER_FULL`
- `SOS_COUNT`
- `SAFE_COUNT`
- `FOOD_NEED`
- `WATER_NEED`
- `MEDICAL_NEED`

### 禁止內容

跨縣市不得傳送：

- 自由聊天
- 一般文字訊息
- 非必要討論內容

## 九、使用情境

### 政府 → 民間

發布：

- 避難資訊
- 道路資訊
- 災情公告
- 停電資訊

### 民間 → 政府

回報：

- 報平安
- 求救
- 醫療需求
- 物資需求

### 民間 → 民間

限定：

- 家庭群組
- 尋人服務
- 區域公告

避免演變成大型聊天室。

## 十、Hermes APP

### 設計原則

不直接暴露：

- LoRa
- Mesh
- Hop Count
- SNR

等技術資訊。

使用者看到的是：

- 我安全
- 我需要協助
- 避難所資訊
- 政府公告
- 家庭群組

### APP 角色

APP 不直接與 LoRa 通訊。

APP 為 MeshBridge 之入口。

```text
Hermes APP
     │
     ▼
MeshBridge
     │
     ▼
HermesBASE
     │
     ▼
Mesh Network
```

## 十一、近期發展方向

### 第一階段

- HermesBASE 2.0
- Raspberry Pi 架構
- MeshBridge MVP
- MeshBBS MVP

### 第二階段

- 區域部署測試
- 花東縱谷驗證
- 避難所情境驗證

### 第三階段

- 縣市級同步
- 多區域聯網

### 第四階段

- 政府導入驗證
- 防災系統整合
- HermesNET 示範網路

## 十二、地方網與骨幹網分流

HermesNET 應明確分成兩張網：

```text
地方網 Local Mesh
  - 每個地區可使用不同頻率或 radio profile
  - 承載自由文字、本地留言、本地 BBS、本地公告與一般狀態
  - 預設不跨區

骨幹網 Backbone Mesh
  - 跨區域骨幹節點使用同一組骨幹頻率或 radio profile
  - 承載 SOS、urgent NEED、跨區公告、區域摘要、gateway heartbeat 與必要同步
  - 不承載一般自由文字
```

設計原則：

```text
Local mesh can be noisy.
Backbone mesh must stay quiet.
```

自由文字應留在地方網。它不是進入骨幹網後再被丟棄，而是一開始就不應由 HermesCore Gateway 送上骨幹。

HermesCore / HermesBASE 在這個架構中扮演 policy bridge：

```text
Local Mesh frequency
        |
        v
HermesCore Gateway
        |
        v
Backbone Mesh frequency
```

正式部署建議 HermesCore Gateway 使用雙 radio：

```text
Radio 1: Local Mesh frequency
Radio 2: Backbone Mesh frequency
```

Local -> Backbone 的基本政策：

```text
SOS              allow
NEED urgent      allow
STATUS summary   allow
BBS important    allow by policy
CHAT/free text   deny
native text      deny or local only
unknown packet   deny
```

Backbone -> Local 的基本政策：

```text
SOS from other region        allow
county/global announcement   allow
resource routing request     allow
gateway control/heartbeat    allow
generic chat/free text       deny
unknown packet               deny
```

HermesX 封包可加入 `net` 與 `sc` 欄位：

```json
{
  "p": "HX302.1",
  "i": "7f2a9c11",
  "o": 12,
  "v": 12,
  "t": 2,
  "e": "CHAT",
  "net": "local",
  "sc": "HLN-CITY",
  "m": "有人需要飲用水嗎？"
}
```

跨區緊急事件則可標成：

```json
{
  "p": "HX302.1",
  "i": "91aa20ef",
  "o": 12,
  "v": 12,
  "t": 3,
  "e": "SOS",
  "net": "backbone",
  "sc": "HLN-COUNTY",
  "m": "花蓮市 A 區需要醫療支援"
}
```

## 核心結論

HermesNET 的目標不是打造另一套 Meshtastic 或 MeshCore。

HermesNET 的目標是建立一套面向台灣情境的韌性備援通訊體系。

LoRa、MeshCore、Meshtastic 只是其中的傳輸工具。

真正的核心是：

- HermesBASE
- MeshBridge
- MeshBBS
- Hermes APP

以及政府與民眾在災害情境下可持續運作的資訊交換機制。
