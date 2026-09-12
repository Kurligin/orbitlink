"""Показатели результата по каждому клиентскому пункту.

Обязательные показатели ТЗ — доля времени видимости, доля времени наличия
сквозного пути и максимальный перерыв — считаются только из состояний
геометрического слоя. Перерывы в начале и конце расчётного периода
учитываются отдельно от внутренних: их истинная длительность неизвестна,
она выходит за горизонт расчёта.

Два счётчика изменения маршрута — `reroute_count` (только полные
перестроения) и `path_change_count` (перестроения плюс локальные ремонты) —
считает `RouteTracker` (`orbitlink.core.tracker`), а не этот модуль:
`ClientAccumulator` наблюдает только `RouteUpdate` одного клиентского пункта
и не видит, был ли конкретный маршрут отремонтирован или перестроен заново.
Оба числа передаются в `finalise()` вызывающим кодом и переносятся в
`ClientMetrics`/`as_dict()` как есть.

Инвариант «доступность не выше видимости» — свойство самого расчёта, а не
требование к вызывающему коду: `observe()` считает отсчёт видимым, если
видимость передана явно ИЛИ на этом отсчёте нашёлся сквозной маршрут (см.
докстринг `observe`). Причина отсутствия маршрута тоже никогда не теряется:
если маршрута нет, а `update.reason` не указан, отсчёт попадает в отдельную
видимую корзину `UNSPECIFIED_REASON`, а не пропадает молча — иначе сумма
`reason_counts` разошлась бы с числом отсчётов без маршрута.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orbitlink.core.tracker import RouteUpdate

UNSPECIFIED_REASON = "unspecified"
"""Ключ `reason_counts` для отсчёта без маршрута и без явной причины.

