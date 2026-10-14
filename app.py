import sys
import asyncio
import httpx
import random
import json
import socket
import struct
import time
import os
import uuid
import itertools
import secrets
import traceback
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME
import Yasin_pb2

from dashboard_server import bot_state, start_web_dashboard

WEB_HOST = "0.0.0.0"
WEB_PORT = 14146
ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
DEVICES_FILE = "devices.json"
ACCOUNT_STATUS_FILE = "account_status.json"
PICO_INFO_API = "https://armas-lk-info-api.vercel.app/info"
TOKEN_CACHE_TTL = 1200
BOT_SETTINGS_FILE = "bot_settings.json"
COMPLETED_ACCOUNTS_FILE = "completed_accounts.json"

START_MATCH_INTERVAL = 3.0
NEW_MATCH_DELAY = 3.0
MAX_MATCH_DURATION = 800
MATCH_IDLE_TIMEOUT = 15.0
LONE_WOLF_UNLOCK_LEVEL = 3
LONE_WOLF_MODE_ID = 43
LONE_WOLF_MAP_ID = 11
LW_MATCH_IDLE_TIMEOUT = 8.0
BR_MODE_ID = 1
BR_MAP_ID = 1

DEFAULT_MAX_STACK_LW = 10
DEFAULT_MAX_STACK_BR = 1
MAX_STACK_LW = DEFAULT_MAX_STACK_LW
MAX_STACK_BR = DEFAULT_MAX_STACK_BR

CANCEL_BR_SESSIONS_ON_LW_UNLOCK = False
LW_UNLOCK_WATCH_REFRESH_INTERVAL = 10.0
UDP_HANDSHAKE_TIMEOUT = 25.0

MODE_PROFILES = {
    "BR": {
        "tag": "BATTLE ROYALE",
        "mode_id": BR_MODE_ID,
        "map_id": BR_MAP_ID,
        "idle_timeout": MATCH_IDLE_TIMEOUT,
        "hold": None,
    },
    "LW": {
        "tag": "LONE WOLF",
        "mode_id": LONE_WOLF_MODE_ID,
        "map_id": LONE_WOLF_MAP_ID,
        "idle_timeout": LW_MATCH_IDLE_TIMEOUT,
        "hold": max(30.0, LW_MATCH_IDLE_TIMEOUT * 3),
    },
}


def mode_for_level(level) -> str:
    try:
        return "LW" if int(level) >= LONE_WOLF_UNLOCK_LEVEL else "BR"
    except Exception:
        return "BR"


def load_bot_settings() -> dict:
    """Load universal bot settings from disk (shared with dashboard)."""
    defaults = {
        "max_stack_lw": DEFAULT_MAX_STACK_LW,
        "max_stack_br": DEFAULT_MAX_STACK_BR,
        "start_match_interval": START_MATCH_INTERVAL,
        "new_match_delay": NEW_MATCH_DELAY,
        "match_idle_timeout": MATCH_IDLE_TIMEOUT,
        "lw_match_idle_timeout": LW_MATCH_IDLE_TIMEOUT,
        "exp_refresh_interval": 25.0,
        "token_cache_ttl": TOKEN_CACHE_TTL,
        "identity_rotate_every_matches": 5,
        "identity_rotate_every_seconds": 900,
        "cancel_br_on_lw_unlock": CANCEL_BR_SESSIONS_ON_LW_UNLOCK,
        "safe_play_mode": True,
        "human_like_movement": True,
    }
    if not os.path.exists(BOT_SETTINGS_FILE):
        return dict(defaults)
    try:
        with open(BOT_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    return defaults


def apply_bot_settings(settings=None):
    """Push settings into module-level knobs used by match loop."""
    global MAX_STACK_LW, MAX_STACK_BR, START_MATCH_INTERVAL, NEW_MATCH_DELAY
    global MATCH_IDLE_TIMEOUT, LW_MATCH_IDLE_TIMEOUT, EXP_REFRESH_INTERVAL
    global TOKEN_CACHE_TTL, IDENTITY_ROTATE_EVERY_MATCHES, IDENTITY_ROTATE_EVERY_SECONDS
    global CANCEL_BR_SESSIONS_ON_LW_UNLOCK, SAFE_PLAY_MODE, HUMAN_LIKE_MOVEMENT
    s = settings if settings is not None else load_bot_settings()
    try:
        MAX_STACK_LW = max(1, int(s.get("max_stack_lw", DEFAULT_MAX_STACK_LW)))
    except Exception:
        MAX_STACK_LW = DEFAULT_MAX_STACK_LW
    try:
        MAX_STACK_BR = max(1, int(s.get("max_stack_br", DEFAULT_MAX_STACK_BR)))
    except Exception:
        MAX_STACK_BR = DEFAULT_MAX_STACK_BR
    try:
        START_MATCH_INTERVAL = float(s.get("start_match_interval", START_MATCH_INTERVAL))
    except Exception:
        pass
    try:
        NEW_MATCH_DELAY = float(s.get("new_match_delay", NEW_MATCH_DELAY))
    except Exception:
        pass
    try:
        MATCH_IDLE_TIMEOUT = float(s.get("match_idle_timeout", MATCH_IDLE_TIMEOUT))
    except Exception:
        pass
    try:
        LW_MATCH_IDLE_TIMEOUT = float(s.get("lw_match_idle_timeout", LW_MATCH_IDLE_TIMEOUT))
    except Exception:
        pass
    try:
        EXP_REFRESH_INTERVAL = float(s.get("exp_refresh_interval", 25.0))
    except Exception:
        pass
    try:
        TOKEN_CACHE_TTL = int(s.get("token_cache_ttl", TOKEN_CACHE_TTL))
    except Exception:
        pass
    try:
        IDENTITY_ROTATE_EVERY_MATCHES = int(s.get("identity_rotate_every_matches", 5))
    except Exception:
        pass
    try:
        IDENTITY_ROTATE_EVERY_SECONDS = int(s.get("identity_rotate_every_seconds", 900))
    except Exception:
        pass
    CANCEL_BR_SESSIONS_ON_LW_UNLOCK = bool(s.get("cancel_br_on_lw_unlock", False))
    SAFE_PLAY_MODE = bool(s.get("safe_play_mode", True))
    HUMAN_LIKE_MOVEMENT = bool(s.get("human_like_movement", True))
    try:
        MODE_PROFILES["BR"]["idle_timeout"] = MATCH_IDLE_TIMEOUT
        MODE_PROFILES["LW"]["idle_timeout"] = LW_MATCH_IDLE_TIMEOUT
        MODE_PROFILES["LW"]["hold"] = max(30.0, LW_MATCH_IDLE_TIMEOUT * 3)
    except Exception:
        pass


def max_stack_for_mode(mode: str) -> int:
    apply_bot_settings()
    return MAX_STACK_LW if mode == "LW" else MAX_STACK_BR


EXP_REFRESH_INTERVAL = 25.0
EXP_REFRESH_AFTER_MATCH_DELAY = 9.0

ANTI_AFK_MIN_INTERVAL = 1.8
ANTI_AFK_MAX_INTERVAL = 3.5

SAFE_PLAY_MODE = True
BYPASS_TIMING_JITTER = True
BYPASS_PACKET_JITTER = True
BYPASS_HELLO_DELAY = True

ENABLE_SPEED_MOVEMENT = True
MOVEMENT_SPEED_MIN = 1.0
MOVEMENT_SPEED_MAX = 1.4
MOVEMENT_PATTERN = "circle"
MOVEMENT_TICK_MS = 240
MOVEMENT_RADIUS = 180
MOVEMENT_UPDATE_SPEED_EVERY = 4.0
MOVEMENT_STATE_IDLE_CHANCE = 0.10
MOVEMENT_STATE_WALK_CHANCE = 0.28
MOVEMENT_STATE_RUN_CHANCE = 0.32
MOVEMENT_STATE_SPRINT_CHANCE = 0.10
MOVEMENT_STATE_JUMP_CHANCE = 0.08
MOVEMENT_STATE_CROUCH_CHANCE = 0.06
MOVEMENT_STATE_PRONE_CHANCE = 0.06
PRIORITY_REGIONS = ["SG", "IND", "BD", "TH", "PH", "VN", "MY", "ID", "HK", "TW"]

MAX_CONSECUTIVE_PARSE_FAILURES = 5.0
NON_MATCH_RECONNECT_DELAY = 1.0

FALLBACK_UID = ""
FALLBACK_PASSWORD = ""

HUMAN_LIKE_MOVEMENT = True
BEHAVIOR_JITTER_MIN = 0.15
BEHAVIOR_JITTER_MAX = 0.85
HUMAN_LIKE_DELAY_MAX = 2.5

IDENTITY_ROTATE_EVERY_MATCHES = 5
IDENTITY_ROTATE_EVERY_SECONDS = 900
MAX_LOGIN_FAILURES_BEFORE_ROTATE = 3

MOVEMENT_SEND_INTERVAL = (1.5, 3.5)
MOVEMENT_BASE_X = 100000
MOVEMENT_BASE_Z = 100000


class AntiBanState:
    def __init__(self):
        self.match_count_since_rotate: Dict[str, int] = {}
        self.last_rotate_time: Dict[str, float] = {}
        self.login_failures: Dict[str, int] = {}
        self.lock = asyncio.Lock()

    async def record_login_failure(self, account_id: str) -> bool:
        async with self.lock:
            acc = str(account_id)
            self.login_failures[acc] = self.login_failures.get(acc, 0) + 1
            if self.login_failures[acc] >= MAX_LOGIN_FAILURES_BEFORE_ROTATE:
                self.login_failures[acc] = 0
                return True
            return False

    async def reset_login_failures(self, account_id: str):
        async with self.lock:
            self.login_failures[str(account_id)] = 0


anti_ban_state = AntiBanState()


async def human_like_delay(base_delay: float) -> float:
    jitter = random.uniform(BEHAVIOR_JITTER_MIN, BEHAVIOR_JITTER_MAX)
    total = base_delay + jitter
    await asyncio.sleep(total)
    return total


def get_randomized_movement(base_x: int, base_z: int, counter: int) -> Tuple[int, int]:
    if not HUMAN_LIKE_MOVEMENT:
        return base_x + counter * 100, base_z

    angle = math.sin(counter * 0.1) * 0.5
    distance = random.randint(80, 150)

    x_offset = int(math.cos(angle) * distance * (counter % 3 - 1))
    z_offset = int(math.sin(angle) * distance * (counter % 2))

    return base_x + x_offset, base_z + z_offset


def bypass_jitter(base: float, spread: float = 0.35) -> float:
    if not (SAFE_PLAY_MODE and BYPASS_TIMING_JITTER):
        return base
    return max(0.05, base + random.uniform(-spread, spread))


def bypass_packet_jitter(base_interval: float, spread_ratio: float = 0.35) -> float:
    if not (SAFE_PLAY_MODE and BYPASS_PACKET_JITTER):
        return base_interval
    spread = base_interval * spread_ratio
    return max(0.1, base_interval + random.uniform(-spread, spread))


def bypass_hello_delay() -> float:
    if not (SAFE_PLAY_MODE and BYPASS_HELLO_DELAY):
        return 0.0
    return random.uniform(0.05, 0.45)


async def get_randomized_interval(min_sec: float, max_sec: float) -> float:
    base = random.uniform(min_sec, max_sec)
    if random.random() < 0.15:
        base *= random.uniform(1.3, 1.8)
    return base


def get_device_for_account(account_identifier: str) -> dict:
    devices = {}
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                devices = json.load(f)
        except Exception:
            pass

    acc_key = str(account_identifier)

    needs_rotate = False
    if acc_key in devices:
        dev = devices[acc_key]
        matches = dev.get("_match_count", 0)
        last_rot = dev.get("_last_rotate", time.time())
        if matches >= IDENTITY_ROTATE_EVERY_MATCHES or (time.time() - last_rot) >= IDENTITY_ROTATE_EVERY_SECONDS:
            needs_rotate = True

    if acc_key in devices and not needs_rotate:
        return devices[acc_key]

    device_list = [
        ("Samsung", "SM-G998B", "Adreno (TM) 660", "Android OS 12 / API-31"),
        ("Xiaomi", "2201122G", "Adreno (TM) 730", "Android OS 13 / API-33"),
        ("Realme", "RMX3700", "Mali-G710", "Android OS 14 / API-34"),
        ("OnePlus", "CPH2451", "Adreno (TM) 740", "Android OS 13 / API-33"),
        ("OPPO", "CPH2611", "Adreno (TM) 720", "Android OS 14 / API-34"),
        ("Vivo", "V2203", "Mali-G710", "Android OS 12 / API-31"),
        ("Poco", "M2102J20SG", "Adreno (TM) 660", "Android OS 13 / API-33"),
    ]
    brand, model, gpu, os_ver = random.choice(device_list)

    new_device = {
        "unique_device_id": f"Google|{str(uuid.uuid4())}",
        "brand": brand,
        "model": model,
        "gpu_renderer": gpu,
        "system_software": os_ver,
        "screen_width": random.choice([1080, 1440, 720, 1280]),
        "screen_height": random.choice([2400, 3200, 1600, 2400]),
        "screen_dpi": str(random.randint(300, 420)),
        "memory": random.randint(2800, 6500),
        "processor_details": f"ARM64 FP ASIMD AES VMH | {random.randint(2200, 3200)} | {random.randint(6, 12)}",
        "client_ip": f"{random.randint(103, 223)}.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}",
        "android_id": secrets.token_hex(8),
        "gsf_id": secrets.token_hex(8),
        "build_fingerprint": f"{brand.lower()}/{model.lower()}/{model.lower()}:{os_ver.split(' / ')[0].replace(' ', '_')}/user/release-keys",
        "serial_number": secrets.token_hex(8),
        "hardware_id": secrets.token_hex(8),
        "_match_count": 0,
        "_last_rotate": time.time(),
    }

    if acc_key in devices and needs_rotate:
        print_warning(f"[ANTIBAN] Rotating device fingerprint for {acc_key}")

    devices[acc_key] = new_device

    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, indent=4)
    except Exception as e:
        print_error(f"Failed to save device mapping: {e}")

    return new_device


def _update_device_match_count(account_identifier: str):
    try:
        if not os.path.exists(DEVICES_FILE):
            return
        with open(DEVICES_FILE, "r", encoding="utf-8") as f:
            devices = json.load(f)
        acc_key = str(account_identifier)
        if acc_key in devices:
            devices[acc_key]["_match_count"] = devices[acc_key].get("_match_count", 0) + 1
            with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                json.dump(devices, f, indent=4)
    except Exception:
        pass


CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, Tuple[str, float]] = {}
_DNS_CACHE_TTL = 300.0

async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname:
        return hostname

    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname

    now = time.time()
    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp:
            return ip

    def _query_cloudflare(server_ip: str) -> Optional[str]:
        s = None
        try:
            tx_id = random.randint(1000, 65535)
            header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
            qname = b"".join(bytes([len(part)]) + part.encode('ascii') for part in hostname.split('.')) + b"\x00"
            query_pkt = header + qname + struct.pack(">HH", 1, 1)

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(query_pkt, (server_ip, 53))
            resp, _ = s.recvfrom(1024)

            if len(resp) >= 12:
                ancount = struct.unpack(">H", resp[6:8])[0]
                if ancount > 0:
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset+10])
                        offset += 10
                        if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                            return socket.inet_ntoa(resp[offset:offset+4])
                        offset += rdlen
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        return None

    loop = asyncio.get_running_loop()
    ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_PRIMARY_DNS)
    if not ip:
        ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ip_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
            if ip_info:
                ip = ip_info[0][4][0]
        except Exception:
            ip = hostname

    if ip:
        _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
    return ip or hostname


def optimize_tcp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    except Exception:
        pass


def optimize_udp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
        if hasattr(socket, 'SIO_UDP_CONNRESET') and os.name == 'nt':
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass
    except Exception:
        pass


client = httpx.AsyncClient(
    verify=False,
    timeout=10.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50)
)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

