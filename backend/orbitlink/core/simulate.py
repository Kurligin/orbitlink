"""Прогон конфигурации по сетке времени.

Геометрия зависит только от времени, поэтому считается один раз и
переиспользуется: варианты отказов различаются лишь маской активности.
Это делает перебор десятков вариантов отказов интерактивным.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orbitlink.core.geometry import EARTH_RADIUS_KM, ConstellationModel, Snapshot
from orbitlink.core.metrics import ClientAccumulator, ClientMetrics
from orbitlink.core.routing import NetworkGraph, Route, RoutingStrategy, _pair
from orbitlink.core.tracker import RouteTracker


class GeometryCache:
    """Предвычисленная геометрия на всей сетке времени."""

    def __init__(self, model: ConstellationModel) -> None:
        self.model = model
        self.times = model.time_grid
        self._positions: list[np.ndarray] = []
        self._isl: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        self._ground: list[dict[str, tuple[np.ndarray, np.ndarray]]] = []

        for t_s in self.times:
            _, fixed = model.positions(t_s)
            self._positions.append(fixed)
            self._isl.append(_potential_links(model, fixed))
            self._ground.append(_ground_geometry(model, fixed))

    def positions_at(self, index: int) -> np.ndarray:
        return self._positions[index]

    def snapshot_at(self, index: int, model: ConstellationModel) -> Snapshot:
        """Состояние сети: геометрия из кэша, маски активности — из модели.

        Модель передаётся снаружи намеренно. Геометрия зависит только от
        времени, поэтому один кэш обслуживает сценарии с разными отказами
        и очередями запуска. Если брать модель из самого кэша, добавленные
        отказы будут молча проигнорированы.
        """
        t_s = self.times[index]
        failed = model.failed_at(t_s)
        offline_gateways = model.offline_gateways_at(t_s)
        active = model.deployed_mask & np.array(
            [sid not in failed for sid in model.satellite_ids], dtype=bool
        )
        pair_i, pair_j, distance = self._isl[index]
        keep = active[pair_i] & active[pair_j]
        edges: list[tuple[str, str, float]] = [
            (model.satellite_ids[a], model.satellite_ids[b], float(d))
            for a, b, d in zip(pair_i[keep], pair_j[keep], distance[keep], strict=True)
        ]

        elevation_deg: dict[str, dict[str, float]] = {}
        for site in model.ground_sites:
            angles, slant = self._ground[index][site["id"]]
            elevation_deg[site["id"]] = {
                sid: float(angles[k]) for k, sid in enumerate(model.satellite_ids) if active[k]
            }
            if site["id"] in offline_gateways:
                continue
            visible = (angles >= model.min_elevation_deg) & active
            edges.extend(
                (site["id"], model.satellite_ids[k], float(slant[k])) for k in np.where(visible)[0]
            )

        return Snapshot(
            t_s=float(self.times[index]),
            satellite_ids=model.satellite_ids,
            positions_km=self._positions[index],
            active=active,
            edges=edges,
            elevation_deg=elevation_deg,
            offline_gateways=set(offline_gateways),
        )

    def graph_at(self, index: int, model: ConstellationModel) -> NetworkGraph:
        return NetworkGraph(
            self.snapshot_at(index, model), model.gateway_ids, isl_range_km=model.isl_range_km
        )


def _potential_links(
    model: ConstellationModel, fixed: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Пары аппаратов, между которыми связь возможна геометрически."""
    i, j = np.triu_indices(len(model.satellite_ids), 1)
    delta = fixed[j] - fixed[i]
    distance = np.linalg.norm(delta, axis=1)
    denominator = np.sum(delta * delta, axis=1)
    lam = np.clip(-np.sum(fixed[i] * delta, axis=1) / np.maximum(denominator, 1e-12), 0.0, 1.0)
    closest = np.linalg.norm(fixed[i] + lam[:, None] * delta, axis=1)
    ok = (distance < model.isl_range_km) & (closest > EARTH_RADIUS_KM)
    return i[ok], j[ok], distance[ok]


