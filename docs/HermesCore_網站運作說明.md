# HermesCore 網站運作說明

更新時間：2026-06-12 00:50:00 +08:00

## 目前定位

HermesCore 是 HermesNET 2.0 在 Raspberry Pi Base 上運作的本地服務。它負責把 MeshCore Base Tracker 接進來，接收或發送 MeshCore 訊息，並提供瀏覽器介面給現場人員使用。

目前主線已收斂成：

```text
MeshCore LoRa 節點
  -> Base Tracker companion_radio_usb
  -> Raspberry Pi HermesCore
  -> SQLite
  -> HermesCore Web UI
```

上層應用保留 MeshBBS 的「看板 / 文章」架構，並吸收 MeshBridge Noteboard 的「類型 / 優先級 / 位置」欄位。也就是說，正式入口會以 `/bbs` 為主，`/noteboard` 只保留為早期實驗原型。

## 網站入口

```text
http://HermesBASEv1.local:8000
```

主要頁面：

```text
/          HermesNET 事件儀表板
/meshcore  MeshCore Gateway 管理頁
/bbs       Hermes BBS 主應用
```

舊實驗頁面：

```text
/noteboard  Noteboard 原型，已不再作為主流程
```

## `/` HermesNET Dashboard

這頁是現場快速狀態看板。

功能：

- 顯示 `SAFE`、`SOS`、`NEED`、總事件數。
- 送出 `SAFE`、`SOS`、`NEED`、`STATUS` 測試訊息。
- 顯示 Base Tracker serial / MeshCore 狀態摘要。
- 顯示近期 HermesNET event。
- 提供前往 MeshCore Manager 與 BBS 的連結。

Dashboard 的重點不是管理 MeshCore，而是讓現場快速知道「目前有沒有收到事件」。

## `/meshcore` MeshCore Manager

這頁是 Base Tracker 的 Gateway 管理頁。

功能：

- 檢查 Base Tracker 是否接在 Raspberry Pi 上。
- 檢查 Companion USB protocol 是否有 RX/TX。
- 套用 AS923-TW 測試 radio profile。
- 寫入 MeshCore channel。
- 發送測試訊息。
- 查看 gateway log。

重要欄位：

```text
Serial open      serial port 是否開啟
Protocol RX      Base Tracker 是否有回應 companion protocol
Frames RX/TX     HermesCore 與 Base Tracker 的收發量
Last TX/RX       最近一次封包狀態
Pending TX       等待送出的命令數
```

Logs 分頁是 terminal-style log，新的 log 由上往下排列，方便照時間閱讀。

## `/bbs` Hermes BBS

這是目前保留的正式上層應用。

它保留 MeshBBS 的核心概念：

- 看板 board
- 文章 post
- 標題 title
- 內文 body
- 作者 author

並加入原本 Noteboard / MeshBridge 比較適合救災與社區協作的欄位：

- `kind`：文章類型，例如公告、資源、避難、請求、狀態。
- `priority`：優先級，例如 normal、high、urgent。
- `location`：位置，例如社區、避難所、公寓、座標描述。

預設看板：

```text
general
resources
shelter
```

BBS 文章可以只存在本地 SQLite，也可以勾選送進 MeshCore channel。

送入 MeshCore 時，不再使用一般聊天室文字，而是使用 HermesX 302.1 data packet：

```text
data_type: 0xFF01
protocol: HX302.1
type: BBS_POST
```

payload 範例：

```json
{
  "p": "HX302.1",
  "t": "BBS_POST",
  "b": "general",
  "k": "notice",
  "s": "停水公告",
  "m": "三樓以上暫時無水。",
  "a": "base",
  "r": "high",
  "l": "A棟"
}
```

這樣做的目的，是讓一般 MeshCore 聊天室不要直接看到一堆 BBS 同步文字，同時 HermesCore 仍然可以辨識並還原成 BBS post。

## `/noteboard` 舊原型

Noteboard 原本用來驗證 MeshBridge 的「訊息分類、優先級、位置」模型。

目前決策是：

