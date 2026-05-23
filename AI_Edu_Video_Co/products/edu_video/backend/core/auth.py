# products/edu_video/backend/core/auth.py
"""
JWT authentication middleware and role-based access control.
Depends on database (User model lookup) but not on cost_tracker.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import get_db

__all__ = [
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "require_role",
    "hash_password",
    "verify_password",
    "InvalidTokenError",
    "ExpiredTokenError",
    "InsufficientPermissionsError",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# --- Custom exceptions ---

class InvalidTokenError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class ExpiredTokenError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )


class InsufficientPermissionsError(HTTPException):
    def __init__(self, required_roles: list[str]) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Required role(s): {required_roles}",
        )


# --- Password utilities ---

def hash_password(plain: str) -> str:
    """Return bcrypt hash of a plaintext password."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return pwd_context.verify(plain, hashed)


# --- Token operations ---

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Encode a JWT access token with optional custom expiry.
    Defaults to ACCESS_TOKEN_EXPIRE_MINUTES from settings.
    """
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    token = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    logger.info("auth.token_created", subject=data.get("sub"))
    return token


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decode and validate a JWT token.
    Returns payload dict on success, None on malformed input.
    Raises ExpiredTokenError if the token has expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except ExpiredSignatureError:
        raise ExpiredTokenError()
    except JWTError:
        return None


# --- FastAPI dependencies ---

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    FastAPI dependency: resolve JWT token → User ORM object.
    Import User model inline to avoid circular imports at module level.
    """
    # Inline import to prevent circular dependency
    from models.user import User  # noqa: PLC0415

    payload = decode_access_token(token)
    if payload is None:
        raise InvalidTokenError()

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise InvalidTokenError()

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("auth.user_not_found", user_id=user_id)
        raise InvalidTokenError()

    logger.info("auth.user_resolved", user_id=user_id, role=user.role)
    return user


def require_role(roles: list[str]):
    """
    Dependency factory: raise 403 if current user's role is not in `roles`.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role(["admin"]))])
    """
    async def role_checker(
        current_user: Annotated[Any, Depends(get_current_user)],
    ) -> Any:
        if current_user.role not in roles:
            logger.warning(
                "auth.insufficient_permissions",
                user_id=str(current_user.id),
                user_role=current_user.role,
                required=roles,
            )
            raise InsufficientPermissionsError(required_roles=roles)
        return current_user

    return role_checker
