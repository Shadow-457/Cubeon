"""Ephemeral emote relay over the existing authenticated friends socket.

No animation frames, chat history, timers or game/server addresses are stored.
The mod sends a hashed room and UUID. The hub supplies the account's username.
"""
import re
import threading
import time
import uuid

DURATIONS = {"wave": 3.0, "dance": 6.0, "bow": 3.0,
             "salute": 3.0, "shrug": 2.5, "point": 3.0,
             "clap": 4.0, "laugh": 4.0, "sit": 6.0, "celebrate": 4.5}
ROOM_RE = re.compile(r"[0-9a-f]{64}\Z")
NAME_RE = re.compile(r"[A-Za-z0-9_]{3,16}\Z")


class EmoteRelay:
    def __init__(self, client, *, clock=time.monotonic):
        self.client = client
        self.clock = clock
        self.lock = threading.RLock()
        self.room = ""
        self.ready = False
        self.updated = 0.0
        self.last_send = float("-inf")
        self.active = {}

    def context(self, body):
        room = body.get("room", "")
        if not isinstance(room, str) or (room and not ROOM_RE.fullmatch(room)):
            return {"ok": False, "error": "Invalid emote room."}
        with self.lock:
            if room != self.room:
                self.room = room
                self.ready = False
                self.active.clear()
            self.updated = self.clock()
            getattr(self.client, "send_emote_room", lambda _room: False)(room)
        return {"ok": True}

    def connection(self, connected):
        with self.lock:
            self.ready = False
            self.active.clear()
            if connected and self.room and self.clock() - self.updated < 45:
                getattr(self.client, "send_emote_room", lambda _room: False)(self.room)

    def acknowledge(self, payload):
        if not isinstance(payload, dict):
            return
        with self.lock:
            if payload.get("room") == self.room:
                self.ready = bool(payload.get("ready"))

    def receive(self, payload):
        if not isinstance(payload, dict):
            return
        with self.lock:
            if not self.room or payload.get("room") != self.room:
                return
            try:
                entity = str(uuid.UUID(payload.get("uuid", "")))
            except (ValueError, TypeError, AttributeError):
                return
            name = payload.get("username", "")
            emote = payload.get("emote")
            if not isinstance(emote, str):
                return
            serial = payload.get("serial")
            age = payload.get("age", 0)
            if (not isinstance(name, str) or not NAME_RE.fullmatch(name)
                    or not isinstance(serial, int) or isinstance(serial, bool)
                    or not 0 <= serial <= 2_147_483_647
                    or not isinstance(age, (int, float)) or isinstance(age, bool)
                    or not 0 <= age <= 6):
                return
            if emote == "stop":
                self.active.pop(entity, None)
                return
            duration = DURATIONS.get(emote)
            if duration is None or age >= duration:
                return
            if len(self.active) >= 128 and entity not in self.active:
                return
            previous = self.active.get(entity)
            if previous and previous["serial"] == serial and previous["emote"] == emote:
                return
            self.active[entity] = {"uuid": entity, "username": name, "emote": emote,
                                   "serial": serial, "started": self.clock() - age}

    def play(self, body):
        emote = body.get("emote")
        serial = body.get("serial")
        try:
            entity = str(uuid.UUID(body.get("uuid", "")))
        except (ValueError, TypeError, AttributeError):
            return {"ok": False, "error": "Invalid player."}
        if (emote not in (*DURATIONS, "stop") or not isinstance(serial, int)
                or isinstance(serial, bool) or not 0 <= serial <= 2_147_483_647):
            return {"ok": False, "error": "Invalid emote."}
        with self.lock:
            if not self.ready or not getattr(self.client, "is_connected", False) or not self.room:
                return {"ok": False, "error": "Emote sync is unavailable. Your emote is local."}
            now = self.clock()
            if emote != "stop" and now - self.last_send < .75:
                return {"ok": False, "error": "Wait a moment before another emote."}
            if self.client.send_emote(entity, emote, serial):
                self.last_send = now
                return {"ok": True}
        return {"ok": False, "error": "Emote sync disconnected. Your emote is local."}

    def snapshot(self):
        with self.lock:
            now = self.clock()
            self.active = {key: value for key, value in self.active.items()
                           if now - value["started"] < DURATIONS[value["emote"]]}
            return {"room": self.room, "ready": self.ready and getattr(self.client, "is_connected", False) and now - self.updated < 45,
                    "active": [{key: value for key, value in item.items() if key != "started"}
                               | {"age": now - item["started"]} for item in self.active.values()]}