CRC7_TABLE = bytes([
    0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
    25, 16, 11, 2, 61, 52, 47, 38, 81, 88, 67, 74, 117, 124, 103, 110,
    50, 59, 32, 41, 22, 31, 4, 13, 122, 115, 104, 97, 94, 87, 76, 69,
    43, 34, 57, 48, 15, 6, 29, 20, 99, 106, 113, 120, 71, 78, 85, 92,
    100, 109, 118, 127, 64, 73, 82, 91, 44, 37, 62, 55, 8, 1, 26, 19,
    125, 116, 111, 102, 89, 80, 75, 66, 53, 60, 39, 46, 17, 24, 3, 10,
    86, 95, 68, 77, 114, 123, 96, 105, 30, 23, 12, 5, 58, 51, 40, 33,
    79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    65, 72, 83, 90, 101, 108, 119, 126, 9, 0, 27, 18, 45, 36, 63, 54,
    88, 81, 74, 67, 124, 117, 110, 103, 16, 25, 2, 11, 52, 61, 38, 47,
    115, 122, 97, 104, 87, 94, 69, 76, 59, 50, 41, 32, 31, 22, 13, 4,
    106, 99, 120, 113, 78, 71, 92, 85, 34, 43, 48, 57, 6, 15, 20, 29,
    37, 44, 55, 62, 1, 8, 19, 26, 109, 100, 127, 118, 73, 64, 91, 82,
    60, 53, 46, 39, 24, 17, 10, 3, 116, 125, 102, 111, 80, 89, 66, 75,
    23, 30, 5, 12, 51, 58, 33, 40, 95, 86, 77, 68, 123, 114, 105, 96,
    14, 7, 28, 21, 42, 35, 56, 49, 70, 79, 84, 93, 98, 107, 112, 121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0: 1, 1: 2, 2: 2, 3: 1, 4: 2}
_FIELD_NAMES = {0: "sendOption", 1: "cmd", 2: "orderId", 3: "flags", 4: "length"}

sai_tail_dul = bytes.fromhex(
    "0101030101045452000103000100000410312e3133302e3232"
    "1432303139313231303430ca0163736f7665727365612e737472"
    "6f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
    "3b302e302e302e303b33342e3132362e37362e34353b33342e38"
    "372e3137372e31343b33342e38372e3137302e3233303b33352e"
    "3138352e3138332e353700000000000001000000000000000000"
    "0000000100000000000100000000000100b8eeec91c5d7ffde110200"
)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}

class Colors:
    HEADER = '\033[95m'
    GREEN = '\033[92m'
    FAIL = '\033[91m'
    WARNING = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'

def print_colored(text, color=Colors.WHITE):
    try:
        print(f"{color}{text}{Colors.ENDC}")
    except Exception:
        try:
            print(f"{color}{text.encode('ascii', errors='replace').decode('ascii')}{Colors.ENDC}")
        except Exception:
            pass

def print_success(text):
    print_colored(f"[+] {text}", Colors.GREEN)
    try:
        bot_state.log(text, "success")
    except Exception:
        pass

def print_error(text):
    print_colored(f"[-] {text}", Colors.FAIL)
    try:
        bot_state.log(text, "error")
    except Exception:
        pass

def print_warning(text):
    print_colored(f"[!] {text}", Colors.WARNING)
    try:
        bot_state.log(text, "warning")
    except Exception:
        pass

def print_info(text):
    print_colored(f"[i] {text}", Colors.CYAN)
    try:
        bot_state.log(text, "info")
    except Exception:
        pass

def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        val = d[key].get('data')
        return val if val is not None else default
    if str(key) in d:
        val = d[str(key)].get('data')
        return val if val is not None else default
    return default


_match_counters: Dict[str, int] = {}
_match_counter_lock = asyncio.Lock()

async def _inc_match(uid: str) -> int:
    async with _match_counter_lock:
        _match_counters[uid] = _match_counters.get(uid, 0) + 1
        return _match_counters[uid]

async def _dec_match(uid: str) -> int:
    async with _match_counter_lock:
        if uid in _match_counters and _match_counters[uid] > 0:
            _match_counters[uid] -= 1
        return _match_counters.get(uid, 0)

async def _get_match_count(uid: str) -> int:
    async with _match_counter_lock:
        return _match_counters.get(uid, 0)

async def _get_total_match_count() -> int:
    async with _match_counter_lock:
        return sum(_match_counters.values())


# mode ("BR"/"LW") each account is currently sending StartMatch for, or None
_searching_mode: Dict[str, Optional[str]] = {}


def dashboard_status_for(uid: str, active_matches: int) -> str:
    """Single rule for the dashboard status: IN_MATCH > SEARCHING > ONLINE.
    These are the exact strings templates/index.html understands."""
    if active_matches > 0:
        return "IN_MATCH"
    if _searching_mode.get(str(uid)) in MODE_PROFILES:
        return "SEARCHING"
    return "ONLINE"


def publish_status(uid, active_matches: int):
    """Push status + searched mode (BR/LW) to the dashboard."""
    uid = str(uid)
    try:
        bot_state.update_status(uid, dashboard_status_for(uid, active_matches), active_matches)
        acc = bot_state.accounts.get(uid)
        if acc is not None:
            m = _searching_mode.get(uid)
            acc["search_mode"] = m if m in MODE_PROFILES else None
    except Exception:
        pass


_token_cache_memo: Dict[str, Any] = {}
_token_cache_memo_time: float = 0.0
_TOKEN_CACHE_MEMO_TTL = 5.0

def _json_serializer(obj):
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(obj).hex()}
    raise TypeError(f"Type {type(obj)} not serializable")

def _json_deserializer(obj):
    if isinstance(obj, dict):
        if "__bytes_hex__" in obj and len(obj) == 1:
            try:
                return bytes.fromhex(obj["__bytes_hex__"])
            except Exception:
                return b""
        return {k: _json_deserializer(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_deserializer(x) for x in obj]
    return obj

def _load_token_cache() -> Dict[str, Any]:
    global _token_cache_memo, _token_cache_memo_time
    now = time.time()
    if _token_cache_memo and (now - _token_cache_memo_time) < _TOKEN_CACHE_MEMO_TTL:
        return _token_cache_memo

    if not os.path.exists(TOKEN_CACHE_FILE):
        return {}
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Cache root must be dict")
        parsed = _json_deserializer(data)
        _token_cache_memo = parsed
        _token_cache_memo_time = now
        return parsed
    except Exception as e:
        print_error(f"Token cache corrupt → deleting: {e}")
        try:
            os.remove(TOKEN_CACHE_FILE)
        except Exception:
            pass
        return {}

def _save_token_cache(cache: Dict[str, Any]):
    global _token_cache_memo, _token_cache_memo_time
    try:
        tmp_file = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=_json_serializer)
        os.replace(tmp_file, TOKEN_CACHE_FILE)
        _token_cache_memo = cache
        _token_cache_memo_time = time.time()
    except Exception as e:
        print_error(f"Token cache save error: {e}")

def cache_get(uid: str) -> Optional[Dict]:
    cache = _load_token_cache()
    entry = cache.get(str(uid))
    if not entry:
        return None
    if time.time() - entry.get("cached_at", 0) > TOKEN_CACHE_TTL:
        print_info(f"[CACHE] UID {uid} expired. Re-login needed.")
        cache_invalidate(uid)
        return None
    if str(entry.get("account_id", "")).isdigit():
        entry["account_id"] = int(entry["account_id"])
    if not isinstance(entry.get("login_payload_data"), (bytes, bytearray)):
        print_warning(f"[CACHE] UID {uid} missing payload → invalidating")
        cache_invalidate(uid)
        return None
    return entry

def cache_set(uid: str, account_data: Dict):
    cache = _load_token_cache()
    entry = dict(account_data)
    entry["cached_at"] = time.time()
    cache[str(uid)] = entry
    _save_token_cache(cache)
    print_success(f"[CACHE] Saved credentials for UID {uid}")

def cache_invalidate(uid: str):
    cache = _load_token_cache()
    if str(uid) in cache:
        del cache[str(uid)]
        _save_token_cache(cache)
        print_warning(f"[CACHE] Invalidated: {uid}")


def _status_auth_key(auth_type: str, auth_id: str) -> str:
    if auth_type == "token":
        return f"token:{str(auth_id)[:10]}"
    return f"guest:{auth_id}"


def load_account_status_raw() -> Dict[str, Any]:
    if not os.path.exists(ACCOUNT_STATUS_FILE):
        return {}
    try:
        with open(ACCOUNT_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print_error(f"Could not load {ACCOUNT_STATUS_FILE}: {e}")
    return {}


def load_account_status() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in load_account_status_raw().items():
        if isinstance(v, dict):
            c = v.get("control")
            if c in ("run", "pause", "stop"):
                out[str(k)] = c
        elif v in ("run", "pause", "stop"):
            out[str(k)] = v
    return out


def save_account_status(status_map: Dict[str, Any]):
    try:
        tmp = ACCOUNT_STATUS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(status_map, f, indent=2)
        os.replace(tmp, ACCOUNT_STATUS_FILE)
    except Exception as e:
        print_error(f"Could not save {ACCOUNT_STATUS_FILE}: {e}")


def get_saved_control(*keys: str) -> str:
    data = load_account_status_raw()
    for k in keys:
        if not k or k not in data:
            continue
        v = data[k]
        if isinstance(v, dict):
            c = v.get("control")
            if c in ("run", "pause", "stop"):
                return c
        elif v in ("run", "pause", "stop"):
            return v
    return "run"


def get_saved_status_meta(*keys: str) -> Dict[str, Any]:
    data = load_account_status_raw()
    for k in keys:
        if not k or k not in data:
            continue
        v = data[k]
        if isinstance(v, dict):
            return dict(v)
        if v in ("run", "pause", "stop"):
            return {"control": v}
    return {}


def set_saved_control(control: str, *keys: str, nickname: Optional[str] = None, account_id: Optional[str] = None, target_level=None, keep_target: bool = True):
    if control not in ("run", "pause", "stop"):
        return
    data = load_account_status_raw()
    for k in keys:
        if not k:
            continue
        prev = data.get(str(k))
        entry: Dict[str, Any] = {}
        if isinstance(prev, dict):
            entry = dict(prev)
        elif prev in ("run", "pause", "stop"):
            entry = {"control": prev}
        entry["control"] = control
        if nickname:
            entry["nickname"] = str(nickname)
        if account_id is not None:
            entry["account_id"] = str(account_id)
        if target_level is not None:
            if target_level == "" or target_level is False:
                entry.pop("target_level", None)
            else:
                try:
                    entry["target_level"] = int(target_level)
                except Exception:
                    pass
        elif not keep_target:
            entry.pop("target_level", None)
        data[str(k)] = entry
    save_account_status(data)


def remove_saved_control(*keys: str):
    data = load_account_status_raw()
    changed = False
    for k in keys:
        if k and k in data:
            del data[k]
            changed = True
    if changed:
        save_account_status(data)


async def aes_encrypt(payload, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(payload, AES.block_size))

async def get_playstore_version():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: play_scraper('com.dts.freefireth', lang='en', country='sg')
    )
    return result.get("version")

async def version_config():
    app_version = await get_playstore_version()
    api_url = (
        "https://version.ggwhitehawk.com/live/ver.php"
        f"?version={app_version}"
        "&lang=hi&device=android&channel=android"
        "&appstore=googleplay&region=SG"
        "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
    )
    try:
        response = await client.get(api_url)
        response.raise_for_status()
        data = response.json()
        server_url = data.get("server_url")
        remote_version = data.get("remote_version")
        latest_release_version = data.get("latest_release_version")
        if not server_url or not remote_version or not latest_release_version:
            return None
        return latest_release_version, remote_version, server_url
    except Exception:
        return None

async def get_access_token(uid, password):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close"
    }
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    for attempt in range(5):
        try:
            await human_like_delay(0.2)
            response = await client.post(url, headers=hdrs, data=data)
            if response.status_code == 200:
                response_data = response.json()
                open_id = response_data.get("open_id")
                access_token = response_data.get("access_token")
                platform = response_data.get("platform", 4)
                if open_id and access_token:
                    return open_id, access_token, platform
            if response.status_code == 429:
                await asyncio.sleep(random.uniform(1.0, 2.0))
                continue
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.4, 0.8))
    return None

async def parse_results(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {"wire_type": result.wire_type}
        if result.wire_type == "varint":
            field_data["data"] = result.data
        elif result.wire_type == "string":
            field_data["data"] = result.data
        elif result.wire_type == "bytes":
            field_data["data"] = result.data
        elif result.wire_type == "length_delimited":
            field_data["data"] = await parse_results(result.data.results)
        result_dict[result.field] = field_data
    return result_dict

async def decode_protobuf(data):
    parsed_results = Parser().parse(data)
    parsed_results_dict = await parse_results(parsed_results)
    return json.dumps(parsed_results_dict)

async def EncodeVarint(number):
    if number < 0:
        raise ValueError("Number must be non-negative")
    EncodedBytes = []
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            byte |= 0x80
        EncodedBytes.append(byte)
        if not number:
            break
    return bytes(EncodedBytes)

async def create_varint_field(FieldNumber, Value):
    FieldHeader = (FieldNumber << 3) | 0
    HeaderBytes = await EncodeVarint(FieldHeader)
    ValueBytes = await EncodeVarint(Value)
    return HeaderBytes + ValueBytes

async def create_length_delimited_field(FieldNumber, Value):
    FieldHeader = (FieldNumber << 3) | 2
    EncodedValue = Value.encode() if isinstance(Value, str) else Value
    HeaderBytes = await EncodeVarint(FieldHeader)
    LengthBytes = await EncodeVarint(len(EncodedValue))
    return HeaderBytes + LengthBytes + EncodedValue


async def create_proto_packet(Fields):
    packet = bytearray()
    for FieldNumber, Value in Fields.items():
        if isinstance(Value, dict):
            NestedPacket = await create_proto_packet(Value)
            FieldBytes = await create_length_delimited_field(FieldNumber, NestedPacket)
            packet.extend(FieldBytes)
        elif isinstance(Value, int):
            FieldBytes = await create_varint_field(FieldNumber, Value)
            packet.extend(FieldBytes)
        elif isinstance(Value, str) or isinstance(Value, bytes):
            FieldBytes = await create_length_delimited_field(FieldNumber, Value)
            packet.extend(FieldBytes)
    return bytes(packet)

async def build_majorlogin_payload(open_id, access_token, platform, client_version, device_info):
    try:
        
        fields = {
            3: str(datetime.now())[:-7],
            4: "free fire",
            5: 1 if str(platform) in ["1", "4"] else int(platform),
            7: str(client_version),
            8: "Android OS 12 / API-31 (SP1A.210812.016/M025FXXS8CXH1)",
            9: "Handheld",
            11: "WIFI",
            12: 1600,
            13: 720,
            14: "280",
            15: "ARMv7 VFPv3 NEON | 1804 | 8",
            16: 3568,
            17: "Adreno (TM) 506",
            18: "OpenGL ES 3.2 V@0502.0 (GIT@5441528417, Id595308a47, 1648575532) (Date:03/29/22)",
            19: "Google|ff911c33-29e3-485f-922d-c6d633af5dc8",
            20: device_info.get("client_ip", "172.68.91.178"),
            21: "en",
            22: str(open_id),
            23: str(platform),
            24: "Handheld",
            25: "samsung SM-M025F",
            26: "BD",
            29: str(access_token),
            30: 1,
            42: "WIFI",
            57: "7428b253defc164018c604a1ebbfebdf",
            60: 53218,
            61: 7153,
            62: 2993,
            63: 18,
            64: 7281,
            65: 53218,
            66: 7281,
            67: 53218,
            70: 1,
            73: 1,
            74: "/data/app/~~mDd3EgZizFacrcWM7AVCDQ==/com.dts.freefireth-kxbpg2ZYeo4ckFSuUuJlFQ==/lib/arm",
            76: 1,
            77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~mDd3EgZizFacrcWM7AVCDQ==/com.dts.freefireth-kxbpg2ZYeo4ckFSuUuJlFQ==/base.apk",
            78: 3,
            79: 1,
            81: "32",
            83: "2019121229",
            85: 3,
            86: "OpenGLES2",
            87: 3071,
            88: int(platform),
            92: random.randint(10000, 13000),
            93: "android",
            94: "KqsHT2jq/39LltltUCKtrCDmH3iPJabTk1ngEtgg9LExoCMwwbvbV5bCVgCB5zUgNsUTxSrQUnHpxLG31Kiq0LLVbPilOj8Y09POZqzihx9iQMSD",
            95: 111207,
            96: "{\"cur_rate\":null,\"support_etc2\":false}",
            97: 1,
            99: str(platform),
            100: str(platform),
            102: "\u0014\u0006MESX_\u0006f",
            104: 61571,
            105: 1,
            106: "https://dl.bs.freefiremobile.com/live/ABHotUpdates/|https://core-bs.freefiremobile.com/live/ABHotUpdates/|a4332cb1c1a84e51dd77441e4856ed5a",
            107: "1.52e738d6c225490e"
        }

        final = await create_proto_packet(fields)

        return await aes_encrypt(final, AES_KEY, AES_IV)
    except Exception:
        return None


def _extract_jwt_from_bytes(content: bytes) -> Optional[str]:
    if b"eyJ" not in content:
        return None
    start = content.find(b"eyJ")
    end = start
    while end < len(content) and content[end] in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.":
        end += 1
    candidate = content[start:end].decode("ascii", errors="ignore")
    if candidate.count(".") >= 2 and len(candidate) > 80:
        return candidate
    return None


def _decode_jwt_payload(jwt_token: str) -> dict:
    try:
        import base64
        parts = jwt_token.split(".")
        if len(parts) < 2:
            return {}
        pad = "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(parts[1] + pad)
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}


