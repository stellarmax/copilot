"""SQLite persistence for AI settings, conversations, and opt-in memories."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .security import decrypt_api_key, encrypt_api_key

SESSION_DAYS = 14
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), dklen=32,
                                   n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(candidate.hex(), digest)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class AgentStore:
    def __init__(self, db_path: str | Path) -> None:
        self.connection = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            -- The single shared key of the pre-login version is dropped on upgrade: every user
            -- now stores and pays for their own key.
            DROP TABLE IF EXISTS ai_provider_settings;
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS user_ai_settings (
                owner_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key_ciphertext BLOB,
                api_key_nonce BLOB,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_preferences (
                owner_id TEXT PRIMARY KEY,
                memory_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_conversations (
                conversation_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES chat_conversations(conversation_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                ON chat_messages(conversation_id, message_id);
            CREATE TABLE IF NOT EXISTS agent_memories (
                memory_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_memories_owner
                ON agent_memories(owner_id, created_at);
            """
        )
        self.connection.commit()

    # ------------------------------------------------------------------ users and sessions
    def create_user(self, email: str, password: str, display_name: str) -> dict[str, str]:
        user = {"user_id": str(uuid.uuid4()), "email": email, "display_name": display_name}
        self.connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (user["user_id"], email, display_name, hash_password(password), _timestamp()),
        )
        self.connection.commit()
        return user

    def update_display_name(self, user_id: str, display_name: str) -> None:
        self.connection.execute("UPDATE users SET display_name=? WHERE user_id=?", (display_name, user_id))
        self.connection.commit()

    def authenticate(self, email: str, password: str) -> dict[str, str] | None:
        row = self.connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            check_password(password, hash_password("timing-equaliser"))  # same cost for unknown e-mails
            return None
        if not check_password(password, row["password_hash"]):
            return None
        return {"user_id": row["user_id"], "email": row["email"], "display_name": row["display_name"]}

    def find_user_by_email(self, email: str) -> dict[str, str] | None:
        row = self.connection.execute("SELECT user_id, email, display_name FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        self.connection.execute(
            "INSERT INTO user_sessions VALUES (?, ?, ?, ?)",
            (self._token_hash(token), user_id, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
        )
        self.connection.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now.isoformat(),))
        self.connection.commit()
        return token

    def session_user(self, token: str | None) -> dict[str, str] | None:
        if not token:
            return None
        row = self.connection.execute(
            """SELECT u.user_id, u.email, u.display_name, s.expires_at FROM user_sessions s
               JOIN users u USING (user_id) WHERE s.token_hash=?""",
            (self._token_hash(token),),
        ).fetchone()
        if row is None or row["expires_at"] < datetime.now(timezone.utc).isoformat():
            return None
        return {"user_id": row["user_id"], "email": row["email"], "display_name": row["display_name"]}

    def delete_session(self, token: str | None) -> None:
        if token:
            self.connection.execute("DELETE FROM user_sessions WHERE token_hash=?", (self._token_hash(token),))
            self.connection.commit()

    # ------------------------------------------------------------------ per-user AI settings
    def get_ai_settings(self, owner_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM user_ai_settings WHERE owner_id=?", (owner_id,)
        ).fetchone()
        if row is None:
            return {
                "provider": "chatgpt",
                "model": "gpt-4.1-mini",
                "has_api_key": False,
                "encryption_ready": bool(os.getenv("AI_CREDENTIALS_ENCRYPTION_KEY")),
                "updated_at": None,
            }
        return {
            "provider": row["provider"],
            "model": row["model"],
            "has_api_key": row["api_key_ciphertext"] is not None,
            "encryption_ready": bool(os.getenv("AI_CREDENTIALS_ENCRYPTION_KEY")),
            "updated_at": row["updated_at"],
        }

    def save_ai_settings(
        self,
        owner_id: str,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT api_key_ciphertext, api_key_nonce FROM user_ai_settings WHERE owner_id=?", (owner_id,)
        ).fetchone()
        ciphertext = existing["api_key_ciphertext"] if existing else None
        nonce = existing["api_key_nonce"] if existing else None
        if api_key is not None:
            ciphertext, nonce = encrypt_api_key(api_key)
        self.connection.execute(
            """INSERT INTO user_ai_settings
               (owner_id, provider, base_url, model, api_key_ciphertext, api_key_nonce, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(owner_id) DO UPDATE SET
                 provider=excluded.provider, base_url=excluded.base_url, model=excluded.model,
                 api_key_ciphertext=excluded.api_key_ciphertext, api_key_nonce=excluded.api_key_nonce,
                 updated_at=excluded.updated_at""",
            (owner_id, provider, base_url, model, ciphertext, nonce, _timestamp()),
        )
        self.connection.commit()
        return self.get_ai_settings(owner_id)

    def get_provider_credentials(self, owner_id: str) -> dict[str, str] | None:
        row = self.connection.execute(
            "SELECT * FROM user_ai_settings WHERE owner_id=?", (owner_id,)
        ).fetchone()
        if row is None or row["api_key_ciphertext"] is None:
            return None
        return {
            "provider": row["provider"],
            "base_url": row["base_url"],
            "model": row["model"],
            "api_key": decrypt_api_key(row["api_key_ciphertext"], row["api_key_nonce"]),
        }

    def key_owner(self, email: str | None = None) -> str:
        """Owner whose saved key a command-line script should use: by e-mail, or the only user with a key."""
        if email:
            user = self.find_user_by_email(email.strip().lower())
            if user is None:
                raise LookupError(f"No account for {email}.")
            return user["user_id"]
        owners = [row[0] for row in self.connection.execute(
            "SELECT owner_id FROM user_ai_settings WHERE api_key_ciphertext IS NOT NULL")]
        if len(owners) != 1:
            raise LookupError("Pass --email: " + ("no account has saved an AI key." if not owners
                                                  else "several accounts have saved AI keys."))
        return owners[0]

    def clear_api_key(self, owner_id: str) -> None:
        self.connection.execute(
            """UPDATE user_ai_settings
               SET api_key_ciphertext=NULL, api_key_nonce=NULL, updated_at=?
               WHERE owner_id=?""",
            (_timestamp(), owner_id),
        )
        self.connection.commit()

    def create_conversation(self, title: str, owner_id: str = "local") -> dict[str, str]:
        now = _timestamp()
        conversation_id = str(uuid.uuid4())
        self.connection.execute(
            "INSERT INTO chat_conversations VALUES (?, ?, ?, ?, ?)",
            (conversation_id, owner_id, title[:100] or "New conversation", now, now),
        )
        self.connection.commit()
        return {
            "conversation_id": conversation_id,
            "title": title[:100] or "New conversation",
            "created_at": now,
            "updated_at": now,
        }

    def list_conversations(self, owner_id: str = "local") -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT c.conversation_id, c.title, c.created_at, c.updated_at,
                      COUNT(m.message_id) AS message_count
               FROM chat_conversations c LEFT JOIN chat_messages m USING (conversation_id)
               WHERE c.owner_id=? GROUP BY c.conversation_id ORDER BY c.updated_at DESC""",
            (owner_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str, owner_id: str = "local") -> dict[str, Any] | None:
        conversation = self.connection.execute(
            "SELECT * FROM chat_conversations WHERE conversation_id=? AND owner_id=?",
            (conversation_id, owner_id),
        ).fetchone()
        if conversation is None:
            return None
        messages = self.connection.execute(
            "SELECT role, content, metadata_json, created_at FROM chat_messages WHERE conversation_id=? ORDER BY message_id",
            (conversation_id,),
        ).fetchall()
        return {
            "conversation_id": conversation["conversation_id"],
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
            "messages": [
                {
                    "role": message["role"],
                    "content": message["content"],
                    "metadata": json.loads(message["metadata_json"]),
                    "created_at": message["created_at"],
                }
                for message in messages
            ],
        }

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _timestamp()
        with self.connection:
            self.connection.execute(
                "INSERT INTO chat_messages (conversation_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            self.connection.execute(
                "UPDATE chat_conversations SET updated_at=? WHERE conversation_id=?",
                (now, conversation_id),
            )

    def delete_conversation(self, conversation_id: str, owner_id: str = "local") -> bool:
        cursor = self.connection.execute(
            "DELETE FROM chat_conversations WHERE conversation_id=? AND owner_id=?",
            (conversation_id, owner_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def memory_enabled(self, owner_id: str = "local") -> bool:
        row = self.connection.execute(
            "SELECT memory_enabled FROM chat_preferences WHERE owner_id=?", (owner_id,)
        ).fetchone()
        return bool(row["memory_enabled"]) if row else False

    def set_memory_enabled(self, enabled: bool, owner_id: str = "local") -> bool:
        self.connection.execute(
            """INSERT INTO chat_preferences (owner_id, memory_enabled, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(owner_id) DO UPDATE SET memory_enabled=excluded.memory_enabled, updated_at=excluded.updated_at""",
            (owner_id, int(enabled), _timestamp()),
        )
        self.connection.commit()
        return enabled

    def list_memories(self, owner_id: str = "local") -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT memory_id, content, created_at FROM agent_memories WHERE owner_id=? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_memory(self, content: str, owner_id: str = "local") -> dict[str, str]:
        memory = {
            "memory_id": str(uuid.uuid4()),
            "content": content.strip(),
            "created_at": _timestamp(),
        }
        self.connection.execute(
            "INSERT INTO agent_memories VALUES (?, ?, ?, ?)",
            (memory["memory_id"], owner_id, memory["content"], memory["created_at"]),
        )
        self.connection.commit()
        return memory

    def delete_memory(self, memory_id: str, owner_id: str = "local") -> bool:
        cursor = self.connection.execute(
            "DELETE FROM agent_memories WHERE memory_id=? AND owner_id=?",
            (memory_id, owner_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def clear_memories(self, owner_id: str = "local") -> int:
        cursor = self.connection.execute("DELETE FROM agent_memories WHERE owner_id=?", (owner_id,))
        self.connection.commit()
        return cursor.rowcount