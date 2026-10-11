# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# ---------- CONFIG ----------
TARGET_LEVEL = 8          # Auto-pause when account reaches this level
MIN_LEVEL = 3             # Accounts below this level NEVER play matches

ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
DEVICES_FILE = "devices.json"


# ============================================================
# GLOBAL BOT STATE
# ============================================================
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 300
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.paused_accounts: Dict[str, bool] = {}
        self.target_reached: Dict[str, bool] = {}

        # ---------- QUEUE ----------
        self.active_account: Optional[str] = None
        self.queue: List[str] = []
        self.queue_lock = asyncio.Lock()

    # ---------- Logging ----------
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

    # ---------- Account registration ----------
    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, avatar_id: int = 0, banner_id: int = 0):
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
                "status": "IDLE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "avatar_id": avatar_id or 0,
                "banner_id": banner_id or 0
            }
            # Mark target reached if level >= TARGET_LEVEL
            if level and int(level) >= TARGET_LEVEL:
                self.paused_accounts[uid_str] = True
                self.target_reached[uid_str] = True
            else:
                self.paused_accounts.setdefault(uid_str, False)
                self.target_reached.setdefault(uid_str, False)
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["last_updated"] = time.strftime("%H:%M:%S")
            if avatar_id:
                acc["avatar_id"] = avatar_id
            if banner_id:
                acc["banner_id"] = banner_id

            # If account reached target level, mark it
            if level and int(level) >= TARGET_LEVEL:
                if not self.target_reached.get(uid_str, False):
                    self.target_reached[uid_str] = True
                    self.paused_accounts[uid_str] = True
                    self.log(
                        f"Account {acc.get('nickname', uid_str)} ({uid_str}) reached Level {level} "
                        f"(target: {TARGET_LEVEL}) — AUTO-PAUSED.",
                        "warning", uid_str
                    )
        self.recalc_totals()

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
            if diff > 0:
                self.log(
                    f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! "
                    f"Total Gained: +{acc['gained_exp']}",
                    "success", uid_str
                )

            # Auto-pause on target reached
            if level is not None and level >= TARGET_LEVEL and not self.target_reached.get(uid_str, False):
                self.target_reached[uid_str] = True
                self.paused_accounts[uid_str] = True
                self.log(
                    f"🎯 Account {acc['nickname']} ({uid_str}) reached Level {level} — "
                    f"TARGET COMPLETE. Auto-paused. Starting next queued account...",
                    "success", uid_str
                )
                self.update_status(uid_str, "LEVEL_COMPLETE")
                asyncio.create_task(self._start_next_in_queue())

            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(
                f"Account {self.accounts[uid_str]['nickname']} finished "
                f"Match #{self.accounts[uid_str]['matches_played']}",
                "info", uid_str
            )

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

    # ---------- Pause / Resume ----------
    def is_paused(self, uid: str) -> bool:
        return self.paused_accounts.get(str(uid), False)

    def is_target_reached(self, uid: str) -> bool:
        return self.target_reached.get(str(uid), False)

    def set_paused(self, uid: str, paused: bool) -> bool:
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return False
        self.paused_accounts[uid_str] = bool(paused)
        if paused:
            self.accounts[uid_str]["status"] = "PAUSED"
            self.log(f"Account {self.accounts[uid_str]['nickname']} ({uid_str}) PAUSED by user.",
                     "warning", uid_str)
        else:
            self.accounts[uid_str]["status"] = "ONLINE"
            self.log(f"Account {self.accounts[uid_str]['nickname']} ({uid_str}) RESUMED.",
                     "success", uid_str)
            self.target_reached[uid_str] = False
        return True

    # ============================================================
    # QUEUE SYSTEM
    # ============================================================
    def _meets_min_level(self, uid: str) -> bool:
        """Check if account level >= MIN_LEVEL."""
        acc = self.accounts.get(str(uid))
        if not acc:
            return False
        try:
            return int(acc.get("level", 1)) >= MIN_LEVEL
        except Exception:
            return False

    def enqueue(self, uid: str) -> bool:
        """Add a UID to the queue. Only starts immediately if no active account
        AND account level meets MIN_LEVEL."""
        uid_str = str(uid)

        if uid_str not in self.accounts:
            return False

        # Level 2 accounts stay in PROCESSING — never enter queue
        if not self._meets_min_level(uid_str):
            self.log(
                f"⚠️ Account {uid_str} is Level {self.accounts[uid_str].get('level')} "
                f"(min required: {MIN_LEVEL}) — staying in PROCESSING.",
                "warning", uid_str
            )
            return False

        if uid_str in self.queue:
            self.log(f"Account {uid_str} is already in queue.", "warning", uid_str)
            return False

        # If there is no active account and this one meets the level requirement, start it
        if self.active_account is None:
            self.active_account = uid_str
            self.paused_accounts[uid_str] = False
            self.target_reached[uid_str] = False
            self.accounts[uid_str]["status"] = "ACTIVE"
            self.log(
                f"▶️ Account {self.accounts[uid_str].get('nickname', uid_str)} ({uid_str}) "
                f"is now ACTIVE (no other account running).",
                "success", uid_str
            )
        else:
            self.queue.append(uid_str)
            self.accounts[uid_str]["status"] = "QUEUED"
            self.log(
                f"⏳ Account {self.accounts[uid_str].get('nickname', uid_str)} ({uid_str}) "
                f"added to QUEUE (position #{len(self.queue)}).",
                "info", uid_str
            )
        return True

    def dequeue(self, uid: str):
        uid_str = str(uid)
        if uid_str in self.queue:
            self.queue.remove(uid_str)
            self.log(f"Removed {uid_str} from queue.", "warning", uid_str)

    async def _start_next_in_queue(self):
        """Called when active account reaches target level.
        Marks old active as completed, then starts the next level-eligible account."""
        async with self.queue_lock:
            # Mark old active as completed
            if self.active_account is not None:
                self.target_reached[self.active_account] = True
                self.paused_accounts[self.active_account] = True
                try:
                    self.accounts[self.active_account]["status"] = "LEVEL_COMPLETE"
                except Exception:
                    pass

            # Find next valid (level >= MIN_LEVEL and not target reached)
            while self.queue:
                nxt = self.queue.pop(0)
                if nxt not in self.accounts:
                    continue
                if self.target_reached.get(nxt, False):
                    continue
                if not self._meets_min_level(nxt):
                    # Level 2 in queue? move it back to processing, skip
                    try:
                        self.accounts[nxt]["status"] = "READY"
                    except Exception:
                        pass
                    self.log(
                        f"⏭️ Skipping {nxt} (Level {self.accounts[nxt].get('level')} < {MIN_LEVEL})",
                        "warning", nxt
                    )
                    continue

                # Found valid next — activate
                self.active_account = nxt
                self.paused_accounts[nxt] = False
                self.target_reached[nxt] = False
                try:
                    self.accounts[nxt]["status"] = "ACTIVE"
                except Exception:
                    pass
                self.log(
                    f"🚀 AUTO-START: Account {self.accounts[nxt].get('nickname', nxt)} "
                    f"({nxt}) is now ACTIVE (queue had {len(self.queue)} remaining).",
                    "success", nxt
                )
                cb = self.refresh_callbacks.get("on_queue_start")
                if cb:
                    try:
                        await cb(nxt)
                    except Exception as e:
                        self.log(f"Queue start callback error: {e}", "error", nxt)
                return

            # Queue empty
            self.active_account = None
            self.log("✅ Queue is empty. No active account running.", "info")


