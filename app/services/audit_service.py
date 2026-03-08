from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AuditLog


def _get_client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # X-Forwarded-For can be a comma-separated list. The left-most is the original client.
        return xff.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


async def log_audit_event(
    *,
    db: AsyncSession,
    action: str,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=_get_client_ip(request),
    )
    db.add(entry)
    # Let the caller control transaction boundaries; flush makes `entry.id` available if needed.
    await db.flush()
    return entry

