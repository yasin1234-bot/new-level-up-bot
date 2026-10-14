# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import re
import os
import time
from collections import deque
from typing import Dict, List, Any, Optional
from aiohttp import web

LEVEL_EXP_MAP = {
    1: (0, 47), 2: (48, 201), 3: (202, 543), 4: (544, 1011), 5: (1012, 1843),
    6: (1844, 2791), 7: (2792, 3799), 8: (3800, 4869), 9: (4870, 6003), 10: (6004, 7191),
    11: (7192, 8447), 12: (8448, 9759), 13: (9760, 11139), 14: (11140, 12565), 15: (12566, 14059),
    16: (14060, 15609), 17: (15610, 17223), 18: (17224, 18901), 19: (18902, 20631), 20: (20632, 22423),
    21: (22424, 24277), 22: (24278, 26191), 23: (26192, 28165), 24: (28166, 30199), 25: (30200, 32293),
    26: (32294, 34447), 27: (34448, 37803), 28: (37804, 41273), 29: (41274, 44869), 30: (44870, 48581),
    31: (48582, 53393), 32: (53394, 58565), 33: (58566, 64095), 34: (64096, 69993), 35: (69994, 76259),
    36: (76260, 83505), 37: (83506, 91127), 38: (91128, 99321), 39: (99322, 108091), 40: (108092, 120143),
    41: (120144, 133265), 42: (133266, 147471), 43: (147472, 162759), 44: (162760, 179125), 45: (179126, 196571),
    46: (196572, 215367), 47: (215368, 235315), 48: (235316, 257009), 49: (257010, 279859), 50: (279860, 304055),
    51: (304056, 348317), 52: (348318, 394981), 53: (394982, 444043), 54: (444044, 495507), 55: (495508, 549363),
    56: (549364, 633755), 57: (633756, 721743), 58: (721744, 813335), 59: (813336, 908521), 60: (908522, 1041437),
    61: (1041438, 1180351), 62: (1180352, 1325265), 63: (1325266, 1476183), 64: (1476184, 1634299), 65: (1634300, 1840945),
    66: (1840946, 2056593), 67: (2056594, 2281241), 68: (2281242, 2514879), 69: (2514880, 2757529), 70: (2757530, 3059505),
    71: (3059506, 3372283), 72: (3372284, 3699455), 73: (3699456, 4041029), 74: (4041030, 4397001), 75: (4397002, 4829103),
    76: (4829104, 5282203), 77: (5282204, 5756303), 78: (5756304, 6251403), 79: (6251404, 6767501), 80: (6767502, 7381323),
    81: (7381324, 8043153), 82: (8043154, 8752981), 83: (8752982, 9510807), 84: (9510808, 10316637), 85: (10316638, 11277189),
    86: (11277190, 12291747), 87: (12291748, 13360303), 88: (13360304, 14482857), 89: (14482858, 15659417), 90: (15659418, 17026707),
    91: (17026708, 18453989), 92: (18453990, 19941279), 93: (19941280, 21488569), 94: (21488570, 23095857), 95: (23095858, 24763137),
    96: (24763138, 26490427), 97: (26490428, 28277707), 98: (28277708, 30124995), 99: (30124996, 32032283),
    100: (32032284, float("inf")),
}
MAX_LEVEL = max(LEVEL_EXP_MAP)

BOT_SETTINGS_FILE = "bot_settings.json"
COMPLETED_ACCOUNTS_FILE = "completed_accounts.json"

DEFAULT_BOT_SETTINGS = {
    "max_stack_lw": 10,
    "max_stack_br": 1,
    "start_match_interval": 3.0,
    "new_match_delay": 3.0,
    "match_idle_timeout": 15.0,
    "lw_match_idle_timeout": 8.0,
    "exp_refresh_interval": 25.0,
    "token_cache_ttl": 1200,
    "identity_rotate_every_matches": 5,
    "identity_rotate_every_seconds": 900,
    "cancel_br_on_lw_unlock": False,
    "safe_play_mode": True,
    "human_like_movement": True,
}

