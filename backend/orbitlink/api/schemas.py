"""Схемы запросов и ответов HTTP-слоя."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from orbitlink.core.routing import RoutingStrategy


class ScenarioPayload(BaseModel):
    scenario: dict[str, Any]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    scenario: dict[str, Any]


class VariantCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    scenario: dict[str, Any]


class VariantPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    scenario: dict[str, Any] | None = None


class RunRequest(BaseModel):
    strategy: RoutingStrategy = RoutingStrategy.MIN_LATENCY
    hysteresis: float = Field(default=0.3, ge=0.0, le=5.0)
    with_backup: bool = True


class CompareRequest(BaseModel):
    """Запрос сравнения базового варианта и варианта — для фронтенда, сверх плана."""

    base_variant_id: str
    variant_id: str
    strategy: RoutingStrategy = RoutingStrategy.MIN_LATENCY
    hysteresis: float = Field(default=0.3, ge=0.0, le=5.0)
    with_backup: bool = True
