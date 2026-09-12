"""Проверка и нормализация входного сценария схемы cosmo-A-1.0.

Правила повторяют «Описание данных» организаторов. Отличие от эталонного
validate() — вместо первой же исключительной ситуации собирается полный
список замечаний с указанием проблемного поля, чтобы интерфейс мог
показать пользователю, что именно нужно исправить.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "cosmo-A-1.0"
RESULT_SCHEMA_VERSION = "cosmo-A-result-1.0"

ENVIRONMENT_KEYS = (
    "altitude_km",
    "inclination_deg",
    "earth_angle0_deg",
    "horizon_s",
    "step_s",
    "min_elevation_deg",
    "isl_range_km",
    "target_availability",
)


@dataclass
class Issue:
    """Одно замечание к входным данным."""

    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message))

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [i.as_dict() for i in self.issues]}


class ScenarioError(ValueError):
    """Сценарий не прошёл проверку."""

    def __init__(self, report: ValidationReport) -> None:
        summary = "; ".join(f"{i.path}: {i.message}" for i in report.issues[:5])
        super().__init__(summary or "Сценарий не прошёл проверку")
        self.report = report


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check_environment(env: Any, report: ValidationReport) -> None:
    if not isinstance(env, dict):
        report.add("environment", "Раздел environment должен быть объектом")
        return

    issues_before = len(report.issues)
    for key in ENVIRONMENT_KEYS:
        if key not in env:
            report.add(f"environment.{key}", "Обязательное поле отсутствует")
        elif not _finite(env[key]):
            report.add(f"environment.{key}", "Значение должно быть конечным числом")

    # Досрочный выход — только если проблема найдена в самом разделе environment
    # (отсутствует или не конечно поле): проверки диапазонов ниже упадут на None.
    # Замечания, добавленные ДО вызова этой функции (schema_version, отсутствующие
    # соседние разделы), не должны глушить проверки environment — иначе отчёт
    # молча теряет часть замечаний при первой же посторонней ошибке.
    if len(report.issues) > issues_before:
        return

    if not 200 <= env["altitude_km"] <= 1200:
        report.add("environment.altitude_km", "Высота орбиты допустима от 200 до 1200 км")
    if not 0 < env["inclination_deg"] <= 180:
        report.add("environment.inclination_deg", "Наклонение допустимо от 0 до 180 градусов")
    if not isinstance(env["step_s"], int) or isinstance(env["step_s"], bool):
        report.add("environment.step_s", "Шаг расчёта задаётся целым числом секунд")
    if not isinstance(env["horizon_s"], int) or isinstance(env["horizon_s"], bool):
        report.add("environment.horizon_s", "Продолжительность задаётся целым числом секунд")

    if isinstance(env["step_s"], int) and isinstance(env["horizon_s"], int):
        if env["step_s"] <= 0:
            report.add("environment.step_s", "Шаг расчёта должен быть положительным")
        elif env["horizon_s"] < env["step_s"]:
            report.add("environment.horizon_s", "Продолжительность не может быть меньше шага")
        elif env["horizon_s"] > 172800:
            report.add("environment.horizon_s", "Продолжительность не превышает 172800 секунд")
        elif env["horizon_s"] % env["step_s"] != 0:
            report.add("environment.horizon_s", "Продолжительность должна быть кратна шагу")

    if not 0 <= env["min_elevation_deg"] < 90:
        report.add("environment.min_elevation_deg", "Угол возвышения допустим от 0 до 90 градусов")
    if not 0 < env["isl_range_km"] <= 10000:
        report.add("environment.isl_range_km", "Дальность межспутниковой связи — от 0 до 10000 км")
    if not 0 <= env["target_availability"] <= 1:
        report.add(
            "environment.target_availability",
            "Целевая доступность задаётся долей от 0 до 1",
        )


def _check_design(design: Any, report: ValidationReport) -> tuple[set[str], set[str]]:
    """Проверяет раздел design, возвращает множества идентификаторов плоскостей и аппаратов."""
    if not isinstance(design, dict):
        report.add("design", "Раздел design должен быть объектом")
        return set(), set()

    planes = design.get("planes")
    plane_ids: set[str] = set()
    if not isinstance(planes, list) or not planes:
        report.add("design.planes", "Нужна хотя бы одна орбитальная плоскость")
    else:
        for idx, plane in enumerate(planes):
            pid = plane.get("id") if isinstance(plane, dict) else None
            if not isinstance(pid, str) or not pid:
                report.add(f"design.planes[{idx}].id", "Идентификатор плоскости обязателен")
                continue
            if pid in plane_ids:
                report.add(f"design.planes[{idx}].id", f"Идентификатор «{pid}» повторяется")
            plane_ids.add(pid)
            for key in ("raan_deg", "phase_deg"):
                value = plane.get(key)
                if not _finite(value):
                    report.add(f"design.planes[{idx}].{key}", "Угол должен быть конечным числом")
                elif not 0 <= value < 360:
                    report.add(
                        f"design.planes[{idx}].{key}",
                        "Угол задаётся от 0 включительно до 360 исключительно",
                    )

    stage = design.get("launch_stage")
    if not isinstance(stage, int) or isinstance(stage, bool) or stage not in (1, 2, 3):
        report.add("design.launch_stage", "Очередь запуска принимает значения 1, 2 или 3")

    satellites = design.get("satellites")
    sat_ids: set[str] = set()
    if not isinstance(satellites, list) or not satellites:
        report.add("design.satellites", "Нужен хотя бы один аппарат")
    else:
        for idx, sat in enumerate(satellites):
            if not isinstance(sat, dict):
                report.add(f"design.satellites[{idx}]", "Описание аппарата должно быть объектом")
                continue
            sid = sat.get("id")
            if not isinstance(sid, str) or not sid:
                report.add(f"design.satellites[{idx}].id", "Идентификатор аппарата обязателен")
            else:
                if sid in sat_ids:
                    report.add(f"design.satellites[{idx}].id", f"Идентификатор «{sid}» повторяется")
                sat_ids.add(sid)
            plane_id = sat.get("plane_id")
            if not isinstance(plane_id, str) or plane_id not in plane_ids:
                report.add(
                    f"design.satellites[{idx}].plane_id",
                    f"Плоскость «{plane_id}» не описана в design.planes",
                )
            if not _finite(sat.get("slot_deg")):
                report.add(f"design.satellites[{idx}].slot_deg", "Положение должно быть числом")
            batch = sat.get("launch_batch")
            if not isinstance(batch, int) or isinstance(batch, bool) or batch not in (1, 2, 3):
                report.add(
                    f"design.satellites[{idx}].launch_batch",
                    "Очередь запуска аппарата принимает значения 1, 2 или 3",
                )

    return plane_ids, sat_ids


def _check_ground_sites(sites: Any, sat_ids: set[str], report: ValidationReport) -> set[str]:
    """Проверяет наземные пункты, возвращает множество идентификаторов шлюзов."""
    if not isinstance(sites, list) or not sites:
        report.add("ground_sites", "Нужен хотя бы один наземный пункт")
        return set()

    seen: set[str] = set()
    gateways: set[str] = set()
    has_client = False

    for idx, site in enumerate(sites):
        if not isinstance(site, dict):
            report.add(f"ground_sites[{idx}]", "Описание пункта должно быть объектом")
            continue
        gid = site.get("id")
        if not isinstance(gid, str) or not gid:
            report.add(f"ground_sites[{idx}].id", "Идентификатор пункта обязателен")
        else:
            if gid in seen:
                report.add(f"ground_sites[{idx}].id", f"Идентификатор «{gid}» повторяется")
            if gid in sat_ids:
                report.add(
                    f"ground_sites[{idx}].id",
                    f"Идентификатор «{gid}» уже занят аппаратом — они должны различаться",
                )
            seen.add(gid)

        role = site.get("role")
        if role == "gateway" and isinstance(gid, str):
            gateways.add(gid)
        elif role == "client":
            has_client = True
        else:
            report.add(f"ground_sites[{idx}].role", "Роль принимает значение client или gateway")

        lat, lon = site.get("lat_deg"), site.get("lon_deg")
        if not _finite(lat) or not -90 <= lat <= 90:
            report.add(f"ground_sites[{idx}].lat_deg", "Широта задаётся от -90 до 90 градусов")
        if not _finite(lon) or not -180 <= lon <= 180:
            report.add(f"ground_sites[{idx}].lon_deg", "Долгота задаётся от -180 до 180 градусов")

    if not has_client:
        report.add("ground_sites", "Нужен хотя бы один пункт с ролью client")
    if not gateways:
        report.add("ground_sites", "Нужен хотя бы один пункт с ролью gateway")

    return gateways


def _check_outages(
    scenario: dict[str, Any],
    sat_ids: set[str],
    gateway_ids: set[str],
    horizon_s: Any,
    report: ValidationReport,
) -> None:
    specs = [
        ("failures", "satellite_id", sat_ids, "аппарат"),
        ("gateway_outages", "gateway_id", gateway_ids, "шлюз"),
    ]
    for field_name, key, valid_ids, subject in specs:
        entries = scenario.get(field_name)
        if entries is None:
            report.add(field_name, "Раздел обязателен, допускается пустой список")
            continue
        if not isinstance(entries, list):
            report.add(field_name, "Раздел должен быть списком")
            continue
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                report.add(f"{field_name}[{idx}]", "Описание периода должно быть объектом")
                continue
            entry_id = entry.get(key)
            if not isinstance(entry_id, str) or entry_id not in valid_ids:
                report.add(
                    f"{field_name}[{idx}].{key}",
                    f"Неизвестный {subject} «{entry_id}»",
                )
            start, end = entry.get("start_s"), entry.get("end_s")
            if not _finite(start) or not _finite(end):
                report.add(f"{field_name}[{idx}]", "Границы периода должны быть числами")
                continue
            if start >= end:
                report.add(f"{field_name}[{idx}]", "Начало периода должно быть раньше конца")
            elif start < 0:
                report.add(
                    f"{field_name}[{idx}].start_s",
                    "Начало периода не может быть отрицательным",
                )
            elif isinstance(horizon_s, int) and end > horizon_s:
                report.add(
                    f"{field_name}[{idx}].end_s",
                    f"Период выходит за горизонт расчёта ({horizon_s} с)",
                )


def validate_scenario(scenario: Any) -> ValidationReport:
    """Полная проверка сценария. Возвращает отчёт со всеми найденными замечаниями."""
    report = ValidationReport()

    if not isinstance(scenario, dict):
        report.add("", "Файл должен содержать объект JSON")
        return report

    if scenario.get("schema_version") != SCHEMA_VERSION:
        got = scenario.get("schema_version")
        report.add(
            "schema_version",
            f"Поддерживается только схема {SCHEMA_VERSION}, получено «{got}»",
        )

    for section in ("environment", "design", "ground_sites"):
        if section not in scenario:
            report.add(section, "Обязательный раздел отсутствует")

    _check_environment(scenario.get("environment"), report)
    _, sat_ids = _check_design(scenario.get("design"), report)
    gateway_ids = _check_ground_sites(scenario.get("ground_sites"), sat_ids, report)

    env = scenario.get("environment")
    horizon = env.get("horizon_s") if isinstance(env, dict) else None
    _check_outages(scenario, sat_ids, gateway_ids, horizon, report)

    return report


def normalize_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Приводит углы к допустимому диапазону и объединяет пересекающиеся периоды.

    Пользователь меняет RAAN и фазирование в интерфейсе, поэтому значения
    вроде 375 или -30 градусов ожидаемы и приводятся к диапазону [0; 360).
    Пересекающиеся периоды недоступности объединяются — по смыслу
    недоступности они равносильны одному непрерывному периоду.
    """
    result = _deep_copy(scenario)

    for plane in result.get("design", {}).get("planes", []):
        for key in ("raan_deg", "phase_deg"):
            if _finite(plane.get(key)):
                plane[key] = float(plane[key]) % 360.0

    for sat in result.get("design", {}).get("satellites", []):
        if _finite(sat.get("slot_deg")):
            sat["slot_deg"] = float(sat["slot_deg"]) % 360.0

    result["failures"] = _merge_outages(result.get("failures", []), "satellite_id")
    result["gateway_outages"] = _merge_outages(result.get("gateway_outages", []), "gateway_id")
    return result


def _merge_outages(entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    by_subject: dict[str, list[tuple[float, float]]] = {}
    for entry in entries:
        span = (float(entry["start_s"]), float(entry["end_s"]))
        by_subject.setdefault(entry[key], []).append(span)

    merged: list[dict[str, Any]] = []
    for subject, spans in by_subject.items():
        spans.sort()
        current_start, current_end = spans[0]
        for start, end in spans[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                merged.append({key: subject, "start_s": current_start, "end_s": current_end})
                current_start, current_end = start, end
        merged.append({key: subject, "start_s": current_start, "end_s": current_end})
    return merged


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def load_scenario(raw: Any) -> dict[str, Any]:
    """Проверяет и нормализует сценарий. Бросает ScenarioError при замечаниях."""
    report = validate_scenario(raw)
    if not report.ok:
        raise ScenarioError(report)
    return normalize_scenario(raw)