def _bytes_field(val) -> bytes:
    if val is None:
        return b""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    if isinstance(val, str):
        try:
            if all(c in "0123456789abcdefABCDEF" for c in val) and len(val) % 2 == 0:
                return bytes.fromhex(val)
        except Exception:
            pass
        return val.encode("utf-8", errors="replace")
    return b""


async def _generic_proto_dict(content: bytes) -> dict:
    for offset in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24, 32, 48, 64, 80, 96, 128):
        if offset >= len(content):
            break
        try:
            parsed = Parser().parse(content[offset:].hex())
            d = await parse_results(parsed)
            if d:
                return d
        except Exception:
            continue
    return {}


def _pick_proto_value(d: dict, *field_nums):
    for n in field_nums:
        v = get_proto_field(d, n, None)
        if v is not None and v != "" and v != 0:
            return v
    return None


class MajorLoginResult:
    def __init__(self):
        self.token = ""
        self.region = "BD"
        self.account_id = 0
        self.server_time = int(time.time())
        self.aes_ak = b""
        self.iv_i = b""
        self.url = ""
        self.lockRegion = ""


async def send_majorlogin(data, release_version, server_url):
    try:
        url = f"{server_url.rstrip('/')}/MajorLogin"
        netloc = urlparse(server_url).netloc

        req_headers = {
            "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.12f1",
            "X-GA": "v1 1",
            "X-GA-SV": "1789535859",
            "ReleaseVersion": release_version,
            "Host": netloc,
            "Content-Length": str(len(data)),
            "Authorization": "Bearer",
        }

        print(f"\n[MajorLogin] POST {url}")
        print(f"[MajorLogin] Host={netloc}  ReleaseVersion={release_version}  Payload={len(data)} bytes")

        response = await client.post(url, headers=req_headers, data=data, timeout=15.0)

        content = response.content or b""
        print(f"[MajorLogin] HTTP {response.status_code}")
        print(f"[MajorLogin] Content-Length: {len(content)}")
        print(f"[MajorLogin] Headers: {dict(response.headers)}")

        try:
            text = content.decode("utf-8", errors="replace")
            print(f"[MajorLogin] Body (text):\n{text[:800]}")
        except Exception:
            text = ""
        print(f"[MajorLogin] Body (hex first 200): {content[:200].hex()}")

        if response.status_code != 200:
            print(f"[MajorLogin] Non-200 response → abort")
            return None

        if len(content) < 20:
            print("[MajorLogin] Body too short")
            return None

        jwt_token = _extract_jwt_from_bytes(content)
        if jwt_token:
            print(f"[MajorLogin] Found embedded JWT (len={len(jwt_token)})")

        res_proto = None

        for offset in (0, 4, 8, 16, 32, 64, 80, 96, 128):
            if offset >= len(content):
                break
            try:
                p = Yasin_pb2.MajorLoginRes()
                p.ParseFromString(content[offset:])
                if (getattr(p, "token", None) or getattr(p, "region", None) or
                    getattr(p, "lockRegion", None) or getattr(p, "serverUrl", None)):
                    res_proto = p
                    print(f"[MajorLogin] Parsed successfully (offset {offset})")
                    break
            except Exception as e:
                if offset == 0:
                    print(f"[MajorLogin] Direct parse failed: {e}")
                continue

        result = MajorLoginResult()
        result.url = server_url

        if res_proto is not None:
            result.token = getattr(res_proto, "token", None) or getattr(res_proto, "Token", None) or ""
            result.region = (
                getattr(res_proto, "region", None)
                or getattr(res_proto, "lockRegion", None)
                or getattr(res_proto, "lock_region", None)
                or "BD"
            )
            result.lockRegion = getattr(res_proto, "lockRegion", None) or result.region
            result.account_id = int(getattr(res_proto, "account_id", 0) or getattr(res_proto, "accountId", 0) or 0)
            result.server_time = int(getattr(res_proto, "server_time", 0) or getattr(res_proto, "serverTime", 0) or time.time())
            result.aes_ak = _bytes_field(getattr(res_proto, "aes_ak", None) or getattr(res_proto, "aesAk", None) or getattr(res_proto, "key", None))
            result.iv_i = _bytes_field(getattr(res_proto, "iv_i", None) or getattr(res_proto, "ivI", None) or getattr(res_proto, "iv", None))
            su = getattr(res_proto, "serverUrl", None) or getattr(res_proto, "server_url", None) or getattr(res_proto, "url", None)
            if su:
                result.url = su if isinstance(su, str) else str(su)
        else:
            print("[MajorLogin] Typed parse failed — trying generic protobuf decode")
            gdict = await _generic_proto_dict(content)
            if gdict:
                tok = _pick_proto_value(gdict, 1, 2, 3, 5, 7, 8, 10) or jwt_token
                if isinstance(tok, bytes):
                    tok = tok.decode("utf-8", errors="ignore")
                if isinstance(tok, str) and "eyJ" in tok:
                    result.token = tok[tok.find("eyJ"):] if "eyJ" in tok else tok
                elif jwt_token:
                    result.token = jwt_token
                elif isinstance(tok, str) and len(tok) > 40:
                    result.token = tok

                reg = _pick_proto_value(gdict, 3, 4, 6, 9, 11, 15)
                if isinstance(reg, str) and 1 < len(reg) <= 8:
                    result.region = reg.upper()

                aid = _pick_proto_value(gdict, 1, 2, 4, 5)
                if isinstance(aid, int) and aid > 1000:
                    result.account_id = aid

                for n in (12, 13, 14, 16, 17, 18, 20, 21, 22, 25, 30):
                    v = get_proto_field(gdict, n, None)
                    if isinstance(v, (bytes, bytearray)) and 8 <= len(v) <= 64:
                        if not result.aes_ak:
                            result.aes_ak = bytes(v)
                        elif not result.iv_i:
                            result.iv_i = bytes(v)
                    if isinstance(v, str) and v.startswith("http"):
                        result.url = v

                st = _pick_proto_value(gdict, 6, 7, 8, 9)
                if isinstance(st, int) and st > 1_600_000_000:
                    result.server_time = st

            if not result.token and jwt_token:
                result.token = jwt_token

        if result.token:
            claims = _decode_jwt_payload(result.token)
            if claims:
                print(f"[MajorLogin] JWT claims keys: {list(claims.keys())[:12]}")
                for k in ("account_id", "accountId", "uid", "user_id", "sub"):
                    if k in claims and not result.account_id:
                        try:
                            result.account_id = int(claims[k])
                        except Exception:
                            pass
                for k in ("region", "lock_region", "lockRegion", "server_region"):
                    if k in claims and claims[k]:
                        result.region = str(claims[k]).upper()
                for k in ("server_url", "serverUrl", "url", "bp_url"):
                    if k in claims and str(claims[k]).startswith("http"):
                        result.url = str(claims[k])

        if not result.token:
            print("[MajorLogin] ✗ No token / JWT found — payload, version or device mismatch")
            return None

        if "version" in (result.url or "").lower() or not result.url:
            result.url = server_url

        print(
            f"[MajorLogin] ✓ SUCCESS  region={result.region}  "
            f"account_id={result.account_id}  token_len={len(result.token)}  "
            f"aes={len(result.aes_ak)} iv={len(result.iv_i)}  url={result.url}"
        )
        return result

    except Exception as e:
        print(f"[MajorLogin] Exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


async def send_getlogin(data, base_url, token, release_version):
    try:
        if not base_url:
            print("[GetLoginData] Missing base_url")
            return None

        url = f"{base_url.rstrip('/')}/GetLoginData"
        netloc = urlparse(base_url).netloc or "clientbp.ppmainecoonghj.com"

        req_headers = headers.copy()
        req_headers["ReleaseVersion"] = release_version
        req_headers["Authorization"] = f"Bearer {token}"
        req_headers["Host"] = netloc
        req_headers["Content-Length"] = str(len(data)) if data else "0"

        print(f"[GetLoginData] POST {url}")
        print(f"[GetLoginData] Host={netloc}  token_len={len(token) if token else 0}")

        await human_like_delay(0.1)
        response = await client.post(url, headers=req_headers, data=data, timeout=15.0)
        response_content = response.content or b""

        print(f"[GetLoginData] HTTP {response.status_code}  body={len(response_content)} bytes")
        if response.status_code != 200:
            try:
                print(f"[GetLoginData] Body preview: {response_content[:300]!r}")
            except Exception:
                pass
            return None

        if len(response_content) < 8:
            print("[GetLoginData] Body too short")
            return None

        res_proto = Yasin_pb2.GetLoginDataRes()
        parsed_successfully = False
        try:
            res_proto.ParseFromString(response_content)
            if getattr(res_proto, "functional_addrs", None) or getattr(res_proto, "informational_addrs", None):
                parsed_successfully = True
                print("[GetLoginData] Parsed at offset 0")
        except Exception as e:
            print(f"[GetLoginData] Direct parse failed: {e}")

        if not parsed_successfully:
            for offset in range(0, min(160, len(response_content))):
                try:
                    candidate = Yasin_pb2.GetLoginDataRes()
                    candidate.ParseFromString(response_content[offset:])
                    if getattr(candidate, "functional_addrs", None) or getattr(candidate, "informational_addrs", None):
                        res_proto = candidate
                        parsed_successfully = True
                        print(f"[GetLoginData] Parsed at offset {offset}")
                        break
                except Exception:
                    pass

        dict_res = {}
        try:
            dict_res = await _generic_proto_dict(response_content)
        except Exception:
            pass

        if not parsed_successfully:
            fa = get_proto_field(dict_res, 14, None) or get_proto_field(dict_res, 15, None)
            ia = get_proto_field(dict_res, 32, None) or get_proto_field(dict_res, 33, None)
            if fa or ia:
                class FakeLogin:
                    pass
                fake = FakeLogin()
                fake.functional_addrs = fa if isinstance(fa, str) else (fa.decode() if isinstance(fa, bytes) else "")
                fake.informational_addrs = ia if isinstance(ia, str) else (ia.decode() if isinstance(ia, bytes) else "")
                fake.nickname = get_proto_field(dict_res, 4, "") or ""
                res_proto = fake
                parsed_successfully = True
                print("[GetLoginData] Using generic field extract")

        if not parsed_successfully and not dict_res:
            print("[GetLoginData] ✗ Could not parse response")
            print(f"[GetLoginData] Hex head: {response_content[:120].hex()}")
            return None

        return res_proto, dict_res
    except Exception as e:
        print(f"[GetLoginData] Exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None

async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="ID", typ='OnLine'):
    uid_hex = f"{int(account_id):016x}"
    timestamp_hex = f"{int(server_time):08x}"
    encode_token = token.encode()
    encrypted_packet = (await aes_encrypt(encode_token, key, iv)).hex()
    encrypted_packet_length = f"{len(encrypted_packet) // 2:08x}"
    reg = str(region).upper() if region else "BD"
    if typ == 'OnLine':
        prefix = '7119' if reg == 'BD' else ('7114' if reg == 'IND' else '7115')
        return f"{prefix}{uid_hex}{timestamp_hex}00000000{encrypted_packet_length}{encrypted_packet}"
    else:
        prefix = '9219' if reg == 'BD' else ('9214' if reg == 'IND' else '9215')
        return f"{prefix}{uid_hex}{timestamp_hex}{encrypted_packet_length}{encrypted_packet}"

async def send_keep_alive(region="BD"):
    try:
        reg = str(region).upper() if region else "BD"
        ka_hex = "0219" if reg == "BD" else ("0214" if reg == "IND" else "0215")
        return bytes.fromhex(ka_hex)
    except Exception:
        return bytes.fromhex("0219")


async def start_game_lone_wolf(region, client_version, writer, key, iv, guard=None):
    packet = bytes.fromhex("080112800a0a010b102b3a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = Yasin_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    packet = proto.SerializeToString()
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    final_packet = "031900" + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    await human_like_delay(0.1)
    if guard is not None and not guard():
        return False
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()
    return True


async def start_game_battle_royale(region, client_version, writer, key, iv, guard=None):
    packet = bytes.fromhex(
        "080112f7090a010110013a110a044944433110d1011a064555524f50453a110a044944433210a1011a064555524f504540014a0801090a0b1219202758016287090a80013038384638324246303241393637363730323031303230303030303030303030303031383030303230303136303030333737383332363333304630303030303034363736323531343131303130343031313737323832363730653734386333663661363865653765303030303030666630303031303130326361636661313664101d1afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f13040648514a0e02007c410856007f0654011a4a420472410504617b7d57630b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0816746757076316134208312e3133302e3231480350015ae10403626253513632347634793538416456324b796f566c6143314b2b4f6a51517248742f314b32626d44644e786f6366432b63304e4f7a376e57466e4b70396d3949616849474a58487a69685437755573656868625545362b6d3849474d524d63777879506672757a38312f5979747269514e387737324a376c714b6e56306b6d3463674e70796f4b63434a7a4f4163677a716a635739374477306d56417a7355782f6859624175336c78626131384f6669572b52323546314466307a4539324a6c6a784c746841493444347155564b7a4c67317a2f32414a37574c6e36524248423677454d423944707972627968684e394e796e397a686f7a41714347667766685447364b6270544a315a354243376369396f4363476a53716d44446a3236437465514a4a4c48434155726778584f466e3778665967634270305345544b2b586f415756527a4f4153515075724856576f3837574c3455334a5a413839346d596b78384365366148516b5a77614d537053796137456f474f6950686152314b50774845505573796264393641534f505a344565426d4635445570474c4b67476e382b46466b306341504a4c76706255774b527a445148784f64525449554974745830524e4e6a5133756c3249614b665a5734557633657831694968346d3478686254516937762f61426849313848596f7352397473446a2f2f344d45642b6c6b7a75363373354258463753566951772f516d53394d4f574b3536734b476564595669554a46394b544a6b434e51565551784435503646485155776a745358723234786b314662417448385771496767376a6555536b44506d6149366b2f4d4f3665a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815"
    )
    proto = Yasin_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    packet = proto.SerializeToString()
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    final_packet = "031900" + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    await human_like_delay(0.1)
    if guard is not None and not guard():
        return False
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()
    return True

async def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)

async def uleb_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8)
    prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8):
            xored[j] = padded[i + j] ^ prev_cipher[j]
        e0, e1 = await tea_enc(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3,
        )
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0)
        struct.pack_into("<I", enc, 4, e1)
        for j in range(8):
            out[i + j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i + 8]
        prev_intermediate[:] = xored
    return bytes(out)

