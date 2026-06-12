# MeshBridge / MeshBBS 在 HermesNET 2.0 的整合定位

## 為什麼目前畫面上還看不到 MeshBridge / MeshBBS

目前 HermesCore 先完成的是 MeshCore gateway transport。

也就是：

```text
MeshCore Tracker
  -> Base Tracker companion_radio_usb
  -> HermesCore
  -> SQLite events
  -> Dashboard
```

這一步是底層通訊管線。

MeshBridge 與 MeshBBS 則是應用層：

```text
MeshBridge = 社區公告板 / chat / noteboard / map / e-paper / captive portal 類功能
MeshBBS    = BBS 看板 / 發文 / 回覆 / client-server BBS 類功能
```

目前還沒看到它們，是因為兩者原本都偏向 Meshtastic 生態，會直接碰 Meshtastic serial / Meshtastic API。

但 HermesNET 現在已經改走 MeshCore，所以不能直接把原始程式丟上去跑，否則會出現兩個問題：

1. 它們會嘗試控制 Meshtastic serial，而不是 MeshCore companion USB。
2. 它們會跟 HermesCore 搶同一個 radio serial port。

因此正確做法不是「直接跑 MeshBridge / MeshBBS」，而是把它們拆成應用層，讓它們透過 HermesCore API 收送訊息。

## 目前三層架構

```text
Transport Layer
  MeshCore companion_radio_usb
  HermesCore serial reader / parser

Core Layer
  HermesCore API
  SQLite event database
  event classifier
  MeshCore Manager

Application Layer
  MeshBridge-like Noteboard
  MeshBBS-like Board System
  HermesNET Dashboard
```

目前已完成：

```text
Transport Layer + Core Layer MVP
```

尚未完成：

```text
MeshBridge / MeshBBS application layer
```

## MeshBridge 應該怎麼接

MeshBridge 原本重點：

- Flask / Socket.IO Web UI
- chat
- noteboard
- local Wi-Fi AP / captive portal
- offline map
- e-paper 顯示
- Meshtastic receive/send

在 HermesNET 裡，MeshBridge 不應該直接碰 radio。

應改成：

```text
MeshBridge UI / Noteboard
  -> HermesCore API
  -> HermesCore event database
  -> HermesCore MeshCore transport
```

可以先搬的功能：

1. Noteboard UI
2. local bulletin board
3. offline-first notes
4. map / shelter display
5. e-paper export

暫時不要搬：

```text
meshtastic.serial_interface
pub.subscribe("meshtastic.receive")
direct LoRa send loop
```

因為這些要改成 HermesCore 的 MeshCore transport。

## MeshBBS 應該怎麼接

MeshBBS 原本重點：

- BBS server
- BBS client
- board list
- post list
- compose post
- Android client
- Meshtastic mesh relay

在 HermesNET 裡，MeshBBS 可以變成：

```text
HermesBBS
  board
  thread
  post
  reply
  mesh sync
```

它應該使用 HermesCore 提供的訊息通道：

```text
POST /api/mesh/send
GET /api/events
GET /api/logs
```

後續應新增 BBS 專用 API：

```text
GET  /api/bbs/boards
GET  /api/bbs/posts
POST /api/bbs/posts
POST /api/bbs/replies
```

然後由 HermesCore 把 BBS event 編碼成 MeshCore channel message。

## 建議整合順序

### Phase 1：先接 MeshBBS 資料模型

先不要搬 Android，也不要搬完整 UI。

先做：

```text
boards
posts
replies
```

SQLite 新增：

```text
bbs_boards
bbs_posts
bbs_replies
```

HermesCore 新增 API：

```text
/api/bbs/boards
/api/bbs/posts
```

MeshCore channel message 先用簡單格式：

```json
{
  "type": "BBS_POST",
  "board": "general",
  "title": "Water point",
  "body": "Water available at shelter A",
  "node": "F807BA14"
}
```

### Phase 2：搬 MeshBridge Noteboard

把 MeshBridge 的 noteboard 概念搬進 HermesCore：

```text
/noteboard
```

用途：

- 公告
- 物資
- 位置
- 避難所狀態
- 社區留言

資料來源：

