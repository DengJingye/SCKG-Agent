from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.settings import PROJECT_ROOT


DEFAULT_STORE_DIR = PROJECT_ROOT / ".sckg_user"
DEFAULT_STORE_PATH = DEFAULT_STORE_DIR / "user_store.sqlite3"
KDF_ITERATIONS = 200_000


class ApiConfigError(RuntimeError):
    """Raised when a saved API configuration cannot be decrypted."""


def init_store(db_path: Path = DEFAULT_STORE_PATH) -> Path:
    """Create the local user store if needed and return its path."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_history (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_conversation_session_time
            ON conversation_history(session_id, created_at);

            CREATE TABLE IF NOT EXISTS project_memory (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS working_context (
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(session_id, key)
            );

            CREATE TABLE IF NOT EXISTS api_configs (
                provider TEXT PRIMARY KEY,
                api_base TEXT NOT NULL,
                model_name TEXT NOT NULL,
                salt_b64 TEXT NOT NULL,
                nonce_b64 TEXT NOT NULL,
                ciphertext_b64 TEXT NOT NULL,
                digest_b64 TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        _ensure_column(conn, "sessions", "pinned", "INTEGER NOT NULL DEFAULT 0")
    return db_path


def create_session(title: str = "New research chat", db_path: Path = DEFAULT_STORE_PATH) -> str:
    init_store(db_path)
    session_id = secrets.token_hex(12)
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions(session_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, title, now, now),
        )
    return session_id


def list_sessions(db_path: Path = DEFAULT_STORE_PATH, limit: int = 30) -> List[Dict[str, Any]]:
    init_store(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT session_id, title, pinned, created_at, updated_at
            FROM sessions
            ORDER BY pinned DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def rename_session(
    session_id: str,
    title: str,
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    init_store(db_path)
    clean_title = _compact_title(title)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (clean_title, time.time(), session_id),
        )


def delete_session(session_id: str, db_path: Path = DEFAULT_STORE_PATH) -> None:
    init_store(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM conversation_history WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM working_context WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def set_session_pinned(
    session_id: str,
    pinned: bool,
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    init_store(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET pinned = ?, updated_at = ? WHERE session_id = ?",
            (1 if pinned else 0, time.time(), session_id),
        )


def save_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    init_store(db_path)
    _ensure_session(session_id, db_path)
    now = time.time()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversation_history(session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, metadata_json, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        if role == "user":
            current = conn.execute(
                "SELECT title FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if current and current["title"] == "New research chat":
                conn.execute(
                    "UPDATE sessions SET title = ? WHERE session_id = ?",
                    (_compact_title(content), session_id),
                )


def load_conversation(
    session_id: str,
    limit: int = 50,
    db_path: Path = DEFAULT_STORE_PATH,
) -> List[Dict[str, Any]]:
    init_store(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT role, content, metadata_json, created_at
            FROM conversation_history
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    messages = []
    for row in reversed(rows):
        metadata = _load_json(row["metadata_json"], {})
        messages.append(
            {
                "role": row["role"],
                "content": row["content"],
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )
    return messages


def clear_conversation(session_id: str, db_path: Path = DEFAULT_STORE_PATH) -> None:
    init_store(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM conversation_history WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM working_context WHERE session_id = ?", (session_id,))
        conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            ("New research chat", time.time(), session_id),
        )


def save_project_memory(
    key: str,
    value: Any,
    source: str = "user",
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    init_store(db_path)
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO project_memory(key, value_json, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), source, now, now),
        )


def load_project_memory(db_path: Path = DEFAULT_STORE_PATH) -> Dict[str, Any]:
    init_store(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value_json FROM project_memory ORDER BY key"
        ).fetchall()
    return {row["key"]: _load_json(row["value_json"], row["value_json"]) for row in rows}


def save_working_context(
    session_id: str,
    key: str,
    value: Any,
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    init_store(db_path)
    _ensure_session(session_id, db_path)
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO working_context(session_id, key, value_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (session_id, key, json.dumps(value, ensure_ascii=False), now, now),
        )


def load_working_context(
    session_id: str,
    db_path: Path = DEFAULT_STORE_PATH,
) -> Dict[str, Any]:
    init_store(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT key, value_json
            FROM working_context
            WHERE session_id = ?
            ORDER BY updated_at DESC
            """,
            (session_id,),
        ).fetchall()
    return {row["key"]: _load_json(row["value_json"], row["value_json"]) for row in rows}


