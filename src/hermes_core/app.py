from datetime import datetime, timezone
import json
import queue
import secrets
import sqlite3
import struct
import threading
import time
import uuid

import serial
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB_PATH = "hermes.db"
CONFIG_PATH = "hermes_config.json"
SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200
TRANSPORT_MODE = "companion_usb"
AUTO_APPLY_RADIO_PROFILE = True
DEFAULT_RADIO_PROFILE = {
    "name": "AS923-TW-TEST",
    "freq_hz": 923_200_000,
    "bw_hz": 125_000,
    "sf": 9,
    "cr": 5,
    "tx_power": 14,
}
DEFAULT_CHANNEL = {
    "name": "HermesNET-TW-TEST",
    "index": 1,
    "secret_hex": "1bf70d10aa44e837f959f940553cf5aa",
}
SYSTEM_EVENT_TYPES = {
    "COMPANION_RX",
    "COMPANION_TX",
    "HERMES_DUPLICATE",
    "HERMES_LOOPBACK",
    "KISS_FRAME",
    "MESSAGES_WAITING",
    "NO_MORE_MESSAGES",
    "RADIO_CONFIG_SET",
    "RADIO_ERROR",
    "RADIO_LOG",
    "RADIO_OK",
    "RADIO_PARSE_ERROR",
    "RADIO_PROFILE_APPLY",
    "RADIO_QUERY",
    "RADIO_RESPONSE",
    "RADIO_RX_META",
    "RADIO_TX_DONE",
}
NOISY_LOG_MESSAGES = {
    "poll sync next message",
    "poll battery",
}

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

KISS_CMD_DATA = 0x00
KISS_CMD_SETHARDWARE = 0x06

HW_GET_IDENTITY = 0x01
HW_GET_RADIO = 0x0B
HW_GET_TX_POWER = 0x0C
HW_GET_CURRENT_RSSI = 0x0D
HW_GET_NOISE_FLOOR = 0x10
HW_GET_VERSION = 0x11
HW_GET_STATS = 0x12
HW_GET_BATTERY = 0x13
HW_GET_MCU_TEMP = 0x14
HW_GET_DEVICE_NAME = 0x16
HW_PING = 0x17
HW_GET_SIGNAL_REPORT = 0x1A

COMP_CMD_APP_START = 0x01
COMP_CMD_SEND_CHANNEL_TXT_MSG = 0x03
COMP_CMD_SET_DEVICE_TIME = 0x06
COMP_CMD_SYNC_NEXT_MESSAGE = 0x0A
COMP_CMD_SET_RADIO_PARAMS = 0x0B
COMP_CMD_SET_RADIO_TX_POWER = 0x0C
COMP_CMD_GET_BATT_AND_STORAGE = 0x14
COMP_CMD_DEVICE_QUERY = 0x16
COMP_CMD_GET_CHANNEL = 0x1F
COMP_CMD_SET_CHANNEL = 0x20
COMP_CMD_SEND_CHANNEL_DATA = 0x3E

HERMES_DATA_TYPE_BBS = 0xFF01
HERMES_DATA_TYPE_NOTE = 0xFF02
HERMES_DATA_TYPE_EVENT = 0xFF03
HERMES_PROTOCOL_CODE = "HX302.1"
HERMES_DEFAULT_TTL = 2

COMP_PACKET_OK = 0x00
COMP_PACKET_ERROR = 0x01
COMP_PACKET_SELF_INFO = 0x05
COMP_PACKET_MSG_SENT = 0x06
COMP_PACKET_CHANNEL_MSG_RECV = 0x08
COMP_PACKET_NO_MORE_MESSAGES = 0x0A
COMP_PACKET_BATTERY = 0x0C
COMP_PACKET_DEVICE_INFO = 0x0D
COMP_PACKET_CHANNEL_MSG_RECV_V3 = 0x11
COMP_PACKET_CHANNEL_INFO = 0x12
COMP_PACKET_CHANNEL_DATA_RECV = 0x1B
COMP_PACKET_MESSAGES_WAITING = 0x83
COMP_PACKET_LOG_DATA = 0x88

app = FastAPI(title="Hermes Core MVP")
tx_queue: "queue.Queue[bytes]" = queue.Queue()
serial_state = {
    "connected": False,
    "last_error": None,
    "last_opened_at": None,
    "frames_rx": 0,
    "frames_tx": 0,
    "transport": TRANSPORT_MODE,
    "last_tx_hex": None,
    "last_rx_byte_hex": None,
    "last_rx_header_at": None,
    "last_rx_frame_at": None,
    "rx_discarded_bytes": 0,
}
radio_state = {
    "identity": None,
    "device_name": None,
    "firmware_version": None,
    "radio": None,
    "tx_power_dbm": None,
    "current_rssi_dbm": None,
    "noise_floor_dbm": None,
    "battery_mv": None,
    "mcu_temp_c": None,
    "stats": None,
    "signal_report_enabled": None,
    "last_pong_at": None,
    "last_rx_meta": None,
    "last_error": None,
    "last_probe_at": None,
    "current_profile": None,
    "last_config_apply_at": None,
    "channels": {},
    "active_channel": None,
    "device_info": None,
    "public_key": None,
}


class EventIn(BaseModel):
    event_type: str
    source_node: str = "manual"
    region: str = "local"
    payload: dict = {}
    transport: str = "manual"
    raw_message: str = ""


class RadioQueryIn(BaseModel):
    command: str


class RadioConfigIn(BaseModel):
    freq_hz: int
    bw_hz: int
    sf: int
    cr: int
    tx_power: int | None = None


class ChannelConfigIn(BaseModel):
    name: str
    index: int = 1
    secret_hex: str


class MeshMessageIn(BaseModel):
    message: str
    channel_index: int | None = None


class BbsBoardIn(BaseModel):
    name: str
    title: str
    description: str = ""


class BbsPostIn(BaseModel):
    board: str = "general"
    kind: str = "post"
    title: str
    body: str
    author: str = "local"
    priority: str = "normal"
    location: str = ""
    send_mesh: bool = True


class NoteboardNoteIn(BaseModel):
    category: str = "notice"
    title: str
    body: str
    author: str = "local"
    priority: str = "normal"
    location: str = ""
    send_mesh: bool = True


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source_node TEXT NOT NULL,
            region TEXT NOT NULL,
            payload TEXT NOT NULL,
            transport TEXT NOT NULL,
            raw_message TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            origin_core INTEGER NOT NULL,
            via_core INTEGER,
            source_transport TEXT NOT NULL,
            event_type TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            UNIQUE(message_id, origin_core)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bbs_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bbs_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'post',
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            location TEXT NOT NULL DEFAULT '',
            transport TEXT NOT NULL,
            mesh_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for column_sql in (
        "ALTER TABLE bbs_posts ADD COLUMN kind TEXT NOT NULL DEFAULT 'post'",
        "ALTER TABLE bbs_posts ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'",
        "ALTER TABLE bbs_posts ADD COLUMN location TEXT NOT NULL DEFAULT ''",
    ):
        try:
            conn.execute(column_sql)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS noteboard_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author TEXT NOT NULL,
            priority TEXT NOT NULL,
            location TEXT NOT NULL,
            transport TEXT NOT NULL,
            mesh_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for name, title, description in (
        ("general", "一般", "一般本地訊息"),
        ("resources", "資源", "食物、水、電力與物資更新"),
        ("shelter", "避難", "避難所與社區狀態"),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO bbs_boards (name, title, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, title, description, now_iso()),
        )
    conn.commit()
    conn.close()


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {
            "transport_mode": TRANSPORT_MODE,
            "radio_profile": DEFAULT_RADIO_PROFILE,
            "channel": DEFAULT_CHANNEL,
            "core_id": secrets.randbelow(65535) + 1,
        }
        save_config(config)
        return config
    except Exception as exc:
        print(f"config load error: {exc}")
        config = {}

    changed = False
    if "transport_mode" not in config:
        config["transport_mode"] = TRANSPORT_MODE
        changed = True
    if "radio_profile" not in config:
        config["radio_profile"] = DEFAULT_RADIO_PROFILE
        changed = True
    if "channel" not in config:
        config["channel"] = DEFAULT_CHANNEL
        changed = True
    if "core_id" not in config:
        config["core_id"] = secrets.randbelow(65535) + 1
        changed = True
    if changed:
        save_config(config)
    return config


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_radio_profile():
    config = load_config()
    profile = config.get("radio_profile") or DEFAULT_RADIO_PROFILE
    merged = dict(DEFAULT_RADIO_PROFILE)
    merged.update(profile)
    return merged


def get_channel_config():
    config = load_config()
    channel = config.get("channel") or DEFAULT_CHANNEL
    merged = dict(DEFAULT_CHANNEL)
    merged.update(channel)
    return merged


def get_core_id():
    return int(load_config().get("core_id") or 0)


def new_message_id():
    return uuid.uuid4().hex[:8]


