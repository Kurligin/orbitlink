"""Сравнение параметров двух сценариев в человекочитаемом виде."""

from __future__ import annotations

from dataclasses import dataclass

ENVIRONMENT_LABELS = {
    "altitude_km": ("Высота орбиты", "км"),
    "inclination_deg": ("Наклонение", "°"),
    "earth_angle0_deg": ("Начальный угол Земли", "°"),
    "horizon_s": ("Продолжительность расчёта", "с"),
    "step_s": ("Шаг расчёта", "с"),
    "min_elevation_deg": ("Минимальный угол возвышения", "°"),
    "isl_range_km": ("Дальность межспутниковой связи", "км"),
    "target_availability": ("Целевая доступность", ""),
}


@dataclass(frozen=True)
class Change:
    path: str
    before: object | None
    after: object | None
    label: str

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "before": self.before,
            "after": self.after,
            "label": self.label,
        }


def _pretty(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def diff_scenarios(base: dict, variant: dict) -> list[Change]:
    """Возвращает список изменений варианта относительно базового сценария."""
    changes: list[Change] = []

    for key, (title, unit) in ENVIRONMENT_LABELS.items():
        before, after = base["environment"].get(key), variant["environment"].get(key)
        if before != after:
            suffix = f" {unit}" if unit else ""
            changes.append(
                Change(
                    f"environment.{key}",
                    before,
                    after,
                    f"{title}: {_pretty(before)} → {_pretty(after)}{suffix}",
                )
            )

    before, after = base["design"]["launch_stage"], variant["design"]["launch_stage"]
    if before != after:
        changes.append(
            Change("design.launch_stage", before, after, f"Очередь запуска: {before} → {after}")
        )

    base_planes = {plane["id"]: plane for plane in base["design"]["planes"]}
    for index, plane in enumerate(variant["design"]["planes"]):
        original = base_planes.get(plane["id"])
        if original is None:
            changes.append(
                Change(
                    f"design.planes[{index}]",
                    None,
                    plane["id"],
                    f"Добавлена плоскость {plane['id']}",
                )
            )
            continue
        for key in ("raan_deg", "phase_deg"):
            if original[key] != plane[key]:
                changes.append(
                    Change(
                        f"design.planes[{index}].{key}",
                        original[key],
                        plane[key],
                        f"{plane['id']}.{key}: {_pretty(original[key])} → {_pretty(plane[key])}",
                    )
                )

    changes.extend(_diff_outages(base, variant))
    return changes


def _diff_outages(base: dict, variant: dict) -> list[Change]:
    specs = [
        ("failures", "satellite_id", "отказ"),
        ("gateway_outages", "gateway_id", "недоступность шлюза"),
    ]
    changes: list[Change] = []
    for field, key, noun in specs:
        before = {(o[key], o["start_s"], o["end_s"]) for o in base.get(field, [])}
        after = {(o[key], o["start_s"], o["end_s"]) for o in variant.get(field, [])}
        for subject, start, end in sorted(after - before):
            changes.append(
                Change(
                    field,
                    None,
                    {key: subject, "start_s": start, "end_s": end},
                    f"Добавлен {noun} {subject}: {_pretty(start)}–{_pretty(end)} с",
                )
            )
        for subject, start, end in sorted(before - after):
            changes.append(
                Change(
                    field,
                    {key: subject, "start_s": start, "end_s": end},
                    None,
                    f"Снят {noun} {subject}: {_pretty(start)}–{_pretty(end)} с",
                )
            )
    return changes