def save_encrypted_api_config(
    provider: str,
    api_base: str,
    model_name: str,
    api_key: str,
    passphrase: str,
    db_path: Path = DEFAULT_STORE_PATH,
) -> None:
    """Save an authenticated encrypted API key for local demo use.

    This avoids plaintext storage without adding heavy dependencies. It should
    be replaced by a standard AEAD backend if the demo becomes a hosted product.
    """

    if not passphrase:
        raise ValueError("passphrase is required")
    if not api_key:
        raise ValueError("api_key is required")
    init_store(db_path)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(passphrase, salt)
    plaintext = api_key.encode("utf-8")
    ciphertext = _xor_stream(plaintext, key, nonce)
    digest = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO api_configs(
                provider, api_base, model_name, salt_b64, nonce_b64,
                ciphertext_b64, digest_b64, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                api_base = excluded.api_base,
                model_name = excluded.model_name,
                salt_b64 = excluded.salt_b64,
                nonce_b64 = excluded.nonce_b64,
                ciphertext_b64 = excluded.ciphertext_b64,
                digest_b64 = excluded.digest_b64,
                updated_at = excluded.updated_at
            """,
            (
                provider,
                api_base,
                model_name,
                _b64(salt),
                _b64(nonce),
                _b64(ciphertext),
                _b64(digest),
                time.time(),
            ),
        )


def load_api_config(
    passphrase: str,
    provider: str = "openai_compatible",
    db_path: Path = DEFAULT_STORE_PATH,
) -> Dict[str, str]:
    if not passphrase:
        raise ApiConfigError("passphrase is required")
    init_store(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT provider, api_base, model_name, salt_b64, nonce_b64,
                   ciphertext_b64, digest_b64
            FROM api_configs
            WHERE provider = ?
            """,
            (provider,),
        ).fetchone()
    if not row:
        raise ApiConfigError("no API config saved")
    salt = _unb64(row["salt_b64"])
    nonce = _unb64(row["nonce_b64"])
    ciphertext = _unb64(row["ciphertext_b64"])
    expected_digest = _unb64(row["digest_b64"])
    key = _derive_key(passphrase, salt)
    actual_digest = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_digest, actual_digest):
        raise ApiConfigError("invalid passphrase or corrupted API config")
    api_key = _xor_stream(ciphertext, key, nonce).decode("utf-8")
    return {
        "provider": row["provider"],
        "api_base": row["api_base"],
        "api_key": api_key,
        "model_name": row["model_name"],
    }


def has_saved_api_config(
    provider: str = "openai_compatible",
    db_path: Path = DEFAULT_STORE_PATH,
) -> bool:
    init_store(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM api_configs WHERE provider = ?",
            (provider,),
        ).fetchone()
    return bool(row)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_session(session_id: str, db_path: Path) -> None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row:
            return
        now = time.time()
        conn.execute(
            """
            INSERT INTO sessions(session_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, "New research chat", now, now),
        )


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        KDF_ITERATIONS,
        dklen=32,
    )


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hmac.new(
            key,
            nonce + counter.to_bytes(8, "big"),
            hashlib.sha256,
        ).digest()
        output.extend(block)
        counter += 1
    return bytes(byte ^ mask for byte, mask in zip(data, output))


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _compact_title(value: str, limit: int = 54) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        return "New research chat"
    if len(title) <= limit:
        return title
    return title[: limit - 3].rstrip() + "..."