def mark_seen_message(message_id, origin_core, via_core, source_transport, event_type):
    if not message_id or origin_core is None:
        return True
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO seen_messages (
                message_id, origin_core, via_core, source_transport,
                event_type, first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(message_id),
                int(origin_core),
                int(via_core) if via_core is not None else None,
                source_transport,
                event_type,
                now_iso(),
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def hermes_message_meta(doc: dict, default_type="HERMES_DATA"):
    packet_type = doc.get("e")
    if not packet_type and isinstance(doc.get("t"), str):
        packet_type = doc.get("t")
    ttl = doc.get("t") if isinstance(doc.get("t"), int) else doc.get("ttl")
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        ttl = 0
    try:
        origin_core = int(doc["o"]) if doc.get("o") is not None else None
    except (TypeError, ValueError):
        origin_core = None
    try:
        via_core = int(doc["v"]) if doc.get("v") is not None else None
    except (TypeError, ValueError):
        via_core = None
    return {
        "message_id": str(doc.get("i") or ""),
        "origin_core": origin_core,
        "via_core": via_core,
        "ttl": ttl,
        "packet_type": packet_type or default_type,
    }


def add_hermes_envelope(doc: dict, packet_type: str, ttl: int = HERMES_DEFAULT_TTL, message_id: str | None = None):
    core_id = get_core_id()
    wrapped = {
        "p": HERMES_PROTOCOL_CODE,
        "i": message_id or new_message_id(),
        "o": core_id,
        "v": core_id,
        "t": int(ttl),
        "e": packet_type,
    }
    wrapped.update(doc)
    mark_seen_message(wrapped["i"], core_id, core_id, "local", packet_type)
    return wrapped


def set_channel_config(channel):
    idx = int(channel.get("index", DEFAULT_CHANNEL["index"]))
    if not 0 <= idx <= 7:
        raise ValueError("channel index must be 0-7")

    secret_hex = channel.get("secret_hex", DEFAULT_CHANNEL["secret_hex"]).strip().lower()
    bytes.fromhex(secret_hex)
    if len(secret_hex) != 32:
        raise ValueError("channel secret must be 16 bytes hex")

    name = channel.get("name", DEFAULT_CHANNEL["name"]).strip() or DEFAULT_CHANNEL["name"]
    config = load_config()
    merged = dict(DEFAULT_CHANNEL)
    merged.update({"name": name, "index": idx, "secret_hex": secret_hex})
    config["channel"] = merged
    save_config(config)
    radio_state["active_channel"] = {"index": merged["index"], "name": merged["name"]}
    return merged


def set_radio_profile(profile):
    config = load_config()
    merged = dict(DEFAULT_RADIO_PROFILE)
    merged.update(profile)
    config["radio_profile"] = merged
    save_config(config)
    radio_state["current_profile"] = merged
    return merged


def insert_event(event_type, source_node, region, payload, transport, raw_message):
    conn = db()
    conn.execute(
        """
        INSERT INTO events (
            event_type, source_node, region, payload,
            transport, raw_message, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            source_node,
            region,
            json.dumps(payload, ensure_ascii=False),
            transport,
            raw_message,
            now_iso(),
        ),
    )
    conn.commit()
    conn.close()


def list_bbs_boards():
    conn = db()
    rows = conn.execute(
        """
        SELECT b.name, b.title, b.description, b.created_at, COUNT(p.id) AS post_count
        FROM bbs_boards b
        LEFT JOIN bbs_posts p ON p.board = b.name
        GROUP BY b.id
        ORDER BY b.id
        """
    ).fetchall()
    conn.close()
    return [
        {
            "name": r[0],
            "title": r[1],
            "description": r[2],
            "created_at": r[3],
            "post_count": r[4],
        }
        for r in rows
    ]


def list_bbs_posts(board=None, limit=50):
    conn = db()
    if board:
        rows = conn.execute(
            """
            SELECT id, board, kind, title, body, author, priority, location, transport, mesh_sent, created_at
            FROM bbs_posts
            WHERE board = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (board, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, board, kind, title, body, author, priority, location, transport, mesh_sent, created_at
            FROM bbs_posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "board": r[1],
            "kind": r[2],
            "title": r[3],
            "body": r[4],
            "author": r[5],
            "priority": r[6],
            "location": r[7],
            "transport": r[8],
            "mesh_sent": bool(r[9]),
            "created_at": r[10],
        }
        for r in rows
    ]


def create_bbs_post(post: BbsPostIn):
    board = post.board.strip().lower() or "general"
    kind = post.kind.strip().lower() or "post"
    title = post.title.strip()
    body = post.body.strip()
    author = post.author.strip() or "local"
    priority = post.priority.strip().lower() or "normal"
    location = post.location.strip()
    if not title or not body:
        raise ValueError("title and body are required")

    conn = db()
    exists = conn.execute("SELECT 1 FROM bbs_boards WHERE name = ?", (board,)).fetchone()
    if not exists:
        conn.close()
        raise ValueError("unknown board")

    mesh_sent = 0
    transport = "local"
    if post.send_mesh:
        companion_queue_channel_data(
            HERMES_DATA_TYPE_BBS,
            build_bbs_datagram(board, kind, title, body, author, priority, location),
        )
        mesh_sent = 1
        transport = "meshcore-data"

    created_at = now_iso()
    cur = conn.execute(
        """
        INSERT INTO bbs_posts (board, kind, title, body, author, priority, location, transport, mesh_sent, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (board, kind, title, body, author, priority, location, transport, mesh_sent, created_at),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()

    insert_event(
        event_type="BBS_POST",
        source_node=author,
        region="local",
        payload={
            "post_id": post_id,
            "board": board,
            "kind": kind,
            "title": title,
            "body": body,
            "priority": priority,
            "location": location,
        },
        transport=transport,
        raw_message=f"[{board}] {title}",
    )

    return {
        "id": post_id,
        "board": board,
        "kind": kind,
        "title": title,
        "body": body,
        "author": author,
        "priority": priority,
        "location": location,
        "transport": transport,
        "mesh_sent": bool(mesh_sent),
        "created_at": created_at,
    }


def list_noteboard_notes(category=None, limit=80):
    conn = db()
    if category:
        rows = conn.execute(
            """
            SELECT id, category, title, body, author, priority, location, transport, mesh_sent, created_at
            FROM noteboard_notes
            WHERE category = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, category, title, body, author, priority, location, transport, mesh_sent, created_at
            FROM noteboard_notes
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "category": r[1],
            "title": r[2],
            "body": r[3],
            "author": r[4],
            "priority": r[5],
            "location": r[6],
            "transport": r[7],
            "mesh_sent": bool(r[8]),
            "created_at": r[9],
        }
        for r in rows
    ]


def build_note_datagram(note: dict) -> bytes:
    doc = add_hermes_envelope(
        {
            "c": note["category"],
            "s": note["title"],
            "m": note["body"],
            "a": note["author"],
            "r": note["priority"],
            "l": note["location"],
        },
        "NOTE",
    )
    while True:
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= 163:
            return raw
        if len(doc["m"]) > 20:
            doc["m"] = doc["m"][:-10]
        elif len(doc["s"]) > 12:
            doc["s"] = doc["s"][:-5]
        else:
            return raw[:163]