def _ground_geometry(
    model: ConstellationModel, fixed: np.ndarray
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for site in model.ground_sites:
        gp = model.ground_position_of(site["id"])
        delta = fixed - gp
        slant = np.linalg.norm(delta, axis=1)
        angles = np.degrees(np.arcsin(np.clip(delta @ (gp / EARTH_RADIUS_KM) / slant, -1.0, 1.0)))
        result[site["id"]] = (angles, slant)
    return result


@dataclass
class RouteRecord:
    t_s: int
    client_id: str
    path: list[str]
    event: str
    reason: str | None = None
    hops: int | None = None
    latency_ms: float | None = None
    has_backup: bool = False

    def as_dict(self) -> dict:
        return {
            "t_s": self.t_s,
            "client_id": self.client_id,
            "path": self.path,
            "event": self.event,
            "reason": self.reason,
            "hops": self.hops,
            "latency_ms": None if self.latency_ms is None else round(self.latency_ms, 3),
            "has_backup": self.has_backup,
        }


@dataclass
class RunResult:
    scenario: dict
    strategy: RoutingStrategy
    times: list[int]
    clients: dict[str, ClientMetrics]
    routes: list[RouteRecord]

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "times": self.times,
            "clients": {cid: m.as_dict() for cid, m in self.clients.items()},
            "routes": [record.as_dict() for record in self.routes],
        }


def run_result_from_payload(scenario: dict, strategy: RoutingStrategy, payload: dict) -> RunResult:
    """Восстанавливает `RunResult` из закэшированного `payload` (см. `as_dict()`).

    Нужно выгрузке (`/api/variants/{id}/export`): она обязана отдавать те же
    числа, что показывались на экране, поэтому сначала ищет готовый прогон в
    кэше по отпечатку конфигурации и, если он найден, строит документ из него
    же, а не пересчитывает заново. Поля `RouteRecord`/`ClientMetrics` и ключи
    их `as_dict()` совпадают один в один, поэтому распаковка `**` собирает
    объект обратно без потерь (округление, уже применённое в `as_dict()`,
    идемпотентно для округления, которое сделает `build_result_document`).
    """
    return RunResult(
        scenario=scenario,
        strategy=strategy,
        times=list(payload["times"]),
        clients={
            client_id: ClientMetrics(**metrics) for client_id, metrics in payload["clients"].items()
        },
        routes=[RouteRecord(**route) for route in payload["routes"]],
    )


def _add_flow(utilisation: dict[tuple[str, str], float], route: Route, share: float) -> None:
    """Наращивает занятость на каждом ребре маршрута на долю `share`.

    Ключ словаря строится через `_pair` — тот же канонический (лексикографический,
    а не числовой) вид пары идентификаторов, каким пользуется `_edge_weight` при
    чтении занятости. Построение ключа другим способом означало бы, что
    производитель молча промахивается мимо словаря, который потом читает
    стратегия LOAD_AWARE (см. докстринг `_pair` в `core/routing.py`).
    """
    for left, right in zip(route.path, route.path[1:], strict=False):
        key = _pair(left, right)
        utilisation[key] = utilisation.get(key, 0.0) + share