async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

async def encode_header(layout, send_option, cmd, order_id, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: length}[code]
        if _FIELD_SIZES[code] == 1:
            out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF)
            out.append((v >> 8) & 0xFF)
    return bytes(out)

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def sv_frame(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + await encode_header(layout, send_option, cmd, order_id, flags, len(body), k, v80)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def build_match_startup_packets(token, udp_key, match_code, account_id, block_val,
                                      server_ip="", region="BD", client_version="1.132.9",
                                      client_version_code="2019121229", access_token="",
                                      mode_id=LONE_WOLF_MODE_ID, map_id=LONE_WOLF_MAP_ID):
    token = token.strip()
    udp_key = bytes.fromhex(udp_key)
    match_code = [int(ch) for ch in str(match_code).strip()]

    thunder_jwt = token[:660] if len(token) > 660 else token
    sharma_jwt = token[660:] if len(token) > 660 else ""
    encoded_thunder_jwt = thunder_jwt.encode() if isinstance(thunder_jwt, str) else thunder_jwt
    encoded_sharma_jwt = sharma_jwt.encode() if isinstance(sharma_jwt, str) else sharma_jwt

    garena420 = await has_ssan_zig(len(encoded_thunder_jwt)) + encoded_thunder_jwt

    reg = str(region).upper() if region else "BD"
    csoversea_block = bytes.fromhex(
        "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
        "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
        "3137302e3233303b33352e3138352e3138332e35370000000000000100000000000000000000000001"
        "00000800000100000000000100a8a2d7bebd8d8bdf110200"
    )

    mid = bytes.fromhex('0000000001000102030101') + await has_ssan_zig(len(reg)) + reg.encode()
    mid += bytes.fromhex('0001030003000004')
    mid += await has_ssan_zig(len(client_version)) + client_version.encode()
    mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
    mid += csoversea_block

    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()

    clean_acc_tok = access_token.strip() if access_token else ""
    if clean_acc_tok:
        mid += await has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()

    mid += await has_ssan_zig(len(encoded_sharma_jwt)) + encoded_sharma_jwt

    tg_garena420 = (
        await uleb_encode(int(account_id)) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(1) +
        await uleb_encode(int(mode_id)) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(int(map_id)) +
        mid
    )

    process = await sv_frame(0x5E, match_code, 2, 447, 0, 1, garena420, udp_key)
    loading = await sv_frame(0x5A, match_code, 2, 448, 1, 1, tg_garena420, udp_key)
    return process.hex(), loading.hex()

async def produce_xor_key(secret_key):
    k = secret_key[0] if secret_key and len(secret_key) > 0 else 10
    return k, ((k << 8) | k) & 0xFFFF

async def parse_layout(layout):
    if isinstance(layout, str):
        return [int(ch) for ch in layout.strip()]
    return list(layout)

async def tea_cbc_decrypt(body, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8)
    prev_cipher = bytearray(8)
    xored = bytearray(8)
    dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8):
            xored[j] = body[i + j] ^ prev_intermediate[j]
        d0, d1 = await tea_dec(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3
        )
        struct.pack_into("<I", dec, 0, d0)
        struct.pack_into("<I", dec, 4, d1)
        for j in range(8):
            out[i + j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i + 8]
        prev_intermediate[:] = dec
    return bytes(out)

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25:
        raise ValueError(f"Text is too long ({len(data)} bytes)")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k, v80 = await produce_xor_key(key)
    layout = await parse_layout(layout)
    padded = await build_padded(content)
    enc_body = await tea_cbc_encrypt(padded, key)
    header_bytes = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = await crc7_buff(0, packet[2:]) & 0x7F
    return bytes(packet).hex()

async def classify(frame):
    cmd = frame["cmd"]
    msg_name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if msg_name == "UDP_HELLO":
        return "HELLO"
    if msg_name == "UDP_ACK":
        return "ACK"
    if msg_name == "UDP_PING":
        return "PING"
    if msg_name == "RUDP_JOIN_MATCH":
        return "JOIN_MATCH"
    if msg_name.startswith("RUDP_"):
        return msg_name
    if msg_name.startswith("UDP_"):
        return msg_name
    return "DATA"

async def build_packet(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: len(body)}[code]
        if _FIELD_SIZES[code] == 1:
            hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF)
            hdr.append((v >> 8) & 0xFF)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr

async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    ru, nr = await layouts_from_mask(mask)
    typ = await classify(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame["content"]
        counter = c[:4] if len(c) >= 4 else c
        return typ, await build_packet(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None

async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_event_loop()
    i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try:
            await loop.sock_sendto(sock, pkt, (ip, port))
        except Exception:
            pass
        i += 1
        interval = await get_randomized_interval(2.5, 3.8)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

async def try_header(buf, layout, k, v80):
    off = 2
    out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf):
            return None
        out[_FIELD_NAMES[code]] = (buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off + 1] << 8)) ^ v80) & 0xFFFF
        off += size
    out["headerLen"] = off
    return out

async def oicq_unpad(padded):
    if not padded or len(padded) < 8:
        return None
    if not all(padded[-1 - i] == 0 for i in range(7)):
        return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len
    e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def decode_packet(packet, key, mask=None):
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8:
        return None
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    candidates = []
    if mask:
        ru, nr = await layouts_from_mask(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0, 1, 2, 3, 4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0, 1, 3, 4])]
    for kind, layout in layouts:
        f = await try_header(data, layout, k, v80)
        if not f:
            continue
        if f["flags"] > 7 or f["sendOption"] > 7:
            continue
        if f["length"] != len(data) - f["headerLen"]:
            continue
        body = data[f["headerLen"]:f["headerLen"] + f["length"]]
        content = None
        padded = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0:
                continue
            padded = await tea_cbc_decrypt(body, key)
            content = await oicq_unpad(padded)
            if content is None:
                continue
        else:
            content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        candidates.append({
            "kind": kind, "layout": layout, "headerLen": f["headerLen"],
            "msgKey": data[0], "cmd": f["cmd"], "flags": f["flags"],
            "sendOption": f["sendOption"], "orderId": f.get("orderId"),
            "length": f["length"], "content": content, "crcOk": crc_ok,
            "padded": padded, "score": score, "total": len(data),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["kind"] == "RUDP" or c["kind"] == "nonRUDP", c["score"]), reverse=True)
    return candidates[0]


async def zigzag_encode_signed(n: int) -> bytes:
    try:
        n = int(n)
    except Exception:
        n = 0
    zz = (n << 1) ^ (n >> 63)
    if zz < 0:
        zz = -zz
    out = bytearray()
    while True:
        b = zz & 0x7F
        zz >>= 7
        if zz:
            b |= 0x80
        out.append(b)
        if not zz:
            break
    return bytes(out)


async def build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z,
                                     tick, counter, move_state, account_uid,
                                     room_code, phase="arena"):
    if phase == "arena":
        TAIL = (b"\x00" * 7 +
                b"\xbd\xb6\xe1\xf3\x03" +
                b"\x00" +
                b"\xc4\xb6\xe1\xfb\x0b" +
                b"\x00\x00")
    elif phase == "game":
        TAIL = (b"\x00" * 7 +
                b"\x93\xca\xd5\xf9\x0b" +
                b"\x8e\xfe\xfc\xf7\x0b" +
                b"\xf4\xe0\xfe\xf7\x03" +
                b"\x00\x00")
    else:
        TAIL = (b"\x00" * 7 +
                b"\xbd\xb6\xe1\xf3\x03" +
                b"\x00" +
                b"\xc4\xb6\xe1\xfb\x0b" +
                b"\x00\x00")

    x_i = int(x)
    y_i = int(y)
    z_i = int(z)

    body = bytearray()
    body += await uleb_encode(int(account_uid))
    body += await uleb_encode(int(player_state))
    body += await zigzag_encode_signed(x_i)
    body += await zigzag_encode_signed(y_i)
    body += await zigzag_encode_signed(z_i)
    body += b"\x00"
    body += await uleb_encode(int(move_state))
    body += TAIL
    body += await uleb_encode(int(tick))
    body += b"\x00\x00\x00"
    body += await uleb_encode(int(counter))
    body = bytes(body)

    k = key_bytes[0]
    v80 = ((k << 8) | k) & 0xFFFF

    h = bytearray()
    h.append(msg_key & 0xFF)
    h.append(0x00)
    h.append(0x00 ^ k)
    h += ((2001 ^ v80) & 0xFFFF).to_bytes(2, "little")
    h += ((len(body) ^ v80) & 0xFFFF).to_bytes(2, "little")
    h.append(0x00 ^ k)

    h[1] = (await crc7_buff(0, bytes(h[2:]) + body)) & 0x7F
    return bytes(h) + body


class MovementTracker:
    PLAYER_STATE = {
        "idle":   0,
        "walk":   1,
        "run":    2,
        "sprint": 3,
        "jump":   4,
        "crouch": 5,
        "prone":  6,
    }

    def __init__(self, pattern="circle", radius=180):
        self.pattern = pattern
        self.radius = int(radius)
        self.tick = 0
        self.counter = 0
        self.angle = random.uniform(0, 6.2832)
        self.speed_multiplier = 1.0
        self.dir_flip = 1
        self._next_speed_roll = time.time()

        self.state = "walk"
        self.state_start = time.time()
        self.state_duration = random.uniform(2.0, 4.0)

        self._roll_new_speed()

    def _roll_new_speed(self):
        try:
            lo, hi = float(MOVEMENT_SPEED_MIN), float(MOVEMENT_SPEED_MAX)
            if hi < lo:
                lo, hi = hi, lo
            self.speed_multiplier = round(random.uniform(lo, hi), 2)
        except Exception:
            self.speed_multiplier = 1.0
        self._next_speed_roll = time.time() + MOVEMENT_UPDATE_SPEED_EVERY

    def _pick_next_state(self):
        r = random.random()
        c_idle   = MOVEMENT_STATE_IDLE_CHANCE
        c_walk   = c_idle   + MOVEMENT_STATE_WALK_CHANCE
        c_run    = c_walk   + MOVEMENT_STATE_RUN_CHANCE
        c_sprint = c_run    + MOVEMENT_STATE_SPRINT_CHANCE
        c_jump   = c_sprint + MOVEMENT_STATE_JUMP_CHANCE
        c_crouch = c_jump   + MOVEMENT_STATE_CROUCH_CHANCE

        if r < c_idle:
            return "idle",   random.uniform(0.6, 1.6)
        elif r < c_walk:
            return "walk",   random.uniform(1.6, 3.0)
        elif r < c_run:
            return "run",    random.uniform(2.0, 4.0)
        elif r < c_sprint:
            return "sprint", random.uniform(1.2, 2.5)
        elif r < c_jump:
            return "jump",   random.uniform(0.35, 0.65)
        elif r < c_crouch:
            return "crouch", random.uniform(1.2, 2.5)
        else:
            return "prone",  random.uniform(1.5, 3.5)

    def _generate_movement(self):
        p = (self.pattern or "circle").lower()
        x = y = z = 0
        ms = 0

        if p == "circle":
            self.angle += 0.35 * self.dir_flip
            if self.angle > 6.2832:
                self.angle -= 6.2832
            elif self.angle < 0:
                self.angle += 6.2832
            x = int(self.radius * random.uniform(0.9, 1.1) * (1.0 if self.angle % 3.14 < 1.57 else -1.0))
            y = int(self.radius * random.uniform(0.4, 0.6))
            z = int(self.radius * random.uniform(0.9, 1.1) * (1.0 if self.angle % 6.28 < 3.14 else -1.0))
            ms = 0x0F
        elif p == "zigzag":
            step = self.radius // 4
            x = random.choice([-1, 1]) * random.randint(step, self.radius)
            y = random.randint(-20, 20)
            z = self.dir_flip * random.randint(step, self.radius)
            if random.random() < 0.25:
                self.dir_flip *= -1
            ms = 0x03
        elif p == "forward":
            x = random.randint(-30, 30)
            y = 0
            z = self.radius * self.dir_flip
            ms = 0x01
        else:
            x = random.randint(-self.radius, self.radius)
            y = random.randint(-40, 40)
            z = random.randint(-self.radius, self.radius)
            ms = random.choice([0x01, 0x02, 0x04, 0x08, 0x0F])

        return x, y, z, ms

    def next(self):
        now = time.time()
        if now >= self._next_speed_roll:
            self._roll_new_speed()

        if now - self.state_start > self.state_duration:
            new_state, new_dur = self._pick_next_state()
            self.state = new_state
            self.state_duration = new_dur
            self.state_start = now

        self.tick = (self.tick + 1) & 0xFFFFFFFF
        self.counter = (self.counter + 1) & 0xFFFFFFFF

        player_state = self.PLAYER_STATE.get(self.state, 1)

        if self.state in ("idle", "crouch", "prone"):
            x = y = z = 0
            move_state = 0
        else:
            x, y, z, move_state = self._generate_movement()

        return player_state, x, y, z, move_state, self.tick, self.counter, self.speed_multiplier, self.state


async def movement_worker(sock, resolved_ip, port, udp_key_bytes, match_code,
                          account_id, stop_event, match_index):
    loop = asyncio.get_event_loop()
    server_addr = (resolved_ip, port)
    tracker = MovementTracker(pattern=MOVEMENT_PATTERN, radius=MOVEMENT_RADIUS)

    try:
        await asyncio.sleep(bypass_jitter(3.0, 0.5))
        while not stop_event.is_set():
            try:
                (player_state, x, y, z, move_state,
                 tick, counter, speed_mult, state_name) = tracker.next()

                pkt = await build_movement_packet_2001(
                    udp_key_bytes, 0x6B, player_state,
                    x, y, z, tick, counter, move_state,
                    account_id, match_code,
                    phase="arena"
                )
                await loop.sock_sendto(sock, pkt, server_addr)

                base_wait = MOVEMENT_TICK_MS / 1000.0
                try:
                    sm = max(0.7, min(float(speed_mult), 1.6))
                except Exception:
                    sm = 1.0
                adj_wait = base_wait / sm
                adj_wait = max(0.10, min(adj_wait, 0.40))
                wait = bypass_packet_jitter(adj_wait, 0.20)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                    break
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                print_warning(f"[MOVE] loop error #{match_index}: {e}")
                await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


async def send_anti_afk_fire(sock, server_addr, udp_key_bytes, match_code, account_id):
    try:
        nr = (await layouts_from_mask(match_code))[1]
        try:
            player_id = int(account_id)
        except Exception:
            player_id = 0
        ts = int(time.time() * 1000) & 0xFFFFFFFF
        weapon_id = random.choice([101, 102, 103, 201, 202])
        fire_body = struct.pack("<IIHB", player_id & 0xFFFFFFFF, ts, weapon_id, 1)
        fire_pkt = await build_packet(0x68, nr, 0, 104, None, 0, fire_body, udp_key_bytes, encrypted=False)
        loop = asyncio.get_event_loop()
        await loop.sock_sendto(sock, fire_pkt, server_addr)
        await asyncio.sleep(bypass_jitter(random.uniform(0.15, 0.30), 0.05))
        stop_body = struct.pack("<IIHB", player_id & 0xFFFFFFFF, ts + 200, weapon_id, 0)
        stop_pkt = await build_packet(0x68, nr, 0, 105, None, 0, stop_body, udp_key_bytes, encrypted=False)
        await loop.sock_sendto(sock, stop_pkt, server_addr)
        return True
    except Exception:
        return False


async def anti_afk_worker(sock, resolved_ip, port, udp_key_bytes, match_code,
                          account_id, stop_event, match_index):
    server_addr = (resolved_ip, port)
    try:
        await asyncio.sleep(bypass_jitter(2.5, 0.5))
        while not stop_event.is_set():
            try:
                await send_anti_afk_fire(sock, server_addr, udp_key_bytes, match_code, account_id)
                wait_time = random.uniform(ANTI_AFK_MIN_INTERVAL, ANTI_AFK_MAX_INTERVAL)
                wait_time = bypass_packet_jitter(wait_time, 0.25)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_time)
                    break
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass


async def _stop_aux_task(task, stop_event=None, grace: float = 2.0):
    if stop_event is not None:
        stop_event.set()
    if not task:
        return
    try:
        await asyncio.wait_for(task, timeout=grace)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    except (asyncio.CancelledError, Exception):
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


async def _play_udp_match(mode: str, server_ip_port, thunder, sharma, udp_key, match_code,
                          account_id, match_index: int, on_match_complete=None):
    """One UDP match session. BR and LW share this exact handshake/keepalive code;
    only the finish rule differs (see MODE_PROFILES). Each session owns its socket,
    keys, tasks and events, so concurrent BR and LW sessions can never touch each other."""
    profile = MODE_PROFILES[mode]
    lbl = f"MATCH #{match_index}|{mode}"
    match_start_time = time.time()
    last_activity = match_start_time
    MAX_IDLE_BEFORE_HELLO_RESEND = 7.0

    ping_task = None
    movement_task = None
    anti_afk_task = None
    sock = None
    ping_stop = asyncio.Event()
    movement_stop = asyncio.Event()
    anti_afk_stop = asyncio.Event()
    uid_str = str(account_id)
    completed_cleanly = False

    try:
        ip, port = server_ip_port.split(":")
        port = int(port)
        resolved_ip = await resolve_host_cloudflare(ip)
        server_addr = (resolved_ip, port)

        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("0.0.0.0", 0))
        except Exception:
            pass
        optimize_udp_socket(sock)
        sock.setblocking(False)
        udp_key_bytes = bytes.fromhex(udp_key)

        await asyncio.sleep(bypass_hello_delay())

        hello_packet = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
        await loop.sock_sendto(sock, bytes.fromhex(hello_packet), server_addr)

        ack_state = "waiting_for_hello_reply"
        thunder_sent = False
        sharma_sent = False
        join_match_received = False
        local_closed = False
        anti_afk_started = False
        send_lock = asyncio.Lock()

        ping_task = asyncio.create_task(
            keepalive_ping(sock, resolved_ip, port, udp_key_bytes, match_code, ping_stop)
        )
        print_colored(
            f"[{lbl}] UDP started -> {server_ip_port} (DNS: {resolved_ip})",
            Colors.MAGENTA
        )

        async def start_anti_afk_once():
            nonlocal anti_afk_task, anti_afk_started, movement_task
            if anti_afk_started:
                return
            anti_afk_started = True
            anti_afk_task = asyncio.create_task(
                anti_afk_worker(sock, resolved_ip, port, udp_key_bytes, match_code,
                                account_id, anti_afk_stop, match_index)
            )
            print_success(f"[AFK] Worker Started | {lbl}")
            if ENABLE_SPEED_MOVEMENT:
                movement_task = asyncio.create_task(
                    movement_worker(sock, resolved_ip, port, udp_key_bytes, match_code,
                                    account_id, movement_stop, match_index)
                )
                print_success(
                    f"[MOVE] Worker Started | {lbl} "
                    f"| Pattern: {MOVEMENT_PATTERN} | Speed: {MOVEMENT_SPEED_MIN}x-{MOVEMENT_SPEED_MAX}x"
                )

        async def send_thunder_sharma_inline():
            nonlocal ack_state, thunder_sent, sharma_sent
            if sharma_sent:
                return
            async with send_lock:
                if sharma_sent:
                    return
                try:
                    if not thunder_sent:
                        await loop.sock_sendto(sock, bytes.fromhex(thunder), server_addr)
                        thunder_sent = True
                        await asyncio.sleep(bypass_jitter(0.1, 0.05))
                        prepare_ack = await build_packet(
                            0x68, (await layouts_from_mask(match_code))[1],
                            0, 2, None, 1, b"\x01\x00", udp_key_bytes
                        )
                        await loop.sock_sendto(sock, prepare_ack, server_addr)
                        await asyncio.sleep(bypass_jitter(0.2, 0.05))
                    await loop.sock_sendto(sock, bytes.fromhex(sharma), server_addr)
                    sharma_sent = True
                    ack_state = "thunder_sharma_sent"
                    print_success(f"[{lbl}] Startup packets delivered")
                    await start_anti_afk_once()
                except Exception as e:
                    print_error(f"[{lbl}] send error: {e}")

        while not local_closed:
            if time.time() - match_start_time > MAX_MATCH_DURATION:
                break
            try:
                response, from_addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535), timeout=1.5
                )
                if response:
                    last_activity = time.time()
                    frame = await decode_packet(response, udp_key_bytes, match_code)
                    if frame:
                        ptype = await classify(frame)
                        if frame["cmd"] in (103, 107):
                            print_success(f"[{lbl}] Completed (cmd {frame['cmd']})")
                            completed_cleanly = True
                            local_closed = True
                            continue
                        if frame["cmd"] == 101:
                            try:
                                ack_pkt = await build_packet(
                                    0x68, (await layouts_from_mask(match_code))[1],
                                    0, 2, None, 1, b"\x01\x00", udp_key_bytes
                                )
                                await loop.sock_sendto(sock, ack_pkt, from_addr)
                            except Exception:
                                pass
                            continue
                        if ptype in ("ACK", "PING", "HELLO", "JOIN_MATCH"):
                            if ptype == "HELLO" and ack_state == "waiting_for_hello_reply":
                                _, reply = await reply_for(frame, udp_key_bytes, match_code, ack_style="short")
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                                ack_state = "ack_sent_waiting"
                            elif ptype == "ACK":
                                if ack_state == "waiting_for_hello_reply":
                                    _, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        await loop.sock_sendto(sock, reply, from_addr)
                                    ack_state = "ready_to_send_thunder"
                                elif ack_state == "ack_sent_waiting":
                                    ack_state = "ready_to_send_thunder"
                                else:
                                    _, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        await loop.sock_sendto(sock, reply, from_addr)
                            elif ptype == "PING":
                                _, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                            elif ptype == "JOIN_MATCH" and not join_match_received:
                                _, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    await loop.sock_sendto(sock, reply, from_addr)
                                    join_match_received = True
            except asyncio.TimeoutError:
                now = time.time()
                if ack_state == "ready_to_send_thunder" and not sharma_sent:
                    await send_thunder_sharma_inline()
                elif ack_state == "waiting_for_hello_reply":
                    if (now - last_activity) > MAX_IDLE_BEFORE_HELLO_RESEND:
                        try:
                            pkt = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
                            await loop.sock_sendto(sock, bytes.fromhex(pkt), server_addr)
                        except Exception:
                            pass
                        last_activity = now
                    if (now - match_start_time) > UDP_HANDSHAKE_TIMEOUT:
                        print_warning(f"[{lbl}] Handshake timeout")
                        break
                elif ack_state == "thunder_sharma_sent":
                    if profile["hold"] is not None:
                        finished = (now - match_start_time) > profile["hold"]
                    else:
                        finished = (now - last_activity) > profile["idle_timeout"]
                    if finished:
                        print_success(f"[{lbl}] Finished naturally")
                        completed_cleanly = True
                        break
                continue
            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if ack_state == "ready_to_send_thunder" and not sharma_sent:
                await send_thunder_sharma_inline()

        if not completed_cleanly and sharma_sent:
            completed_cleanly = True
            print_success(f"[{lbl}] Counted as played (joined match)")

        return f"match #{match_index} finished"
    except asyncio.CancelledError:
        print_warning(f"[{lbl}] cancelled")
        raise
    except Exception as e:
        print_error(f"[{lbl}] error: {e}")
        return f"match #{match_index} error"
    finally:
        if completed_cleanly:
            try:
                bot_state.increment_match(uid_str)
                _update_device_match_count(uid_str)
            except Exception as e:
                print_error(f"[{lbl}] increment_match failed: {e}")
            if on_match_complete:
                try:
                    asyncio.create_task(on_match_complete())
                except Exception as e:
                    print_warning(f"[EXP-REFRESH] post-match trigger failed: {e}")
        await _stop_aux_task(anti_afk_task, anti_afk_stop)
        await _stop_aux_task(movement_task, movement_stop)
        await _stop_aux_task(ping_task, ping_stop)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        remaining = await _dec_match(uid_str)
        total = await _get_total_match_count()
        print_info(f"[{lbl}] Closed. UID active: {remaining} | Total active: {total}")
        try:
            publish_status(uid_str, remaining)
        except Exception:
            pass


async def play_game(server_ip_port, thunder, sharma, udp_key, match_code,
                    account_id, player_region, client_version, key, iv,
                    match_index: int, on_match_complete=None):
    return await _play_udp_match("BR", server_ip_port, thunder, sharma, udp_key, match_code,
                                 account_id, match_index, on_match_complete)


async def play_game_lw(server_ip_port, thunder, sharma, udp_key, match_code,
                       account_id, player_region, client_version, key, iv,
                       match_index: int, on_match_complete=None):
    return await _play_udp_match("LW", server_ip_port, thunder, sharma, udp_key, match_code,
                                 account_id, match_index, on_match_complete)


