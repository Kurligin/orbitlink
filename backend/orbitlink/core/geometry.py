"""Геометрия группировки: положение аппаратов и состав доступных связей.

Формулы взяты из документа «Описание данных» и реализованы заново, чтобы
расчёт был частью проекта, а не внешней зависимостью. Эталонный модуль
организаторов лежит в docs/reference_geometry.py и используется в тестах
как источник истины: tests/test_reference_parity.py сверяет координаты,
углы возвышения и состав рёбер на контрольных отсчётах.

Модель: круговые орбиты, сферическая Земля, единый порог угла возвышения
для наземных линий, межспутниковый контакт по дальности и отсутствию
пересечения линии связи с Землёй.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

EARTH_RADIUS_KM = 6371.0
EARTH_MU = 398600.435507
EARTH_ROTATION_PERIOD_S = 86164.09054
EARTH_ANGULAR_RATE = 2 * math.pi / EARTH_ROTATION_PERIOD_S
LIGHT_SPEED_KM_S = 299792.458


@dataclass
class Snapshot:
    """Состояние сети в один отсчёт времени."""

    t_s: float
    satellite_ids: list[str]
    positions_km: np.ndarray
    """Положения аппаратов в системе, связанной с Землёй, форма (N, 3)."""
    active: np.ndarray
    """Булев массив: аппарат выведен на текущей очереди и не находится в отказе."""
    edges: list[tuple[str, str, float]]
    """Двунаправленные контакты: спутник-спутник и наземный пункт-спутник."""
    elevation_deg: dict[str, dict[str, float]]
    """Углы возвышения активных аппаратов по каждому наземному пункту."""
    offline_gateways: set[str]

    def adjacency(self) -> dict[str, list[tuple[str, float]]]:
        """Список смежности с длинами рёбер в километрах."""
        adjacency: dict[str, list[tuple[str, float]]] = {}
        for a, b, distance in self.edges:
            adjacency.setdefault(a, []).append((b, distance))
            adjacency.setdefault(b, []).append((a, distance))
        return adjacency

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": self.t_s,
            "satellites": [
                {
                    "id": sid,
                    "x_km": float(self.positions_km[k, 0]),
                    "y_km": float(self.positions_km[k, 1]),
                    "z_km": float(self.positions_km[k, 2]),
                    "active": bool(self.active[k]),
                }
                for k, sid in enumerate(self.satellite_ids)
            ],
            "edges": [[a, b, distance] for a, b, distance in self.edges],
            "elevation_deg": self.elevation_deg,
        }


class ConstellationModel:
    """Расчёт состояния группировки на произвольный момент времени.

    Постоянные для сценария величины (угловые положения, ориентации
    плоскостей, координаты наземных пунктов) вычисляются один раз при
    создании модели, поэтому прогон по всей сетке времени идёт без
    повторной подготовки данных.
    """

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        env = scenario["environment"]
        design = scenario["design"]

        self.step_s: int = int(env["step_s"])
        self.horizon_s: int = int(env["horizon_s"])
        self.min_elevation_deg: float = float(env["min_elevation_deg"])
        self.isl_range_km: float = float(env["isl_range_km"])
        self.target_availability: float = float(env["target_availability"])
        self.launch_stage: int = int(design["launch_stage"])

        self.orbit_radius_km: float = EARTH_RADIUS_KM + float(env["altitude_km"])
        self.mean_motion: float = math.sqrt(EARTH_MU / self.orbit_radius_km**3)
        self.inclination: float = math.radians(float(env["inclination_deg"]))
        self.earth_angle0: float = math.radians(float(env["earth_angle0_deg"]))

        planes = {p["id"]: p for p in design["planes"]}
        satellites = design["satellites"]
        self.satellite_ids: list[str] = [s["id"] for s in satellites]
        self.satellite_index: dict[str, int] = {sid: i for i, sid in enumerate(self.satellite_ids)}
        self.satellite_plane: dict[str, str] = {s["id"]: s["plane_id"] for s in satellites}

        self._u0 = np.array(
            [math.radians(s["slot_deg"] + planes[s["plane_id"]]["phase_deg"]) for s in satellites]
        )
        self._raan = np.array([math.radians(planes[s["plane_id"]]["raan_deg"]) for s in satellites])
        self._launch_batch = np.array([int(s["launch_batch"]) for s in satellites])

        self.ground_sites: list[dict[str, Any]] = list(scenario["ground_sites"])
        self.client_ids: list[str] = [g["id"] for g in self.ground_sites if g["role"] == "client"]
        self.gateway_ids: list[str] = [g["id"] for g in self.ground_sites if g["role"] == "gateway"]
        self._ground_positions = {g["id"]: ground_position(g) for g in self.ground_sites}

        self.deployed_mask = self._launch_batch <= self.launch_stage
        self._pair_i, self._pair_j = np.triu_indices(len(self.satellite_ids), 1)

    @property
    def time_grid(self) -> list[int]:
        """Отсчёты расчёта: 0, step, 2·step, ..., правый конец не включается."""
        return list(range(0, self.horizon_s, self.step_s))

    def failed_at(self, t_s: float) -> set[str]:
        """Аппараты, находящиеся в отказе на момент t_s. Начало включается, конец — нет."""
        return {
            f["satellite_id"] for f in self.scenario["failures"] if f["start_s"] <= t_s < f["end_s"]
        }

    def offline_gateways_at(self, t_s: float) -> set[str]:
        """Шлюзы, недоступные на момент t_s."""
        return {
            o["gateway_id"]
            for o in self.scenario["gateway_outages"]
            if o["start_s"] <= t_s < o["end_s"]
        }

    def positions(self, t_s: float) -> tuple[np.ndarray, np.ndarray]:
        """Положения аппаратов: инерциальные и в системе, связанной с Землёй."""
        u = self._u0 + self.mean_motion * t_s
        cos_u, sin_u = np.cos(u), np.sin(u)
        cos_raan, sin_raan = np.cos(self._raan), np.sin(self._raan)
        cos_inc, sin_inc = math.cos(self.inclination), math.sin(self.inclination)

        inertial = self.orbit_radius_km * np.stack(
            (
                cos_raan * cos_u - sin_raan * sin_u * cos_inc,
                sin_raan * cos_u + cos_raan * sin_u * cos_inc,
                sin_u * sin_inc,
            ),
            axis=1,
        )

        theta = self.earth_angle0 + EARTH_ANGULAR_RATE * t_s
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        rotation = np.array([[cos_t, -sin_t, 0.0], [sin_t, cos_t, 0.0], [0.0, 0.0, 1.0]])
        return inertial, inertial @ rotation

    def snapshot(self, t_s: float) -> Snapshot:
        """Полное состояние сети в момент t_s."""
        _, fixed = self.positions(t_s)
        failed = self.failed_at(t_s)
        active = self.deployed_mask & np.array(
            [sid not in failed for sid in self.satellite_ids], dtype=bool
        )

        edges = self._inter_satellite_edges(fixed, active)
        offline = self.offline_gateways_at(t_s)
        elevation_deg: dict[str, dict[str, float]] = {}

        for site in self.ground_sites:
            gp = self._ground_positions[site["id"]]
            delta = fixed - gp
            slant = np.linalg.norm(delta, axis=1)
            elevation = np.degrees(
                np.arcsin(np.clip(delta @ (gp / EARTH_RADIUS_KM) / slant, -1.0, 1.0))
            )
            elevation_deg[site["id"]] = {
                sid: float(elevation[k]) for k, sid in enumerate(self.satellite_ids) if active[k]
            }
            site_offline = site["id"] in offline
            visible = (elevation >= self.min_elevation_deg) & active & (not site_offline)
            edges.extend(
                (site["id"], self.satellite_ids[k], float(slant[k])) for k in np.where(visible)[0]
            )

        return Snapshot(
            t_s=float(t_s),
            satellite_ids=self.satellite_ids,
            positions_km=fixed,
            active=active,
            edges=edges,
            elevation_deg=elevation_deg,
            offline_gateways=offline,
        )

    def _inter_satellite_edges(
        self, fixed: np.ndarray, active: np.ndarray
    ) -> list[tuple[str, str, float]]:
        """Межспутниковые связи: в пределах дальности и без пересечения Земли."""
        i, j = self._pair_i, self._pair_j
        delta = fixed[j] - fixed[i]
        distance = np.linalg.norm(delta, axis=1)

        # Ближайшая к центру Земли точка отрезка [a; b]: если она выше поверхности,
        # линия связи не перекрыта планетой.
        denominator = np.sum(delta * delta, axis=1)
        lam = np.clip(-np.sum(fixed[i] * delta, axis=1) / np.maximum(denominator, 1e-12), 0.0, 1.0)
        closest = np.linalg.norm(fixed[i] + lam[:, None] * delta, axis=1)

        ok = (distance < self.isl_range_km) & (closest > EARTH_RADIUS_KM) & active[i] & active[j]
        return [
            (self.satellite_ids[a], self.satellite_ids[b], float(d))
            for a, b, d in zip(i[ok], j[ok], distance[ok], strict=True)
        ]

    def ground_position_of(self, site_id: str) -> np.ndarray:
        """Координаты наземного пункта по его идентификатору."""
        return self._ground_positions[site_id]


def ground_position(site: dict[str, Any]) -> np.ndarray:
    """Координаты наземного пункта в системе, связанной с Землёй."""
    lat = math.radians(float(site["lat_deg"]))
    lon = math.radians(float(site["lon_deg"]))
    return EARTH_RADIUS_KM * np.array(
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    )
