"""Расчётное ядро: геометрия, маршрутизация, показатели.

Ядро не зависит от веб-слоя и работает с обычными словарями сценария
схемы cosmo-A-1.0, поэтому его можно запускать из командной строки,
из тестов и из API одинаково.

Реэкспорт намеренно ограничен модулями, которые уже существуют:
остальные подключаются по мере готовности, чтобы импорт пакета не падал
на недописанных частях.
"""

from orbitlink.core.geometry import ConstellationModel, Snapshot, ground_position
from orbitlink.core.scenario import (
    RESULT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ScenarioError,
    ValidationReport,
    load_scenario,
    normalize_scenario,
    validate_scenario,
)
from orbitlink.core.simulate import GeometryCache, RouteRecord, RunResult, simulate

__all__ = [
    "ConstellationModel",
    "Snapshot",
    "ground_position",
    "RESULT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "ScenarioError",
    "ValidationReport",
    "load_scenario",
    "normalize_scenario",
    "validate_scenario",
    "GeometryCache",
    "RouteRecord",
    "RunResult",
    "simulate",
]