`RouteUpdate.reason` типизирован как `NoRouteReason | None` — трекер сегодня
всегда передаёт причину, но контракт этим не гарантирован. Отдельный видимый
ключ (а не молчаливая потеря отсчёта и не слияние с одной из четырёх причин
ТЗ) держит инвариант «сумма reason_counts == число отсчётов без маршрута» и
не бросает исключение посреди прогона."""


@dataclass
class ClientMetrics:
    """Свод показателей результата по одному клиентскому пункту за прогон."""

    client_id: str
    steps: int
    step_s: int
    visibility_fraction: float
    availability_fraction: float
    max_gap_s: int
    gap_count: int
    leading_gap_s: int
    trailing_gap_s: int
    mean_hops: float | None
    mean_latency_ms: float | None
    backup_fraction: float
    reroute_count: int
    path_change_count: int
    mean_route_lifetime_s: float | None
    reason_counts: dict[str, int]
    margin_levels: list[int]
    target_met: bool

    def as_dict(self) -> dict:
        """Сериализуемое представление для отчёта/API — числа округлены."""
        return {
            "client_id": self.client_id,
            "steps": self.steps,
            "step_s": self.step_s,
            "visibility_fraction": round(self.visibility_fraction, 6),
            "availability_fraction": round(self.availability_fraction, 6),
            "max_gap_s": self.max_gap_s,
            "gap_count": self.gap_count,
            "leading_gap_s": self.leading_gap_s,
            "trailing_gap_s": self.trailing_gap_s,
            "mean_hops": None if self.mean_hops is None else round(self.mean_hops, 3),
            "mean_latency_ms": (
                None if self.mean_latency_ms is None else round(self.mean_latency_ms, 3)
            ),
            "backup_fraction": round(self.backup_fraction, 6),
            "reroute_count": self.reroute_count,
            "path_change_count": self.path_change_count,
            "mean_route_lifetime_s": (
                None if self.mean_route_lifetime_s is None else round(self.mean_route_lifetime_s, 1)
            ),
            "reason_counts": dict(self.reason_counts),
            "margin_levels": list(self.margin_levels),
            "target_met": self.target_met,
        }


@dataclass
class ClientAccumulator:
    """Накапливает наблюдения по отсчётам одного клиентского пункта.

    Запас связности (`margin_levels`) — намеренно трёхзначный: 0 — связи нет,
    1 — связь есть, но резервного пути нет, 2 — есть резерв. Различать «два»
    и «три и более» независимых пути сервис не пытается — это осознанное
    решение, а не недосмотр.
    """

    client_id: str
    step_s: int
    target_availability: float

    _steps: int = 0
    _visible_steps: int = 0
    _connected_steps: int = 0
    _backup_steps: int = 0
    _hops: list[int] = field(default_factory=list)
    _latency_ms: list[float] = field(default_factory=list)
    _reasons: dict[str, int] = field(default_factory=dict)
    _margin: list[int] = field(default_factory=list)
    _gaps: list[int] = field(default_factory=list)
    _current_gap: int = 0
    _leading_gap: int = 0
    _seen_connection: bool = False

    def observe(self, *, visible: bool, update: RouteUpdate) -> None:
        """Учитывает состояние клиентского пункта на одном отсчёте.

        `visible` — геометрическая видимость (клиентскому пункту видно хотя
        бы один аппарат), которой заполняется `visibility_fraction`. Реально
        учитываемая видимость — это `visible` ИЛИ сам факт найденного
        маршрута (`update.route is not None`): сквозной путь физически не
        существует без видимости хотя бы одного аппарата, поэтому наличие
        маршрута само по себе доказывает видимость на этом отсчёте, даже
        если вызывающий код передал `visible=False`. Это свойство расчёта, а
        не требование к вызывающему коду — оно и держит инвариант
        `availability_fraction <= visibility_fraction` структурно, а не на
        честном слове о согласованности аргументов.
        """
        self._steps += 1
        if visible or update.route is not None:
            self._visible_steps += 1

        if update.route is None:
            self._current_gap += 1
            key = update.reason.value if update.reason is not None else UNSPECIFIED_REASON
            self._reasons[key] = self._reasons.get(key, 0) + 1
            self._margin.append(0)
            return

        if self._current_gap:
            if self._seen_connection:
                # Внутренний перерыв: с обеих сторон он ограничен наблюдаемой
                # связью — его истинная длительность известна.
                self._gaps.append(self._current_gap)
            else:
                # Перерыв в начале периода: связи ещё не было ни разу, его
                # истинное начало могло быть и раньше горизонта расчёта.
                self._leading_gap = self._current_gap
            self._current_gap = 0

        self._seen_connection = True
        self._connected_steps += 1
        self._hops.append(update.route.hops)
        self._latency_ms.append(update.route.latency_ms)
        if update.backup is not None:
            self._backup_steps += 1
            self._margin.append(2)
        else:
            self._margin.append(1)

    def finalise(
        self, reroute_count: int, path_change_count: int, lifetimes_s: list[int]
    ) -> ClientMetrics:
        """Сводит накопленные наблюдения в `ClientMetrics`.

        `reroute_count` и `path_change_count` аккумулятор не считает сам —
        их предоставляет `RouteTracker` того же клиентского пункта (см. его
        докстринг про разницу между полным перестроением и локальным
        ремонтом). Оба числа переносятся в показатели без проверки, так как
        инвариант `path_change_count >= reroute_count` — контракт трекера,
        а не аккумулятора.
        """
        trailing = self._current_gap if self._seen_connection else 0
        leading = self._leading_gap if self._seen_connection else self._current_gap

        steps = max(self._steps, 1)
        availability = self._connected_steps / steps
        return ClientMetrics(
            client_id=self.client_id,
            steps=self._steps,
            step_s=self.step_s,
            visibility_fraction=self._visible_steps / steps,
            availability_fraction=availability,
            max_gap_s=(max(self._gaps) if self._gaps else 0) * self.step_s,
            gap_count=len(self._gaps),
            leading_gap_s=leading * self.step_s,
            trailing_gap_s=trailing * self.step_s,
            mean_hops=(sum(self._hops) / len(self._hops)) if self._hops else None,
            mean_latency_ms=(
                sum(self._latency_ms) / len(self._latency_ms) if self._latency_ms else None
            ),
            backup_fraction=self._backup_steps / steps,
            reroute_count=reroute_count,
            path_change_count=path_change_count,
            mean_route_lifetime_s=(sum(lifetimes_s) / len(lifetimes_s) if lifetimes_s else None),
            reason_counts=dict(self._reasons),
            margin_levels=list(self._margin),
            target_met=availability >= self.target_availability,
        )
