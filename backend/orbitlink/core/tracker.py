"""Сопровождение маршрута во времени.

В действующей сети смена маршрута означает переустановку соединения и
потерю данных, поэтому беспричинные переключения между равноценными
путями нежелательны. `RouteTracker` хранит текущий маршрут клиента между
отсчётами и на каждом новом отсчёте решает, что с ним делать:

1. если все рёбра маршрута ещё существуют в графе и его стоимость по весам
   действующей стратегии не хуже наилучшего доступного более чем на порог
   `hysteresis` — маршрут сохраняется (`KEPT`), меняется только пересчитанная
   длина/задержка;
2. если ровно одно ребро маршрута пропало (аппараты разошлись за пределы
   дальности связи или снялась видимость), трекер пробует обойти именно этот
   повреждённый участок по весам той же стратегии — и принимает обход, только
   если его стоимость тоже не хуже наилучшего доступного более чем на
   `hysteresis` (`REPAIRED`);
3. если обойти локально не удалось (пропало более одного ребра, обход не
   найден, либо и обход, и сохранённый путь просели по стоимости ниже порога)
   — строится заново лучший маршрут (`REBUILT`);
4. если маршрута нет вовсе — сообщается причина (`LOST`).

Это отвечает половине критерия «поиск и обновление маршрутов», которую не
закрывает голый повторный поиск на каждом отсчёте: маршрут переживает
отсчёты, пока это оправдано, и правится локально, а не перестраивается
целиком по любому поводу.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from enum import Enum

from orbitlink.core.routing import (
    NetworkGraph,
    NoRouteReason,
    Route,
    RoutingStrategy,
    _build_route,
    _edge_weight,
    classify_no_route,
    find_backup_route,
    find_route,
    route_cost,
)


class RouteEvent(str, Enum):
    """Что случилось с маршрутом клиента на очередном отсчёте."""

    KEPT = "kept"
    REPAIRED = "repaired"
    REBUILT = "rebuilt"
    LOST = "lost"


@dataclass
class RouteUpdate:
    """Итог одного вызова `RouteTracker.update`."""

    route: Route | None
    event: RouteEvent
    reason: NoRouteReason | None = None
    backup: Route | None = None


class RouteTracker:
    """Сопровождает основной маршрут одного клиента между отсчётами.

    Хранит текущий маршрут (`current`) и статистику сопровождения — два разных
    счётчика, потому что у них разные потребители и разный смысл:

    - `reroute_count` — число ПОЛНЫХ перестроений (`REBUILT`): случаев, когда
      локальный ремонт не сработал или был отвергнут по качеству, и клиент
      получил маршрут, найденный заново с нуля. Это метрика ПЕРЕУСТАНОВОК
      СОЕДИНЕНИЯ, которых не удалось избежать локальным обходом — НЕ метрика
      вычислительной экономии: `find_route` выполняется безусловно первой
      строкой `update()` на каждом отсчёте (нужен, чтобы было с чем сравнивать
      стоимость `KEPT`/`REPAIRED`, и что вернуть при `REBUILT`), в том числе
      на отсчётах, закончившихся `KEPT` или `REPAIRED`. Дейкстра не экономится
      никогда — экономится именно переустановка соединения на стороне клиента.
    - `path_change_count` — число ЛЮБЫХ изменений физического пути (`REPAIRED`
      И `REBUILT` вместе). Для потребителя услуги переустановкой соединения
      оборачивается любая смена пути, а не только полное перестроение —
      считать одни перестроения означало бы занижать картину нарушений связи.

    `path_change_count >= reroute_count` всегда (перестроение — это тоже смена
    пути), а разница между ними — число разрывов, которые удалось погасить
    локальным ремонтом, не перестраивая маршрут целиком: это и есть
    количественный аргумент в пользу сопровождения с ремонтом.

    `lifetimes_s` — времена жизни маршрутов, которые были заменены
    (отремонтированы или перестроены) или потеряны, в секундах. Период жизни
    ПОСЛЕДНЕГО, ещё не заменённого маршрута в него не попадает сам по себе —
    его нужно закрыть явным вызовом `flush()` по окончании прогона.
    """

    def __init__(
        self,
        client_id: str,
        strategy: RoutingStrategy,
        *,
        isl_range_km: float,
        hysteresis: float = 0.3,
    ) -> None:
        self.client_id = client_id
        self.strategy = strategy
        self.isl_range_km = isl_range_km
        self.hysteresis = hysteresis
        """Допустимое относительное ухудшение стоимости текущего/отремонтированного
        маршрута до перестроения: маршрут (или обход) принимается, пока его
        стоимость по весам действующей стратегии не превышает стоимость
        наилучшего доступного более чем в (1 + hysteresis) раз."""

        self.current: Route | None = None
        self.reroute_count: int = 0
        self.path_change_count: int = 0
        self.lifetimes_s: list[int] = []
        self._age_s: int = 0
        """Возраст текущего маршрута в секундах — накапливается на step_s на
        каждом KEPT/REPAIRED-отсчёте и фиксируется в lifetimes_s при замене
        (или принудительно — методом flush())."""

    def update(
        self,
        graph: NetworkGraph,
        *,
        utilisation: dict[tuple[str, str], float] | None = None,
        with_backup: bool = True,
        step_s: int = 1,
    ) -> RouteUpdate:
        """Обновляет сопровождаемый маршрут на очередном отсчёте.

        `step_s` — длительность отсчёта в секундах; накапливается в возрасте
        маршрута, чтобы `lifetimes_s` измерялись в секундах, а не в числе
        вызовов `update` (прогон передаёт сюда реальный шаг расчёта модели).
        `utilisation` и `with_backup` — см. `find_route`/`find_backup_route`.
        """
        best = find_route(
            graph,
            self.client_id,
            self.strategy,
            isl_range_km=self.isl_range_km,
            utilisation=utilisation,
        )
        best_cost = (
            route_cost(
                best, graph, self.strategy, isl_range_km=self.isl_range_km, utilisation=utilisation
            )
            if best is not None
            else None
        )

        if self.current is not None and self._is_intact(graph, self.current):
            refreshed = _build_route(self.current.path, graph)
            refreshed_cost = route_cost(
                refreshed,
                graph,
                self.strategy,
                isl_range_km=self.isl_range_km,
                utilisation=utilisation,
            )
            if best_cost is None or refreshed_cost <= best_cost * (1.0 + self.hysteresis):
                self.current = refreshed
                self._age_s += step_s
                return RouteUpdate(
                    refreshed,
                    RouteEvent.KEPT,
                    backup=self._backup(graph, refreshed, with_backup, utilisation),
                )

        if self.current is not None:
            repaired = self._repair(graph, utilisation)
            if repaired is not None:
                repaired_cost = route_cost(
                    repaired,
                    graph,
                    self.strategy,
                    isl_range_km=self.isl_range_km,
                    utilisation=utilisation,
                )
                if best_cost is None or repaired_cost <= best_cost * (1.0 + self.hysteresis):
                    # Локальный ремонт не увеличивает reroute_count: это и есть
                    # дешёвая (по переустановкам, не по вычислениям — см. докстроку
                    # класса) альтернатива полному перестроению. Но путь всё же
                    # физически изменился, поэтому path_change_count растёт.
                    self._close_lifetime()
                    self.current = repaired
                    self.path_change_count += 1
                    self._age_s = step_s
                    return RouteUpdate(
                        repaired,
                        RouteEvent.REPAIRED,
                        backup=self._backup(graph, repaired, with_backup, utilisation),
                    )
                # Обход нашёлся, но заметно хуже лучшего доступного — не
                # принимаем заплатку вслепую, падаем в полное перестроение.

        if best is None:
            self._close_lifetime()
            self.current = None
            self._age_s = 0
            return RouteUpdate(
                None, RouteEvent.LOST, reason=classify_no_route(graph, self.client_id)
            )

        self._close_lifetime()
        self.current = best
        self.reroute_count += 1
        self.path_change_count += 1
        self._age_s = step_s
        return RouteUpdate(
            best, RouteEvent.REBUILT, backup=self._backup(graph, best, with_backup, utilisation)
        )

    def flush(self) -> None:
        """Принудительно закрывает период жизни ТЕКУЩЕГО маршрута.

        `lifetimes_s` пополняется только при ЗАМЕНЕ маршрута (`_close_lifetime`
        вызывается из `update()` перед тем, как записать новый `current`) — а
        конец прогона не является заменой, поэтому без явного вызова время
        жизни последнего живого маршрута молча теряется, и среднее по
        `lifetimes_s` смещается вниз. Прогон вызывает `flush()` перед сбором
        показателей. Идемпотентен: после первого вызова возраст обнуляется,
        поэтому повторный вызов ничего не добавляет.
        """
        self._close_lifetime()
        self._age_s = 0

    def _is_intact(self, graph: NetworkGraph, route: Route) -> bool:
        """Все рёбра сохранённого маршрута всё ещё есть в графе отсчёта."""
        return all(
            graph.edge_length(left, right) is not None
            for left, right in zip(route.path, route.path[1:], strict=False)
        )

    def _repair(
        self, graph: NetworkGraph, utilisation: dict[tuple[str, str], float] | None
    ) -> Route | None:
        """Локальный обход единственного разорванного участка маршрута.

        Если разорвано ровно одно ребро — ищет замену через промежуточные
        аппараты, минимальную по весам ДЕЙСТВУЮЩЕЙ СТРАТЕГИИ (а не по числу
        переходов — иначе под MIN_LATENCY/LOAD_AWARE/ROBUST обход выбирался
        бы по критерию, отличному от того, по которому построен сам маршрут),
        не затрагивающую остальной путь. Если разорвано больше одного ребра
        (например, отказал аппарат — тогда рвутся сразу два смежных с ним
        ребра) — локальный ремонт не пытается угадывать, маршрут отправляется
        на полное перестроение. Качество найденного обхода (не хуже ли он
        наилучшего доступного) проверяет вызывающий код в `update()`.
        """
        assert self.current is not None
        broken = [
            (left, right)
            for left, right in zip(self.current.path, self.current.path[1:], strict=False)
            if graph.edge_length(left, right) is None
        ]
        if len(broken) != 1:
            return None

        left, right = broken[0]
        detour = _shortest_between(
            graph,
            left,
            right,
            forbidden=frozenset(self.current.path) - {left, right},
            strategy=self.strategy,
            isl_range_km=self.isl_range_km,
            utilisation=utilisation,
        )
        if detour is None:
            return None

        index = self.current.path.index(left)
        new_path = self.current.path[:index] + detour + self.current.path[index + 2 :]
        if len(set(new_path)) != len(new_path):
            return None

        return _build_route(new_path, graph)

    def _backup(
        self,
        graph: NetworkGraph,
        route: Route,
        with_backup: bool,
        utilisation: dict[tuple[str, str], float] | None,
    ) -> Route | None:
        """Резервный маршрут для текущего пути, если он вообще запрошен."""
        if not with_backup:
            return None
        return find_backup_route(
            graph,
            self.client_id,
            self.strategy,
            route,
            isl_range_km=self.isl_range_km,
            utilisation=utilisation,
        )

    def _close_lifetime(self) -> None:
        """Фиксирует возраст маршрута, который прямо сейчас заменяется/теряется."""
        if self._age_s:
            self.lifetimes_s.append(self._age_s)


def _shortest_between(
    graph: NetworkGraph,
    source: str,
    target: str,
    *,
    forbidden: frozenset[str],
    strategy: RoutingStrategy,
    isl_range_km: float,
    utilisation: dict[tuple[str, str], float] | None,
) -> tuple[str, ...] | None:
    """Кратчайший ПО ВЕСУ СТРАТЕГИИ участок между двумя узлами через аппараты.

    Промежуточные узлы обхода — только активные аппараты (наземные пункты не
    ретранслируют); сам `target` может быть и шлюзом, если ремонтируется
    последний участок маршрута. Минимизируется суммарный вес `_edge_weight`
    ТОЙ ЖЕ стратегии, что и основной маршрут, — не число переходов: под
    MIN_LATENCY/LOAD_AWARE/ROBUST обход по минимуму переходов мог бы оказаться
    коротким по числу хопов, но длинным (или дорогим) по факту. Возвращает
    путь включительно `source` и `target`, либо `None`, если обхода нет.
    """
    best_cost: dict[str, float] = {source: 0.0}
    previous: dict[str, str] = {}
    queue: list[tuple[float, str]] = [(0.0, source)]

    while queue:
        cost, node = heapq.heappop(queue)
        if cost > best_cost.get(node, float("inf")):
            continue
        if node == target:
            path = [target]
            while path[-1] != source:
                path.append(previous[path[-1]])
            path.reverse()
            return tuple(path)

        for neighbour, distance in graph.neighbours(node):
            if neighbour in forbidden:
                continue
            if neighbour != target and neighbour not in graph.satellites:
                continue
            weight = _edge_weight(
                node, neighbour, distance, strategy, graph, isl_range_km, utilisation
            )
            candidate = cost + weight
            if candidate < best_cost.get(neighbour, float("inf")):
                best_cost[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, neighbour))

    return None
