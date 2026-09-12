"""Общие зависимости HTTP-слоя."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from orbitlink.storage.models import Variant
from orbitlink.storage.repository import get_variant


def require_variant(variant_id: str, session: Session) -> Variant:
    """Возвращает вариант по идентификатору или бросает 404, если он не найден."""
    variant = get_variant(session, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Вариант не найден")
    return variant
