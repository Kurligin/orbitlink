"""Поиск и выбор маршрута «клиентский пункт — аппараты — шлюз».

Маршрут ищется алгоритмом Дейкстры по графу контактов текущего отсчёта.
Вес ребра зависит от выбранной стратегии, поэтому один и тот же алгоритм
даёт минимум переходов, минимум задержки, обход перегруженных участков
или обход связей, работающих у предела дальности.

Наземные пункты не ретранслируют: из клиентского пункта можно уйти только
в аппарат, а шлюз является конечным узлом.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import Enum

from orbitlink.core.geometry import LIGHT_SPEED_KM_S, Snapshot

ROBUST_PENALTY_WEIGHT = 3.0
"""Во сколько раз дороже обходится связь, работающая на пределе дальности."""


class RoutingStrategy(str, Enum):
    MIN_HOPS = "min_hops"
    MIN_LATENCY = "min_latency"
    LOAD_AWARE = "load_aware"
    ROBUST = "robust"


class NoRouteReason(str, Enum):
    GATEWAY_OFFLINE = "gateway_offline"
    NO_VISIBLE_SATELLITE = "no_visible_satellite"
    NO_GATEWAY_CONTACT = "no_gateway_contact"
    ISL_NETWORK_SPLIT = "isl_network_split"


@dataclass(frozen=True)
class Route:
    path: tuple[str, ...]
    hops: int
    length_km: float
    latency_ms: float

    @property
    def relays(self) -> tuple[str, ...]:
        """Промежуточные узлы маршрута — только аппараты."""
        return self.path[1:-1]

    def as_dict(self) -> dict:
        return {
            "path": list(self.path),
            "hops": self.hops,
            "length_km": round(self.length_km, 3),
            "latency_ms": round(self.latency_ms, 3),
        }


def _pair(a: str, b: str) -> tuple[str, str]:
    """Канонический вид пары идентификаторов узлов одного ребра.

    Это единственное место, где строится такая пара — используется и в весе
    ребра (ключ `utilisation`), и в кэше длин рёбер графа, и в тестах. Раньше
    идиома ``(min(a, b), max(a, b))`` была продублирована в нескольких местах:
    производитель словаря `utilisation`, собравший ключ по-другому (например,
    числовым сравнением), промахивался бы мимо словаря молча, без ошибки.

    Канонизация лексикографическая (обычное сравнение строк Python), а НЕ
    числовая: для идентификаторов вида `S9`/`S10` результат —
    ``_pair("S9", "S10") == ("S10", "S9")``, потому что символ `"1"` меньше
    символа `"9"`, хотя по значению 9 меньше 10. Всегда стройте пару через эту
    функцию, а не вручную.
    """
    return (a, b) if a < b else (b, a)


class NetworkGraph:
    """Граф контактов одного отсчёта времени."""

    def __init__(
        self,
        snapshot: Snapshot,
        gateway_ids: list[str],
        isl_range_km: float | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.isl_range_km = isl_range_km
        """Дальность межспутниковой связи по умолчанию для find_route/find_backup_route
        этого графа (см. их параметр isl_range_km) — не обязана быть задана, если
        вызывающий код всегда передаёт её явно."""
        self.gateways = {g for g in gateway_ids if g not in snapshot.offline_gateways}
        self.offline_gateways = set(snapshot.offline_gateways)
        self.satellites = {
            sid for index, sid in enumerate(snapshot.satellite_ids) if snapshot.active[index]
        }
        self._adjacency: dict[str, list[tuple[str, float]]] = {}
        self._edge_lengths: dict[tuple[str, str], float] = {}
        for left, right, distance in snapshot.edges:
            self._adjacency.setdefault(left, []).append((right, distance))
            self._adjacency.setdefault(right, []).append((left, distance))
            self._edge_lengths[_pair(left, right)] = distance

    def neighbours(self, node: str) -> list[tuple[str, float]]:
        return self._adjacency.get(node, [])

    def visible_satellites(self, site_id: str) -> set[str]:
        return {node for node, _ in self.neighbours(site_id) if node in self.satellites}

    def edge_length(self, a: str, b: str) -> float | None:
        """Длина ребра `a`-`b` в километрах, либо `None`, если такого ребра нет.

        Публичный доступ к кэшу длин рёбер (`_edge_lengths`), собранному один
        раз в `__init__`, — чтобы другим модулям (например, `core/tracker.py`)
        не приходилось ни пересобирать его заново, ни обращаться к приватному
        атрибуту напрямую."""
        return self._edge_lengths.get(_pair(a, b))


def _edge_weight(
    left: str,
    right: str,
    distance_km: float,
    strategy: RoutingStrategy,
    graph: NetworkGraph,
    isl_range_km: float,
    utilisation: dict[tuple[str, str], float] | None,
) -> float:
    """Вес ребра для алгоритма Дейкстры — зависит от стратегии.

    `utilisation` — доля занятости ребра, число от 0.0 до 1.0. Ключ — канонический
    вид пары идентификаторов узлов, построенный `_pair(left, right)` (см. её докстринг
    про лексикографическую, а не числовую канонизацию). Ребро, отсутствующее в
    словаре, считается свободным (загрузка 0.0). Контракт производителя словаря
    задаётся здесь и в `find_route`.
    """
    if strategy is RoutingStrategy.MIN_HOPS:
        return 1.0
    if strategy is RoutingStrategy.MIN_LATENCY:
        return distance_km
    if strategy is RoutingStrategy.LOAD_AWARE:
        load = (utilisation or {}).get(_pair(left, right), 0.0)
        return distance_km / max(1.0 - min(load, 0.99), 0.01)
    # ROBUST: связь, работающая у предела дальности, скоро оборвётся из-за
    # расхождения аппаратов, поэтому маршрут через неё живёт недолго.
    both_satellites = left in graph.satellites and right in graph.satellites
    if not both_satellites:
        return distance_km
    margin = min(distance_km / isl_range_km, 1.0)
    return distance_km * (1.0 + ROBUST_PENALTY_WEIGHT * margin**4)


def find_route(
    graph: NetworkGraph,
    client_id: str,
    strategy: RoutingStrategy,
    *,
    isl_range_km: float | None = None,
    excluded: frozenset[str] = frozenset(),
    utilisation: dict[tuple[str, str], float] | None = None,
) -> Route | None:
    """Кратчайший по весу стратегии маршрут до любого доступного шлюза.

    `isl_range_km` — дальность межспутниковой связи, нужна только для штрафа
    стратегии ROBUST. Если не передана явно, берётся из `graph.isl_range_km`
    (см. `NetworkGraph.__init__`); явная передача всегда имеет приоритет над
    значением графа. Если не задана ни там, ни там — `ValueError`: без нужного
    диапазона стратегию ROBUST не на чем считать, а тихая подстановка значения
    по умолчанию замаскировала бы рассинхронизацию с геометрией сценария.

    `utilisation` — см. контракт ключа словаря в `_edge_weight`: ключ строится
    через `_pair`, канонизация лексикографическая, а не числовая.
    """
    if not graph.gateways:
        return None

    resolved_isl_range_km = isl_range_km if isl_range_km is not None else graph.isl_range_km
    if resolved_isl_range_km is None:
        raise ValueError(
            "isl_range_km не задан: передайте его в find_route()/find_backup_route() "
            "явно либо создайте NetworkGraph с isl_range_km."
        )

    best_cost: dict[str, float] = {client_id: 0.0}
    previous: dict[str, str] = {}
    queue: list[tuple[float, str]] = [(0.0, client_id)]
    reached: str | None = None

    while queue:
        cost, node = heapq.heappop(queue)
        if cost > best_cost.get(node, float("inf")):
            continue
        if node in graph.gateways and node != client_id:
            reached = node
            break
        # Из наземного пункта уходим только в аппараты, шлюз — терминальный узел.
        if node != client_id and node not in graph.satellites:
            continue

        for neighbour, distance in graph.neighbours(node):
            if neighbour in excluded or neighbour == client_id:
                continue
            if neighbour not in graph.satellites and neighbour not in graph.gateways:
                continue
            weight = _edge_weight(
                node, neighbour, distance, strategy, graph, resolved_isl_range_km, utilisation
            )
            candidate = cost + weight
            if candidate < best_cost.get(neighbour, float("inf")):
                best_cost[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, neighbour))

    if reached is None:
        return None

    path = [reached]
    while path[-1] != client_id:
        path.append(previous[path[-1]])
    path.reverse()
    return _build_route(tuple(path), graph)


def _build_route(path: tuple[str, ...], graph: NetworkGraph) -> Route:
    """Пересобирает длину и задержку маршрута по кэшу длин рёбер графа.

    Длины уже посчитаны один раз в `NetworkGraph.__init__` (`graph._edge_lengths`),
    поэтому здесь нет повторного прохода по `graph.snapshot.edges` на каждый вызов —
    это заметно при массовом пересчёте сохранённых маршрутов на всей сетке времени.
    """
    total_km = sum(
        graph._edge_lengths[_pair(left, right)] for left, right in zip(path, path[1:], strict=False)
    )
    return Route(
        path=path,
        hops=len(path) - 1,
        length_km=total_km,
        latency_ms=total_km / LIGHT_SPEED_KM_S * 1000.0,
    )


def route_cost(
    route: Route,
    graph: NetworkGraph,
    strategy: RoutingStrategy,
    *,
    isl_range_km: float | None = None,
    utilisation: dict[tuple[str, str], float] | None = None,
) -> float:
    """Суммарный вес маршрута по весам ребра ВЫБРАННОЙ СТРАТЕГИИ (`_edge_weight`).

    Нужна всюду, где произвольный путь (например, результат локального ремонта
    в `core/tracker.py`) требуется сравнить с лучшим маршрутом в тех же
    единицах, какими пользовался поиск, — а не по `length_km`, который
    бессодержателен для `MIN_HOPS` (там оптимизируется число переходов, а не
    расстояние) и не учитывает занятость для `LOAD_AWARE`. `isl_range_km` и
    `utilisation` разрешаются и трактуются так же, как в `find_route` — см.
    его докстринг и докстринг `_edge_weight`.

    Бросает `ValueError`, если у маршрута есть ребро, которого нет в графе:
    стоимость несуществующего ребра посчитать нечем, а тихо пропустить его —
    исказить стоимость молча.
    """
    resolved_isl_range_km = isl_range_km if isl_range_km is not None else graph.isl_range_km
    if resolved_isl_range_km is None:
        raise ValueError(
            "isl_range_km не задан: передайте его в route_cost() явно либо "
            "создайте NetworkGraph с isl_range_km."
        )

    total = 0.0
    for left, right in zip(route.path, route.path[1:], strict=False):
        distance_km = graph.edge_length(left, right)
        if distance_km is None:
            raise ValueError(f"ребро {left}-{right} отсутствует в графе — маршрут не оценить")
        total += _edge_weight(
            left, right, distance_km, strategy, graph, resolved_isl_range_km, utilisation
        )
    return total


def find_backup_route(
    graph: NetworkGraph,
    client_id: str,
    strategy: RoutingStrategy,
    primary: Route,
    *,
    isl_range_km: float | None = None,
    utilisation: dict[tuple[str, str], float] | None = None,
) -> Route | None:
    """Маршрут, не использующий ни одного аппарата основного.

    `isl_range_km` необязателен по тем же правилам, что и в `find_route` — см. его
    докстринг.
    """
    return find_route(
        graph,
        client_id,
        strategy,
        isl_range_km=isl_range_km,
        excluded=frozenset(primary.relays),
        utilisation=utilisation,
    )


def classify_no_route(
    graph: NetworkGraph, client_id: str, excluded: frozenset[str] = frozenset()
) -> NoRouteReason:
    """Определяет, почему сквозного маршрута нет. Порядок проверок важен.

    Предусловие: вызывается, когда ``find_route(graph, client_id, ..., excluded=excluded)``
    для тех же `graph`/`client_id`/`excluded` вернул `None`. Если предусловие нарушено
    (маршрут в действительности есть), функция всё равно детерминированно возвращает
    `ISL_NETWORK_SPLIT` — ни одна из более ранних проверок не срабатывает, а это
    единственная безусловная ветка `else`. Это документированное поведение при
    неправильном вызове, а не гарантия отсутствия маршрута.

    `excluded` — узлы, которые нужно считать недоступными при объяснении причины
    (обычно аппараты уже использованного основного маршрута). Тот же набор, что
    передаётся в `find_backup_route`, чтобы эта функция могла объяснить отсутствие
    не только основного, но и резервного маршрута.
    """
    if not graph.gateways:
        return NoRouteReason.GATEWAY_OFFLINE
    if not (graph.visible_satellites(client_id) - excluded):
        return NoRouteReason.NO_VISIBLE_SATELLITE
    if not any(graph.visible_satellites(gateway) - excluded for gateway in graph.gateways):
        return NoRouteReason.NO_GATEWAY_CONTACT
    return NoRouteReason.ISL_NETWORK_SPLIT