def _check_cache_matches_model(cache: GeometryCache, model: ConstellationModel) -> None:
    """Кэш геометрии обязан быть построен для той же сетки/дальности/состава аппаратов.

    Отказы, очередь запуска, офлайн-шлюзы и минимальный угол возвышения кэш
    сознательно берёт из ПЕРЕДАННОЙ модели, а не из модели, с которой был
    построен, — на этом держится переиспользование кэша между вариантами
    отказов (см. докстринг `snapshot_at`). Но дальность межспутниковой связи
    запекается в состав рёбер кэша при постройке (`_potential_links` читает
    `model.isl_range_km`), а сетка времени задаёт число итераций цикла в
    `simulate()`. Если модель, для которой кэш строился (`cache.model`),
    отличается от переданной по любому из этих параметров — переиспользовать
    кэш нельзя: состав рёбер и число отсчётов останутся от старой модели, а
    трекер и штраф ROBUST возьмут дальность связи из новой, — числа будут
    тихо неверными, а не просто другими.
    """
    cached_model = cache.model
    if cache.times != model.time_grid:
        raise ValueError(
            "кэш геометрии построен для другой сетки времени (не совпадают step_s/"
            "horizon_s) — переиспользовать для этой модели нельзя"
        )
    if cached_model.isl_range_km != model.isl_range_km:
        raise ValueError(
            "кэш геометрии построен для дальности межспутниковой связи "
            f"{cached_model.isl_range_km} км, а модель требует {model.isl_range_km} км — "
            "состав межспутниковых рёбер задним числом не пересчитать"
        )
    if cached_model.satellite_ids != model.satellite_ids:
        raise ValueError(
            "кэш геометрии построен для другого состава аппаратов — переиспользовать "
            "для этой модели нельзя"
        )


def simulate(
    scenario: dict,
    *,
    strategy: RoutingStrategy = RoutingStrategy.MIN_LATENCY,
    hysteresis: float = 0.3,
    with_backup: bool = True,
    cache: GeometryCache | None = None,
) -> RunResult:
    """Прогоняет конфигурацию по всей сетке времени."""
    # Модель всегда строится из переданного сценария: кэш хранит только
    # геометрию, которая от отказов и очереди запуска не зависит.
    model = ConstellationModel(scenario)
    cache = cache or GeometryCache(model)
    _check_cache_matches_model(cache, model)

    trackers = {
        client_id: RouteTracker(
            client_id, strategy, isl_range_km=model.isl_range_km, hysteresis=hysteresis
        )
        for client_id in model.client_ids
    }
    accumulators = {
        client_id: ClientAccumulator(client_id, model.step_s, model.target_availability)
        for client_id in model.client_ids
    }
    records: list[RouteRecord] = []

    share = 1.0 / max(len(model.client_ids), 1)

    for index, t_s in enumerate(cache.times):
        graph = cache.graph_at(index, model)
        # Клиентские пункты обслуживаются последовательно: каждый следующий
        # видит линии, уже занятые маршрутами предыдущих. Без этого словарь
        # занятости всегда пуст, и стратегия LOAD_AWARE не может отличаться
        # от MIN_LATENCY.
        utilisation: dict[tuple[str, str], float] = {}
        for client_id in model.client_ids:
            visible = bool(graph.visible_satellites(client_id))
            update = trackers[client_id].update(
                graph,
                utilisation=utilisation,
                with_backup=with_backup,
                step_s=model.step_s,
            )
            accumulators[client_id].observe(visible=visible, update=update)
            if update.route is not None:
                _add_flow(utilisation, update.route, share)
            records.append(
                RouteRecord(
                    t_s=t_s,
                    client_id=client_id,
                    path=list(update.route.path) if update.route else [],
                    event=update.event.value,
                    reason=update.reason.value if update.reason else None,
                    hops=update.route.hops if update.route else None,
                    latency_ms=update.route.latency_ms if update.route else None,
                    has_backup=update.backup is not None,
                )
            )

    # Закрываем период жизни последнего маршрута: без этого он теряется
    # молча и среднее время жизни смещается вниз.
    for tracker in trackers.values():
        tracker.flush()

    clients = {
        client_id: accumulators[client_id].finalise(
            trackers[client_id].reroute_count,
            trackers[client_id].path_change_count,
            trackers[client_id].lifetimes_s,
        )
        for client_id in model.client_ids
    }
    return RunResult(scenario, strategy, list(cache.times), clients, records)