async def functional_lone_wolf(addrs, starter_packet, account_region, client_version,
                                key, iv, account_id="", account_data=None,
                                account_level: int = 2, max_reconnects=10):
    reconnects = 0
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    search_attempts = 0
    current_level = int(account_level or 2)
    last_start_time = 0.0
    uid_str = str(account_id)

    consecutive_parse_failures = 0
    match_modes: Dict[asyncio.Task, str] = {}

    current_token = starter_packet
    current_key = key
    current_iv = iv
    current_account_data = account_data

    async def trigger_post_match_refresh():
        await asyncio.sleep(EXP_REFRESH_AFTER_MATCH_DELAY)
        try:
            cd = bot_state.account_credentials.get(uid_str)
            if cd:
                await refresh_account_profile(cd)
        except Exception as e:
            print_warning(f"[EXP-REFRESH] post-match refresh error: {e}")

    def _resolve_current_level() -> int:
        lvl = int(account_level or 2)
        try:
            if current_account_data and current_account_data.get('level') is not None:
                lvl = max(lvl, int(current_account_data['level']))
        except Exception:
            pass
        try:
            live = bot_state.accounts.get(uid_str, {}).get('level')
            if live is not None:
                lvl = max(lvl, int(live))
        except Exception:
            pass
        try:
            cred = bot_state.account_credentials.get(uid_str)
            if cred and cred.get('level') is not None:
                lvl = max(lvl, int(cred['level']))
        except Exception:
            pass
        return lvl

    def _control_state() -> str:
        try:
            acc = bot_state.accounts.get(uid_str)
            if not acc:
                return "run"
            if acc.get("control") == "stop":
                return "stop"
            if acc.get("control") == "pause":
                return "pause"
        except Exception:
            pass
        return "run"

    def desired_mode() -> str:
        """Single source of truth for BR vs LW, evaluated live every time it is asked."""
        nonlocal current_level
        lvl = _resolve_current_level()
        if lvl != current_level:
            print_info(f"[LEVEL] UID {uid_str}: {current_level} -> {lvl}")
            current_level = lvl
            # Fire-and-forget target check on observed level-up
            try:
                asyncio.create_task(maybe_check_target_level(uid_str, lvl))
            except Exception:
                pass
        return mode_for_level(lvl)

    def cancel_stale_sessions(new_mode: str):
        if new_mode != "LW" or not CANCEL_BR_SESSIONS_ON_LW_UNLOCK:
            return
        for t, m in list(match_modes.items()):
            if m == "BR" and not t.done():
                print_warning(f"[MODE SWITCH] UID {uid_str}: cancelling running BR session")
                t.cancel()

    try:
        while True:
            ctrl = _control_state()
            if ctrl == "stop":
                print_warning(f"[FUNCTIONAL] Stop requested for {uid_str} — exiting worker")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                _searching_mode[uid_str] = None
                try:
                    bot_state.update_status(uid_str, "STOPPED", 0)
                except Exception:
                    pass
                return
            if ctrl == "pause":
                try:
                    bot_state.update_status(uid_str, "PAUSED", await _get_match_count(uid_str))
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                continue

            writer = None
            try:
                if current_account_data:
                    fresh = None
                    if current_account_data.get('auth_type') == 'guest' and current_account_data.get('auth_uid'):
                        fresh = cache_get(str(current_account_data['auth_uid']))
                    elif current_account_data.get('auth_type') == 'token' and current_account_data.get('auth_token'):
                        fresh = cache_get(f"tok_{current_account_data['auth_token'][:20]}")

                    if fresh:
                        current_account_data = fresh
                        current_key = fresh['aes_ak']
                        current_iv = fresh['iv_i']
                        current_token = await build_tcp_startup_packet(
                            fresh['account_id'],
                            fresh['token'],
                            fresh['server_time'],
                            current_key,
                            current_iv,
                            region=fresh.get('region', account_region),
                            typ='OnLine'
                        )
                    else:
                        print_warning(f"[FUNCTIONAL] Cache miss for {uid_str} → re-login needed")
                        try:
                            if current_account_data.get('auth_uid'):
                                cache_invalidate(str(current_account_data['auth_uid']))
                            if current_account_data.get('auth_token'):
                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                        except Exception:
                            pass
                        raise ConnectionError("Cache expired, triggering fresh login")

                desired_mode()

                resolved_ip = await resolve_host_cloudflare(ip)
                reader, writer = await asyncio.open_connection(resolved_ip, int(port))

                raw_sock = writer.get_extra_info('socket')
                if raw_sock:
                    optimize_tcp_socket(raw_sock)

                writer.write(bytes.fromhex(current_token))
                await writer.drain()

                try:
                    init_ka = await send_keep_alive(account_region)
                    if init_ka and writer and not writer.is_closing():
                        writer.write(init_ka)
                        await asyncio.wait_for(writer.drain(), timeout=3)
                except Exception:
                    pass

                print_success(f"[FUNCTIONAL] TCP Gateway Connected for UID: {uid_str} (DNS: {resolved_ip})")
                reconnects = 0
                no_response_count = 0
                last_start_time = 0.0

                # Per-connection state. A connection only ever searches ONE mode; a mode
                # change always means: drop this connection, reconnect, search the new mode.
                conn = {"mode": None, "switch": False}
                _searching_mode[uid_str] = None

                async def live_stack() -> int:
                    """Ground-truth active UDP sessions for this account."""
                    play_matches[:] = [m for m in play_matches if not m.done()]
                    cnt = await _get_match_count(uid_str)
                    return max(int(cnt), len(play_matches))

                async def send_start_match():
                    nonlocal search_attempts, last_start_time
                    if _control_state() != "run":
                        return False
                    mode = desired_mode()
                    if conn["mode"] is not None and conn["mode"] != mode:
                        conn["switch"] = True
                        return False
                    profile = MODE_PROFILES[mode]
                    mode_tag = profile["tag"]
                    stack_cap = max_stack_for_mode(mode)
                    active = await live_stack()
                    if active >= stack_cap:
                        print_info(
                            f"[STACK] {mode_tag} at cap {active}/{stack_cap} "
                            f"— withholding StartMatch"
                        )
                        try:
                            publish_status(uid_str, active)
                        except Exception:
                            pass
                        return False
                    starter_func = start_game_lone_wolf if mode == "LW" else start_game_battle_royale
                    current_region = "BD"
                    search_attempts += 1

                    print_info(
                        f"[{mode_tag}] Sending StartMatch #{search_attempts} "
                        f"region: {current_region} (Lvl {current_level}) "
                        f"[stack {active}/{stack_cap}]"
                    )
                    try:
                        await asyncio.sleep(random.uniform(0.15, 0.4))
                        # Re-check after jitter: a match may have started meanwhile
                        active2 = await live_stack()
                        if active2 >= stack_cap or _control_state() != "run":
                            print_info(
                                f"[STACK] Cap hit during delay ({active2}/{stack_cap}) — abort StartMatch"
                            )
                            return False
                        # guard runs right before the bytes hit the socket, after every delay
                        sent = await starter_func(
                            current_region, client_version, writer, current_key, current_iv,
                            guard=lambda: (
                                _control_state() == "run"
                                and desired_mode() == mode
                            ),
                        )
                        if sent is False:
                            if desired_mode() != mode:
                                print_info(f"[MODE GUARD] {mode_tag} StartMatch withheld (mode changed)")
                                conn["switch"] = True
                            return False
                        conn["mode"] = mode
                        _searching_mode[uid_str] = mode
                        print_success(
                            f"[{mode_tag}] StartMatch packet sent "
                            f"(active {active2}/{stack_cap})"
                        )
                        publish_status(uid_str, active2)
                    except Exception as e:
                        print_error(f"start_game_{mode_tag.lower().replace(' ', '_')} error: {e}")
                        return False
                    last_start_time = asyncio.get_running_loop().time()
                    return True

                # Only open a search slot if under the mode stack cap
                await send_start_match()

                while True:
                    ctrl = _control_state()
                    if ctrl == "stop":
                        raise ConnectionError("Stop requested")
                    if ctrl == "pause":
                        try:
                            bot_state.update_status(uid_str, "PAUSED", await _get_match_count(uid_str))
                        except Exception:
                            pass
                        await asyncio.sleep(1.0)
                        continue

                    play_matches[:] = [m for m in play_matches if not m.done()]
                    for _t in [t for t in match_modes if t.done()]:
                        match_modes.pop(_t, None)

                    live_mode = desired_mode()
                    if conn["switch"] or (conn["mode"] is not None and conn["mode"] != live_mode):
                        print_info(
                            f"[MODE SWITCH] UID {uid_str}: {conn['mode']} -> {live_mode} "
                            f"(Lvl {current_level}) — dropping old search, reconnecting"
                        )
                        cancel_stale_sessions(live_mode)
                        try:
                            writer.close()
                            await writer.wait_closed()
                        except Exception:
                            pass
                        await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                        break

                    active_count = await live_stack()
                    try:
                        publish_status(uid_str, active_count)
                    except Exception:
                        pass

                    now = asyncio.get_running_loop().time()
                    random_interval = START_MATCH_INTERVAL + random.uniform(-0.5, 1.0)
                    stack_cap = max_stack_for_mode(live_mode)
                    # Cap reached: stay online, wait for a slot to free — never overshoot
                    if active_count >= stack_cap:
                        pass
                    elif now - last_start_time >= max(1.5, random_interval):
                        await send_start_match()

                    try:
                        data = await asyncio.wait_for(reader.read(8192), timeout=0.5)
                    except asyncio.TimeoutError:
                        no_response_count += 1
                        if no_response_count > 80:
                            print_warning(f"[FUNCTIONAL] Gateway silent ({uid_str}). Reconnecting...")
                            raise ConnectionError("Gateway idle timeout")
                        continue

                    if not data:
                        raise ConnectionError("Connection closed by server")

                    hex_data = data.hex()
                    packet_length = len(data)
                    no_response_count = 0

                    if hex_data.startswith("0300") and 10 < packet_length < 30:
                        print_info("Match starting, please wait...")
                        continue

                    if hex_data.startswith("0300") and packet_length >= 300:
                        print_colored("=" * 60, Colors.GREEN)
                        print_colored(f"MATCH FOUND! Loading...", Colors.GREEN)
                        print_colored("=" * 60, Colors.GREEN)

                        try:
                            res = json.loads(await decode_protobuf(hex_data[10:]))
                            token = None
                            udp_key = None
                            match_code = None
                            server_ip_port = None
                            match_account_id = None
                            block_val = None

                            if '42' in res and 'data' in res['42']:
                                match_code = res['42']['data']
                            if '5' in res and 'data' in res['5']:
                                res_field5 = res['5']['data']
                                server_ip_port = res_field5.get('2', {}).get('data')
                                udp_key = res_field5.get('3', {}).get('data')
                                token = res_field5.get('4', {}).get('data')
                                if '42' in res_field5:
                                    match_code = res_field5['42']['data']
                            if '1' in res and 'data' in res['1']:
                                match_account_id = res['1']['data']
                            if '5' in res and 'data' in res['5']:
                                block_val = res['5']['data'].get('1', {}).get('data')

                            effective_acc_id = match_account_id or account_id or "BD_BOT"

                            if token and udp_key and match_code and server_ip_port:
                                acc_tok = ""
                                if current_account_data:
                                    acc_tok = current_account_data.get('access_token', '') or ""
                                match_mode = conn["mode"] or desired_mode()
                                live_mode = desired_mode()
                                if match_mode != live_mode:
                                    print_warning(
                                        f"[MODE GUARD] Discarding stale {match_mode} match "
                                        f"(now Lvl {current_level} -> {live_mode})"
                                    )
                                    cancel_stale_sessions(live_mode)
                                    try:
                                        writer.close()
                                        await writer.wait_closed()
                                    except Exception:
                                        pass
                                    await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                                    break
                                match_profile = MODE_PROFILES[match_mode]
                                selected_mode_id = match_profile["mode_id"]
                                selected_map_id = match_profile["map_id"]
                                mode_tag = match_profile["tag"].replace(" ", "_")
                                print_info(
                                    f"[TARGET] Mode: {mode_tag} | mode_id={selected_mode_id} | "
                                    f"map_id={selected_map_id} | UID: {uid_str}"
                                )
                                thunder, sharma = await build_match_startup_packets(
                                    token, udp_key, match_code, effective_acc_id, block_val or 0,
                                    server_ip=server_ip_port,
                                    region=account_region,
                                    client_version=client_version,
                                    access_token=acc_tok,
                                    mode_id=selected_mode_id,
                                    map_id=selected_map_id
                                )

                                match_index = await _inc_match(uid_str)
                                total = await _get_total_match_count()
                                print_colored(
                                    f"🚀 [MATCH #{match_index}] UDP starting → {server_ip_port} (background)",
                                    Colors.CYAN
                                )
                                print_success(
                                    f"[FUNCTIONAL] UDP task started. "
                                    f"UID active: {match_index} | Total: {total}"
                                )

                                play_fn = play_game_lw if match_mode == "LW" else play_game
                                new_match = asyncio.create_task(
                                    play_fn(
                                        server_ip_port,
                                        thunder,
                                        sharma,
                                        udp_key,
                                        match_code,
                                        effective_acc_id,
                                        "BD",
                                        client_version,
                                        current_key,
                                        current_iv,
                                        match_index=match_index,
                                        on_match_complete=trigger_post_match_refresh
                                    )
                                )
                                play_matches.append(new_match)
                                match_modes[new_match] = match_mode
                                _searching_mode[uid_str] = None

                                consecutive_parse_failures = 0

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass

                                active_now = await live_stack()
                                cap_now = max_stack_for_mode(match_mode)
                                if active_now >= cap_now:
                                    print_info(
                                        f"[STACK] Cap reached {active_now}/{cap_now} "
                                        f"— offline then wait for free slot"
                                    )
                                else:
                                    print_info(
                                        f"[OFFLINE] {NEW_MATCH_DELAY}s offline → "
                                        f"reload token → new StartMatch "
                                        f"({active_now}/{cap_now})"
                                    )
                                await human_like_delay(NEW_MATCH_DELAY - 0.5)
                                reconnects = 0
                                break

                            else:
                                consecutive_parse_failures += 1
                                print_warning(
                                    f"[FUNCTIONAL] Non-match big packet "
                                    f"(#{consecutive_parse_failures}/{MAX_CONSECUTIVE_PARSE_FAILURES}) "
                                    f"→ reconnecting"
                                )

                                if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                    print_error(
                                        f"[FUNCTIONAL] {MAX_CONSECUTIVE_PARSE_FAILURES}x parse failures "
                                        f"→ invalidating cache for fresh login"
                                    )
                                    if current_account_data:
                                        try:
                                            if current_account_data.get('auth_uid'):
                                                cache_invalidate(str(current_account_data['auth_uid']))
                                            if current_account_data.get('auth_token'):
                                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                        except Exception:
                                            pass
                                    consecutive_parse_failures = 0

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass
                                await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                                break

                        except Exception as e:
                            print_error(f"[FUNCTIONAL] Match packet error: {e}")
                            consecutive_parse_failures += 1
                            if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                if current_account_data:
                                    try:
                                        if current_account_data.get('auth_uid'):
                                            cache_invalidate(str(current_account_data['auth_uid']))
                                        if current_account_data.get('auth_token'):
                                            cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                    except Exception:
                                        pass
                                consecutive_parse_failures = 0
                            try:
                                writer.close()
                                await writer.wait_closed()
                            except Exception:
                                pass
                            await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                            break

                    if 30 <= packet_length <= 40:
                        continue

            except asyncio.CancelledError:
                print_warning(f"[FUNCTIONAL] Cancelled — cancelling {len(play_matches)} UDP matches")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                raise
            except Exception as e:
                print_error(f"[FUNCTIONAL] TCP state ({uid_str}): {e}")

                play_matches[:] = [m for m in play_matches if not m.done()]

                if writer:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

                if "Cache expired" in str(e):
                    print_warning(f"[FUNCTIONAL] Triggering re-login for {uid_str}")
                    break

                reconnects += 1
                if reconnects > max_reconnects:
                    print_error("[FUNCTIONAL] Max reconnects reached, retrying...")
                    reconnects = 0
                    await asyncio.sleep(3)
                    continue

                await asyncio.sleep(min(reconnects, 2))

    except asyncio.CancelledError:
        print_warning(f"[FUNCTIONAL] Outer cancelled. {len(play_matches)} UDP matches still running.")
        for m in play_matches:
            if not m.done():
                m.cancel()
        if play_matches:
            await asyncio.gather(*play_matches, return_exceptions=True)
        play_matches.clear()
        raise


async def informational(addrs, starter_packet, key, iv, region="BD", max_reconnects=3):
    reconnects = 0
    ip, port = addrs.split(":")
    while True:
        writer = None
        ping_task = None
        try:
            resolved_ip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(resolved_ip, int(port))

            raw_sock = writer.get_extra_info('socket')
            if raw_sock:
                optimize_tcp_socket(raw_sock)

            writer.write(bytes.fromhex(starter_packet))
            await writer.drain()
            reconnects = 0

            try:
                init_ka = await send_keep_alive(region)
                if init_ka and writer and not writer.is_closing():
                    writer.write(init_ka)
                    await asyncio.wait_for(writer.drain(), timeout=3)
            except Exception:
                pass

            async def info_keepalive():
                ka_bytes = await send_keep_alive(region)
                while True:
                    interval = await get_randomized_interval(4.0, 6.5)
                    await asyncio.sleep(interval)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka_bytes)
                            await writer.drain()
                    except Exception:
                        break

            ping_task = asyncio.create_task(info_keepalive())

            while True:
                data = await reader.read(8192)
                if not data:
                    raise ConnectionError("Connection closed")
        except asyncio.CancelledError:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            raise
        except Exception:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            reconnects += 1
            if reconnects > max_reconnects:
                await asyncio.sleep(3)
                reconnects = 0
            else:
                await asyncio.sleep(random.uniform(0.8, 1.5))


def _register_credentials(account_data: Dict):
    try:
        acc_id = str(account_data['account_id'])
        bot_state.account_credentials[acc_id] = account_data
        if account_data.get('auth_uid'):
            bot_state.account_credentials[str(account_data['auth_uid'])] = account_data
        if account_data.get('auth_token'):
            bot_state.account_credentials[f"tok_{account_data['auth_token'][:20]}"] = account_data
        if acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["auth_type"] = account_data.get("auth_type", "guest")
            bot_state.accounts[acc_id]["auth_uid"] = account_data.get("auth_uid")
            bot_state.accounts[acc_id]["auth_token"] = account_data.get("auth_token")
            if account_data.get("auth_type") == "token" and account_data.get("auth_token"):
                bot_state.accounts[acc_id]["worker_key"] = account_data["auth_token"][:10]
            elif account_data.get("auth_uid"):
                bot_state.accounts[acc_id]["worker_key"] = str(account_data["auth_uid"])
    except Exception:
        pass


async def fetch_profile_card(account_id, region) -> Optional[str]:
    try:
        import base64
        acc_id = str(int(account_id))
        reg = (region or "BD").strip() or "BD"
        url = f"{PICO_INFO_API}?uid={acc_id}&region={reg}"
        print_info(f"[PROFILE] Fetching card for {acc_id} ({reg})…")
        try:
            resp = await client.get(url, timeout=12.0)
        except Exception:
            async with httpx.AsyncClient(timeout=12.0, verify=False) as http:
                resp = await http.get(url)
        if resp.status_code != 200:
            print_warning(f"[PROFILE] API HTTP {resp.status_code} for {acc_id}")
            return None
        data = resp.json()
        b64 = data.get("profile_card") or data.get("profileCard") or ""
        if not b64:
            print_warning(f"[PROFILE] No profile_card for {acc_id}")
            return None
        if "," in b64 and b64.strip().startswith("data:"):
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        try:
            bot_state.profile_images[acc_id] = raw
        except Exception:
            pass
        path = f"/api/account/image/{acc_id}"
        print_success(f"[PROFILE] Loaded into memory for {acc_id} ({len(raw)} bytes)")
        return path
    except Exception as e:
        print_error(f"[PROFILE] {e}")
        return None


def delete_account_image(account_id):
    try:
        bot_state.profile_images.pop(str(int(account_id)), None)
        bot_state.profile_images.pop(str(account_id), None)
    except Exception:
        pass


_completing_targets = set()


async def complete_target_level(acc_id: str, level: int):
    acc_id = str(acc_id)
    if acc_id in _completing_targets:
        return
    _completing_targets.add(acc_id)
    try:
        await _complete_target_level_impl(acc_id, level)
    finally:
        _completing_targets.discard(acc_id)


async def _complete_target_level_impl(acc_id: str, level: int):
    acc_id = str(acc_id)
    acc = bot_state.accounts.get(acc_id) or {}
    print_success(f"[TARGET] {acc.get('nickname', acc_id)} reached Lv{level} — archiving")
    # Halt matchmaking immediately
    try:
        if acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["control"] = "stop"
            bot_state.accounts[acc_id]["status"] = "STOPPED"
            bot_state.accounts[acc_id]["target_level"] = None
        bot_state.set_control(acc_id, "stop")
    except Exception:
        pass
    out_file = f"{int(level)}_level_accounts.json"
    entry = { }
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                rows = json.load(f)
            for row in rows:
                if acc.get("auth_uid") and str(row.get("uid")) == str(acc.get("auth_uid")):
                    entry["uid"] = row.get("uid")
                    entry["password"] = row.get("password")
                    break
                if acc.get("auth_token") and row.get("token") == acc.get("auth_token"):
                    entry["token"] = row.get("token")
                    break
    except Exception:
        pass
    if not entry.get("password") and acc.get("auth_uid"):
        # Prefer live credential password
        try:
            cred = bot_state.account_credentials.get(str(acc_id)) or {}
            if cred.get("auth_password"):
                entry["uid"] = entry.get("uid") or acc.get("auth_uid")
                entry["password"] = cred.get("auth_password")
        except Exception:
            pass
    if not entry and acc.get("auth_uid"):
        entry = {"uid": acc.get("auth_uid"), "password": ""}
        try:
            cred = bot_state.account_credentials.get(str(acc_id)) or {}
            if cred.get("auth_password"):
                entry["password"] = cred["auth_password"]
        except Exception:
            pass
    if not entry and acc.get("auth_token"):
        entry = {"token": acc.get("auth_token")}
    entry["account_id"] = acc_id
    entry["level"] = int(level)
    entry["nickname"] = acc.get("nickname") or ""
    entry["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    existing = []
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing = [e for e in existing if str(e.get("account_id")) != acc_id]
    existing.append(entry)
    try:
        tmp = out_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, out_file)
    except Exception as e:
        print_error(f"[TARGET] write {out_file}: {e}")
    try:
        cred_entry = {}
        if entry.get("uid") is not None:
            cred_entry["uid"] = entry.get("uid")
            cred_entry["password"] = entry.get("password", "")
        if entry.get("token"):
            cred_entry["token"] = entry.get("token")
        completed = []
        if os.path.exists(COMPLETED_ACCOUNTS_FILE):
            try:
                with open(COMPLETED_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    completed = json.load(f)
                if not isinstance(completed, list):
                    completed = []
            except Exception:
                completed = []
        def _same(a, b):
            if a.get("uid") and b.get("uid") and str(a["uid"]) == str(b["uid"]):
                return True
            if a.get("token") and b.get("token") and a["token"] == b["token"]:
                return True
            return False
        completed = [c for c in completed if not _same(c, cred_entry)]
        if cred_entry:
            completed.append(cred_entry)
        tmp = COMPLETED_ACCOUNTS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(completed, f, indent=2)
        os.replace(tmp, COMPLETED_ACCOUNTS_FILE)
    except Exception as e:
        print_error(f"[TARGET] completed_accounts.json: {e}")

    try:
        bot_state.set_control(acc_id, "stop")
    except Exception:
        pass
    auth_uid = acc.get("auth_uid")
    auth_token = acc.get("auth_token")
    worker_key = acc.get("worker_key")
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                rows = json.load(f)
            filtered = []
            for row in rows:
                if auth_uid and str(row.get("uid")) == str(auth_uid):
                    continue
                if auth_token and row.get("token") == auth_token:
                    continue
                if str(row.get("uid")) == acc_id:
                    continue
                filtered.append(row)
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2)
    except Exception as e:
        print_error(f"[TARGET] accounts.json: {e}")
    try:
        if auth_uid:
            cache_invalidate(str(auth_uid))
        if auth_token:
            cache_invalidate(f"tok_{auth_token[:20]}")
        cache_invalidate(acc_id)
    except Exception:
        pass
    delete_account_image(acc_id)
    for k in {acc_id, str(worker_key or ""), str(auth_uid or ""), str(auth_token or "")[:10]}:
        if not k:
            continue
        task = bot_state.account_workers.pop(k, None)
        if task and not task.done():
            task.cancel()
    bot_state.accounts.pop(acc_id, None)
    bot_state._exp_samples.pop(acc_id, None)
    bot_state.account_credentials.pop(acc_id, None)
    bot_state.recalc_totals()
    bot_state.log(f"Target Lv{level} reached — archived → {out_file}", "success", acc_id)


