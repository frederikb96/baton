"""SQLite store on the data volume: settings, watch keys, UI sessions, Spotify login."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watch_keys (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, hint TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL, last_used_at REAL, revoked_at REAL,
    scope TEXT NOT NULL DEFAULT 'watch'
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY, verifier TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS spotify_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1), refresh_token TEXT NOT NULL, access_token TEXT,
    access_expires_at REAL, scope TEXT, authorized_at REAL NOT NULL, invalid_reason TEXT
);
"""

SETTINGS_KEY = "settings"
UI_KEY_FINGERPRINT = "ui_key_fingerprint"
KEY_PREFIX = "bk_"
WATCH_SCOPE = "watch"
AGENT_SCOPE = "agent"
KEY_SCOPES = (WATCH_SCOPE, AGENT_SCOPE)
USED_TOUCH_SECONDS = 60


def hash_secret(value: str) -> str:
    """Hex SHA-256 of a high-entropy random secret (keys, session tokens)."""
    return hashlib.sha256(value.encode()).hexdigest()


def key_fingerprint(ui_key: str | None) -> str:
    """Salted, slow hash of the UI key, so the stored value does not reveal a human-chosen key."""
    salt = secrets.token_bytes(16)
    return salt.hex() + "$" + _scrypt(ui_key, salt)


def key_fingerprint_matches(ui_key: str | None, stored: str) -> bool:
    """Whether ``stored`` is the fingerprint of ``ui_key``."""
    salt, _, digest = stored.partition("$")
    return hmac.compare_digest(_scrypt(ui_key, bytes.fromhex(salt)), digest)


def _scrypt(ui_key: str | None, salt: bytes) -> str:
    return hashlib.scrypt((ui_key or "").encode(), salt=salt, n=2**14, r=8, p=1).hex()


@dataclass(frozen=True)
class Ref:
    """A Spotify object picked by the user, stored with its display name."""

    id: str
    name: str


@dataclass(frozen=True)
class UserSettings:
    """Runtime settings changed through the API and the web page."""

    target_playlist: Ref | None = None
    default_device: Ref | None = None
    market: str | None = None
    saved_playlists: tuple[Ref, ...] = ()

    def to_json(self) -> dict[str, object]:
        """Plain dict for the API."""
        return asdict(self)


@dataclass(frozen=True)
class WatchKey:
    """Metadata of a watch key; the key itself is never stored."""

    id: str
    name: str
    hint: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None
    scope: str = WATCH_SCOPE


@dataclass(frozen=True)
class SpotifyAuthRecord:
    """The stored Spotify login."""

    refresh_token: str
    access_token: str | None
    access_expires_at: float | None
    scope: str | None
    authorized_at: float
    invalid_reason: str | None = None


