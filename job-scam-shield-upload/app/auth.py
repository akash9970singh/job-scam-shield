"""Placement-officer accounts: password hashing, login sessions and simple rate limiting.

Passwords are hashed with scrypt. Session tokens are random and only their SHA-256 hash is
stored, so a leaked database doesn't leak working tokens.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import db

SESSION_HOURS = 12
MIN_PASSWORD_LENGTH = 10
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


@dataclass
class User:
    id: int
    name: str
    email: str
    role: str  # "officer" or "admin"
    college_id: int | None
    college_name: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT_PARAMS)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **SCRYPT_PARAMS)
    return hmac.compare_digest(digest.hex(), digest_hex)


# Spent on unknown emails too, so response time doesn't reveal which emails have accounts.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(email: str, password: str) -> tuple[str, User] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if not row:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), row["id"], expires.isoformat()),
        )
        user_id = row["id"]
    return token, get_user(user_id)


def logout(token: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def get_user(user_id: int) -> User:
    with db.connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.name, u.email, u.role, u.college_id, c.name AS college_name
               FROM users u LEFT JOIN colleges c ON c.id = u.college_id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
    return User(**dict(row))


def user_for_token(token: str) -> User | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (_token_hash(token), db.now()),
        ).fetchone()
    return get_user(row["user_id"]) if row else None


bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    """FastAPI dependency: the logged-in officer, or 401."""
    user = user_for_token(credentials.credentials) if credentials else None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


class RateLimiter:
    """Allow `limit` calls per `window` seconds per client IP. In-memory: one server process."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        cutoff = time.monotonic() - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                raise HTTPException(status_code=429, detail="Too many requests. Please wait and try again.")
            hits.append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=10, window=15 * 60)
report_limiter = RateLimiter(limit=20, window=60 * 60)