def insert_noteboard_note(note: dict, transport: str, mesh_sent: bool):
    created_at = now_iso()
    conn = db()
    cur = conn.execute(
        """
        INSERT INTO noteboard_notes (
            category, title, body, author, priority, location,
            transport, mesh_sent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note["category"],
            note["title"],
            note["body"],
            note["author"],
            note["priority"],
            note["location"],
            transport,
            1 if mesh_sent else 0,
            created_at,
        ),
    )
    conn.commit()
    note_id = cur.lastrowid
    conn.close()
    saved = dict(note)
    saved.update(
        {
            "id": note_id,
            "transport": transport,
            "mesh_sent": bool(mesh_sent),
            "created_at": created_at,
        }
    )
    return saved


def create_noteboard_note(note_in: NoteboardNoteIn):
    note = {
        "category": (note_in.category or "notice").strip().lower(),
        "title": note_in.title.strip(),
        "body": note_in.body.strip(),
        "author": note_in.author.strip() or "local",
        "priority": (note_in.priority or "normal").strip().lower(),
        "location": note_in.location.strip(),
    }
    if not note["title"] or not note["body"]:
        raise ValueError("title and body are required")

    transport = "local"
    mesh_sent = False
    if note_in.send_mesh:
        companion_queue_channel_data(HERMES_DATA_TYPE_NOTE, build_note_datagram(note))
        transport = "meshcore-data"
        mesh_sent = True

    saved = insert_noteboard_note(note, transport, mesh_sent)
    insert_event(
        event_type="NOTE",
        source_node=saved["author"],
        region="local",
        payload=saved,
        transport=transport,
        raw_message=f"[{saved['category']}] {saved['title']}",
    )
    return saved


def classify_message(text, raw_hex):
    upper = (text or "").upper()
    if "SOS" in upper:
        return "SOS"
    if "SAFE" in upper:
        return "SAFE"
    if "NEED" in upper:
        return "NEED"
    if "STATUS" in upper:
        return "STATUS"
    if "RESOURCE" in upper:
        return "RESOURCE"
    if "HEARTBEAT" in upper:
        return "HEARTBEAT"
    if raw_hex:
        return "MESHCORE_FRAME"
    return "MESSAGE"


def kiss_unescape(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == FESC and i + 1 < len(data):
            nxt = data[i + 1]
            if nxt == TFEND:
                out.append(FEND)
            elif nxt == TFESC:
                out.append(FESC)
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


def kiss_escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == FEND:
            out.extend([FESC, TFEND])
        elif b == FESC:
            out.extend([FESC, TFESC])
        else:
            out.append(b)
    return bytes(out)


def build_kiss_frame(kiss_cmd: int, payload: bytes = b"") -> bytes:
    type_byte = kiss_cmd & 0x0F
    return bytes([FEND]) + kiss_escape(bytes([type_byte]) + payload) + bytes([FEND])


def queue_hardware_request(subcmd: int, data: bytes = b""):
    tx_queue.put(build_kiss_frame(KISS_CMD_SETHARDWARE, bytes([subcmd]) + data))
    insert_event(
        event_type="RADIO_QUERY",
        source_node="hermes-core",
        region="local",
        payload={"subcmd": subcmd},
        transport="meshcore-kiss",
        raw_message=f"hardware query 0x{subcmd:02x}",
    )


def queue_set_radio(freq_hz: int, bw_hz: int, sf: int, cr: int):
    payload = struct.pack("<IIBB", freq_hz, bw_hz, sf, cr)
    tx_queue.put(build_kiss_frame(KISS_CMD_SETHARDWARE, bytes([0x09]) + payload))
    insert_event(
        event_type="RADIO_CONFIG_SET",
        source_node="hermes-core",
        region="local",
        payload={"freq_hz": freq_hz, "bw_hz": bw_hz, "sf": sf, "cr": cr},
        transport="meshcore-kiss",
        raw_message=f"set radio {freq_hz}Hz bw={bw_hz} sf={sf} cr={cr}",
    )


def queue_set_tx_power(power_dbm: int):
    tx_queue.put(build_kiss_frame(KISS_CMD_SETHARDWARE, bytes([0x0A, power_dbm & 0xFF])))
    insert_event(
        event_type="RADIO_CONFIG_SET",
        source_node="hermes-core",
        region="local",
        payload={"tx_power_dbm": power_dbm},
        transport="meshcore-kiss",
        raw_message=f"set tx power {power_dbm}dBm",
    )


def queue_apply_radio_profile(profile, reason="manual"):
    queue_set_radio(profile["freq_hz"], profile["bw_hz"], profile["sf"], profile["cr"])
    if profile.get("tx_power") is not None:
        queue_set_tx_power(profile["tx_power"])

    radio_state["current_profile"] = profile
    radio_state["last_config_apply_at"] = now_iso()

    insert_event(
        event_type="RADIO_PROFILE_APPLY",
        source_node="hermes-core",
        region="local",
        payload={"profile": profile, "reason": reason},
        transport="meshcore-kiss",
        raw_message=f"apply profile {profile.get('name', 'unnamed')}",
    )

    for subcmd in (
        HW_PING,
        HW_GET_DEVICE_NAME,
        HW_GET_VERSION,
        HW_GET_RADIO,
        HW_GET_TX_POWER,
        HW_GET_CURRENT_RSSI,
        HW_GET_NOISE_FLOOR,
        HW_GET_STATS,
        HW_GET_BATTERY,
        HW_GET_MCU_TEMP,
        HW_GET_SIGNAL_REPORT,
    ):
        queue_hardware_request(subcmd)


def build_companion_frame(payload: bytes) -> bytes:
    if len(payload) > 176:
        raise ValueError("companion frame too large")
    return b"<" + struct.pack("<H", len(payload)) + payload


def queue_companion_payload(payload: bytes, label: str):
    tx_queue.put(build_companion_frame(payload))
    insert_event(
        event_type="COMPANION_TX",
        source_node="hermes-core",
        region="local",
        payload={"cmd": payload[0] if payload else None, "len": len(payload)},
        transport="meshcore-companion-usb",
        raw_message=label,
    )


def pad_fixed_utf8(text: str, size: int) -> bytes:
    raw = text.encode("utf-8")[:size]
    return raw + (b"\x00" * (size - len(raw)))


def companion_queue_startup(reason="serial_open"):
    channel = get_channel_config()
    profile = get_radio_profile()
    now = int(time.time())

    queue_companion_payload(
        bytes([COMP_CMD_APP_START]) + b"\x00" * 7 + b"HermesCore",
        f"app start ({reason})",
    )
    queue_companion_payload(bytes([COMP_CMD_DEVICE_QUERY, 0x03]), "device query")
    queue_companion_payload(bytes([COMP_CMD_SET_DEVICE_TIME]) + struct.pack("<I", now), "set device time")
    companion_queue_apply_radio_profile(profile, reason=reason)
    companion_queue_set_channel(channel, reason=reason)
    for idx in range(8):
        queue_companion_payload(bytes([COMP_CMD_GET_CHANNEL, idx]), f"get channel {idx}")
    queue_companion_payload(bytes([COMP_CMD_GET_BATT_AND_STORAGE]), "get battery")
    queue_companion_payload(bytes([COMP_CMD_SYNC_NEXT_MESSAGE]), "sync next message")


def companion_queue_apply_radio_profile(profile, reason="manual"):
    freq_khz = int(profile["freq_hz"] // 1000)
    bw_hz = int(profile["bw_hz"])
    payload = bytes([COMP_CMD_SET_RADIO_PARAMS]) + struct.pack(
        "<IIBB", freq_khz, bw_hz, int(profile["sf"]), int(profile["cr"])
    )
    queue_companion_payload(payload, f"set radio {freq_khz}kHz bw={bw_hz} sf={profile['sf']} cr={profile['cr']}")
    if profile.get("tx_power") is not None:
        queue_companion_payload(
            bytes([COMP_CMD_SET_RADIO_TX_POWER, int(profile["tx_power"]) & 0xFF]),
            f"set tx power {profile['tx_power']}dBm",
        )

    radio_state["current_profile"] = profile
    radio_state["last_config_apply_at"] = now_iso()
    insert_event(
        event_type="RADIO_PROFILE_APPLY",
        source_node="hermes-core",
        region="local",
        payload={"profile": profile, "reason": reason},
        transport="meshcore-companion-usb",
        raw_message=f"apply profile {profile.get('name', 'unnamed')}",
    )


def companion_queue_set_channel(channel, reason="manual"):
    secret = bytes.fromhex(channel["secret_hex"])
    if len(secret) != 16:
        raise ValueError("MeshCore channel secret must be 16 bytes")
    idx = int(channel["index"])
    payload = (
        bytes([COMP_CMD_SET_CHANNEL, idx])
        + pad_fixed_utf8(channel["name"], 32)
        + secret
    )
    queue_companion_payload(payload, f"set channel {idx} {channel['name']} ({reason})")
    radio_state["active_channel"] = {"index": idx, "name": channel["name"]}


def companion_queue_channel_message(message: str, channel_index: int | None = None):
    channel = get_channel_config()
    idx = int(channel["index"] if channel_index is None else channel_index)
    text = message.encode("utf-8")[:133]
    payload = (
        bytes([COMP_CMD_SEND_CHANNEL_TXT_MSG, 0x00, idx])
        + struct.pack("<I", int(time.time()))
        + text
    )
    queue_companion_payload(payload, f"send channel {idx}: {message[:80]}")


def companion_queue_channel_data(data_type: int, payload_bytes: bytes, channel_index: int | None = None):
    channel = get_channel_config()
    idx = int(channel["index"] if channel_index is None else channel_index)
    payload_bytes = payload_bytes[:163]
    payload = (
        bytes([COMP_CMD_SEND_CHANNEL_DATA, idx, 0xFF])
        + struct.pack("<H", data_type)
        + payload_bytes
    )
    queue_companion_payload(payload, f"send data channel {idx} type=0x{data_type:04x} len={len(payload_bytes)}")


def build_event_datagram(event_type: str, message: str, source_node: str = "dashboard", region: str = "local") -> bytes:
    doc = add_hermes_envelope(
        {
            "k": event_type,
            "m": message,
            "a": source_node,
            "l": region,
        },
        "EVENT",
    )
    while True:
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= 163:
            return raw
        if len(doc["m"]) > 20:
            doc["m"] = doc["m"][:-10]
        else:
            return raw[:163]


def build_bbs_datagram(
    board: str,
    kind: str,
    title: str,
    body: str,
    author: str,
    priority: str,
    location: str,
) -> bytes:
    doc = add_hermes_envelope(
        {
            "b": board,
            "k": kind,
            "s": title,
            "m": body,
            "a": author,
            "r": priority,
            "l": location,
        },
        "BBS_POST",
    )
    while True:
        raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= 163:
            return raw
        if len(doc["m"]) > 20:
            doc["m"] = doc["m"][:-10]
        elif len(doc["s"]) > 12:
            doc["s"] = doc["s"][:-5]
        else:
            return raw[:163]


def parse_c_string(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def as_i8(value: int) -> int:
    return struct.unpack("b", bytes([value]))[0]


def parse_hardware_response(subcmd: int, data: bytes):
    name = f"0x{subcmd:02x}"
    payload = {"subcmd": subcmd, "data_hex": data.hex()}
    event_type = "RADIO_RESPONSE"

    try:
        if subcmd == 0x81:
            name = "Identity"
            radio_state["identity"] = data.hex()
            payload["identity"] = radio_state["identity"]
        elif subcmd == 0x8B and len(data) >= 10:
            name = "Radio"
            freq_hz, bw_hz, sf, cr = struct.unpack("<IIBB", data[:10])
            radio_state["radio"] = {
                "freq_hz": freq_hz,
                "bw_hz": bw_hz,
                "sf": sf,
                "cr": cr,
            }
            payload.update(radio_state["radio"])
        elif subcmd == 0x8C and data:
            name = "TxPower"
            radio_state["tx_power_dbm"] = data[0]
            payload["tx_power_dbm"] = data[0]
        elif subcmd == 0x8D and data:
            name = "CurrentRssi"
            radio_state["current_rssi_dbm"] = as_i8(data[0])
            payload["current_rssi_dbm"] = radio_state["current_rssi_dbm"]
        elif subcmd == 0x90 and len(data) >= 2:
            name = "NoiseFloor"
            radio_state["noise_floor_dbm"] = struct.unpack("<h", data[:2])[0]
            payload["noise_floor_dbm"] = radio_state["noise_floor_dbm"]
        elif subcmd == 0x91 and len(data) >= 2:
            name = "Version"
            radio_state["firmware_version"] = {"version": data[0], "reserved": data[1]}
            payload.update(radio_state["firmware_version"])
        elif subcmd == 0x92 and len(data) >= 12:
            name = "Stats"
            rx, tx, errors = struct.unpack("<III", data[:12])
            radio_state["stats"] = {"rx": rx, "tx": tx, "errors": errors}
            payload.update(radio_state["stats"])
        elif subcmd == 0x93 and len(data) >= 2:
            name = "Battery"
            radio_state["battery_mv"] = struct.unpack("<H", data[:2])[0]
            payload["battery_mv"] = radio_state["battery_mv"]
        elif subcmd == 0x94 and len(data) >= 2:
            name = "MCUTemp"
            radio_state["mcu_temp_c"] = struct.unpack("<h", data[:2])[0] / 10.0
            payload["mcu_temp_c"] = radio_state["mcu_temp_c"]
        elif subcmd == 0x96:
            name = "DeviceName"
            radio_state["device_name"] = data.decode("utf-8", errors="replace")
            payload["device_name"] = radio_state["device_name"]
        elif subcmd == 0x97:
            name = "Pong"
            radio_state["last_pong_at"] = now_iso()
            payload["pong"] = True
        elif subcmd == 0x9A and data:
            name = "SignalReport"
            radio_state["signal_report_enabled"] = data[0] != 0
            payload["signal_report_enabled"] = radio_state["signal_report_enabled"]
        elif subcmd == 0xF1 and data:
            name = "Error"
            event_type = "RADIO_ERROR"
            radio_state["last_error"] = data[0]
            payload["error_code"] = data[0]
        elif subcmd == 0xF8 and data:
            name = "TxDone"
            event_type = "RADIO_TX_DONE"
            payload["success"] = data[0] == 1
        elif subcmd == 0xF9 and len(data) >= 2:
            name = "RxMeta"
            event_type = "RADIO_RX_META"
            radio_state["last_rx_meta"] = {
                "snr_db": as_i8(data[0]) / 4.0,
                "rssi_dbm": as_i8(data[1]),
            }
            payload.update(radio_state["last_rx_meta"])
    except Exception as exc:
        event_type = "RADIO_PARSE_ERROR"
        payload["error"] = str(exc)

    insert_event(
        event_type=event_type,
        source_node="meshcore-radio",
        region="local",
        payload=payload,
        transport="meshcore-kiss",
        raw_message=name,
    )
    print(f"radio {name}: {payload}")


def handle_kiss_frame(decoded: bytes):
    if not decoded:
        return

    serial_state["frames_rx"] += 1
    type_byte = decoded[0]
    kiss_cmd = type_byte & 0x0F
    payload = decoded[1:]

    if kiss_cmd == KISS_CMD_DATA:
        raw_hex = decoded.hex()
        text = payload.decode("utf-8", errors="ignore").strip()
        event_type = classify_message(text, raw_hex)

        insert_event(
            event_type=event_type,
            source_node="meshcore-radio",
            region="local",
            payload={
                "kiss_cmd": kiss_cmd,
                "text": text,
                "raw_hex": raw_hex,
            },
            transport="meshcore-kiss",
            raw_message=text or raw_hex,
        )
        print(f"stored {event_type}: {text or raw_hex[:80]}")
        return

    if kiss_cmd == KISS_CMD_SETHARDWARE and payload:
        parse_hardware_response(payload[0], payload[1:])
        return

    insert_event(
        event_type="KISS_FRAME",
        source_node="meshcore-radio",
        region="local",
        payload={"kiss_cmd": kiss_cmd, "raw_hex": decoded.hex()},
        transport="meshcore-kiss",
        raw_message=decoded.hex(),
    )


def parse_companion_channel_message(data: bytes):
    packet_type = data[0]
    offset = 1
    snr = None
    if packet_type == COMP_PACKET_CHANNEL_MSG_RECV_V3:
        snr = as_i8(data[offset]) / 4.0
        offset += 3
    if len(data) < offset + 7:
        return None
    channel_idx = data[offset]
    path_len = data[offset + 1]
    txt_type = data[offset + 2]
    timestamp = struct.unpack("<I", data[offset + 3 : offset + 7])[0]
    message = data[offset + 7 :].decode("utf-8", errors="replace").strip()
    return {
        "channel_idx": channel_idx,
        "path_len": path_len,
        "txt_type": txt_type,
        "timestamp": timestamp,
        "message": message,
        "snr": snr,
    }


def parse_companion_channel_data(data: bytes):
    if len(data) < 9:
        return None
    data_len = data[8]
    if len(data) < 9 + data_len:
        return None
    return {
        "snr": as_i8(data[1]) / 4.0,
        "channel_idx": data[4],
        "path_len": data[5],
        "data_type": struct.unpack("<H", data[6:8])[0],
        "data_hex": data[9 : 9 + data_len].hex(),
        "payload_bytes": data[9 : 9 + data_len],
    }


def handle_hermes_channel_data(parsed):
    if parsed.get("data_type") not in (HERMES_DATA_TYPE_BBS, HERMES_DATA_TYPE_NOTE, HERMES_DATA_TYPE_EVENT):
        return None

    raw = parsed["payload_bytes"]
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {
            "event_type": "BBS_DATA_ERROR",
            "payload": {"error": str(exc), "data_hex": raw.hex()},
            "raw_message": "invalid BBS datagram",
        }

    if doc.get("p") != HERMES_PROTOCOL_CODE:
        return {
            "event_type": "HERMES_DATA",
            "payload": {"data_type": parsed.get("data_type"), "doc": doc},
            "raw_message": "unknown Hermes datagram",
        }

    meta = hermes_message_meta(doc)
    if meta["message_id"] and meta["origin_core"] == get_core_id():
        return {
            "event_type": "HERMES_LOOPBACK",
            "payload": {"data_type": parsed.get("data_type"), "meta": meta},
            "raw_message": f"drop loopback {meta['message_id']}",
        }
    if meta["message_id"] and not mark_seen_message(
        meta["message_id"],
        meta["origin_core"],
        meta["via_core"],
        "meshcore-data",
        meta["packet_type"],
    ):
        return {
            "event_type": "HERMES_DUPLICATE",
            "payload": {"data_type": parsed.get("data_type"), "meta": meta},
            "raw_message": f"drop duplicate {meta['message_id']}",
        }

    if parsed.get("data_type") == HERMES_DATA_TYPE_EVENT and meta["packet_type"] == "EVENT":
        event_type = str(doc.get("k") or "MESSAGE").strip().upper()
        message = str(doc.get("m") or "").strip()
        source_node = str(doc.get("a") or f"core-{meta['origin_core'] or 'unknown'}").strip()
        region = str(doc.get("l") or "mesh").strip()
        return {
            "event_type": event_type,
            "payload": {
                "message": message,
                "source_node": source_node,
                "region": region,
                "data_type": parsed.get("data_type"),
                "snr": parsed.get("snr"),
                "meta": meta,
            },
            "raw_message": message or event_type,
        }

    if parsed.get("data_type") == HERMES_DATA_TYPE_NOTE and meta["packet_type"] == "NOTE":
        note = {
            "category": str(doc.get("c") or "notice").strip().lower(),
            "title": str(doc.get("s") or "Untitled").strip(),
            "body": str(doc.get("m") or "").strip() or "(empty)",
            "author": str(doc.get("a") or "meshcore").strip(),
            "priority": str(doc.get("r") or "normal").strip().lower(),
            "location": str(doc.get("l") or "").strip(),
        }
        try:
            saved = insert_noteboard_note(note, "meshcore-data", False)
        except Exception as exc:
            return {
                "event_type": "NOTE_DATA_ERROR",
                "payload": {"error": str(exc), "doc": doc},
                "raw_message": f"Note data rejected: {note['title']}",
            }
        return {
            "event_type": "NOTE",
            "payload": {"note": saved, "data_type": parsed.get("data_type"), "snr": parsed.get("snr"), "meta": meta},
            "raw_message": f"[{saved['category']}] {saved['title']}",
        }

    if parsed.get("data_type") != HERMES_DATA_TYPE_BBS or meta["packet_type"] != "BBS_POST":
        return {
            "event_type": "HERMES_DATA",
            "payload": {"data_type": parsed.get("data_type"), "doc": doc},
            "raw_message": "unknown Hermes datagram",
        }

    board = str(doc.get("b") or "general").strip().lower()
    kind = str(doc.get("k") or "post").strip().lower()
    title = str(doc.get("s") or "Untitled").strip()
    body = str(doc.get("m") or "").strip()
    author = str(doc.get("a") or "meshcore").strip()
    priority = str(doc.get("r") or "normal").strip().lower()
    location = str(doc.get("l") or "").strip()

    try:
        conn = db()
        exists = conn.execute("SELECT 1 FROM bbs_boards WHERE name = ?", (board,)).fetchone()
        if not exists:
            board = "general"
        created_at = now_iso()
        cur = conn.execute(
            """
            INSERT INTO bbs_posts (board, kind, title, body, author, priority, location, transport, mesh_sent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (board, kind, title, body or "(empty)", author, priority, location, "meshcore-data", 0, created_at),
        )
        conn.commit()
        post_id = cur.lastrowid
        conn.close()
        post = {
            "id": post_id,
            "board": board,
            "kind": kind,
            "title": title,
            "body": body or "(empty)",
            "author": author,
            "priority": priority,
            "location": location,
            "transport": "meshcore-data",
            "mesh_sent": False,
            "created_at": created_at,
        }
    except Exception as exc:
        return {
            "event_type": "BBS_DATA_ERROR",
            "payload": {"error": str(exc), "doc": doc},
            "raw_message": f"BBS data rejected: {title}",
        }

    return {
        "event_type": "BBS_POST",
        "payload": {"post": post, "data_type": parsed.get("data_type"), "snr": parsed.get("snr"), "meta": meta},
        "raw_message": f"[{board}] {title}",
    }


def parse_companion_frame(frame: bytes):
    if not frame:
        return

    serial_state["frames_rx"] += 1
    packet_type = frame[0]
    payload = {"packet_type": packet_type, "raw_hex": frame.hex()}
    event_type = "COMPANION_RX"
    raw_message = f"packet 0x{packet_type:02x}"

    try:
        if packet_type == COMP_PACKET_OK:
            event_type = "RADIO_OK"
            raw_message = "OK"
        elif packet_type == COMP_PACKET_ERROR:
            event_type = "RADIO_ERROR"
            radio_state["last_error"] = frame[1] if len(frame) > 1 else None
            payload["error_code"] = radio_state["last_error"]
            raw_message = f"Error {radio_state['last_error']}"
        elif packet_type == COMP_PACKET_SELF_INFO and len(frame) >= 58:
            event_type = "RADIO_RESPONSE"
            raw_message = "SelfInfo"
            radio_state["tx_power_dbm"] = frame[2]
            radio_state["identity"] = frame[4:36].hex()
            radio_state["public_key"] = radio_state["identity"]
            radio_state["radio"] = {
                "freq_hz": struct.unpack("<I", frame[48:52])[0] * 1000,
                "bw_hz": struct.unpack("<I", frame[52:56])[0],
                "sf": frame[56],
                "cr": frame[57],
            }
            if len(frame) > 58:
                radio_state["device_name"] = frame[58:].decode("utf-8", errors="replace").strip()
            payload.update(
                {
                    "identity": radio_state["identity"],
                    "device_name": radio_state["device_name"],
                    "radio": radio_state["radio"],
                    "tx_power_dbm": radio_state["tx_power_dbm"],
                }
            )
        elif packet_type == COMP_PACKET_DEVICE_INFO and len(frame) >= 2:
            event_type = "RADIO_RESPONSE"
            raw_message = "DeviceInfo"
            info = {"fw_ver": frame[1]}
            if frame[1] >= 3 and len(frame) >= 80:
                info.update(
                    {
                        "max_contacts": frame[2] * 2,
                        "max_channels": frame[3],
                        "ble_pin": struct.unpack("<I", frame[4:8])[0],
                        "fw_build": parse_c_string(frame[8:20]),
                        "model": parse_c_string(frame[20:60]),
                        "version": parse_c_string(frame[60:80]),
                    }
                )
                radio_state["firmware_version"] = info.get("version") or info["fw_ver"]
                radio_state["device_name"] = info.get("model") or radio_state["device_name"]
            radio_state["device_info"] = info
            payload.update(info)
        elif packet_type == COMP_PACKET_CHANNEL_INFO and len(frame) >= 50:
            event_type = "RADIO_RESPONSE"
            idx = frame[1]
            channel = {
                "index": idx,
                "name": parse_c_string(frame[2:34]),
                "secret_hex": frame[34:50].hex(),
            }
            radio_state["channels"][str(idx)] = channel
            raw_message = f"Channel {idx}: {channel['name'] or '-'}"
            payload.update(channel)
        elif packet_type == COMP_PACKET_BATTERY and len(frame) >= 3:
            event_type = "RADIO_RESPONSE"
            raw_message = "Battery"
            radio_state["battery_mv"] = struct.unpack("<H", frame[1:3])[0]
            payload["battery_mv"] = radio_state["battery_mv"]
            if len(frame) >= 11:
                payload["storage_used_kb"] = struct.unpack("<I", frame[3:7])[0]
                payload["storage_total_kb"] = struct.unpack("<I", frame[7:11])[0]
        elif packet_type in (COMP_PACKET_CHANNEL_MSG_RECV, COMP_PACKET_CHANNEL_MSG_RECV_V3):
            parsed = parse_companion_channel_message(frame)
            if parsed:
                text = parsed["message"]
                event_type = classify_message(text, frame.hex())
                payload.update(parsed)
                raw_message = text
        elif packet_type == COMP_PACKET_CHANNEL_DATA_RECV:
            parsed = parse_companion_channel_data(frame)
            if parsed:
                event_type = "MESHCORE_CHANNEL_DATA"
                payload.update({k: v for k, v in parsed.items() if k != "payload_bytes"})
                hermes = handle_hermes_channel_data(parsed)
                if hermes:
                    event_type = hermes["event_type"]
                    payload.update(hermes["payload"])
                    raw_message = hermes["raw_message"]
                else:
                    raw_message = parsed["data_hex"]
        elif packet_type == COMP_PACKET_MESSAGES_WAITING:
            event_type = "MESSAGES_WAITING"
            raw_message = "messages waiting"
            queue_companion_payload(bytes([COMP_CMD_SYNC_NEXT_MESSAGE]), "sync next message")
        elif packet_type == COMP_PACKET_NO_MORE_MESSAGES:
            event_type = "NO_MORE_MESSAGES"
            raw_message = "no more messages"
        elif packet_type == COMP_PACKET_MSG_SENT:
            event_type = "RADIO_TX_DONE"
            raw_message = "message sent"
        elif packet_type == COMP_PACKET_LOG_DATA:
            event_type = "RADIO_LOG"
            raw_message = frame[1:].decode("utf-8", errors="ignore").strip() or "log"
    except Exception as exc:
        event_type = "RADIO_PARSE_ERROR"
        payload["error"] = str(exc)

    insert_event(
        event_type=event_type,
        source_node="meshcore-radio",
        region="local",
        payload=payload,
        transport="meshcore-companion-usb",
        raw_message=raw_message,
    )
    print(f"companion {raw_message}: {payload}")


def serial_reader_kiss():
    while True:
        try:
            print(f"opening serial {SERIAL_PORT} {SERIAL_BAUD}")
            with serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1) as ser:
                serial_state["connected"] = True
                serial_state["last_error"] = None
                serial_state["last_opened_at"] = now_iso()
                if AUTO_APPLY_RADIO_PROFILE:
                    queue_apply_radio_profile(get_radio_profile(), reason="serial_open")
                frame = bytearray()
                in_frame = False

                while True:
                    while True:
                        try:
                            outgoing = tx_queue.get_nowait()
                        except queue.Empty:
                            break
                        ser.write(outgoing)
                        serial_state["frames_tx"] += 1
                        print(f"sent kiss frame: {outgoing.hex()}")

                    b = ser.read(1)
                    if not b:
                        continue

                    val = b[0]

                    if val == FEND:
                        if in_frame and frame:
                            decoded = kiss_unescape(bytes(frame))
                            handle_kiss_frame(decoded)

                        frame = bytearray()
                        in_frame = True
                    elif in_frame:
                        frame.append(val)

        except Exception as e:
            serial_state["connected"] = False
            serial_state["last_error"] = str(e)
            print(f"serial error: {e}")
            time.sleep(3)


