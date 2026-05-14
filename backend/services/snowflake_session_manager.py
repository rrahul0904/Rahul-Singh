from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional


SNOWFLAKE_MFA_EXPIRED_MESSAGE = "Snowflake MFA session expired. Unlock Snowflake and retry. No data was moved."


class SnowflakeSessionManager:
    """In-memory Snowflake session registry.

    The registry intentionally keeps only safe metadata in public responses.
    The live connector object remains process-local and MFA passcodes are never
    stored in the entry.
    """

    def __init__(self, ttl_minutes: int = 60):
        self.ttl_minutes = max(int(ttl_minutes), 60)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(self, *, user_id: str, connection_id: str, connector: Any, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        now = datetime.utcnow()
        session_id = str(uuid.uuid4())
        entry = {
            "session_id": session_id,
            "user_id": str(user_id),
            "connection_id": str(connection_id),
            "connector": connector,
            "lock": threading.RLock(),
            "created_at": now,
            "expires_at": now + timedelta(minutes=self.ttl_minutes),
            "last_used_at": now,
            "status": "ACTIVE",
            "metadata": self._safe_metadata(metadata or {}),
        }
        with self._lock:
            self._cleanup_locked()
            self._sessions[session_id] = entry
        return self.public(entry)

    def get(self, session_id: str, *, user_id: str, connection_id: Optional[str] = None, touch: bool = True) -> Optional[dict[str, Any]]:
        with self._lock:
            self._cleanup_locked()
            entry = self._sessions.get(session_id)
            if not entry or entry["user_id"] != str(user_id):
                return None
            if connection_id and entry["connection_id"] != str(connection_id):
                return None
            if touch:
                now = datetime.utcnow()
                entry["last_used_at"] = now
                entry["expires_at"] = now + timedelta(minutes=self.ttl_minutes)
            return entry

    def get_active_session(self, *, user_id: str, connection_id: str, touch: bool = True) -> Optional[dict[str, Any]]:
        """Return the active session for this user/connection pair.

        Accessing an active session refreshes its rolling TTL by default. This
        lets SQL Workspace, readiness checks, and approved job execution reuse a
        single MFA unlock without storing the MFA passcode anywhere.
        """
        with self._lock:
            self._cleanup_locked()
            for entry in self._sessions.values():
                if (
                    entry["user_id"] == str(user_id)
                    and entry["connection_id"] == str(connection_id)
                    and entry["status"] == "ACTIVE"
                ):
                    if touch:
                        now = datetime.utcnow()
                        entry["last_used_at"] = now
                        entry["expires_at"] = now + timedelta(minutes=self.ttl_minutes)
                    return entry
            return None

    def active_for_user(self, *, user_id: str, connection_id: str) -> Optional[dict[str, Any]]:
        return self.get_active_session(user_id=user_id, connection_id=connection_id)

    def lock(self, session_id: str, *, user_id: Optional[str] = None) -> bool:
        with self._lock:
            entry = self._sessions.get(session_id)
            if not entry:
                return True
            if user_id is not None and entry["user_id"] != str(user_id):
                return False
            entry = self._sessions.pop(session_id)
            entry["status"] = "LOCKED"
        self._disconnect(entry)
        return True

    def close(self, session_id: str, *, user_id: Optional[str] = None) -> bool:
        return self.lock(session_id, user_id=user_id)

    def expire(self, session_id: str, *, user_id: Optional[str] = None) -> bool:
        with self._lock:
            entry = self._sessions.get(session_id)
            if not entry:
                return True
            if user_id is not None and entry["user_id"] != str(user_id):
                return False
            entry["expires_at"] = datetime.utcnow() - timedelta(seconds=1)
            self._cleanup_locked()
        return True

    def heartbeat(self, session_id: str, *, user_id: str, connection_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        entry = self.get(session_id, user_id=user_id, connection_id=connection_id, touch=True)
        return self.public(entry) if entry else None

    def status_for_user(self, *, user_id: str, connection_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_locked()
            rows = [
                self.public(entry)
                for entry in self._sessions.values()
                if entry["user_id"] == str(user_id)
                and (connection_id is None or entry["connection_id"] == str(connection_id))
            ]
        return rows

    def public(self, entry: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not entry:
            return {}
        return {
            "session_id": entry["session_id"],
            "user_id": entry["user_id"],
            "connection_id": entry["connection_id"],
            "created_at": entry["created_at"].isoformat() + "Z",
            "expires_at": entry["expires_at"].isoformat() + "Z",
            "last_used_at": entry["last_used_at"].isoformat() + "Z",
            "status": entry["status"],
            "ttl_minutes": self.ttl_minutes,
            "metadata": entry.get("metadata") or {},
        }

    def _cleanup_locked(self) -> None:
        now = datetime.utcnow()
        expired = [sid for sid, entry in self._sessions.items() if entry["expires_at"] <= now]
        for sid in expired:
            entry = self._sessions.pop(sid)
            entry["status"] = "EXPIRED"
            self._disconnect(entry)

    def _disconnect(self, entry: dict[str, Any]) -> None:
        try:
            entry["connector"].disconnect()
        except Exception:
            pass

    def _safe_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        blocked = ("password", "passcode", "mfa", "secret", "token", "private_key")
        return {
            key: value
            for key, value in metadata.items()
            if not any(part in str(key).lower() for part in blocked)
        }


snowflake_session_manager = SnowflakeSessionManager()