- 不再把 Noteboard 當獨立正式產品。
- 不再從主選單連到 Noteboard。
- Noteboard 的概念已吸收到 `/bbs`。
- 程式碼暫時保留，避免破壞既有測試資料與 API。

後續如果 `/bbs` 已穩定，可以再移除 `/noteboard` API 與資料表。

## API 摘要

事件：

```text
GET  /api/events
POST /api/events
GET  /api/summary
```

MeshCore Gateway：

```text
GET  /api/radio
POST /api/radio/probe
POST /api/radio/config/as923
POST /api/radio/channel
POST /api/mesh/send
GET  /api/logs
```

BBS：

```text
GET  /api/bbs/boards
POST /api/bbs/boards
GET  /api/bbs/posts
POST /api/bbs/posts
```

舊 Noteboard：

```text
GET  /api/noteboard/notes
POST /api/noteboard/notes
```

## 資料庫

HermesCore 使用 SQLite：

```text
hermes.db
```

主要資料表：

```text
events
bbs_boards
bbs_posts
noteboard_notes
```

`bbs_posts` 目前欄位重點：

```text
board
kind
title
body
author
priority
location
transport
mesh_sent
created_at
```

其中 `kind / priority / location` 是從 Noteboard 收斂進 BBS 的欄位。

## MeshCore 收訊流程

遠端 Tracker 在 MeshCore channel 送出訊息後：

```text
1. Base Tracker 收到 MeshCore message
2. HermesCore 透過 Companion USB 收到 messages waiting
3. HermesCore 發出 sync next message
4. Base Tracker 回傳 channel message 或 channel datagram
5. HermesCore 解析內容
6. 寫入 SQLite
7. Web UI 更新
```

已驗證案例：

```text
F807BA14 -> MeshCore -> Base Tracker -> HermesCore -> SAFE event
```

## Local / Backbone Gateway Policy

HermesCore 不只是接收 MeshCore 訊息的 Web UI，也應是地方網與骨幹網之間的 policy bridge。

建議部署模型：

```text
Local Mesh radio
  - 地方頻率
  - 自由文字、本地留言、本地 BBS、本地公告

Backbone Mesh radio
  - 骨幹頻率
  - SOS、urgent NEED、跨區公告、區域摘要、gateway heartbeat
```

正式版 HermesCore Gateway 建議使用雙 radio：

```text
Radio 1: Local Mesh frequency
Radio 2: Backbone Mesh frequency
```

HermesCore 的核心規則：

```text
Local mesh can be noisy.
Backbone mesh must stay quiet.
```

Local -> Backbone：

```text
SOS              allow
NEED urgent      allow
STATUS summary   allow
BBS important    allow by policy
CHAT/free text   deny
native text      deny or local only
unknown packet   deny
```

Backbone -> Local：

```text
SOS from other region        allow
county/global announcement   allow
resource routing request     allow
gateway control/heartbeat    allow
generic chat/free text       deny
unknown packet               deny
```

自由文字不應進入骨幹網。若使用者透過 HermesCore 的留言或聊天功能送出自由文字，HermesCore 應將它標記為 `net=local`，並只在地方網下發。跨區資訊必須是 SOS、urgent NEED、管理公告、摘要或明確允許的 BBS 內容。

## 目前狀態

已完成：

- Raspberry Pi 上 HermesCore FastAPI 服務。
- MeshCore Companion USB 連線。
- AS923-TW 測試 profile。
- MeshCore channel 設定與收訊。
- SAFE/SOS/NEED 事件 Dashboard。
- MeshCore Manager 與 terminal log。
- Hermes BBS MVP。
- BBS 使用 HermesX 302.1 data packet 同步。
- BBS 吸收 `kind / priority / location` 欄位。

仍待處理：

- BBS post thread / reply。
- 多 Base gateway 同步策略。
- 節點別名管理。
- shelter / repeater / base topology。
- 更完整的 HermesX 302.1 schema。
- channel secret 私密化與設定檔整理。
- 移除或封存 Noteboard 原型。