bot_state = BotState()


# ============================================================
# HELPER: Purge account from all storage files
# ============================================================
def _purge_account_from_files(uid: str, token: Optional[str] = None):
    """Remove ONLY the given account from accounts.json, token_cache.json, devices.json.
    Other accounts are untouched."""

    uid_str = str(uid).strip()
    if not uid_str:
        return

    # --- accounts.json (list) ---
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, list):
                new_list = []
                for acc in existing:
                    if str(acc.get("uid", "")).strip() == uid_str:
                        continue  # remove this one
                    # Also remove if token matches (defensive)
                    if token and acc.get("token") == token:
                        continue
                    new_list.append(acc)
                with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                    json.dump(new_list, f, indent=2)
    except Exception as e:
        bot_state.log(f"accounts.json purge error: {e}", "error", uid_str)

    # --- token_cache.json (dict) ---
    try:
        if os.path.exists(TOKEN_CACHE_FILE):
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            cache = json.loads(content) if content else {}
            if isinstance(cache, dict):
                # Direct uid key
                cache.pop(uid_str, None)
                # token-prefixed key
                if token:
                    cache.pop(f"tok_{token[:20]}", None)
                # Scan entries by account_id / access_token
                to_delete = []
                for k, v in cache.items():
                    if isinstance(v, dict):
                        if str(v.get("account_id", "")) == uid_str:
                            to_delete.append(k)
                        elif token and v.get("access_token") == token:
                            to_delete.append(k)
                for k in to_delete:
                    cache.pop(k, None)
                with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2)
    except Exception as e:
        bot_state.log(f"token_cache.json purge error: {e}", "error", uid_str)

    # --- devices.json (dict keyed by uid) ---
    try:
        if os.path.exists(DEVICES_FILE):
            with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                devices = json.load(f)
            if isinstance(devices, dict):
                devices.pop(uid_str, None)
                with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                    json.dump(devices, f, indent=4)
    except Exception as e:
        bot_state.log(f"devices.json purge error: {e}", "error", uid_str)