def serial_reader_companion():
    while True:
        try:
            print(f"opening companion serial {SERIAL_PORT} {SERIAL_BAUD}")
            with serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.2) as ser:
                serial_state["connected"] = True
                serial_state["transport"] = "companion_usb"
                serial_state["last_error"] = None
                serial_state["last_opened_at"] = now_iso()
                companion_queue_startup(reason="serial_open")

                rx_state = 0
                frame_len = 0
                frame = bytearray()
                last_poll = 0.0
                last_battery = 0.0

                while True:
                    while True:
                        try:
                            outgoing = tx_queue.get_nowait()
                        except queue.Empty:
                            break
                        ser.write(outgoing)
                        serial_state["frames_tx"] += 1
                        serial_state["last_tx_hex"] = outgoing.hex()
                        print(f"sent companion frame: {outgoing.hex()}")
                        time.sleep(0.08)

                    now = time.time()
                    if now - last_poll > 5:
                        queue_companion_payload(bytes([COMP_CMD_SYNC_NEXT_MESSAGE]), "poll sync next message")
                        last_poll = now
                    if now - last_battery > 60:
                        queue_companion_payload(bytes([COMP_CMD_GET_BATT_AND_STORAGE]), "poll battery")
                        last_battery = now

                    b = ser.read(1)
                    if not b:
                        continue
                    val = b[0]
                    serial_state["last_rx_byte_hex"] = f"{val:02x}"

                    if rx_state == 0:
                        if val == ord(">"):
                            serial_state["last_rx_header_at"] = now_iso()
                            rx_state = 1
                        else:
                            serial_state["rx_discarded_bytes"] += 1
                    elif rx_state == 1:
                        frame_len = val
                        rx_state = 2
                    elif rx_state == 2:
                        frame_len |= val << 8
                        frame = bytearray()
                        rx_state = 3 if frame_len > 0 else 0
                    else:
                        frame.append(val)
                        if len(frame) >= frame_len:
                            serial_state["last_rx_frame_at"] = now_iso()
                            parse_companion_frame(bytes(frame))
                            rx_state = 0

        except Exception as e:
            serial_state["connected"] = False
            serial_state["last_error"] = str(e)
            print(f"companion serial error: {e}")
            time.sleep(3)


