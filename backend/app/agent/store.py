"""SQLite persistence for AI settings, conversations, and opt-in memories."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import decrypt_api_key, encrypt_api_key


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
            CREATE TABLE IF NOT EXISTS ai_provider_settings (
                settings_id TEXT PRIMARY KEY CHECK (settings_id = 'local'),
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

    def get_ai_settings(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM ai_provider_settings WHERE settings_id='local'"
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
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT api_key_ciphertext, api_key_nonce FROM ai_provider_settings WHERE settings_id='local'"
        ).fetchone()
        ciphertext = existing["api_key_ciphertext"] if existing else None
        nonce = existing["api_key_nonce"] if existing else None
        if api_key is not None:
            ciphertext, nonce = encrypt_api_key(api_key)
        self.connection.execute(
            """INSERT INTO ai_provider_settings
               (settings_id, provider, base_url, model, api_key_ciphertext, api_key_nonce, updated_at)
               VALUES ('local', ?, ?, ?, ?, ?, ?)
               ON CONFLICT(settings_id) DO UPDATE SET
                 provider=excluded.provider, base_url=excluded.base_url, model=excluded.model,
                 api_key_ciphertext=excluded.api_key_ciphertext, api_key_nonce=excluded.api_key_nonce,
                 updated_at=excluded.updated_at""",
            (provider, base_url, model, ciphertext, nonce, _timestamp()),
        )
        self.connection.commit()
        return self.get_ai_settings()

    def get_provider_credentials(self) -> dict[str, str] | None:
        row = self.connection.execute(
            "SELECT * FROM ai_provider_settings WHERE settings_id='local'"
        ).fetchone()
        if row is None or row["api_key_ciphertext"] is None:
            return None
        return {
            "provider": row["provider"],
            "base_url": row["base_url"],
            "model": row["model"],
            "api_key": decrypt_api_key(row["api_key_ciphertext"], row["api_key_nonce"]),
        }

    def clear_api_key(self) -> None:
        self.connection.execute(
            """UPDATE ai_provider_settings
               SET api_key_ciphertext=NULL, api_key_nonce=NULL, updated_at=?
               WHERE settings_id='local'""",
            (_timestamp(),),
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