def _resolve_target_for_account(acc_id: str, acc=None):
    """Resolve target_level from memory, then account_status.json (all known keys)."""
    acc_id = str(acc_id)
    if acc is None:
        acc = bot_state.accounts.get(acc_id)
    if acc and acc.get("target_level") is not None and acc.get("target_level") != "":
        try:
            return int(acc["target_level"])
        except Exception:
            pass
    keys = [f"acc:{acc_id}"]
    if acc:
        if acc.get("auth_uid"):
            keys.append(f"guest:{acc['auth_uid']}")
        if acc.get("auth_token"):
            keys.append(f"token:{str(acc['auth_token'])[:10]}")
        if acc.get("worker_key"):
            wk = str(acc["worker_key"])
            keys.append(f"guest:{wk}")
            keys.append(f"token:{wk}")
    try:
        cred = bot_state.account_credentials.get(acc_id) or {}
        if cred.get("auth_uid"):
            keys.append(f"guest:{cred['auth_uid']}")
        if cred.get("auth_token"):
            keys.append(f"token:{str(cred['auth_token'])[:10]}")
    except Exception:
        pass
    seen = set()
    ordered = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
    try:
        data = load_account_status_raw()
        for k in ordered:
            v = data.get(k)
            if isinstance(v, dict) and v.get("target_level") is not None and v.get("target_level") != "":
                try:
                    tl = int(v["target_level"])
                    if acc is not None:
                        acc["target_level"] = tl
                    return tl
                except Exception:
                    continue
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            if str(v.get("account_id") or "") != acc_id:
                continue
            if v.get("target_level") is not None and v.get("target_level") != "":
                try:
                    tl = int(v["target_level"])
                    if acc is not None:
                        acc["target_level"] = tl
                    return tl
                except Exception:
                    continue
    except Exception:
        pass
    return None


async def maybe_check_target_level(acc_id: str, level: int):
    acc_id = str(acc_id)
    acc = bot_state.accounts.get(acc_id)
    target = _resolve_target_for_account(acc_id, acc)
    if target is None:
        return
    try:
        target = int(target)
        level = int(level)
    except Exception:
        return
    if target > 0 and level >= target:
        print_success(
            f"[TARGET] UID {acc_id} level {level} >= target {target} — stopping & archiving"
        )
        await complete_target_level(acc_id, level)


def _update_cache_profile(account_data: Dict, level: int, exp: int):
    try:
        auth_uid = account_data.get('auth_uid')
        auth_token = account_data.get('auth_token')
        keys = []
        if auth_uid:
            keys.append(str(auth_uid))
        if auth_token:
            keys.append(f"tok_{auth_token[:20]}")
        if not keys:
            return
        cache = _load_token_cache()
        changed = False
        for k in keys:
            if k in cache and isinstance(cache[k], dict):
                cache[k]['level'] = level
                cache[k]['exp'] = exp
                changed = True
        if changed:
            _save_token_cache(cache)
    except Exception as e:
        print_warning(f"[EXP-REFRESH] cache update failed: {e}")


async def refresh_account_profile(account_data_or_uid: Any):
    try:
        if isinstance(account_data_or_uid, str):
            uid = str(account_data_or_uid)
            account_data = bot_state.account_credentials.get(uid)
        else:
            account_data = account_data_or_uid
            uid = str(account_data.get('account_id')) if account_data else "?"
        if not account_data:
            print_warning(f"[EXP-REFRESH] No credentials for UID {uid}")
            return
        url = account_data.get('server_url')
        token = account_data.get('token')
        release_version = account_data.get('release_version')
        payload = account_data.get('login_payload_data')
        if not (url and token and release_version and payload):
            print_warning(f"[EXP-REFRESH] Missing fields for {uid}")
            return
        res = None
        try:
            res = await send_getlogin(payload, url, token, release_version)
        except Exception as e:
            print_error(f"[EXP-REFRESH] send_getlogin exception for {uid}: {e}")
            return
        if not res:
            print_warning(f"[EXP-REFRESH] GetLoginData returned None for {uid}")
            return
        res_proto, dict_res = res

        def _safe_int(v, default):
            try:
                if v is None or v == "":
                    return default
                return int(v)
            except Exception:
                return default

        level = _safe_int(get_proto_field(dict_res, 6, None), None)
        exp = _safe_int(get_proto_field(dict_res, 7, None), None)
        likes = _safe_int(get_proto_field(dict_res, 8, None), None)
        nickname = ""
        try:
            nickname = res_proto.nickname or get_proto_field(dict_res, 4, "") or ""
        except Exception:
            nickname = ""
        if level is None and exp is None:
            print_warning(f"[EXP-REFRESH] No level/exp field parsed for {uid}")
            return
        level = level if level is not None else 1
        exp = exp if exp is not None else 0
        likes = likes if likes is not None else 0
        acc_id = str(account_data['account_id'])
        old_level = 0
        old_exp = 0
        try:
            if acc_id in bot_state.accounts:
                old_level = int(bot_state.accounts[acc_id].get('level', 0) or 0)
                old_exp = int(bot_state.accounts[acc_id].get('exp', 0) or 0)
        except Exception:
            pass
        try:
            bot_state.update_exp(acc_id, exp, level)
        except Exception as e:
            print_error(f"[EXP-REFRESH] update_exp failed for {acc_id}: {e}")
        if likes > 0 and acc_id in bot_state.accounts:
            try:
                bot_state.accounts[acc_id]["likes"] = likes
            except Exception:
                pass
        if nickname and acc_id in bot_state.accounts:
            try:
                bot_state.accounts[acc_id]["nickname"] = nickname
            except Exception:
                pass
        _update_cache_profile(account_data, level, exp)
        account_data['level'] = level
        account_data['exp'] = exp
        if likes > 0:
            account_data['likes'] = likes
        if nickname:
            account_data['nickname'] = nickname
        if old_level > 0 and level > old_level:
            print_success(f"[LEVEL UP] UID {acc_id} : Lvl {old_level} -> {level} (EXP {old_exp} -> {exp})")
            if level >= LONE_WOLF_UNLOCK_LEVEL and old_level < LONE_WOLF_UNLOCK_LEVEL:
                print_success(f"[MODE LOCK] UID {acc_id} reached Lvl {level} -> next search will be LONE WOLF")
        elif old_exp != exp:
            print_success(f"[EXP] UID {acc_id} Lvl {level} | EXP {old_exp} -> {exp} (+{exp - old_exp})")
        else:
            print_info(f"[EXP-REFRESH] UID {acc_id} -> Level: {level}, EXP: {exp}")
        await maybe_check_target_level(acc_id, level)
    except Exception as e:
        print_error(f"refresh_account_profile error: {e}")
        traceback.print_exc()


async def process_account_uid_pass(uid: str, password: str) -> Optional[Dict]:
    cached = cache_get(uid)
    if cached:
        print_success(f"[CACHE HIT] UID {uid} loaded from token_cache.json (no login)")
        acc_id = str(cached['account_id'])
        img = await fetch_profile_card(
            cached.get('account_id'),
            cached.get('lock_region') or cached.get('region') or 'BD',
        )
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'BD'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        if img and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]['profile_image'] = img
        _register_credentials(cached)
        return cached

    print_info(f"[LOGIN] Full login for UID {uid}...")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            print("Version Config Failed")
            return None
        release_version, client_version, server_url = verconfig_res

        tokengrant_response = await get_access_token(uid, password)
        if tokengrant_response is None:
            print("Token Grant Attempt Failed")
            need_rotate = await anti_ban_state.record_login_failure(str(uid))
            if need_rotate:
                print_warning(f"[ANTIBAN] Rotating device for {uid} due to repeated login failures")
                try:
                    if os.path.exists(DEVICES_FILE):
                        with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                            devices = json.load(f)
                        if str(uid) in devices:
                            del devices[str(uid)]
                            with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                                json.dump(devices, f, indent=4)
                except Exception:
                    pass
            return None
        open_id, access_token, platform = tokengrant_response

        await anti_ban_state.reset_login_failures(str(uid))

        device_info = get_device_for_account(uid)

        login_payload_data = await build_majorlogin_payload(open_id, access_token, platform, client_version, device_info)

        print(login_payload_data.hex())

        print("Access:", access_token)
        print("Release:", release_version)
        print("Server:", server_url)
        print("Client:", client_version)

        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url)
        if majorlogin_response is None:
            print("MajorLogin Response is empty")
            return None
        getlogin_result = await send_getlogin(login_payload_data, majorlogin_response.url, majorlogin_response.token, release_version)
        if getlogin_result is None:
            print("GetLoginData Response is empty")
            return None
        res_proto, dict_res = getlogin_result

        game_account_id = int(getattr(majorlogin_response, "account_id", 0) or 0)
        lock_region = (
            getattr(majorlogin_response, "lockRegion", None)
            or getattr(majorlogin_response, "region", None)
            or "BD"
        )
        profile_image = await fetch_profile_card(game_account_id, lock_region)

        acc_id = str(game_account_id or majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "BD")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)
        if profile_image and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["profile_image"] = profile_image

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'lock_region': lock_region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'guest',
            'auth_uid': uid,
            'auth_password': password,
            'profile_image': profile_image,
        }
        _register_credentials(account_data)
        cache_set(uid, account_data)
        try:
            aid = str(account_data['account_id'])
            tl = _resolve_target_for_account(aid, bot_state.accounts.get(aid))
            if tl is not None and aid in bot_state.accounts:
                bot_state.accounts[aid]["target_level"] = tl
            await maybe_check_target_level(aid, int(level))
        except Exception as e:
            print_warning(f"[TARGET] post-login check: {e}")
        return account_data
    except Exception as e:
        print_error(f"process_account_uid_pass error: {e}")
        return None


async def process_account_token(access_token: str) -> Optional[Dict]:
    cache_key = f"tok_{access_token[:20]}"
    cached = cache_get(cache_key)
    if cached:
        print_success(f"[CACHE HIT] Token {access_token[:10]}... loaded from cache")
        acc_id = str(cached['account_id'])
        img = await fetch_profile_card(
            cached.get('account_id'),
            cached.get('lock_region') or cached.get('region') or 'BD',
        )
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'BD'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        if img and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]['profile_image'] = img
        _register_credentials(cached)
        return cached

    print_info("[LOGIN] Full login with Access Token...")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            return None
        release_version, client_version, server_url = verconfig_res

        import requests
        url = f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}"
        hdrs = {
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "close",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "100067.connect.garena.com",
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)"
        }
        await human_like_delay(0.2)
        resp = await asyncio.to_thread(requests.get, url, headers=hdrs, timeout=10)
        data = resp.json()

        if 'error' in data:
            return None

        open_id = data.get('open_id')
        platform = data.get('platform', 4)

        if not open_id:
            return None

        device_info = get_device_for_account(open_id)

        login_payload_data = await build_majorlogin_payload(open_id, access_token, str(platform), client_version, device_info)
        if not login_payload_data:
            return None

        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url)
        if majorlogin_response is None:
            return None

        getlogin_result = await send_getlogin(
            login_payload_data,
            majorlogin_response.url,
            majorlogin_response.token,
            release_version
        )
        if getlogin_result is None:
            return None

        res_proto, dict_res = getlogin_result
        game_account_id = int(getattr(majorlogin_response, "account_id", 0) or 0)
        lock_region = (
            getattr(majorlogin_response, "lockRegion", None)
            or getattr(majorlogin_response, "region", None)
            or "BD"
        )
        profile_image = await fetch_profile_card(game_account_id, lock_region)

        acc_id = str(game_account_id or majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "BD")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)
        if profile_image and acc_id in bot_state.accounts:
            bot_state.accounts[acc_id]["profile_image"] = profile_image

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'lock_region': lock_region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'token',
            'auth_token': access_token,
            'profile_image': profile_image,
        }
        _register_credentials(account_data)
        cache_set(cache_key, account_data)
        try:
            aid = str(account_data['account_id'])
            tl = _resolve_target_for_account(aid, bot_state.accounts.get(aid))
            if tl is not None and aid in bot_state.accounts:
                bot_state.accounts[aid]["target_level"] = tl
            await maybe_check_target_level(aid, int(level))
        except Exception as e:
            print_warning(f"[TARGET] post-login check: {e}")
        return account_data
    except Exception as e:
        print_error(f"process_account_token error: {e}")
        return None


