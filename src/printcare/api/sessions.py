"""In-memory session store for the HTTP API.

Sessions live only in the server process and expire after a fixed idle time;
multi-turn state is not persisted across restarts. This is documented in
``docs/interfaces.md``.
"""

from __future__ import annotations

import threading
import time

from printcare.assistant.session import Session


class SessionStore:
    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl_seconds = ttl_minutes * 60
        self._entries: dict[str, tuple[Session, float]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            session, last_seen = entry
            if time.monotonic() - last_seen > self._ttl_seconds:
                self._entries.pop(session_id, None)
                return None
            self._entries[session_id] = (session, time.monotonic())
            return session

    def create(self, machine: str) -> Session:
        session = Session.create(machine)
        self.save(session)
        return session

    def save(self, session: Session) -> None:
        with self._lock:
            self._entries[session.session_id] = (session, time.monotonic())

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._entries.pop(session_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._entries)
