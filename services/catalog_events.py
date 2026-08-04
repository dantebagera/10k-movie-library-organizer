"""Bounded post-commit catalog event broker."""

import collections
import json
import queue
import threading
import time
from datetime import datetime, timezone


class CatalogEventBroker:
    RING_CAPACITY = 256
    CLIENT_CAPACITY = 32
    HEARTBEAT_SECONDS = 15
    _SENTINEL = object()

    def __init__(self):
        self._lock = threading.RLock()
        self._events = collections.deque(maxlen=self.RING_CAPACITY)
        self._clients = set()
        self._closed = False
        self._last_error = ""

    @staticmethod
    def _sync(generation):
        return {"type": "catalog-sync", "generation": int(generation or 0)}

    def publish(self, generation, *, reason, movie_keys=(), changed_count=0, correlation_id=""):
        keys = list(dict.fromkeys(str(key) for key in movie_keys if key))
        event = {
            "type": "catalog-ready", "generation": int(generation),
            "reason": str(reason or "recovery"), "movie_keys": keys[:100],
            "changed_count": int(changed_count), "truncated": len(keys) > 100,
            "correlation_id": str(correlation_id or ""),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if self._closed:
                self._last_error = "broker_closed"
                return False
            if self._events and event["generation"] <= self._events[-1]["generation"]:
                return False
            self._events.append(event)
            for client in tuple(self._clients):
                try:
                    client.put_nowait(event)
                except queue.Full:
                    while True:
                        try: client.get_nowait()
                        except queue.Empty: break
                    client.put_nowait(self._sync(event["generation"]))
            return True

    def subscribe(self, last_event_id=None, current_generation=0):
        client = queue.Queue(maxsize=self.CLIENT_CAPACITY)
        with self._lock:
            if self._closed:
                client.put_nowait(self._SENTINEL)
                return client
            try: last_generation = int(last_event_id) if last_event_id not in (None, "") else None
            except (TypeError, ValueError): last_generation = None
            retained = list(self._events)
            if last_generation is None:
                client.put_nowait(self._sync(current_generation))
            elif retained and last_generation >= retained[0]["generation"] - 1:
                for event in retained:
                    if event["generation"] > last_generation: client.put_nowait(event)
            elif last_generation != int(current_generation or 0):
                client.put_nowait(self._sync(current_generation))
            self._clients.add(client)
        return client

    def unsubscribe(self, client):
        with self._lock: self._clients.discard(client)

    @staticmethod
    def encode(event):
        event_type = event.get("type")
        event_id = f"id: {event['generation']}\n" if event_type == "catalog-ready" else ""
        return f"{event_id}event: {event_type}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

    def stream(self, last_event_id=None, current_generation=0):
        client = self.subscribe(last_event_id, current_generation)
        try:
            yield "retry: 2000\n\n"
            while True:
                try: event = client.get(timeout=self.HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                if event is self._SENTINEL: return
                yield self.encode(event)
        finally:
            self.unsubscribe(client)

    def status(self):
        with self._lock:
            return {"retained": len(self._events), "ring_capacity": self.RING_CAPACITY,
                    "clients": len(self._clients), "client_capacity": self.CLIENT_CAPACITY,
                    "closed": self._closed, "last_error": self._last_error}

    def shutdown(self):
        with self._lock:
            self._closed = True
            for client in tuple(self._clients):
                while True:
                    try: client.get_nowait()
                    except queue.Empty: break
                client.put_nowait(self._SENTINEL)
            self._clients.clear()
