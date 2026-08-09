#!/usr/bin/env python3
"""Provision a player-restricted MA token without printing the credential.

Run this inside the Music Assistant server image with its data volume mounted at
/data and the intercom auth volume mounted at /run/intercom-auth.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import timedelta
from pathlib import Path

from music_assistant.helpers.datetime import utc
from music_assistant.helpers.jwt_auth import JWTHelper
from music_assistant_models.auth import User, UserRole


DATABASE = Path("/data/auth.db")
TOKEN_FILE = Path("/run/intercom-auth/music-assistant-token")
TOKEN_NAME = "Intercom Voice PE"
USER_ID = "intercom-voice-pe"
PLAYER_ID = os.environ["MUSIC_ASSISTANT_PLAYER_ID"]


def main() -> None:
    if not DATABASE.is_file():
        raise SystemExit("Music Assistant auth database does not exist")

    now = utc()
    expires_at = now + timedelta(days=365)
    token_id = secrets.token_urlsafe(32)

    with sqlite3.connect(DATABASE, timeout=30) as database:
        database.execute("PRAGMA busy_timeout=30000")
        secret_row = database.execute(
            "SELECT value FROM settings WHERE key = 'jwt_secret'"
        ).fetchone()
        if not secret_row:
            raise SystemExit("Music Assistant JWT secret has not been initialized")

        user = User(
            user_id=USER_ID,
            username=USER_ID,
            role=UserRole.USER,
            enabled=True,
            created_at=now,
            display_name="Intercom Voice PE",
            player_filter=[PLAYER_ID],
        )
        token = JWTHelper(str(secret_row[0])).encode_token(
            user=user,
            token_id=token_id,
            token_name=TOKEN_NAME,
            expires_at=expires_at,
            is_long_lived=True,
        )

        database.execute("DELETE FROM auth_tokens WHERE user_id = ?", (USER_ID,))
        database.execute("DELETE FROM users WHERE user_id = ?", (USER_ID,))
        database.execute(
            """INSERT INTO users
               (user_id, username, role, enabled, created_at, display_name,
                avatar_url, preferences, player_filter, provider_filter)
               VALUES (?, ?, ?, 1, ?, ?, NULL, '{}', ?, '[]')""",
            (
                USER_ID,
                USER_ID,
                UserRole.USER.value,
                now.isoformat(),
                "Intercom Voice PE",
                json.dumps([PLAYER_ID]),
            ),
        )
        database.execute(
            """INSERT INTO auth_tokens
               (token_id, user_id, token_hash, name, created_at, expires_at, is_long_lived)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (
                token_id,
                USER_ID,
                hashlib.sha256(token.encode()).hexdigest(),
                TOKEN_NAME,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        database.commit()

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = TOKEN_FILE.with_suffix(".new")
    temporary.write_text(token)
    os.chown(temporary, 1000, 1000)
    os.chmod(temporary, 0o400)
    temporary.replace(TOKEN_FILE)

    claims = JWTHelper(str(secret_row[0])).decode_token(TOKEN_FILE.read_text())
    if claims.get("sub") != USER_ID or claims.get("jti") != token_id:
        raise SystemExit("provisioned token failed local validation")
    print("provisioned=true player_scope=1 token_exposed=false")


if __name__ == "__main__":
    main()