def serial_reader():
    if TRANSPORT_MODE == "companion_usb":
        serial_reader_companion()
    else:
        serial_reader_kiss()


@app.on_event("startup")
def startup():
    init_db()
    threading.Thread(target=serial_reader, daemon=True).start()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "core_id": get_core_id(),
        "serial_port": SERIAL_PORT,
        "baud": SERIAL_BAUD,
        "serial": serial_state,
    }


@app.get("/api/radio")
def radio():
    return {
        "serial": serial_state,
        "radio": radio_state,
        "config": load_config(),
        "pending_tx": tx_queue.qsize(),
    }


@app.post("/api/radio/probe")
def probe_radio():
    radio_state["last_probe_at"] = now_iso()
    if TRANSPORT_MODE == "companion_usb":
        queue_companion_payload(bytes([COMP_CMD_APP_START]) + b"\x00" * 7 + b"HermesCore", "app start")
        queue_companion_payload(bytes([COMP_CMD_DEVICE_QUERY, 0x03]), "device query")
        for idx in range(8):
            queue_companion_payload(bytes([COMP_CMD_GET_CHANNEL, idx]), f"get channel {idx}")
        queue_companion_payload(bytes([COMP_CMD_GET_BATT_AND_STORAGE]), "get battery")
        queue_companion_payload(bytes([COMP_CMD_SYNC_NEXT_MESSAGE]), "sync next message")
        return {"status": "queued", "transport": TRANSPORT_MODE, "pending_tx": tx_queue.qsize()}

    for subcmd in (
        HW_PING,
        HW_GET_DEVICE_NAME,
        HW_GET_VERSION,
        HW_GET_IDENTITY,
        HW_GET_RADIO,
        HW_GET_TX_POWER,
        HW_GET_CURRENT_RSSI,
        HW_GET_NOISE_FLOOR,
        HW_GET_STATS,
        HW_GET_BATTERY,
        HW_GET_MCU_TEMP,
        HW_GET_SIGNAL_REPORT,
    ):
        queue_hardware_request(subcmd)
    return {"status": "queued", "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/companion/app-start")
def companion_app_start():
    queue_companion_payload(
        bytes([COMP_CMD_APP_START]) + b"\x00" * 7 + b"HermesCore",
        "manual app start",
    )
    return {"status": "queued", "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/query")
def query_radio(query: RadioQueryIn):
    commands = {
        "ping": HW_PING,
        "device_name": HW_GET_DEVICE_NAME,
        "version": HW_GET_VERSION,
        "identity": HW_GET_IDENTITY,
        "radio": HW_GET_RADIO,
        "tx_power": HW_GET_TX_POWER,
        "rssi": HW_GET_CURRENT_RSSI,
        "noise_floor": HW_GET_NOISE_FLOOR,
        "stats": HW_GET_STATS,
        "battery": HW_GET_BATTERY,
        "mcu_temp": HW_GET_MCU_TEMP,
        "signal_report": HW_GET_SIGNAL_REPORT,
    }
    key = query.command.strip().lower()
    if key not in commands:
        return {"status": "unknown_command", "command": query.command, "known": sorted(commands)}
    queue_hardware_request(commands[key])
    return {"status": "queued", "command": key, "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/config")
def configure_radio(config: RadioConfigIn):
    if not 400_000_000 <= config.freq_hz <= 1_000_000_000:
        return {"status": "invalid", "field": "freq_hz"}
    if config.bw_hz not in (31_250, 62_500, 125_000, 250_000, 500_000):
        return {"status": "invalid", "field": "bw_hz"}
    if not 5 <= config.sf <= 12:
        return {"status": "invalid", "field": "sf"}
    if not 5 <= config.cr <= 8:
        return {"status": "invalid", "field": "cr"}
    if config.tx_power is not None and not 0 <= config.tx_power <= 22:
        return {"status": "invalid", "field": "tx_power"}

    profile = set_radio_profile(
        {
            "name": "CUSTOM",
            "freq_hz": config.freq_hz,
            "bw_hz": config.bw_hz,
            "sf": config.sf,
            "cr": config.cr,
            "tx_power": config.tx_power,
        }
    )
    if TRANSPORT_MODE == "companion_usb":
        companion_queue_apply_radio_profile(profile, reason="api_config")
    else:
        queue_apply_radio_profile(profile, reason="api_config")

    return {"status": "queued", "profile": profile, "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/config/as923")
def configure_as923():
    profile = set_radio_profile(DEFAULT_RADIO_PROFILE)
    if TRANSPORT_MODE == "companion_usb":
        companion_queue_apply_radio_profile(profile, reason="api_as923")
    else:
        queue_apply_radio_profile(profile, reason="api_as923")
    return {"status": "queued", "profile": profile, "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/channel/apply")
def apply_channel():
    channel = get_channel_config()
    companion_queue_set_channel(channel, reason="api_channel_apply")
    queue_companion_payload(bytes([COMP_CMD_GET_CHANNEL, int(channel["index"])]), "get active channel")
    return {"status": "queued", "channel": {"index": channel["index"], "name": channel["name"]}, "pending_tx": tx_queue.qsize()}


@app.post("/api/radio/channel")
def configure_channel(channel: ChannelConfigIn):
    try:
        saved = set_channel_config(
            {
                "name": channel.name,
                "index": channel.index,
                "secret_hex": channel.secret_hex,
            }
        )
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc)}

    if TRANSPORT_MODE == "companion_usb":
        companion_queue_set_channel(saved, reason="api_channel_config")
        queue_companion_payload(bytes([COMP_CMD_GET_CHANNEL, int(saved["index"])]), "get active channel")
    return {
        "status": "queued",
        "channel": {"index": saved["index"], "name": saved["name"]},
        "pending_tx": tx_queue.qsize(),
    }


@app.post("/api/mesh/send")
def send_mesh_message(message: MeshMessageIn):
    text = message.message.strip()
    if not text:
        return {"status": "invalid", "field": "message"}
    if TRANSPORT_MODE != "companion_usb":
        return {"status": "unsupported_transport", "transport": TRANSPORT_MODE}

    companion_queue_channel_message(text, message.channel_index)
    event_type = classify_message(text, "")
    if event_type in {"SAFE", "SOS", "NEED", "STATUS", "RESOURCE", "HEARTBEAT"}:
        companion_queue_channel_data(
            HERMES_DATA_TYPE_EVENT,
            build_event_datagram(event_type, text, source_node="dashboard", region="local"),
            message.channel_index,
        )
    insert_event(
        event_type=event_type,
        source_node="dashboard",
        region="local",
        payload={
            "message": text,
            "channel_index": message.channel_index or get_channel_config()["index"],
            "core_id": get_core_id(),
        },
        transport="meshcore-companion-usb",
        raw_message=text,
    )
    return {"status": "queued", "event_type": event_type, "pending_tx": tx_queue.qsize()}


@app.get("/api/bbs/boards")
def api_bbs_boards():
    return list_bbs_boards()