class Store:
    """Thread-safe SQLite access; the file is created with mode 0600."""

    def __init__(self, directory: Path, now: Callable[[], float]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "baton.db"
        self._now = now
        self._lock = threading.RLock()
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(watch_keys)")}
        if "scope" not in columns:
            self._db.execute(
                f"ALTER TABLE watch_keys ADD COLUMN scope TEXT NOT NULL DEFAULT '{WATCH_SCOPE}'"
            )

    def close(self) -> None:
        """Close the database."""
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # settings

    def get_settings(self) -> UserSettings:
        """Return the stored settings, defaults when none were saved."""
        rows = self._exec("SELECT value FROM kv WHERE key = ?", (SETTINGS_KEY,))
        if not rows:
            return UserSettings()
        data = json.loads(rows[0]["value"])

        def ref(name: str) -> Ref | None:
            item = data.get(name)
            return Ref(item["id"], item["name"]) if item else None

        saved = tuple(Ref(item["id"], item["name"]) for item in data.get("saved_playlists") or [])
        return UserSettings(
            ref("target_playlist"), ref("default_device"), data.get("market"), saved
        )

    def save_settings(self, settings: UserSettings) -> None:
        """Persist the settings."""
        self._exec(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, json.dumps(settings.to_json())),
        )

    # watch keys

    def create_watch_key(self, name: str, scope: str = WATCH_SCOPE) -> tuple[WatchKey, str]:
        """Create a key; the plain value is returned once and only its hash is stored."""
        if scope not in KEY_SCOPES:
            raise ValueError(f"unknown key scope {scope!r}")
        plain = KEY_PREFIX + secrets.token_urlsafe(32)
        key_id = secrets.token_hex(4)
        now = self._now()
        self._exec(
            "INSERT INTO watch_keys (id, name, hint, key_hash, created_at, scope) "
            "VALUES (?,?,?,?,?,?)",
            (key_id, name, plain[: len(KEY_PREFIX) + 4], hash_secret(plain), now, scope),
        )
        hint = plain[: len(KEY_PREFIX) + 4]
        return WatchKey(key_id, name, hint, now, None, None, scope), plain

    def verify_watch_key(self, plain: str) -> str | None:
        """Scope of an existing, not revoked key (None for any other); records the use."""
        digest = hash_secret(plain)
        rows = self._exec(
            "SELECT id, key_hash, last_used_at, scope FROM watch_keys "
            "WHERE key_hash = ? AND revoked_at IS NULL",
            (digest,),
        )
        if not rows or not hmac.compare_digest(rows[0]["key_hash"], digest):
            return None
        now = self._now()
        last = rows[0]["last_used_at"]
        if last is None or now - last > USED_TOUCH_SECONDS:
            self._exec("UPDATE watch_keys SET last_used_at = ? WHERE id = ?", (now, rows[0]["id"]))
        return str(rows[0]["scope"])

    def list_watch_keys(self) -> list[WatchKey]:
        """All keys, newest first."""
        rows = self._exec("SELECT * FROM watch_keys ORDER BY created_at DESC")
        return [
            WatchKey(
                r["id"],
                r["name"],
                r["hint"],
                r["created_at"],
                r["last_used_at"],
                r["revoked_at"],
                r["scope"],
            )
            for r in rows
        ]

    def set_watch_key_scope(self, key_id: str, scope: str) -> bool:
        """Change the scope of an active key; False when it does not exist or is revoked."""
        if scope not in KEY_SCOPES:
            raise ValueError(f"unknown key scope {scope!r}")
        with self._lock:
            cur = self._db.execute(
                "UPDATE watch_keys SET scope = ? WHERE id = ? AND revoked_at IS NULL",
                (scope, key_id),
            )
            return cur.rowcount > 0

    def revoke_watch_key(self, key_id: str) -> bool:
        """Revoke a key; False when it does not exist or is already revoked."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE watch_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (self._now(), key_id),
            )
            return cur.rowcount > 0

    # UI sessions

    def sync_ui_key(self, ui_key: str | None) -> None:
        """Drop every session when the UI key differs from the one the sessions were issued for."""
        with self._lock:
            rows = self._exec("SELECT value FROM kv WHERE key = ?", (UI_KEY_FINGERPRINT,))
            stored = rows[0]["value"] if rows else None
            if stored is not None and key_fingerprint_matches(ui_key, stored):
                return
            self._exec("DELETE FROM sessions")
            self._exec(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (UI_KEY_FINGERPRINT, key_fingerprint(ui_key)),
            )

    def create_session(self, lifetime_seconds: float) -> str:
        """Create a session and return its token."""
        token = secrets.token_urlsafe(32)
        now = self._now()
        self._exec("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self._exec(
            "INSERT INTO sessions (token_hash, created_at, expires_at) VALUES (?,?,?)",
            (hash_secret(token), now, now + lifetime_seconds),
        )
        return token

    def verify_session(self, token: str) -> bool:
        """True for a known, unexpired session token."""
        rows = self._exec(
            "SELECT expires_at FROM sessions WHERE token_hash = ?", (hash_secret(token),)
        )
        return bool(rows) and rows[0]["expires_at"] > self._now()

    def delete_session(self, token: str) -> None:
        """Forget a session."""
        self._exec("DELETE FROM sessions WHERE token_hash = ?", (hash_secret(token),))

    # OAuth state

    def put_oauth_state(self, state: str, verifier: str, ttl_seconds: float) -> None:
        """Remember a pending login."""
        now = self._now()
        self._exec("DELETE FROM oauth_states WHERE expires_at < ?", (now,))
        self._exec(
            "INSERT INTO oauth_states (state, verifier, expires_at) VALUES (?,?,?)",
            (state, verifier, now + ttl_seconds),
        )

    def pop_oauth_state(self, state: str) -> str | None:
        """Return the PKCE verifier of a pending login and delete it (single use)."""
        with self._lock:
            rows = self._exec(
                "SELECT verifier, expires_at FROM oauth_states WHERE state = ?", (state,)
            )
            self._exec("DELETE FROM oauth_states WHERE state = ?", (state,))
        if not rows or rows[0]["expires_at"] < self._now():
            return None
        return str(rows[0]["verifier"])

    # Spotify login

    def get_spotify_auth(self) -> SpotifyAuthRecord | None:
        """The stored login, if any."""
        rows = self._exec("SELECT * FROM spotify_auth WHERE id = 1")
        if not rows:
            return None
        r = rows[0]
        return SpotifyAuthRecord(
            r["refresh_token"],
            r["access_token"],
            r["access_expires_at"],
            r["scope"],
            r["authorized_at"],
            r["invalid_reason"],
        )

    def save_spotify_auth(self, record: SpotifyAuthRecord) -> None:
        """Replace the stored login."""
        self._exec(
            "INSERT INTO spotify_auth (id, refresh_token, access_token, access_expires_at, scope,"
            " authorized_at, invalid_reason) VALUES (1,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET refresh_token=excluded.refresh_token,"
            " access_token=excluded.access_token, access_expires_at=excluded.access_expires_at,"
            " scope=excluded.scope, authorized_at=excluded.authorized_at,"
            " invalid_reason=excluded.invalid_reason",
            (
                record.refresh_token,
                record.access_token,
                record.access_expires_at,
                record.scope,
                record.authorized_at,
                record.invalid_reason,
            ),
        )

    def clear_spotify_auth(self) -> None:
        """Forget the Spotify login."""
        self._exec("DELETE FROM spotify_auth")