def load_bot_settings() -> dict:
    out = dict(DEFAULT_BOT_SETTINGS)
    if os.path.exists(BOT_SETTINGS_FILE):
        try:
            with open(BOT_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out.update(data)
        except Exception:
            pass
    return out

def save_bot_settings(settings: dict):
    merged = dict(DEFAULT_BOT_SETTINGS)
    merged.update(settings or {})
    tmp = BOT_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    os.replace(tmp, BOT_SETTINGS_FILE)
    return merged

def load_completed_accounts() -> list:
    if not os.path.exists(COMPLETED_ACCOUNTS_FILE):
        return []
    try:
        with open(COMPLETED_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def save_completed_accounts(rows: list):
    tmp = COMPLETED_ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    os.replace(tmp, COMPLETED_ACCOUNTS_FILE)

# Rolling window used to measure the current EXP speed
SPEED_WINDOW_SEC = 15 * 60
# Minimum span between first and last sample before a speed is trusted
SPEED_MIN_SPAN_SEC = 20


def level_from_exp(exp: int) -> int:
    """Level that a given total EXP belongs to."""
    for lvl, (lo, hi) in LEVEL_EXP_MAP.items():
        if lo <= exp <= hi:
            return lvl
    return MAX_LEVEL if exp > 0 else 1


def level_progress(level: int, exp: int) -> Dict[str, Any]:
    """Position of `exp` inside `level`, using LEVEL_EXP_MAP.

    If the reported level doesn't contain the EXP (stale level), the level is
    re-derived from the EXP so the bar never lies.
    """
    exp = max(0, int(exp or 0))
    lvl = level if level in LEVEL_EXP_MAP else level_from_exp(exp)
    lo, hi = LEVEL_EXP_MAP[lvl]
    if not (lo <= exp <= hi):
        lvl = level_from_exp(exp)
        lo, hi = LEVEL_EXP_MAP[lvl]

    if hi == float("inf"):  # max level
        return {"level": lvl, "level_start_exp": lo, "level_end_exp": None,
                "exp_in_level": exp - lo, "exp_needed": None,
                "exp_to_next": 0, "progress_pct": 100.0, "is_max": True}

    span = (hi - lo) + 1  # EXP needed to clear this level
    done = exp - lo
    return {"level": lvl, "level_start_exp": lo, "level_end_exp": hi,
            "exp_in_level": done, "exp_needed": span,
            "exp_to_next": max(0, hi + 1 - exp),
            "progress_pct": round(min(100.0, max(0.0, done / span * 100.0)), 2),
            "is_max": False}


# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        # uid -> deque[(timestamp, exp)] used to estimate EXP/hour
        self._exp_samples: Dict[str, deque] = {}
        # uid -> raw PNG bytes (in-memory only, no disk)
        self.profile_images: Dict[str, bytes] = {}

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": level or 1,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "status": "ONLINE",
                "control": "run",          # run | pause | stop
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "auth_type": None,
                "auth_uid": None,
                "auth_token": None,
                "worker_key": None,
                "target_level": None,
                "profile_image": None,
                "runtime_accumulated": 0.0,
                "running_since": time.time(),
            }
            self._exp_samples[uid_str] = deque([(time.time(), exp)], maxlen=400)
            # Restore target_level from account_status.json if present
            try:
                tl = _resolve_target_level(f"acc:{uid_str}", acc=self.accounts[uid_str])
                if tl is not None:
                    self.accounts[uid_str]["target_level"] = tl
            except Exception:
                pass
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            if exp != acc["current_exp"]:
                self._add_sample(uid_str, exp)
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            # Do not clobber PAUSED / STOPPED status from a register call
            if acc.get("control") not in ("pause", "stop"):
                acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
            if "runtime_accumulated" not in acc:
                acc["runtime_accumulated"] = 0.0
            if "running_since" not in acc:
                acc["running_since"] = time.time() if acc.get("control") == "run" else None
            if acc.get("target_level") is None:
                try:
                    keys = [f"acc:{uid_str}"]
                    if acc.get("auth_uid"):
                        keys.append(f"guest:{acc['auth_uid']}")
                    if acc.get("auth_token"):
                        keys.append(f"token:{str(acc['auth_token'])[:10]}")
                    tl = _resolve_target_level(*keys, acc=acc)
                    if tl is not None:
                        acc["target_level"] = tl
                except Exception:
                    pass
        self.recalc_totals()

    def set_control(self, uid: str, control: str) -> bool:
        """Set per-account control flag: run | pause | stop (persisted to disk)."""
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return False
        if control not in ("run", "pause", "stop"):
            return False
        acc = self.accounts[uid_str]
        prev = acc.get("control") or "run"
        now = time.time()
        if control == "pause":
            if prev == "run" and acc.get("running_since"):
                try:
                    acc["runtime_accumulated"] = float(acc.get("runtime_accumulated") or 0) + max(0.0, now - float(acc["running_since"]))
                except Exception:
                    pass
            acc["running_since"] = None
        elif control == "stop":
            acc["runtime_accumulated"] = 0.0
            acc["running_since"] = None
        elif control == "run":
            if prev == "stop":
                acc["runtime_accumulated"] = 0.0
                acc["running_since"] = now
            elif prev == "pause":
                acc["running_since"] = now
            else:
                if not acc.get("running_since"):
                    acc["running_since"] = now
        acc["control"] = control
        status_map = {"run": "ONLINE", "pause": "PAUSED", "stop": "STOPPED"}
        acc["status"] = status_map[control]
        acc["last_updated"] = time.strftime("%H:%M:%S")
        self.log(
            f"Account {self.accounts[uid_str].get('nickname', uid_str)} → {control.upper()}",
            "info" if control == "run" else "warning",
            uid_str,
        )
        # Persist so a script restart restores pause/stop/run
        try:
            acc = self.accounts[uid_str]
            keys = [f"acc:{uid_str}"]
            if acc.get("auth_uid"):
                keys.append(f"guest:{acc['auth_uid']}")
            if acc.get("auth_token"):
                keys.append(f"token:{str(acc['auth_token'])[:10]}")
            if acc.get("worker_key"):
                # guest worker_key is uid; token worker_key is token[:10]
                wk = str(acc["worker_key"])
                if acc.get("auth_type") == "token":
                    keys.append(f"token:{wk}")
                else:
                    keys.append(f"guest:{wk}")
            status_path = "account_status.json"
            data = {}
            if os.path.exists(status_path):
                try:
                    with open(status_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            nick = acc.get("nickname") or ""
            for k in keys:
                prev = data.get(k)
                entry = dict(prev) if isinstance(prev, dict) else (
                    {"control": prev} if prev in ("run", "pause", "stop") else {}
                )
                entry["control"] = control
                if nick:
                    entry["nickname"] = nick
                entry["account_id"] = uid_str
                # Preserve existing target_level if memory doesn't have one
                if acc.get("target_level") is not None and acc.get("target_level") != "":
                    try:
                        entry["target_level"] = int(acc["target_level"])
                    except Exception:
                        pass
                elif "target_level" not in entry and isinstance(prev, dict) and prev.get("target_level") is not None:
                    try:
                        entry["target_level"] = int(prev["target_level"])
                    except Exception:
                        pass
                data[k] = entry
            tmp = status_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, status_path)
        except Exception:
            pass
        return True

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff != 0:
                self._add_sample(uid_str, current_exp)
            if diff > 0:
                self.log(f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}", "success", uid_str)
            self.recalc_totals()

    def _add_sample(self, uid_str: str, exp: int):
        samples = self._exp_samples.setdefault(uid_str, deque(maxlen=400))
        samples.append((time.time(), exp))

    def _speed(self, uid_str: str, current_exp: int) -> float:
        """EXP per second over the recent window (0 if not enough data)."""
        samples = self._exp_samples.get(uid_str)
        if not samples:
            return 0.0
        now = time.time()
        recent = [(t, e) for t, e in samples if now - t <= SPEED_WINDOW_SEC]
        # Keep the sample just before the window so a single gain still has a baseline
        if len(recent) < len(samples) and len(recent) < 2:
            recent = list(samples)[-2:]
        if len(recent) < 2:
            return 0.0
        t0, e0 = recent[0]
        t1, e1 = recent[-1]
        # Measure up to "now" so the speed decays while the account is idle
        span = max(now, t1) - t0
        gained = e1 - e0
        if gained <= 0 or span < SPEED_MIN_SPAN_SEC:
            return 0.0
        return gained / span

    def snapshot_account(self, acc: Dict[str, Any]) -> Dict[str, Any]:
        """Account dict + level progress, speed and ETA for the dashboard."""
        out = dict(acc)
        try:
            accumulated = float(acc.get("runtime_accumulated") or 0)
            rs = acc.get("running_since")
            if rs and (acc.get("control") or "run") == "run":
                accumulated += max(0.0, time.time() - float(rs))
            out["runtime_seconds"] = int(accumulated)
        except Exception:
            out["runtime_seconds"] = 0
        prog = level_progress(acc.get("level", 1), acc.get("current_exp", 0))
        out["level"] = prog["level"]
        out.update(prog)
        speed = self._speed(acc["uid"], acc.get("current_exp", 0))
        out["exp_per_hour"] = int(speed * 3600)
        if prog["is_max"] or speed <= 0:
            out["eta_seconds"] = None
        else:
            out["eta_seconds"] = int(prog["exp_to_next"] / speed)
        # Never embed raw base64 / data-URLs in stats (kills mobile + bloats JSON).
        # Prefer in-memory image endpoint; fall back to a short path if set.
        uid = str(acc.get("uid") or "")
        if uid and uid in self.profile_images:
            out["profile_image"] = f"/api/account/image/{uid}"
        else:
            pi = out.get("profile_image")
            if isinstance(pi, str) and pi.startswith("data:"):
                out["profile_image"] = f"/api/account/image/{uid}" if uid else None
            elif isinstance(pi, str) and pi.startswith("/api/"):
                pass
            elif not pi:
                out["profile_image"] = None
        return out

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            # Don't let background match counters clobber an explicit pause/stop
            ctrl = self.accounts[uid_str].get("control", "run")
            if ctrl == "pause" and status not in ("PAUSED", "STOPPED"):
                status = "PAUSED"
            elif ctrl == "stop" and status not in ("STOPPED",):
                status = "STOPPED"
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        # Resolve account even if caller passed auth_uid / worker key
        acc = self.accounts.get(uid_str)
        if acc is None:
            for a in self.accounts.values():
                if str(a.get("uid")) == uid_str:
                    acc = a
                    break
                if str(a.get("auth_uid") or "") == uid_str:
                    acc = a
                    break
                if str(a.get("worker_key") or "") == uid_str:
                    acc = a
                    break
        if acc is not None:
            acc["matches_played"] = int(acc.get("matches_played") or 0) + 1
            acc["last_match_time"] = time.strftime("%H:%M:%S")
            acc["last_updated"] = time.strftime("%H:%M:%S")
            self.log(
                f"Account {acc.get('nickname', uid_str)} finished Match #{acc['matches_played']}",
                "info",
                str(acc.get("uid", uid_str)),
            )
        else:
            self.log(f"Match finished for unknown uid {uid_str} (total={self.total_matches})", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ==================== HTTP HANDLERS ====================

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")

async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


ACCOUNT_ORDER_FILE = "account_order.json"


def _status_rank(acc: Dict[str, Any]) -> int:
    """Lower = higher in list. Running → Paused → Stopped → other."""
    ctrl = acc.get("control") or ""
    st = (acc.get("status") or "").upper()
    if ctrl == "stop" or st == "STOPPED":
        return 2
    if ctrl == "pause" or st == "PAUSED":
        return 1
    if st in ("ERROR", "OFFLINE"):
        return 3
    return 0  # running / online / match / searching / connecting


def _load_account_order() -> List[str]:
    if not os.path.exists(ACCOUNT_ORDER_FILE):
        return []
    try:
        with open(ACCOUNT_ORDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def _save_account_order(order: List[str]):
    try:
        tmp = ACCOUNT_ORDER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(order, f, indent=2)
        os.replace(tmp, ACCOUNT_ORDER_FILE)
    except Exception:
        pass


def _sort_accounts(accounts_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order = _load_account_order()
    order_idx = {uid: i for i, uid in enumerate(order)}

    def key(a):
        uid = str(a.get("uid", ""))
        return (
            _status_rank(a),
            order_idx.get(uid, 10_000),
            str(a.get("nickname") or uid).lower(),
        )

    return sorted(accounts_data, key=key)


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = [bot_state.snapshot_account(a) for a in bot_state.accounts.values()]
    accounts_data = _sort_accounts(accounts_data)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "uptime": int(time.time() - bot_state.start_time),
        "server_time": time.time()
    })


def _load_accounts_file() -> list:
    accounts_file = "accounts.json"
    if not os.path.exists(accounts_file):
        return []
    try:
        with open(accounts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_accounts_file(rows: list):
    accounts_file = "accounts.json"
    tmp = accounts_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    os.replace(tmp, accounts_file)


def _normalize_account_entry(item) -> Optional[dict]:
    """Accept dict with uid/password or token; ignore junk."""
    if not isinstance(item, dict):
        return None
    if item.get("token"):
        tok = str(item["token"]).strip()
        if tok:
            return {"token": tok}
    uid = item.get("uid") if item.get("uid") is not None else item.get("guest_uid")
    if uid is None:
        uid = ""
    uid = str(uid).strip()
    pwd = str(item.get("password") or item.get("pass") or "").strip()
    if uid and pwd:
        return {"uid": uid, "password": pwd}
    return None


def parse_loose_accounts_json(raw: str) -> list:
    """Parse accounts JSON that may be an array, NDJSON, or comma-separated objects
    (including trailing commas and numeric uids)."""
    text = (raw or "").strip()
    if not text:
        return []
    # Strip JS-style trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    candidates = [cleaned]
    if not cleaned.startswith("["):
        candidates.append("[" + cleaned + "]")
        # if it ends with a trailing comma after last object
        candidates.append("[" + cleaned.rstrip().rstrip(",") + "]")
    last_err = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return [data]
            if isinstance(data, list):
                return data
        except Exception as e:
            last_err = e
    # NDJSON fallback
    rows = []
    for line in text.splitlines():
        line2 = line.strip().rstrip(",")
        if not line2 or line2 in ("[", "]"):
            continue
        line2 = re.sub(r",\s*([}\]])", r"\1", line2)
        try:
            rows.append(json.loads(line2))
        except Exception:
            continue
    if rows:
        return rows
    if last_err:
        raise last_err
    return []


def _merge_account_rows(existing: list, incoming: list) -> tuple:
    """Merge incoming into existing; dedupe by uid or token. Returns (merged, added_list)."""
    by_uid = {}
    by_token = {}
    order = []
    for acc in existing:
        if not isinstance(acc, dict):
            continue
        if acc.get("token"):
            key = ("t", str(acc["token"]))
            by_token[str(acc["token"])] = acc
            order.append(key)
        elif acc.get("uid"):
            key = ("u", str(acc["uid"]))
            by_uid[str(acc["uid"])] = acc
            order.append(key)
    added = []
    for item in incoming:
        norm = _normalize_account_entry(item)
        if not norm:
            continue
        if "token" in norm:
            t = norm["token"]
            if t in by_token:
                by_token[t] = norm
            else:
                by_token[t] = norm
                order.append(("t", t))
                added.append(norm)
        else:
            u = str(norm["uid"])
            if u in by_uid:
                by_uid[u] = norm
            else:
                by_uid[u] = norm
                order.append(("u", u))
                added.append(norm)
    merged = []
    seen = set()
    for kind, key in order:
        sk = (kind, key)
        if sk in seen:
            continue
        seen.add(sk)
        if kind == "t":
            merged.append(by_token[key])
        else:
            merged.append(by_uid[key])
    return merged, added


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        existing = _load_accounts_file()

        # Bulk: { "accounts": [ {...}, ... ] } or raw list or { "raw": "..." }
        bulk = None
        if isinstance(data, list):
            bulk = data
        elif isinstance(data, dict):
            if isinstance(data.get("accounts"), list):
                bulk = data["accounts"]
            elif isinstance(data.get("raw"), str):
                bulk = parse_loose_accounts_json(data["raw"])

        if bulk is not None:
            merged, added = _merge_account_rows(existing, bulk)
            _save_accounts_file(merged)
            bot_state.log(f"Bulk import: {len(added)} new account(s) ({len(merged)} total)", "success")
            cb = bot_state.refresh_callbacks.get("on_account_added")
            if cb:
                for row in added:
                    asyncio.create_task(cb(row))
            return web.json_response({
                "status": "ok",
                "added": len(added),
                "total": len(merged),
            })

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd})
            row = {"uid": uid, "password": pwd}
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            existing.append({"token": token})
            row = {"token": token}
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        _save_accounts_file(existing)
        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](row))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_get_accounts_file(request: web.Request) -> web.Response:
    """Return raw accounts.json list for the editor."""
    try:
        rows = _load_accounts_file()
        return web.json_response({"status": "ok", "accounts": rows, "raw": json.dumps(rows, indent=2)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_put_accounts_file(request: web.Request) -> web.Response:
    """Replace accounts.json from editor. Accepts {raw: "..."} or {accounts: [...]} or a list."""
    try:
        data = await request.json()
        rows = None
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            if "accounts" in data and isinstance(data["accounts"], list):
                rows = data["accounts"]
            elif "raw" in data:
                raw = data["raw"]
                if isinstance(raw, str):
                    rows = parse_loose_accounts_json(raw)
                elif isinstance(raw, list):
                    rows = raw
        if rows is None:
            return web.json_response({"status": "error", "error": "Provide accounts list or raw JSON"})
        if not isinstance(rows, list):
            return web.json_response({"status": "error", "error": "accounts must be a JSON array"})
        cleaned = []
        for item in rows:
            norm = _normalize_account_entry(item)
            if norm:
                cleaned.append(norm)
        prev = _load_accounts_file()
        _save_accounts_file(cleaned)
        # Launch workers for newly appearing accounts
        prev_uids = {str(a.get("uid")) for a in prev if isinstance(a, dict) and a.get("uid")}
        prev_toks = {str(a.get("token")) for a in prev if isinstance(a, dict) and a.get("token")}
        cb = bot_state.refresh_callbacks.get("on_account_added")
        launched = 0
        if cb:
            for row in cleaned:
                if row.get("uid") and str(row["uid"]) not in prev_uids:
                    asyncio.create_task(cb(row))
                    launched += 1
                elif row.get("token") and str(row["token"]) not in prev_toks:
                    asyncio.create_task(cb(row))
                    launched += 1
        bot_state.log(f"accounts.json saved ({len(cleaned)} entries, {launched} new workers)", "success")
        return web.json_response({"status": "ok", "total": len(cleaned), "launched": launched})
    except json.JSONDecodeError as e:
        return web.json_response({"status": "error", "error": f"Invalid JSON: {e}"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    """Permanently remove an account from rotation, accounts.json, cache and workers.

    The dashboard sends the *game* account_id. We resolve auth_uid / auth_token
    so the matching entry is removed from accounts.json (which stores guest UID
    or token), otherwise the account reappears on the next restart.
    """
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()  # game account_id from the dashboard

        acc_meta = bot_state.accounts.get(uid, {})
        auth_uid = acc_meta.get("auth_uid") or (bot_state.account_credentials.get(uid) or {}).get("auth_uid")
        auth_token = acc_meta.get("auth_token") or (bot_state.account_credentials.get(uid) or {}).get("auth_token")
        worker_key = acc_meta.get("worker_key")

        # --- accounts.json: remove by guest uid OR token ---
        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
            filtered = []
            for acc in existing:
                if auth_uid and str(acc.get("uid")) == str(auth_uid):
                    continue
                if auth_token and acc.get("token") == auth_token:
                    continue
                # also drop if someone stored the game id as uid by mistake
                if str(acc.get("uid")) == uid:
                    continue
                filtered.append(acc)
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(filtered, f, indent=2)

        # --- token cache (edit file directly to avoid circular import with app) ---
        try:
            cache_file = "token_cache.json"
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                changed = False
                for key in list(cache.keys()):
                    drop = (
                        key == str(auth_uid)
                        or key == uid
                        or (auth_token and key.startswith("tok_") and auth_token[:20] in key)
                    )
                    if drop:
                        del cache[key]
                        changed = True
                if changed:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
        except Exception:
            pass

        # --- account_status.json (pause/run/stop persistence) ---
        try:
            status_path = "account_status.json"
            if os.path.exists(status_path):
                with open(status_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                if isinstance(st, dict):
                    for k in list(st.keys()):
                        if (
                            k == f"acc:{uid}"
                            or (auth_uid and k == f"guest:{auth_uid}")
                            or (auth_token and k == f"token:{auth_token[:10]}")
                            or (worker_key and (k == f"guest:{worker_key}" or k == f"token:{worker_key}"))
                        ):
                            del st[k]
                    with open(status_path, "w", encoding="utf-8") as f:
                        json.dump(st, f, indent=2)
        except Exception:
            pass

        # --- cancel worker(s) ---
        keys_to_cancel = {uid}
        if worker_key:
            keys_to_cancel.add(str(worker_key))
        if auth_uid:
            keys_to_cancel.add(str(auth_uid))
        if auth_token:
            keys_to_cancel.add(auth_token[:10])
        for k in keys_to_cancel:
            t = bot_state.account_workers.pop(k, None)
            if t and not t.done():
                t.cancel()

        # --- in-memory state ---
        bot_state.accounts.pop(uid, None)
        bot_state._exp_samples.pop(uid, None)
        for k in list(bot_state.account_credentials.keys()):
            cred = bot_state.account_credentials.get(k)
            if not cred:
                continue
            if str(cred.get("account_id")) == uid or str(k) == uid:
                bot_state.account_credentials.pop(k, None)
            elif auth_uid and str(cred.get("auth_uid")) == str(auth_uid):
                bot_state.account_credentials.pop(k, None)
            elif auth_token and cred.get("auth_token") == auth_token:
                bot_state.account_credentials.pop(k, None)

        try:
            bot_state.profile_images.pop(uid, None)
            if uid in bot_state.accounts:
                bot_state.accounts[uid]["profile_image"] = None
        except Exception:
            pass

        bot_state.recalc_totals()
        bot_state.log(f"Account {uid} permanently removed.", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_control_account(request: web.Request) -> web.Response:
    """Pause / resume / stop / start / restart an account without removing it."""
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        action = str(data.get("action", "")).strip().lower()
        if action not in ("pause", "resume", "stop", "start", "restart"):
            return web.json_response({"status": "error", "error": "action must be pause|resume|stop|start|restart"})
        if uid not in bot_state.accounts:
            return web.json_response({"status": "error", "error": "account not found"})

        if action == "pause":
            bot_state.set_control(uid, "pause")
        elif action == "resume":
            bot_state.set_control(uid, "run")
        elif action == "stop":
            bot_state.set_control(uid, "stop")
        elif action == "start":
            bot_state.set_control(uid, "run")
            bot_state.update_status(uid, "CONNECTING", 0)
        elif action == "restart":
            acc = bot_state.accounts[uid]
            # Snapshot identity fields so restart cannot drop them
            auth_uid = acc.get("auth_uid")
            auth_token = acc.get("auth_token")
            auth_type = acc.get("auth_type")
            worker_key = acc.get("worker_key")
            saved_target = acc.get("target_level")
            # Never write/modify accounts.json on restart
            bot_state.set_control(uid, "stop")
            bot_state.update_status(uid, "STOPPED", 0)
            try:
                cache_file = "token_cache.json"
                if os.path.exists(cache_file):
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                    for key in list(cache.keys()):
                        if key == uid or (auth_uid and key == str(auth_uid)):
                            del cache[key]
                        elif auth_token and key.startswith("tok_") and auth_token[:20] in key:
                            del cache[key]
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
            except Exception:
                pass
            await asyncio.sleep(0.4)
            # Restore identity in case anything cleared them
            acc = bot_state.accounts.get(uid) or acc
            if auth_uid:
                acc["auth_uid"] = auth_uid
            if auth_token:
                acc["auth_token"] = auth_token
            if auth_type:
                acc["auth_type"] = auth_type
            if worker_key:
                acc["worker_key"] = worker_key
            if saved_target is not None:
                acc["target_level"] = saved_target
            bot_state.set_control(uid, "run")
            bot_state.update_status(uid, "CONNECTING", 0)
            bot_state.log(f"Restart requested for {acc.get('nickname', uid)}", "warning", uid)

        return web.json_response({"status": "ok", "control": bot_state.accounts[uid].get("control")})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_all(request: web.Request) -> web.Response:
    """Refresh EXP for every registered account."""
    try:
        cb = bot_state.refresh_callbacks.get("on_refresh_account")
        if not cb:
            return web.json_response({"status": "error", "error": "refresh not available"})
        uids = list(bot_state.accounts.keys())
        for uid in uids:
            try:
                asyncio.create_task(cb(uid))
            except Exception:
                pass
        bot_state.log(f"Refresh EXP requested for {len(uids)} accounts", "info")
        return web.json_response({"status": "ok", "count": len(uids)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_reorder_accounts(request: web.Request) -> web.Response:
    """Persist manual account order (list of uids)."""
    try:
        data = await request.json()
        order = data.get("order")
        if not isinstance(order, list):
            return web.json_response({"status": "error", "error": "order must be a list of uids"})
        cleaned = [str(u).strip() for u in order if str(u).strip()]
        _save_account_order(cleaned)
        return web.json_response({"status": "ok", "order": cleaned})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


def _lookup_guest_password(auth_uid: Optional[str] = None, game_uid: Optional[str] = None) -> tuple:
    """Find guest uid + password from accounts.json / live credentials. Never returns wiped password if known."""
    guest_uid = str(auth_uid or "") if auth_uid else ""
    password = ""
    # 1) Live credentials from successful login
    for key, cred in list(bot_state.account_credentials.items()):
        if not isinstance(cred, dict):
            continue
        if auth_uid and str(cred.get("auth_uid") or "") == str(auth_uid):
            password = str(cred.get("auth_password") or password)
            guest_uid = str(cred.get("auth_uid") or guest_uid)
        if game_uid and str(cred.get("account_id") or "") == str(game_uid):
            if cred.get("auth_uid"):
                guest_uid = str(cred.get("auth_uid") or guest_uid)
            password = str(cred.get("auth_password") or password)
    # 2) accounts.json
    rows = _load_accounts_file()
    for row in rows:
        if not isinstance(row, dict) or not row.get("uid"):
            continue
        rid = str(row.get("uid"))
        if guest_uid and rid == str(guest_uid):
            password = str(row.get("password") or password)
            guest_uid = rid
            break
        if not guest_uid and game_uid and rid == str(game_uid):
            # rare: game id stored as uid
            guest_uid = rid
            password = str(row.get("password") or password)
            break
    # 3) account_status meta may hold auth_uid
    if not guest_uid and game_uid:
        try:
            status_path = "account_status.json"
            if os.path.exists(status_path):
                with open(status_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                for k, v in (st if isinstance(st, dict) else {}).items():
                    if not isinstance(v, dict):
                        continue
                    if str(v.get("account_id") or "") == str(game_uid) and k.startswith("guest:"):
                        guest_uid = k.split(":", 1)[1]
                        break
        except Exception:
            pass
        if guest_uid:
            for row in rows:
                if str(row.get("uid") or "") == str(guest_uid):
                    password = str(row.get("password") or password)
                    break
    return guest_uid, password


def _resolve_target_level(*keys, acc: Optional[dict] = None) -> Optional[int]:
    """Prefer in-memory target, else account_status.json for any of the keys."""
    if acc and acc.get("target_level") is not None and acc.get("target_level") != "":
        try:
            return int(acc["target_level"])
        except Exception:
            pass
    try:
        status_path = "account_status.json"
        if not os.path.exists(status_path):
            return None
        with open(status_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict):
            return None
        for k in keys:
            if not k or k not in st:
                continue
            v = st[k]
            if isinstance(v, dict) and v.get("target_level") is not None:
                try:
                    return int(v["target_level"])
                except Exception:
                    pass
    except Exception:
        pass
    return None


async def handle_get_credentials(request: web.Request) -> web.Response:
    """Return editable credentials for one account (from accounts.json + meta)."""
    try:
        uid = str(request.query.get("uid") or "").strip()
        if not uid or uid not in bot_state.accounts:
            return web.json_response({"status": "error", "error": "account not found"})
        acc = bot_state.accounts[uid]
        auth_type = acc.get("auth_type") or "guest"
        auth_uid = acc.get("auth_uid")
        auth_token = acc.get("auth_token")
        password = ""
        token = auth_token or ""
        guest_uid = str(auth_uid or "")

        if auth_type == "token" or auth_token:
            auth_type = "token"
            token = auth_token or token
            # still try accounts.json for token
            for row in _load_accounts_file():
                if isinstance(row, dict) and row.get("token") and (
                    (auth_token and row.get("token") == auth_token) or row.get("token") == token
                ):
                    token = str(row.get("token") or token)
                    break
        else:
            auth_type = "guest"
            guest_uid, password = _lookup_guest_password(auth_uid=auth_uid, game_uid=uid)
            if guest_uid and not acc.get("auth_uid"):
                acc["auth_uid"] = guest_uid

        # Target level: memory first, then status file
        keys = [f"acc:{uid}"]
        if guest_uid:
            keys.append(f"guest:{guest_uid}")
        if auth_token:
            keys.append(f"token:{str(auth_token)[:10]}")
        if acc.get("worker_key"):
            wk = str(acc["worker_key"])
            keys.append(f"guest:{wk}")
            keys.append(f"token:{wk}")
        target = _resolve_target_level(*keys, acc=acc)
        if target is not None:
            acc["target_level"] = target

        return web.json_response({
            "status": "ok",
            "uid": uid,
            "nickname": acc.get("nickname"),
            "auth_type": auth_type,
            "guest_uid": guest_uid,
            "password": password,
            "token": token,
            "target_level": acc.get("target_level"),
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_update_credentials(request: web.Request) -> web.Response:
    """Update uid/password or token in accounts.json and live meta; force re-login if needed."""
    try:
        data = await request.json()
        uid = str(data.get("uid") or "").strip()
        if not uid or uid not in bot_state.accounts:
            return web.json_response({"status": "error", "error": "account not found"})

        acc = bot_state.accounts[uid]
        auth_type = str(data.get("auth_type") or acc.get("auth_type") or "guest").lower()
        old_auth_uid = acc.get("auth_uid")
        old_token = acc.get("auth_token")

        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        if auth_type == "token":
            new_token = str(data.get("token") or "").strip()
            if not new_token:
                return web.json_response({"status": "error", "error": "token is required"})
            filtered = []
            for row in existing:
                if old_token and row.get("token") == old_token:
                    continue
                if row.get("token") == new_token:
                    continue
                filtered.append(row)
            filtered.append({"token": new_token})
            existing = filtered
            acc["auth_type"] = "token"
            acc["auth_token"] = new_token
            acc["auth_uid"] = None
            # Invalidate old token cache key
            try:
                cache_file = "token_cache.json"
                if os.path.exists(cache_file):
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                    for key in list(cache.keys()):
                        if old_token and key.startswith("tok_") and old_token[:20] in key:
                            del cache[key]
                        if new_token and key.startswith("tok_") and new_token[:20] in key:
                            del cache[key]
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
            except Exception:
                pass
        else:
            new_guest = str(data.get("guest_uid") or data.get("guestUid") or "").strip()
            new_pass = str(data.get("password") or "").strip()
            if not new_guest or not new_pass:
                return web.json_response({"status": "error", "error": "guest UID and password are required"})
            filtered = []
            for row in existing:
                if old_auth_uid and str(row.get("uid")) == str(old_auth_uid):
                    continue
                if str(row.get("uid")) == new_guest:
                    continue
                if str(row.get("uid")) == uid:
                    continue
                filtered.append(row)
            filtered.append({"uid": new_guest, "password": new_pass})
            existing = filtered
            acc["auth_type"] = "guest"
            acc["auth_uid"] = new_guest
            acc["auth_token"] = None
            try:
                cache_file = "token_cache.json"
                if os.path.exists(cache_file):
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                    for key in list(cache.keys()):
                        if old_auth_uid and key == str(old_auth_uid):
                            del cache[key]
                        if key == new_guest:
                            del cache[key]
                        if key == uid:
                            del cache[key]
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
            except Exception:
                pass

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        if "target_level" in data:
            tl = data.get("target_level")
            if tl is None or str(tl).strip() == "":
                acc["target_level"] = None
            else:
                try:
                    acc["target_level"] = int(tl)
                except Exception:
                    return web.json_response({"status": "error", "error": "target_level must be a number"})
            # Persist target into account_status.json immediately
            try:
                status_path = "account_status.json"
                st = {}
                if os.path.exists(status_path):
                    with open(status_path, "r", encoding="utf-8") as f:
                        st = json.load(f)
                    if not isinstance(st, dict):
                        st = {}
                keys = [f"acc:{uid}"]
                if acc.get("auth_uid"):
                    keys.append(f"guest:{acc['auth_uid']}")
                if acc.get("auth_token"):
                    keys.append(f"token:{str(acc['auth_token'])[:10]}")
                for k in keys:
                    prev = st.get(k)
                    entry = dict(prev) if isinstance(prev, dict) else (
                        {"control": prev} if prev in ("run", "pause", "stop") else {}
                    )
                    entry.setdefault("control", acc.get("control") or "run")
                    entry["account_id"] = uid
                    if acc.get("nickname"):
                        entry["nickname"] = acc["nickname"]
                    if acc.get("target_level") is None:
                        entry.pop("target_level", None)
                    else:
                        entry["target_level"] = int(acc["target_level"])
                    st[k] = entry
                tmp = status_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(st, f, indent=2)
                os.replace(tmp, status_path)
            except Exception:
                pass

        # If currently stopped, stay stopped; otherwise force a clean re-login
        was_stopped = acc.get("control") == "stop"
        if not was_stopped:
            bot_state.set_control(uid, "stop")
            await asyncio.sleep(0.3)
            bot_state.set_control(uid, "run")
            bot_state.update_status(uid, "CONNECTING", 0)
        else:
            bot_state.set_control(uid, "stop")

        # If guest uid changed while only a placeholder exists, relaunch worker
        if auth_type == "guest" and old_auth_uid and str(old_auth_uid) != str(acc.get("auth_uid")):
            cb = bot_state.refresh_callbacks.get("on_account_added")
            if cb:
                # cancel old worker keys
                for k in list(bot_state.account_workers.keys()):
                    if k in (str(old_auth_uid), uid, str(acc.get("worker_key") or "")):
                        t = bot_state.account_workers.pop(k, None)
                        if t and not t.done():
                            t.cancel()
                asyncio.create_task(cb({"uid": acc["auth_uid"], "password": new_pass}))

        if auth_type == "token" and old_token and old_token != acc.get("auth_token"):
            cb = bot_state.refresh_callbacks.get("on_account_added")
            if cb:
                for k in list(bot_state.account_workers.keys()):
                    if k in (str(old_token)[:10], uid, str(acc.get("worker_key") or "")):
                        t = bot_state.account_workers.pop(k, None)
                        if t and not t.done():
                            t.cancel()
                asyncio.create_task(cb({"token": acc["auth_token"]}))

        bot_state.log(f"Credentials updated for {acc.get('nickname', uid)}", "success", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})



async def handle_account_image(request: web.Request) -> web.Response:
    """Serve in-memory profile PNG for one account (no disk)."""
    uid = str(request.match_info.get("uid") or "").strip()
    raw = bot_state.profile_images.get(uid)
    if not raw:
        # try int-normalized key
        try:
            raw = bot_state.profile_images.get(str(int(uid)))
        except Exception:
            raw = None
    if not raw:
        return web.Response(status=404, text="not found")
    return web.Response(
        body=raw,
        content_type="image/png",
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Length": str(len(raw)),
        },
    )


async def handle_get_settings(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "settings": load_bot_settings()})


async def handle_save_settings(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return web.json_response({"status": "error", "error": "invalid payload"})
        current = load_bot_settings()
        mapping = {
            "max_stack_lw": int,
            "max_stack_br": int,
            "start_match_interval": float,
            "new_match_delay": float,
            "match_idle_timeout": float,
            "lw_match_idle_timeout": float,
            "exp_refresh_interval": float,
            "token_cache_ttl": int,
            "identity_rotate_every_matches": int,
            "identity_rotate_every_seconds": int,
            "cancel_br_on_lw_unlock": bool,
            "safe_play_mode": bool,
            "human_like_movement": bool,
        }
        for key, caster in mapping.items():
            if key not in data:
                continue
            val = data[key]
            try:
                if caster is bool:
                    current[key] = bool(val) if not isinstance(val, str) else val.strip().lower() in ("1", "true", "yes", "on")
                else:
                    current[key] = caster(val)
            except Exception:
                return web.json_response({"status": "error", "error": f"invalid value for {key}"})
        if current["max_stack_lw"] < 1:
            current["max_stack_lw"] = 1
        if current["max_stack_br"] < 1:
            current["max_stack_br"] = 1
        saved = save_bot_settings(current)
        bot_state.log("Bot settings updated", "success")
        return web.json_response({"status": "ok", "settings": saved})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


def format_accounts_pretty(creds: list) -> str:
    """Multi-line objects separated by commas (no outer array) for copy/paste."""
    if not creds:
        return ""
    chunks = []
    for c in creds:
        # Prefer numeric uid when possible
        obj = {}
        if "uid" in c and c.get("uid") is not None:
            try:
                obj["uid"] = int(str(c["uid"]))
            except Exception:
                obj["uid"] = c["uid"]
            obj["password"] = c.get("password", "")
        elif c.get("token"):
            obj["token"] = c["token"]
        else:
            continue
        chunk = json.dumps(obj, indent=4, ensure_ascii=False)
        chunks.append(chunk)
    return ",\n".join(chunks)


async def handle_get_completed(request: web.Request) -> web.Response:
    rows = load_completed_accounts()
    creds = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("uid") is not None:
            creds.append({"uid": r.get("uid"), "password": r.get("password", "")})
        elif r.get("token"):
            creds.append({"token": r.get("token")})
    return web.json_response({
        "status": "ok",
        "accounts": creds,
        "count": len(creds),
        "pretty": format_accounts_pretty(creds),
    })


async def handle_clear_completed(request: web.Request) -> web.Response:
    try:
        save_completed_accounts([])
        bot_state.log("Completed accounts list cleared", "warning")
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_get("/api/accounts/file", handle_get_accounts_file)
    app.router.add_post("/api/accounts/file", handle_put_accounts_file)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/control", handle_control_account)
    app.router.add_post("/api/account/refresh_all", handle_refresh_all)
    app.router.add_post("/api/account/reorder", handle_reorder_accounts)
    app.router.add_get("/api/account/credentials", handle_get_credentials)
    app.router.add_post("/api/account/credentials", handle_update_credentials)
    app.router.add_get("/api/account/image/{uid}", handle_account_image)
    app.router.add_get("/api/settings", handle_get_settings)
    app.router.add_post("/api/settings", handle_save_settings)
    app.router.add_get("/api/completed", handle_get_completed)
    app.router.add_post("/api/completed/clear", handle_clear_completed)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