@app.post("/api/bbs/boards")
def api_create_bbs_board(board: BbsBoardIn):
    name = board.name.strip().lower()
    if not name:
        return {"status": "invalid", "field": "name"}
    conn = db()
    conn.execute(
        """
        INSERT OR IGNORE INTO bbs_boards (name, title, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name, board.title.strip() or name, board.description.strip(), now_iso()),
    )
    conn.commit()
    conn.close()
    return {"status": "stored", "board": name}


@app.get("/api/bbs/posts")
def api_bbs_posts(board: str | None = None, limit: int = 50):
    return list_bbs_posts(board=board, limit=limit)


@app.post("/api/bbs/posts")
def api_create_bbs_post(post: BbsPostIn):
    try:
        saved = create_bbs_post(post)
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc)}
    return {"status": "stored", "post": saved, "pending_tx": tx_queue.qsize()}


@app.get("/api/noteboard/notes")
def api_noteboard_notes(category: str | None = None, limit: int = 80):
    return list_noteboard_notes(category=category, limit=limit)


@app.post("/api/noteboard/notes")
def api_create_noteboard_note(note: NoteboardNoteIn):
    try:
        saved = create_noteboard_note(note)
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc)}
    return {"status": "stored", "note": saved, "pending_tx": tx_queue.qsize()}


@app.get("/bbs", response_class=HTMLResponse)
def bbs_page():
    return """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes BBS</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #657180;
      --line: #d9e0e7;
      --accent: #0f766e;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    nav { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    a { color: var(--accent); text-decoration: none; }
    main {
      width: min(1180px, calc(100% - 32px));
      margin: 20px auto 40px;
    }
    .layout {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .toolbar, .form-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    .toolbar { margin-bottom: 14px; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      cursor: pointer;
    }
    button.primary { border-color: var(--accent); background: var(--accent); color: #fff; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 14px;
      background: #fff;
    }
    textarea { min-height: 120px; resize: vertical; }
    label { display: block; color: var(--muted); font-size: 13px; margin: 10px 0 6px; }
    .status { color: var(--muted); font-size: 14px; margin-left: auto; }
    .board {
      width: 100%;
      text-align: left;
      margin-bottom: 8px;
      border-color: var(--line);
    }
    .board.active {
      border-color: var(--accent);
      background: #e8f6f3;
    }
    .post {
      border-bottom: 1px solid var(--line);
      padding: 13px 0;
    }
    .post:first-child { padding-top: 0; }
    .post:last-child { border-bottom: 0; }
    .post h3 { margin: 0 0 6px; font-size: 18px; letter-spacing: 0; }
    .meta { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
    .body { white-space: pre-wrap; line-height: 1.5; }
    .empty { color: var(--muted); padding: 12px 0; }
    .checkbox {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      margin-top: 10px;
    }
    .checkbox input { width: auto; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      .layout { grid-template-columns: 1fr; }
      .status { margin-left: 0; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Hermes BBS</h1>
    <nav>
      <a href="/">儀表板</a>
      <a href="/meshcore">MeshCore 管理</a>
      <span class="mono">MeshBBS MVP</span>
    </nav>
  </header>

  <main>
    <div class="toolbar">
      <button class="primary" onclick="refresh()">重新整理</button>
      <span id="status" class="status">載入中...</span>
    </div>

    <section class="layout">
      <aside class="panel">
        <label>看板</label>
        <div id="boards"></div>
      </aside>

      <section>
        <div class="panel">
          <label>新增文章</label>
          <select id="post-board"></select>
          <label>類型</label>
          <select id="post-kind">
            <option value="post">一般文章</option>
            <option value="notice">公告</option>
            <option value="resource">資源</option>
            <option value="shelter">避難</option>
            <option value="request">請求</option>
            <option value="status">狀態</option>
          </select>
          <label>優先級</label>
          <select id="post-priority">
            <option value="normal">一般</option>
            <option value="high">高</option>
            <option value="urgent">緊急</option>
          </select>
          <label>標題</label>
          <input id="post-title" placeholder="主旨">
          <label>內容</label>
          <textarea id="post-body" placeholder="訊息內容"></textarea>
          <label>位置</label>
          <input id="post-location" placeholder="選填，例如 A 棟、避難所、社區名稱">
          <label>作者</label>
          <input id="post-author" placeholder="local" value="local">
          <label class="checkbox">
            <input id="post-send-mesh" type="checkbox" checked>
            送出為 HermesX 資料封包
          </label>
          <div class="toolbar" style="margin: 12px 0 0;">
            <button class="primary" onclick="createPost()">發布</button>
          </div>
        </div>

        <div class="panel" style="margin-top: 14px;">
          <label id="post-heading">文章</label>
          <div id="posts"></div>
        </div>
      </section>
    </section>
  </main>

  <script>
    let currentBoard = 'general';
    let boards = [];

    function setStatus(text) {
      document.getElementById('status').textContent = text;
    }

    function esc(text) {
      return String(text || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[ch]));
    }

    async function refresh() {
      try {
        const [boardData, postData] = await Promise.all([
          fetch('/api/bbs/boards').then(r => r.json()),
          fetch('/api/bbs/posts?board=' + encodeURIComponent(currentBoard)).then(r => r.json()),
        ]);
        boards = boardData;
        renderBoards();
        renderPosts(postData);
        setStatus('已更新 ' + new Date().toLocaleTimeString());
      } catch (err) {
        setStatus('錯誤：' + err.message);
      }
    }

    function renderBoards() {
      document.getElementById('boards').innerHTML = boards.map(board => `
        <button class="board ${board.name === currentBoard ? 'active' : ''}" onclick="selectBoard('${esc(board.name)}')">
          <strong>${esc(board.title)}</strong><br>
          <span class="meta">${esc(board.name)}，${board.post_count} 篇文章</span>
        </button>
      `).join('');

      document.getElementById('post-board').innerHTML = boards.map(board => `
        <option value="${esc(board.name)}" ${board.name === currentBoard ? 'selected' : ''}>${esc(board.title)}</option>
      `).join('');
    }

    function renderPosts(posts) {
      const board = boards.find(item => item.name === currentBoard);
      document.getElementById('post-heading').textContent = board ? board.title + '文章' : '文章';
      document.getElementById('posts').innerHTML = posts.length ? posts.map(post => `
        <article class="post">
          <h3>${esc(post.title)}</h3>
          <div class="meta">#${post.id}，${esc(post.kind)}，${esc(post.priority)}，${esc(post.author)}，${esc(post.created_at)}，${post.mesh_sent ? 'HermesX 已排程送出' : post.transport}</div>
          ${post.location ? `<div class="meta">位置：${esc(post.location)}</div>` : ''}
          <div class="body">${esc(post.body)}</div>
        </article>
      `).join('') : '<div class="empty">目前沒有文章。</div>';
    }

    function selectBoard(name) {
      currentBoard = name;
      refresh();
    }

    async function createPost() {
      const body = {
        board: document.getElementById('post-board').value,
        kind: document.getElementById('post-kind').value,
        title: document.getElementById('post-title').value.trim(),
        body: document.getElementById('post-body').value.trim(),
        author: document.getElementById('post-author').value.trim() || 'local',
        priority: document.getElementById('post-priority').value,
        location: document.getElementById('post-location').value.trim(),
        send_mesh: document.getElementById('post-send-mesh').checked,
      };
      if (!body.title || !body.body) {
        setStatus('請填寫標題與內容');
        return;
      }
      setStatus('發布中...');
      const result = await fetch('/api/bbs/posts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json());

      if (result.status === 'invalid') {
        setStatus(result.error);
        return;
      }

      currentBoard = result.post.board;
      document.getElementById('post-title').value = '';
      document.getElementById('post-body').value = '';
      document.getElementById('post-location').value = '';
      setStatus(result.post.mesh_sent ? '文章已儲存，並已排程送出 HermesX 資料封包' : '文章已儲存在本機');
      refresh();
    }

    refresh();
    setInterval(refresh, 8000);
  </script>
</body>
</html>
    """


@app.get("/noteboard", response_class=HTMLResponse)
def noteboard_page():
    return """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Noteboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #657180;
      --line: #d9e0e7;
      --accent: #0f766e;
      --danger: #b42318;
      --warn: #b54708;
      --ok: #067647;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    nav { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    a { color: var(--accent); text-decoration: none; }
    main {
      width: min(1180px, calc(100% - 32px));
      margin: 20px auto 40px;
    }
    .layout {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .toolbar, .form-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    .toolbar { margin-bottom: 14px; }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      cursor: pointer;
    }
    button.primary { border-color: var(--accent); background: var(--accent); color: #fff; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 14px;
      background: #fff;
    }
    textarea { min-height: 130px; resize: vertical; }
    label { display: block; color: var(--muted); font-size: 13px; margin: 10px 0 6px; }
    .status { color: var(--muted); font-size: 14px; margin-left: auto; }
    .note {
      border-bottom: 1px solid var(--line);
      padding: 13px 0;
    }
    .note:first-child { padding-top: 0; }
    .note:last-child { border-bottom: 0; }
    .note h3 { margin: 0 0 6px; font-size: 18px; letter-spacing: 0; }
    .meta { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
    .body { white-space: pre-wrap; line-height: 1.5; }
    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 6px;
    }
    .priority-urgent { color: var(--danger); border-color: #f1a29b; background: #fff1f0; }
    .priority-high { color: var(--warn); border-color: #f7b27a; background: #fff7ed; }
    .priority-normal { color: var(--ok); border-color: #75c7a0; background: #edfcf2; }
    .empty { color: var(--muted); padding: 12px 0; }
    .checkbox {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text);
      margin-top: 10px;
    }
    .checkbox input { width: auto; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      .layout { grid-template-columns: 1fr; }
      .status { margin-left: 0; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Hermes Noteboard</h1>
    <nav>
      <a href="/">儀表板</a>
      <a href="/bbs">BBS</a>
      <a href="/meshcore">MeshCore 管理</a>
      <span class="mono">MeshBridge 原型</span>
    </nav>
  </header>

  <main>
    <div class="toolbar">
      <button class="primary" onclick="refresh()">重新整理</button>
      <select id="filter-category" style="width:180px;" onchange="refresh()">
        <option value="">全部分類</option>
        <option value="notice">公告</option>
        <option value="resource">資源</option>
        <option value="shelter">避難</option>
        <option value="request">請求</option>
        <option value="status">狀態</option>
      </select>
      <span id="status" class="status">載入中...</span>
    </div>

    <section class="layout">
      <aside class="panel">
        <label>新增便條</label>
        <select id="note-category">
          <option value="notice">公告</option>
          <option value="resource">資源</option>
          <option value="shelter">避難</option>
          <option value="request">請求</option>
          <option value="status">狀態</option>
        </select>
        <label>優先級</label>
        <select id="note-priority">
          <option value="normal">一般</option>
          <option value="high">高</option>
          <option value="urgent">緊急</option>
        </select>
        <label>標題</label>
        <input id="note-title" placeholder="簡短標題">
        <label>內容</label>
        <textarea id="note-body" placeholder="公告、資源、避難或其他現場資訊"></textarea>
        <label>位置</label>
        <input id="note-location" placeholder="選填">
        <label>作者</label>
        <input id="note-author" placeholder="local" value="local">
        <label class="checkbox">
          <input id="note-send-mesh" type="checkbox" checked>
          送出為 HermesX 資料封包
        </label>
        <div class="toolbar" style="margin: 12px 0 0;">
          <button class="primary" onclick="createNote()">發布</button>
        </div>
      </aside>

      <section class="panel">
        <label>便條</label>
        <div id="notes"></div>
      </section>
    </section>
  </main>

  <script>
    function setStatus(text) {
      document.getElementById('status').textContent = text;
    }

    function esc(text) {
      return String(text || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }[ch]));
    }

    async function refresh() {
      try {
        const category = document.getElementById('filter-category').value;
        const url = '/api/noteboard/notes?limit=80' + (category ? '&category=' + encodeURIComponent(category) : '');
        const notes = await fetch(url).then(r => r.json());
        renderNotes(notes);
        setStatus('已更新 ' + new Date().toLocaleTimeString());
      } catch (err) {
        setStatus('錯誤：' + err.message);
      }
    }

    function renderNotes(notes) {
      document.getElementById('notes').innerHTML = notes.length ? notes.map(note => `
        <article class="note">
          <h3>${esc(note.title)}</h3>
          <div class="meta">
            <span class="pill priority-${esc(note.priority)}">${esc(note.priority)}</span>
            ${esc(note.category)}，${esc(note.author)}，${esc(note.created_at)}，${note.mesh_sent ? 'HermesX 已排程送出' : note.transport}
          </div>
          ${note.location ? `<div class="meta">位置：${esc(note.location)}</div>` : ''}
          <div class="body">${esc(note.body)}</div>
        </article>
      `).join('') : '<div class="empty">目前沒有便條。</div>';
    }

    async function createNote() {
      const body = {
        category: document.getElementById('note-category').value,
        priority: document.getElementById('note-priority').value,
        title: document.getElementById('note-title').value.trim(),
        body: document.getElementById('note-body').value.trim(),
        location: document.getElementById('note-location').value.trim(),
        author: document.getElementById('note-author').value.trim() || 'local',
        send_mesh: document.getElementById('note-send-mesh').checked,
      };
      if (!body.title || !body.body) {
        setStatus('請填寫標題與內容');
        return;
      }
      setStatus('發布中...');
      const result = await fetch('/api/noteboard/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json());
      if (result.status === 'invalid') {
        setStatus(result.error);
        return;
      }
      document.getElementById('note-title').value = '';
      document.getElementById('note-body').value = '';
      document.getElementById('note-location').value = '';
      setStatus(result.note.mesh_sent ? '便條已儲存，並已排程送出 HermesX 資料封包' : '便條已儲存在本機');
      refresh();
    }

    refresh();
    setInterval(refresh, 8000);
  </script>
</body>
</html>
    """


@app.get("/meshcore", response_class=HTMLResponse)
def meshcore_manager():
    return """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MeshCore 管理</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #657180;
      --line: #d9e0e7;
      --accent: #0f766e;
      --danger: #b42318;
      --ok: #067647;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    nav { display: flex; gap: 12px; align-items: center; }
    a { color: var(--accent); text-decoration: none; }
    main {
      width: min(1120px, calc(100% - 32px));
      margin: 20px auto 40px;
    }
    .toolbar, .form-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }
    .toolbar { margin-bottom: 16px; }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 16px;
    }
    .tab {
      border-color: var(--line);
      background: #fff;
    }
    .tab.active {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      cursor: pointer;
    }
    button.primary { border-color: var(--accent); background: var(--accent); color: #fff; }
    button.danger { border-color: var(--danger); color: var(--danger); }
    input, select {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 10px;
      font-size: 14px;
      background: #fff;
      min-width: 120px;
    }
    input.secret { min-width: 360px; }
    .status { color: var(--muted); font-size: 14px; margin-left: auto; }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 112px;
    }
    .wide { grid-column: span 3; }
    .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
      line-height: 1.5;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }
    th { background: #eef2f5; color: #334155; }
    tr:last-child td { border-bottom: 0; }
    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
    }
    .ok { color: var(--ok); border-color: #75c7a0; background: #edfcf2; }
    .notice {
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
    }
    .notice.error { color: var(--danger); }
    .terminal {
      min-height: 360px;
      max-height: 520px;
      overflow: auto;
      background: #0b1220;
      color: #d6e2ff;
      border-radius: 8px;
      padding: 14px;
      font-size: 13px;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .hidden { display: none; }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      nav { flex-wrap: wrap; }
      .grid { grid-template-columns: 1fr; }
      .wide { grid-column: span 1; }
      input.secret { min-width: 100%; }
      .status { margin-left: 0; }
    }
  </style>
</head>
<body>
  <header>
    <h1>MeshCore 管理</h1>
    <nav>
      <a href="/">儀表板</a>
      <a href="/bbs">BBS</a>
      <span class="mono">Companion USB</span>
    </nav>
  </header>

  <main>
    <div class="toolbar">
      <button class="primary" onclick="refresh()">重新整理</button>
      <button onclick="probeRadio()">偵測無線電</button>
      <button onclick="appStart()">啟動 Companion</button>
      <button onclick="setAS923()">套用 AS923</button>
      <button onclick="applyChannel()">加入頻道</button>
      <span id="status" class="status">載入中...</span>
    </div>

    <div class="tabs">
      <button id="tab-overview" class="tab active" onclick="switchView('overview')">總覽</button>
      <button id="tab-channels" class="tab" onclick="switchView('channels')">頻道</button>
      <button id="tab-logs" class="tab" onclick="switchView('logs')">紀錄</button>
    </div>

    <section class="grid">
      <div class="panel view-overview">
        <div class="label">裝置</div>
        <div id="device" class="mono">-</div>
      </div>
      <div class="panel view-overview">
        <div class="label">無線電</div>
        <div id="radio" class="mono">-</div>
      </div>
      <div class="panel view-overview">
        <div class="label">序列連線</div>
        <div id="serial" class="mono">-</div>
      </div>

      <div class="panel wide view-channels hidden">
        <div class="label">頻道設定</div>
        <div class="form-row">
          <select id="channel-index">
            <option value="1">槽位 1</option>
            <option value="2">槽位 2</option>
            <option value="3">槽位 3</option>
            <option value="4">槽位 4</option>
            <option value="5">槽位 5</option>
            <option value="6">槽位 6</option>
            <option value="7">槽位 7</option>
          </select>
          <input id="channel-name" placeholder="頻道名稱">
          <input id="channel-secret" class="secret" placeholder="16-byte secret hex">
          <button class="primary" onclick="saveChannel()">儲存並加入</button>
        </div>
        <div id="channel-result" class="notice">按「儲存並加入」會把此頻道寫入 Base Tracker。</div>
      </div>

      <div class="panel wide view-channels hidden">
        <div class="label">送出測試訊息</div>
        <div class="form-row">
          <input id="message" class="secret" placeholder="SAFE / SOS / NEED / 自訂訊息">
          <button onclick="sendMessage()">送出</button>
          <button class="danger" onclick="quickSend('SOS')">SOS</button>
          <button onclick="quickSend('SAFE')">SAFE</button>
          <button onclick="quickSend('NEED')">NEED</button>
        </div>
      </div>

      <div class="panel wide view-channels hidden">
        <div class="label">已知頻道</div>
        <table>
          <thead>
            <tr>
              <th style="width:90px;">槽位</th>
              <th>名稱</th>
              <th>密鑰</th>
            </tr>
          </thead>
          <tbody id="channels"></tbody>
        </table>
      </div>

      <div class="panel wide view-logs hidden">
        <div class="label">終端紀錄</div>
        <pre id="terminal-log" class="terminal">載入中...</pre>
      </div>
    </section>
  </main>

  <script>
    let actionBusy = false;

    function fmt(value) {
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    }

    function setStatus(text) {
      document.getElementById('status').textContent = text;
    }

    function switchView(name) {
      for (const key of ['overview', 'channels', 'logs']) {
        document.querySelectorAll('.view-' + key).forEach(el => {
          el.classList.toggle('hidden', key !== name);
        });
        document.getElementById('tab-' + key).classList.toggle('active', key === name);
      }
      refresh();
    }

    function setChannelResult(text, isError = false) {
      const el = document.getElementById('channel-result');
      el.textContent = text;
      el.classList.toggle('error', isError);
    }

    function maskSecret(value) {
      if (!value) return '-';
      if (value.length <= 12) return value;
      return value.slice(0, 6) + '...' + value.slice(-6);
    }

    async function refresh() {
      try {
        const [data, events] = await Promise.all([
          fetch('/api/radio').then(r => r.json()),
          fetch('/api/logs?limit=80').then(r => r.json()),
        ]);
        const rs = data.radio || {};
        const ss = data.serial || {};
        const config = data.config || {};
        const profile = config.radio_profile || {};
        const current = rs.radio || {};
        const channel = config.channel || {};

        document.getElementById('device').innerHTML = [
          '名稱：' + fmt(rs.device_name),
          '韌體：' + fmt(rs.firmware_version),
          '電池：' + fmt(rs.battery_mv ? rs.battery_mv + ' mV' : null),
          'Identity：' + fmt(rs.identity),
        ].join('<br>');

        document.getElementById('radio').innerHTML = [
          '設定檔：' + fmt(profile.name),
          '目前：' + fmt(current.freq_hz ? current.freq_hz + ' Hz / BW ' + current.bw_hz + ' / SF' + current.sf + ' / CR' + current.cr : null),
          '目標：' + fmt(profile.freq_hz ? profile.freq_hz + ' Hz / BW ' + profile.bw_hz + ' / SF' + profile.sf + ' / CR' + profile.cr : null),
          '發射功率：' + fmt(rs.tx_power_dbm),
        ].join('<br>');

        document.getElementById('serial').innerHTML = [
          'Serial 開啟：' + (ss.connected ? '<span class="pill ok">是</span>' : '否'),
          'Protocol RX：' + (ss.frames_rx > 0 ? '<span class="pill ok">是</span>' : '否'),
          '傳輸：' + fmt(ss.transport),
          '接收 Frames：' + fmt(ss.frames_rx),
          '送出 Frames：' + fmt(ss.frames_tx),
          '待送 TX：' + fmt(data.pending_tx),
          '最後 TX：' + fmt(ss.last_tx_hex),
          '最後 RX byte：' + fmt(ss.last_rx_byte_hex),
          '最後 RX header：' + fmt(ss.last_rx_header_at),
          '丟棄 bytes：' + fmt(ss.rx_discarded_bytes),
          '最後錯誤：' + fmt(ss.last_error || rs.last_error),
        ].join('<br>');

        document.getElementById('channel-index').value = String(channel.index || 1);
        document.getElementById('channel-name').value = channel.name || '';
        document.getElementById('channel-secret').value = channel.secret_hex || '';

        const channels = rs.channels || {};
        const configuredChannel = {
          index: Number(channel.index || 1),
          name: channel.name || '',
          secret_hex: channel.secret_hex || '',
        };
        const confirmed = channels[String(configuredChannel.index)];
        const rows = Object.keys(channels).sort((a, b) => Number(a) - Number(b)).map(key => {
          const c = channels[key] || {};
          return `<tr>
            <td class="mono">${fmt(c.index)}</td>
            <td>${fmt(c.name)}</td>
            <td class="mono">${maskSecret(c.secret_hex)}</td>
          </tr>`;
        }).join('');
        document.getElementById('channels').innerHTML = rows || `
          <tr>
            <td class="mono">${configuredChannel.index}</td>
            <td>${configuredChannel.name}</td>
            <td class="mono">本機已設定，但 Base Tracker 尚未回報確認。Protocol RX 目前${ss.frames_rx > 0 ? '可用' : '不可用'}。</td>
          </tr>
        `;
        if (confirmed && confirmed.name === configuredChannel.name && confirmed.secret_hex === configuredChannel.secret_hex) {
          setChannelResult(`Base Tracker 已確認槽位 ${confirmed.index}（${confirmed.name}）。`);
        }

        document.getElementById('terminal-log').textContent = events.map(event => {
          const time = (event.received_at || '').replace('T', ' ').replace('+00:00', 'Z');
          return `[${time}] #${event.id} ${event.event_type} ${event.source_node} ${event.raw_message || ''}`;
        }).join('\\n') || '目前沒有紀錄。';
        const terminal = document.getElementById('terminal-log');
        terminal.scrollTop = terminal.scrollHeight;

        setStatus('已更新 ' + new Date().toLocaleTimeString());
      } catch (err) {
        setStatus('錯誤：' + err.message);
      }
    }

    async function probeRadio() {
      if (actionBusy) return;
      actionBusy = true;
      setStatus('正在排程偵測...');
      await fetch('/api/radio/probe', { method: 'POST' });
      setTimeout(refresh, 900);
      setTimeout(refresh, 2200);
      setTimeout(() => { actionBusy = false; }, 1200);
    }

    async function appStart() {
      if (actionBusy) return;
      actionBusy = true;
      setStatus('正在送出 Companion 啟動命令...');
      await fetch('/api/radio/companion/app-start', { method: 'POST' });
      setTimeout(refresh, 900);
      setTimeout(refresh, 2200);
      setTimeout(() => { actionBusy = false; }, 1200);
    }

    async function setAS923() {
      if (actionBusy) return;
      actionBusy = true;
      setStatus('正在套用 AS923...');
      await fetch('/api/radio/config/as923', { method: 'POST' });
      setTimeout(refresh, 1200);
      setTimeout(refresh, 2400);
      setTimeout(() => { actionBusy = false; }, 1400);
    }

    async function applyChannel() {
      if (actionBusy) return;
      actionBusy = true;
      setStatus('正在加入頻道...');
      await fetch('/api/radio/channel/apply', { method: 'POST' });
      setTimeout(refresh, 1200);
      setTimeout(refresh, 2400);
      setTimeout(() => { actionBusy = false; }, 1400);
    }

    async function saveChannel() {
      if (actionBusy) return;
      actionBusy = true;
      const body = {
        index: Number(document.getElementById('channel-index').value),
        name: document.getElementById('channel-name').value.trim(),
        secret_hex: document.getElementById('channel-secret').value.trim(),
      };
      setStatus('正在儲存頻道...');
      const result = await fetch('/api/radio/channel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(r => r.json());
      if (result.status === 'invalid') {
        setStatus(result.error);
        setChannelResult(result.error, true);
      } else {
        const pending = result.pending_tx || 0;
        setStatus('頻道命令已排程');
        setChannelResult(`本機設定已儲存，已排程寫入槽位 ${result.channel.index}（${result.channel.name}）。待送 TX：${pending}。Protocol RX 變成「是」且「已知頻道」顯示同一槽位後，才代表 Base Tracker 已確認。`);
      }
      setTimeout(refresh, 1200);
      setTimeout(refresh, 2400);
      setTimeout(() => { actionBusy = false; }, 1400);
    }

    async function sendMessage() {
      const message = document.getElementById('message').value.trim();
      if (!message) return;
      setStatus('正在送出訊息...');
      await fetch('/api/mesh/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      document.getElementById('message').value = '';
      setTimeout(refresh, 900);
    }

    function quickSend(message) {
      document.getElementById('message').value = message;
      sendMessage();
    }

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Core</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #657180;
      --line: #d9e0e7;
      --accent: #0f766e;
      --danger: #b42318;
      --warn: #b54708;
      --ok: #067647;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }
    nav {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    a {
      color: var(--accent);
      text-decoration: none;
    }
    main {
      width: min(1120px, calc(100% - 32px));
      margin: 20px auto 40px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-bottom: 16px;
    }
    button {
      appearance: none;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    button.danger {
      border-color: var(--danger);
      color: var(--danger);
    }
    .status {
      color: var(--muted);
      font-size: 14px;
      margin-left: auto;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .radio-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric, .table-wrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .radio-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 96px;
    }
    .radio-panel .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .radio-panel .value {
      font-size: 14px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .metric {
      padding: 14px;
      min-height: 90px;
    }
    .metric .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .metric .value {
      font-size: 30px;
      font-weight: 750;
      line-height: 1;
    }
    .table-wrap {
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
      vertical-align: top;
    }
    th {
      background: #eef2f5;
      color: #334155;
      font-weight: 650;
    }
    tr:last-child td { border-bottom: 0; }
    .type {
      display: inline-block;
      min-width: 86px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 12px;
      font-weight: 700;
      text-align: center;
    }
    .type.SAFE { color: var(--ok); border-color: #75c7a0; background: #edfcf2; }
    .type.SOS { color: var(--danger); border-color: #f1a29b; background: #fff1f0; }
    .type.NEED { color: var(--warn); border-color: #f7b27a; background: #fff7ed; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }
    .muted { color: var(--muted); }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .radio-grid { grid-template-columns: 1fr; }
      .hide-sm { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Hermes Core</h1>
    <nav>
      <a href="/bbs">BBS</a>
      <a href="/meshcore">MeshCore 管理</a>
      <div class="muted">MeshCore Gateway / HermesNET MVP</div>
    </nav>
  </header>
  <main>
    <div class="toolbar">
      <button class="primary" onclick="refresh()">重新整理</button>
      <button onclick="sendEvent('SAFE')">安全 SAFE</button>
      <button class="danger" onclick="sendEvent('SOS')">求救 SOS</button>
      <button onclick="sendEvent('NEED')">需求 NEED</button>
      <button onclick="sendEvent('STATUS')">狀態 STATUS</button>
      <button onclick="location.href='/meshcore'">管理 MeshCore</button>
      <span id="status" class="status">載入中...</span>
    </div>

    <section class="grid">
      <div class="metric"><div class="label">安全 SAFE</div><div id="m-safe" class="value">0</div></div>
      <div class="metric"><div class="label">求救 SOS</div><div id="m-sos" class="value">0</div></div>
      <div class="metric"><div class="label">需求 NEED</div><div id="m-need" class="value">0</div></div>
      <div class="metric"><div class="label">總數</div><div id="m-total" class="value">0</div></div>
    </section>

    <section class="radio-grid">
      <div class="radio-panel">
        <div class="label">無線電</div>
        <div id="radio-main" class="value mono">-</div>
      </div>
      <div class="radio-panel">
        <div class="label">連線</div>
        <div id="radio-link" class="value mono">-</div>
      </div>
      <div class="radio-panel">
        <div class="label">統計</div>
        <div id="radio-stats" class="value mono">-</div>
      </div>
    </section>

    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width:86px;">ID</th>
            <th style="width:130px;">類型</th>
            <th style="width:150px;">來源</th>
            <th class="hide-sm" style="width:120px;">傳輸</th>
            <th>訊息</th>
            <th class="hide-sm" style="width:220px;">接收時間</th>
          </tr>
        </thead>
        <tbody id="events"></tbody>
      </table>
    </section>
  </main>

  <script>
    function setStatus(text) {
      document.getElementById('status').textContent = text;
    }

    function messageOf(event) {
      const p = event.payload || {};
      if (p.message) return p.message;
      if (p.text) return p.text;
      return event.raw_message || '';
    }

    function fmt(value) {
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    }

    async function refresh() {
      try {
        const [summary, events, radio] = await Promise.all([
          fetch('/api/summary').then(r => r.json()),
          fetch('/api/events?limit=50').then(r => r.json()),
          fetch('/api/radio').then(r => r.json()),
        ]);
        document.getElementById('m-safe').textContent = summary.SAFE || 0;
        document.getElementById('m-sos').textContent = summary.SOS || 0;
        document.getElementById('m-need').textContent = summary.NEED || 0;
        document.getElementById('m-total').textContent = Object.values(summary).reduce((a, b) => a + b, 0);

        const rs = radio.radio || {};
        const ss = radio.serial || {};
        const profile = (radio.config && radio.config.radio_profile) || rs.current_profile || {};
        const channel = (radio.config && radio.config.channel) || rs.active_channel || {};
        const radioConfig = rs.radio || {};
        document.getElementById('radio-main').innerHTML = [
          '名稱：' + fmt(rs.device_name),
          '版本：' + fmt(rs.firmware_version),
          '電池：' + fmt(rs.battery_mv ? rs.battery_mv + ' mV' : null),
          '溫度：' + fmt(rs.mcu_temp_c ? rs.mcu_temp_c + ' C' : null),
        ].join('<br>');
        document.getElementById('radio-link').innerHTML = [
          'Serial：' + (ss.connected ? '已連線' : '未連線'),
          '模式：' + fmt(ss.transport),
          'Port：/dev/ttyACM0',
          'RSSI: ' + fmt(rs.current_rssi_dbm ? rs.current_rssi_dbm + ' dBm' : null),
          'Noise: ' + fmt(rs.noise_floor_dbm ? rs.noise_floor_dbm + ' dBm' : null),
          '無線電：' + fmt(radioConfig.freq_hz ? (radioConfig.freq_hz + ' Hz SF' + radioConfig.sf) : null),
          '設定檔：' + fmt(profile.name),
          '頻道：' + fmt((channel.index !== undefined ? channel.index + ' ' : '') + (channel.name || '')),
        ].join('<br>');
        document.getElementById('radio-stats').innerHTML = [
          '接收 Frames：' + fmt(ss.frames_rx),
          '送出 Frames：' + fmt(ss.frames_tx),
          '統計：' + fmt(rs.stats),
          '最後 Pong：' + fmt(rs.last_pong_at),
          '套用時間：' + fmt(rs.last_config_apply_at),
        ].join('<br>');

        const tbody = document.getElementById('events');
        tbody.innerHTML = events.map(event => `
          <tr>
            <td class="mono">${event.id}</td>
            <td><span class="type ${event.event_type}">${event.event_type}</span></td>
            <td class="mono">${event.source_node}</td>
            <td class="mono hide-sm">${event.transport}</td>
            <td>${messageOf(event)}</td>
            <td class="mono hide-sm">${event.received_at}</td>
          </tr>
        `).join('');

        setStatus('已更新 ' + new Date().toLocaleTimeString());
      } catch (err) {
        setStatus('錯誤：' + err.message);
      }
    }

    async function sendEvent(type) {
      await fetch('/api/mesh/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: type }),
      });
      refresh();
    }

    async function probeRadio() {
      setStatus('正在排程無線電偵測...');
      await fetch('/api/radio/probe', { method: 'POST' });
      setTimeout(refresh, 600);
    }

    async function setAS923() {
      setStatus('正在套用 AS923 測試設定...');
      await fetch('/api/radio/config/as923', { method: 'POST' });
      setTimeout(refresh, 1200);
      setTimeout(refresh, 2400);
    }

    async function applyChannel() {
      setStatus('正在加入 Hermes 頻道...');
      await fetch('/api/radio/channel/apply', { method: 'POST' });
      setTimeout(refresh, 1200);
      setTimeout(refresh, 2400);
    }

    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
    """


@app.post("/api/events")
def create_event(event: EventIn):
    insert_event(
        event.event_type,
        event.source_node,
        event.region,
        event.payload,
        event.transport,
        event.raw_message,
    )
    return {"status": "stored"}


@app.get("/api/events")
def list_events(limit: int = 50, include_system: bool = False):
    conn = db()
    if include_system:
        rows = conn.execute(
            """
            SELECT id, event_type, source_node, region, payload,
                   transport, raw_message, received_at
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in SYSTEM_EVENT_TYPES)
        rows = conn.execute(
            f"""
            SELECT id, event_type, source_node, region, payload,
                   transport, raw_message, received_at
            FROM events
            WHERE event_type NOT IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            (*SYSTEM_EVENT_TYPES, limit),
        ).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "event_type": r[1],
            "source_node": r[2],
            "region": r[3],
            "payload": json.loads(r[4]),
            "transport": r[5],
            "raw_message": r[6],
            "received_at": r[7],
        }
        for r in rows
    ]


@app.get("/api/logs")
def list_logs(limit: int = 80, include_noise: bool = False):
    conn = db()
    if include_noise:
        rows = conn.execute(
            """
            SELECT id, event_type, source_node, region, payload,
                   transport, raw_message, received_at
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in NOISY_LOG_MESSAGES)
        rows = conn.execute(
            f"""
            SELECT id, event_type, source_node, region, payload,
                   transport, raw_message, received_at
            FROM events
            WHERE raw_message NOT IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            (*NOISY_LOG_MESSAGES, limit),
        ).fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "event_type": r[1],
            "source_node": r[2],
            "region": r[3],
            "payload": json.loads(r[4]),
            "transport": r[5],
            "raw_message": r[6],
            "received_at": r[7],
        }
        for r in reversed(rows)
    ]


@app.get("/api/summary")
def summary(include_system: bool = False):
    conn = db()
    if include_system:
        rows = conn.execute(
            """
            SELECT event_type, COUNT(*)
            FROM events
            GROUP BY event_type
            ORDER BY event_type
            """
        ).fetchall()
    else:
        placeholders = ",".join("?" for _ in SYSTEM_EVENT_TYPES)
        rows = conn.execute(
            f"""
            SELECT event_type, COUNT(*)
            FROM events
            WHERE event_type NOT IN ({placeholders})
            GROUP BY event_type
            ORDER BY event_type
            """,
            tuple(SYSTEM_EVENT_TYPES),
        ).fetchall()
    conn.close()
    return {event_type: count for event_type, count in rows}