# ============================================================
# HTTP HANDLERS
# ============================================================
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")


async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = []
    for acc in bot_state.accounts.values():
        acc_copy = dict(acc)
        uid_str = acc_copy["uid"]
        acc_copy["paused"] = bot_state.is_paused(uid_str)
        acc_copy["target_reached"] = bot_state.is_target_reached(uid_str)
        acc_copy["is_active"] = (bot_state.active_account == uid_str)
        acc_copy["in_queue"] = (uid_str in bot_state.queue)
        acc_copy["meets_min_level"] = bot_state._meets_min_level(uid_str)
        accounts_data.append(acc_copy)

    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)

    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-80:],
        "uptime": int(time.time() - bot_state.start_time),
        "target_level": TARGET_LEVEL,
        "min_level": MIN_LEVEL,
        "active_account": bot_state.active_account,
        "queue": list(bot_state.queue),
        "queue_size": len(bot_state.queue),
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        existing = []
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        # ===== DUPLICATE CHECK =====
        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})

            for acc in existing:
                if str(acc.get("uid", "")).strip() == uid:
                    return web.json_response({
                        "status": "error",
                        "error": f"UID {uid} already exists! Duplicate login blocked."
                    })
            for acc in bot_state.accounts.values():
                if str(acc.get("uid")) == uid:
                    return web.json_response({
                        "status": "error",
                        "error": f"UID {uid} is already running! Duplicate blocked."
                    })

            existing.append({"uid": uid, "password": pwd})
            display_key = uid

        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})

            for acc in existing:
                if acc.get("token") == token:
                    return web.json_response({
                        "status": "error",
                        "error": "This token already exists! Duplicate login blocked."
                    })
            existing.append({"token": token})
            display_key = f"tok_{token[:10]}"
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {display_key}", "success")

        # Trigger dynamic worker launch (Main.py will login and register account)
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})

        # Find token for this uid in accounts.json (before purge)
        token_for_uid = None
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    for acc in json.load(f):
                        if str(acc.get("uid", "")) == uid:
                            token_for_uid = acc.get("token")
            except Exception:
                pass

        # Also check account_credentials for token
        if not token_for_uid:
            creds = bot_state.account_credentials.get(uid)
            if creds:
                token_for_uid = creds.get("access_token") or creds.get("auth_token")

        # ---------- PURGE FROM ALL FILES ----------
        _purge_account_from_files(uid, token_for_uid)

        # ---------- PURGE FROM MEMORY ----------
        if uid in bot_state.accounts:
            del bot_state.accounts[uid]
        bot_state.paused_accounts.pop(uid, None)
        bot_state.target_reached.pop(uid, None)
        bot_state.dequeue(uid)

        # Remove credentials
        for k in list(bot_state.account_credentials.keys()):
            v = bot_state.account_credentials[k]
            if isinstance(v, dict) and str(v.get("account_id", "")) == uid:
                del bot_state.account_credentials[k]
        bot_state.account_credentials.pop(uid, None)

        # If this was the active account, clear it and start next
        if bot_state.active_account == uid:
            bot_state.active_account = None
            asyncio.create_task(bot_state._start_next_in_queue())

        # Cancel worker
        if uid in bot_state.account_workers:
            try:
                bot_state.account_workers[uid].cancel()
            except Exception:
                pass
            del bot_state.account_workers[uid]

        bot_state.log(f"🗑️ Account {uid} permanently removed (files + memory).", "warning", uid)
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


async def handle_pause_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        paused = bool(data.get("paused", True))
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        ok = bot_state.set_paused(uid, paused)
        if not ok:
            return web.json_response({"status": "error", "error": "Account not found"})

        if not paused and bot_state.active_account is None and bot_state._meets_min_level(uid):
            bot_state.active_account = uid
            bot_state.dequeue(uid)

        if paused and bot_state.active_account == uid:
            bot_state.active_account = None
            asyncio.create_task(bot_state._start_next_in_queue())

        return web.json_response({"status": "ok", "paused": bot_state.is_paused(uid)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_queue_add(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        if uid not in bot_state.accounts:
            return web.json_response({"status": "error", "error": "Account not registered"})
        ok = bot_state.enqueue(uid)
        return web.json_response({"status": "ok", "in_queue": uid in bot_state.queue, "activated": ok})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/pause", handle_pause_account)
    app.router.add_post("/api/account/queue", handle_queue_add)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")