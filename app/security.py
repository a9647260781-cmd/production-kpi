from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.errors import APIError
from app.models import AuthSession, User, UserRole


CAPABILITIES_BY_ROLE: dict[str, set[str]] = {
    "WORKER": {"scan", "read_entities"},
    "FOREMAN": {
        "scan", "read_entities", "manage_genealogy", "manage_assignments",
        "manage_time_entries", "manage_rework", "view_reports", "resolve_pending",
    },
    "QC": {"scan", "read_entities", "quality_decide", "manage_rework", "view_reports"},
    "AUDITOR": {"read_entities", "quality_audit", "view_reports", "view_audit"},
    "PLANNER": {"manage_assignments", "manage_time_entries", "manage_plans", "view_reports"},
    "TECHNOLOGIST": {"manage_standards", "manage_plans", "read_entities", "view_reports"},
    "SUPERVISOR": {"read_entities", "view_reports", "approve_shift", "view_audit"},
    "ADMIN": {
        "scan", "read_entities", "manage_genealogy", "manage_assignments",
        "manage_time_entries", "quality_decide", "quality_audit", "manage_rework",
        "manage_plans", "manage_standards", "view_reports", "approve_shift",
        "view_audit", "resolve_pending", "admin",
    },
}

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(db: Session, user: User) -> tuple[AuthSession, str]:
    settings = get_settings()
    raw_token = token_urlsafe(32)
    csrf = token_urlsafe(24)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_token=csrf,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours),
    )
    db.add(auth_session)
    db.flush()
    return auth_session, raw_token


@dataclass(frozen=True)
class AuthContext:
    user: User
    auth_session: AuthSession
    role_names: tuple[str, ...]
    row_ids: tuple[str, ...]
    capabilities: tuple[str, ...]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_auth_context(request: Request, db: Session = Depends(get_session)) -> AuthContext:
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise APIError(401, "AUTH_REQUIRED", "Требуется вход в систему")
    auth_session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash(raw_token))
    )
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or _aware(auth_session.expires_at) <= datetime.now(timezone.utc)
    ):
        raise APIError(401, "SESSION_EXPIRED", "Сессия недействительна или истекла")
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise APIError(401, "USER_DISABLED", "Учётная запись недоступна")
    roles = list(db.scalars(select(UserRole).where(UserRole.user_id == user.id)))
    role_names = tuple(sorted({role.role for role in roles}))
    row_ids = tuple(sorted({role.row_id for role in roles if role.row_id is not None}))
    capabilities = tuple(sorted(set().union(*(CAPABILITIES_BY_ROLE.get(role, set()) for role in role_names))))
    return AuthContext(user, auth_session, role_names, row_ids, capabilities)


def require_capability(capability: str):
    def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if capability not in context.capabilities:
            raise APIError(403, "CAPABILITY_REQUIRED", "Недостаточно прав для действия")
        return context
    return dependency


def require_csrf(request: Request, context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    supplied = request.headers.get("X-CSRF-Token")
    if not supplied or supplied != context.auth_session.csrf_token:
        raise APIError(403, "CSRF_INVALID", "CSRF-токен отсутствует или недействителен")
    return context


def require_csrf_capability(capability: str):
    def dependency(
        request: Request,
        context: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        supplied = request.headers.get("X-CSRF-Token")
        if not supplied or supplied != context.auth_session.csrf_token:
            raise APIError(403, "CSRF_INVALID", "CSRF-токен отсутствует или недействителен")
        if capability not in context.capabilities:
            raise APIError(403, "CAPABILITY_REQUIRED", "Недостаточно прав для действия")
        return context
    return dependency

