import uuid
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from app.config import settings

# Argon2id with sensible defaults (time_cost=3, memory_cost=65536, parallelism=4)
_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a plaintext password with Argon2id. Never log the return value."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the Argon2id hash, False otherwise."""
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    """Create a signed HS256 JWT for the given user_id."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> uuid.UUID:
    """
    Decode and validate a JWT. Returns the user_id (UUID).
    Raises JWTError on invalid/expired tokens — callers should convert to 401.
    """
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    sub: str | None = payload.get("sub")
    if sub is None:
        raise JWTError("Token missing 'sub' claim")
    return uuid.UUID(sub)