```text
HermesCore events
HermesBBS posts
manual notes
```

### Phase 3：做 MeshBridge gateway features

再處理：

- local Wi-Fi AP
- captive portal
- offline map
- e-paper output

這些比較偏部署與硬體整合，可以等核心資料流穩定後再接。

### Phase 4：才回頭接 MeshBBS Android

Android 端如果要保留，需要改成：

```text
Android App
  -> HermesCore HTTP API
```

而不是：

```text
Android App
  -> Meshtastic Android service
```

## 最小可見成果

下一個最合理的成果，不是一次搬完整 MeshBridge / MeshBBS。

而是先讓 HermesCore 多兩個頁面：

```text
/bbs
/noteboard
```

其中：

```text
/bbs       = MeshBBS 的影子
/noteboard = MeshBridge 的影子
```

這樣畫面上才會開始看得到兩套系統的整合方向。

## 2026-06-11 目前已開始實作

已新增：

```text
/bbs
/noteboard
```

這是 MeshBBS 在 HermesCore 裡的第一個 MVP。

目前功能：

- 顯示 boards。
- 顯示 posts。
- 新增 post。
- 可選擇將 post 送到 MeshCore channel。

目前資料表：

```text
bbs_boards
bbs_posts
```

目前 API：

```text
GET  /api/bbs/boards
POST /api/bbs/boards
GET  /api/bbs/posts
POST /api/bbs/posts
```

目前 MeshCore data 格式：

```text
data_type = 0xFF01
payload = {"p":"HX302.1","t":"BBS_POST","b":"general","s":"title","m":"body","a":"author"}
```

這個格式走 MeshCore channel data datagram，不是一般 channel text message，因此不會顯示在一般聊天室。

這還不是完整 MeshBBS 移植，只是先讓 HermesCore 網站上出現 BBS 應用層。

`/noteboard` 是 MeshBridge 公告板功能的第一個 MVP。

目前功能：

- 顯示 notes。
- 新增 note。
- 支援 category。
- 支援 priority。
- 支援 location。
- 可選擇送成 HermesX data packet。

目前資料表：

```text
noteboard_notes
```

目前 API：

```text
GET  /api/noteboard/notes
POST /api/noteboard/notes
```

目前 MeshCore data 格式：

```text
data_type = 0xFF02
payload = {"p":"HX302.1","t":"NOTE","c":"notice","s":"title","m":"body","a":"author","r":"normal","l":"location"}
```

這是 MeshBridge noteboard 的應用層移植，不包含 Wi-Fi AP、offline map、e-paper。

## 結論

目前 MeshBridge / MeshBBS 沒出現在畫面上，不是因為它們不重要，而是因為 HermesNET 已經從 Meshtastic 改成 MeshCore，底層 transport 必須先重接。

現在 MeshCore gateway 已經成功收到：

```text
F807BA14: SAFE
```

所以接下來可以開始把 MeshBridge / MeshBBS 放到 HermesCore 上層。

建議下一步：

```text
先做 HermesCore /bbs 頁面與 BBS SQLite schema
再做 /noteboard 頁面
最後再搬 MeshBridge Wi-Fi / map / e-paper 功能
```

## 2026-06-12 收斂決策

目前決定不再把 MeshBBS 與 MeshBridge Noteboard 做成兩個長期並列的應用入口。

新的方向：

```text
保留 MeshBBS 的 board / post 模型
吸收 MeshBridge Noteboard 的 priority / location / kind 元素
正式入口集中在 /bbs
```

也就是：

```text
/bbs = HermesNET 的主要文字公告 / 看板 / 資源 / 避難所資訊入口
```

目前 `/bbs` post 已新增欄位：

```text
kind
priority
location
```

BBS datagram 仍使用：

```text
data_type = 0xFF01
protocol = HX302.1
type = BBS_POST
```

payload 會帶入：

```json
{
  "p": "HX302.1",
  "t": "BBS_POST",
  "b": "resources",
  "k": "resource",
  "s": "Water point",
  "m": "Water available",
  "a": "local",
  "r": "high",
  "l": "Shelter A"
}
```

`/noteboard` 暫時保留為 legacy/prototype endpoint，但不再作為主要導覽入口。