async def run_account_worker(account_data: Dict, label: str):
    acc_id = str(account_data['account_id'])
    informational_task = None
    exp_task = None
    try:
        reg = account_data.get('region', 'BD')
        tcp_packet_online = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='OnLine'
        )

        tcp_packet_chat = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='ChaT'
        )

        informational_task = asyncio.create_task(
            informational(
                account_data['informational_addrs'],
                tcp_packet_chat,
                account_data['aes_ak'],
                account_data['iv_i'],
                region=reg
            )
        )

        async def exp_refresher():
            try:
                fresh = bot_state.account_credentials.get(acc_id)
                if fresh:
                    await refresh_account_profile(fresh)
            except Exception as e:
                print_warning(f"[EXP-REFRESH] initial refresh error ({acc_id}): {e}")
            while True:
                _interval = EXP_REFRESH_INTERVAL
                try:
                    _lvl = bot_state.accounts.get(acc_id, {}).get("level")
                    if _lvl is not None and int(_lvl) == LONE_WOLF_UNLOCK_LEVEL - 1:
                        _interval = LW_UNLOCK_WATCH_REFRESH_INTERVAL
                except Exception:
                    pass
                _spread = 3.0 if _interval == EXP_REFRESH_INTERVAL else 1.0
                await asyncio.sleep(_interval + random.uniform(-_spread, _spread))
                try:
                    fresh = bot_state.account_credentials.get(acc_id)
                    if fresh:
                        await refresh_account_profile(fresh)
                except Exception as e:
                    print_warning(f"[EXP-REFRESH] periodic refresh error ({acc_id}): {e}")

        exp_task = asyncio.create_task(exp_refresher())

        functional_task = asyncio.create_task(
            functional_lone_wolf(
                account_data['functional_addrs'],
                tcp_packet_online,
                account_data['region'],
                account_data['client_version'],
                account_data['aes_ak'],
                account_data['iv_i'],
                account_id=acc_id,
                account_data=account_data,
                account_level=int(account_data.get('level', 2) or 2)
            )
        )

        await functional_task

    except asyncio.CancelledError:
        raise
    except Exception as e:
        print_error(f"run_account_worker error for {label}: {e}")
    finally:
        for t in (informational_task, exp_task):
            if t and not t.done():
                t.cancel()
        for t in (informational_task, exp_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


def _ensure_dashboard_placeholder(
    display_uid: str,
    *,
    auth_type: str,
    auth_uid: Optional[str] = None,
    auth_token: Optional[str] = None,
    worker_key: Optional[str] = None,
    control: str = "stop",
):
    display_uid = str(display_uid)
    nick = f"Player_{display_uid[:6]}"
    region = "BD"
    level, exp = 1, 0
    try:
        meta_keys = []
        if auth_type == "guest" and auth_uid:
            meta_keys.append(f"guest:{auth_uid}")
        if auth_type == "token" and auth_token:
            meta_keys.append(f"token:{str(auth_token)[:10]}")
        meta_keys.append(f"acc:{display_uid}")
        meta = get_saved_status_meta(*meta_keys)
        if meta.get("nickname"):
            nick = str(meta["nickname"])
        if meta.get("account_id") and str(meta["account_id"]) != display_uid:
            pass
    except Exception:
        pass
    try:
        cache_key = display_uid if auth_type == "guest" else f"tok_{(auth_token or '')[:20]}"
        cached = cache_get(cache_key) if cache_key else None
        if cached:
            nick = cached.get("nickname") or nick
            region = cached.get("region") or region
            level = int(cached.get("level") or level)
            exp = int(cached.get("exp") or exp)
    except Exception:
        pass

    bot_state.register_account(
        uid=display_uid, nickname=nick, region=region, level=level, exp=exp, likes=0
    )
    acc = bot_state.accounts.get(display_uid)
    if not acc:
        return
    acc["auth_type"] = auth_type
    if auth_uid:
        acc["auth_uid"] = str(auth_uid)
    if auth_token:
        acc["auth_token"] = auth_token
    if worker_key:
        acc["worker_key"] = worker_key
    if control in ("run", "pause", "stop"):
        acc["control"] = control
        acc["status"] = {"run": "ONLINE", "pause": "PAUSED", "stop": "STOPPED"}[control]
    try:
        meta_keys = []
        if auth_type == "guest" and auth_uid:
            meta_keys.append(f"guest:{auth_uid}")
        if auth_type == "token" and auth_token:
            meta_keys.append(f"token:{str(auth_token)[:10]}")
        meta_keys.append(f"acc:{display_uid}")
        meta = get_saved_status_meta(*meta_keys)
        if meta.get("target_level") is not None:
            try:
                acc["target_level"] = int(meta["target_level"])
            except Exception:
                pass
    except Exception:
        pass
    acc["last_updated"] = time.strftime("%H:%M:%S")
    try:
        keys = [f"acc:{display_uid}"]
        if auth_uid:
            keys.append(f"guest:{auth_uid}")
        if auth_token:
            keys.append(f"token:{str(auth_token)[:10]}")
        set_saved_control(control, *keys, nickname=nick)
    except Exception:
        pass


def _dashboard_control(uid: str) -> Optional[str]:
    acc = bot_state.accounts.get(str(uid))
    if acc:
        return acc.get("control")
    return None


def _remove_placeholder_if_different(placeholder_uid: str, real_acc_id: str):
    p, r = str(placeholder_uid), str(real_acc_id)
    if p != r and p in bot_state.accounts and r in bot_state.accounts:
        try:
            del bot_state.accounts[p]
        except Exception:
            pass
        try:
            if p in bot_state._exp_samples:
                del bot_state._exp_samples[p]
        except Exception:
            pass
        bot_state.recalc_totals()


async def account_loop_guest(uid: str, password: str):
    auth_key = _status_auth_key("guest", uid)
    while True:
        try:
            while True:
                saved = get_saved_control(auth_key)
                live = _dashboard_control(uid)
                if saved != "stop" and live != "stop":
                    break
                if live == "run" or saved == "run":
                    set_saved_control("run", auth_key)
                    if uid in bot_state.accounts:
                        bot_state.accounts[uid]["control"] = "run"
                        bot_state.accounts[uid]["status"] = "CONNECTING"
                    break
                _ensure_dashboard_placeholder(
                    uid, auth_type="guest", auth_uid=uid, worker_key=uid, control="stop"
                )
                print_info(f"[CONTROL] Guest {uid} is STOPPED — waiting for Start")
                await asyncio.sleep(1.5)

            print_info(f"[LOGIN] Starting login for Guest UID: {uid}...")
            try:
                if uid in bot_state.accounts:
                    bot_state.accounts[uid]["status"] = "CONNECTING"
                    bot_state.accounts[uid]["control"] = "run"
                else:
                    bot_state.update_status(str(uid), "CONNECTING")
            except Exception:
                pass
            account_data = await process_account_uid_pass(uid, password)
            if not account_data:
                print_error(f"Login failed for UID: {uid}. Retrying in 15 seconds...")
                try:
                    bot_state.update_status(str(uid), "ERROR")
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(12.0, 18.0))
                continue

            acc_id = str(account_data['account_id'])
            acc_key = f"acc:{acc_id}"
            task = asyncio.current_task()
            if task is not None:
                bot_state.account_workers[uid] = task
                bot_state.account_workers[acc_id] = task

            saved = get_saved_control(auth_key, acc_key)
            if acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["worker_key"] = uid
                bot_state.accounts[acc_id]["auth_uid"] = uid
                bot_state.accounts[acc_id]["auth_type"] = "guest"
                bot_state.accounts[acc_id]["control"] = saved if saved in ("run", "pause", "stop") else "run"
                if saved == "pause":
                    bot_state.accounts[acc_id]["status"] = "PAUSED"
                elif saved == "stop":
                    bot_state.accounts[acc_id]["status"] = "STOPPED"
                else:
                    bot_state.accounts[acc_id]["status"] = "ONLINE"
                try:
                    meta = get_saved_status_meta(auth_key, acc_key)
                    if meta.get("target_level") is not None:
                        bot_state.accounts[acc_id]["target_level"] = int(meta["target_level"])
                    tl = _resolve_target_for_account(acc_id, bot_state.accounts.get(acc_id))
                    if tl is not None:
                        bot_state.accounts[acc_id]["target_level"] = tl
                except Exception:
                    pass
            _remove_placeholder_if_different(uid, acc_id)
            _nick = bot_state.accounts.get(acc_id, {}).get("nickname") or account_data.get("nickname")
            set_saved_control(
                bot_state.accounts.get(acc_id, {}).get("control", "run"),
                auth_key, acc_key,
                nickname=_nick,
                account_id=acc_id,
            )

            await run_account_worker(account_data, uid)

            if bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                print_warning(f"Account {acc_id} stopped — waiting for Start")
                set_saved_control(
                    "stop", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                try:
                    bot_state.update_status(acc_id, "STOPPED", 0)
                except Exception:
                    pass
                while bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                    await asyncio.sleep(1.5)
                cache_invalidate(str(uid))
                set_saved_control(
                    "run", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                continue

            print_warning(f"Session finished for {uid}. Reconnecting in 3s...")
            await asyncio.sleep(random.uniform(2.5, 4.5))
        except asyncio.CancelledError:
            print_warning(f"Worker for {uid} stopped.")
            try:
                bot_state.update_status(str(uid), "OFFLINE")
            except Exception:
                pass
            break
        except Exception as e:
            print_error(f"Error for UID {uid}: {e}. Retrying in 10s...")
            await asyncio.sleep(random.uniform(8.0, 12.0))


async def account_loop_token(token: str):
    token_label = token[:10]
    auth_key = _status_auth_key("token", token)
    while True:
        try:
            while True:
                saved = get_saved_control(auth_key)
                live = _dashboard_control(token_label)
                if saved != "stop" and live != "stop":
                    break
                if live == "run" or saved == "run":
                    set_saved_control("run", auth_key)
                    if token_label in bot_state.accounts:
                        bot_state.accounts[token_label]["control"] = "run"
                        bot_state.accounts[token_label]["status"] = "CONNECTING"
                    break
                _ensure_dashboard_placeholder(
                    token_label,
                    auth_type="token",
                    auth_token=token,
                    worker_key=token_label,
                    control="stop",
                )
                print_info(f"[CONTROL] Token {token_label} is STOPPED — waiting for Start")
                await asyncio.sleep(1.5)

            print_info("[LOGIN] Starting login with Access Token...")
            account_data = await process_account_token(token)
            if not account_data:
                print_error("Login failed for Token. Retrying in 15 seconds...")
                await asyncio.sleep(random.uniform(12.0, 18.0))
                continue

            acc_id = str(account_data['account_id'])
            acc_key = f"acc:{acc_id}"
            task = asyncio.current_task()
            if task is not None:
                bot_state.account_workers[token_label] = task
                bot_state.account_workers[acc_id] = task

            saved = get_saved_control(auth_key, acc_key)
            if acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["worker_key"] = token_label
                bot_state.accounts[acc_id]["auth_token"] = token
                bot_state.accounts[acc_id]["auth_type"] = "token"
                bot_state.accounts[acc_id]["control"] = saved if saved in ("run", "pause", "stop") else "run"
                if saved == "pause":
                    bot_state.accounts[acc_id]["status"] = "PAUSED"
                elif saved == "stop":
                    bot_state.accounts[acc_id]["status"] = "STOPPED"
                else:
                    bot_state.accounts[acc_id]["status"] = "ONLINE"
                try:
                    meta = get_saved_status_meta(auth_key, acc_key)
                    if meta.get("target_level") is not None:
                        bot_state.accounts[acc_id]["target_level"] = int(meta["target_level"])
                    tl = _resolve_target_for_account(acc_id, bot_state.accounts.get(acc_id))
                    if tl is not None:
                        bot_state.accounts[acc_id]["target_level"] = tl
                except Exception:
                    pass
            _remove_placeholder_if_different(token_label, acc_id)
            _nick = bot_state.accounts.get(acc_id, {}).get("nickname") or account_data.get("nickname")
            set_saved_control(
                bot_state.accounts.get(acc_id, {}).get("control", "run"),
                auth_key, acc_key,
                nickname=_nick,
                account_id=acc_id,
            )

            await run_account_worker(account_data, acc_id)

            if bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                print_warning(f"Account {acc_id} stopped — waiting for Start")
                set_saved_control(
                    "stop", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                try:
                    bot_state.update_status(acc_id, "STOPPED", 0)
                except Exception:
                    pass
                while bot_state.accounts.get(acc_id, {}).get("control") == "stop":
                    await asyncio.sleep(1.5)
                cache_invalidate(f"tok_{token[:20]}")
                set_saved_control(
                    "run", auth_key, acc_key,
                    nickname=bot_state.accounts.get(acc_id, {}).get("nickname"),
                    account_id=acc_id,
                )
                continue

            print_warning("Token session finished. Reconnecting in 3s...")
            await asyncio.sleep(random.uniform(2.5, 4.5))
        except asyncio.CancelledError:
            print_warning(f"Worker for token {token_label} stopped.")
            break
        except Exception as e:
            print_error(f"Token error: {e}. Retrying in 10s...")
            await asyncio.sleep(random.uniform(8.0, 12.0))


def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    accounts = data
        except Exception as e:
            print_error(f"Could not load {ACCOUNTS_FILE}: {e}")

    if not accounts and FALLBACK_UID and FALLBACK_PASSWORD:
        accounts.append({"uid": FALLBACK_UID, "password": FALLBACK_PASSWORD})

    return accounts


async def main():
    print_colored("=" * 60, Colors.CYAN)
    print_colored("    TEAM 84FF - FreeFire Level Up Bot (Web Dashboard Mode)", Colors.GREEN)
    print_colored("   Persistent Device ID + TRUE Parallel + Smart DNS + Anti-Ban", Colors.WHITE)
    print_colored("=" * 60, Colors.CYAN)
    print_info(f"Start Match Interval: {START_MATCH_INTERVAL}s (jittered)")
    print_info(f"Offline Wait: {NEW_MATCH_DELAY}s (after match found)")
    print_info(f"Non-match Reconnect: {NON_MATCH_RECONNECT_DELAY}s")
    print_info(f"Cache Invalidation Threshold: {MAX_CONSECUTIVE_PARSE_FAILURES}x")
    apply_bot_settings()
    print_info(f"Parallel Matches: LW max {MAX_STACK_LW} | BR max {MAX_STACK_BR}")
    print_info(f"Cache TTL: {TOKEN_CACHE_TTL}s ({TOKEN_CACHE_TTL//60} min)")
    print_info(f"Priority Regions: {PRIORITY_REGIONS}")
    print_info("Device System: 1 ID = 1 Persistent Device ID (devices.json)")
    print_info(f"Control status file: {ACCOUNT_STATUS_FILE} (pause/run/stop survives restart)")
    print_info("Dashboard controls: Pause / Resume / Stop / Start")
    print_colored("=" * 60, Colors.GREEN)
    print_colored("🛡️ ANTI-BAN ACTIVE:", Colors.GREEN)
    print_colored(f"   • Human-like movement: {HUMAN_LIKE_MOVEMENT}", Colors.GREEN)
    print_colored(f"   • Behavior jitter: {BEHAVIOR_JITTER_MIN}s - {BEHAVIOR_JITTER_MAX}s", Colors.GREEN)
    print_colored(f"   • Device rotation: every {IDENTITY_ROTATE_EVERY_MATCHES} matches / {IDENTITY_ROTATE_EVERY_SECONDS}s", Colors.GREEN)
    print_colored(f"   • Login failure rotation: after {MAX_LOGIN_FAILURES_BEFORE_ROTATE} fails", Colors.GREEN)
    print_colored(f"   • Movement interval: {MOVEMENT_SEND_INTERVAL[0]}s - {MOVEMENT_SEND_INTERVAL[1]}s", Colors.GREEN)
    print_colored("=" * 60, Colors.CYAN)

    try:
        await start_web_dashboard(host=WEB_HOST, port=WEB_PORT)
        print_success(f"Web Dashboard live at http://localhost:{WEB_PORT}")
    except Exception as e:
        print_error(f"Could not start web dashboard: {e}")

    async def on_account_added_handler(data):
        if "token" in data and data["token"]:
            t = str(data["token"]).strip()
            task = asyncio.create_task(account_loop_token(t))
            bot_state.account_workers[t[:10]] = task
        elif "uid" in data and "password" in data:
            u = str(data["uid"]).strip()
            p = str(data["password"]).strip()
            task = asyncio.create_task(account_loop_guest(u, p))
            bot_state.account_workers[u] = task

    async def on_refresh_account_handler(uid):
        await refresh_account_profile(uid)

    bot_state.refresh_callbacks["on_account_added"] = on_account_added_handler
    bot_state.refresh_callbacks["on_refresh_account"] = on_refresh_account_handler

    accounts = load_accounts()

    if not accounts:
        print_warning(f"No accounts found in {ACCOUNTS_FILE}! Add accounts from Web Dashboard.")
        print_warning(f"Open: http://localhost:{WEB_PORT}")

    for acc in accounts:
        if "token" in acc and acc["token"]:
            t = asyncio.create_task(account_loop_token(acc["token"]))
            bot_state.account_workers[acc["token"][:10]] = t
        elif "uid" in acc and "password" in acc and acc["uid"]:
            u = str(acc["uid"])
            t = asyncio.create_task(account_loop_guest(u, acc["password"]))
            bot_state.account_workers[u] = t

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print_warning("\n[STOP] Shutting down all accounts...")
        for t in list(bot_state.account_workers.values()):
            t.cancel()
        await asyncio.gather(*bot_state.account_workers.values(), return_exceptions=True)
        print_success("All sessions cleanly closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\nProgram stopped by user.")
