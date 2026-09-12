"""Показатели результата и их инварианты.

`finalise(reroute_count, path_change_count, lifetimes_s)` принимает оба
счётчика: полные перестроения и любые смены пути. Отдельные тесты проверяют,
что счётчики не путаются местами, что доступность не превышает видимость, что
отсчёт без маршрута и без причины попадает в отдельную корзину и что пустой
прогон даёт определённые показатели.
"""

import dataclasses

import pytest

from orbitlink.core.metrics import UNSPECIFIED_REASON, ClientAccumulator, ClientMetrics
from orbitlink.core.routing import NoRouteReason, Route
from orbitlink.core.tracker import RouteEvent, RouteUpdate

STEP_S = 120


def route(*nodes: str) -> Route:
    return Route(path=tuple(nodes), hops=len(nodes) - 1, length_km=3000.0, latency_ms=10.0)


def connected() -> RouteUpdate:
    return RouteUpdate(route("C65", "S01", "G_MUR"), RouteEvent.KEPT)


def lost(reason: NoRouteReason | None) -> RouteUpdate:
    return RouteUpdate(None, RouteEvent.LOST, reason=reason)


def build(
    observations,
    *,
    reroute_count: int = 1,
    path_change_count: int = 1,
    lifetimes_s: list[int] | None = None,
) -> ClientMetrics:
    accumulator = ClientAccumulator("C65", STEP_S, 0.9)
    for visible, update in observations:
        accumulator.observe(visible=visible, update=update)
    return accumulator.finalise(
        reroute_count=reroute_count,
        path_change_count=path_change_count,
        lifetimes_s=[240] if lifetimes_s is None else lifetimes_s,
    )


def test_availability_never_exceeds_visibility():
    metrics = build([(True, connected())] * 8 + [(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 2)
    assert metrics.availability_fraction <= metrics.visibility_fraction


def test_reason_counts_sum_to_steps_without_route():
    metrics = build(
        [(True, connected())] * 5
        + [(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 3
        + [(False, lost(NoRouteReason.NO_VISIBLE_SATELLITE))] * 2
    )
    without_route = metrics.steps - round(metrics.availability_fraction * metrics.steps)
    assert sum(metrics.reason_counts.values()) == without_route


def test_max_gap_is_multiple_of_step():
    metrics = build(
        [(True, connected())]
        + [(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 4
        + [(True, connected())]
    )
    assert metrics.max_gap_s == 4 * STEP_S
    assert metrics.max_gap_s % STEP_S == 0


def test_leading_and_trailing_gaps_are_counted_separately():
    """ТЗ: перерывы в начале и конце периода учитываются отдельно."""
    metrics = build(
        [(True, lost(NoRouteReason.NO_GATEWAY_CONTACT))] * 2
        + [(True, connected())] * 5
        + [(True, lost(NoRouteReason.NO_GATEWAY_CONTACT))] * 3
    )
    assert metrics.leading_gap_s == 2 * STEP_S
    assert metrics.trailing_gap_s == 3 * STEP_S
    assert metrics.gap_count == 0


def test_leading_gap_absorbs_a_period_with_no_connection_at_all():
    """Если сквозной связи не было ни разу за весь период — единственный
    перерыв целиком относится к краевым (его истинная длительность выходит
    за горизонт расчёта в обе стороны), а не считается внутренним."""
    metrics = build([(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 6)

    assert metrics.leading_gap_s == 6 * STEP_S
    assert metrics.trailing_gap_s == 0
    assert metrics.gap_count == 0
    assert metrics.availability_fraction == 0.0


def test_target_met_reflects_threshold():
    good = build([(True, connected())] * 10)
    bad = build([(True, connected())] * 5 + [(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 5)
    assert good.target_met is True
    assert bad.target_met is False


def test_margin_levels_track_backup_presence():
    accumulator = ClientAccumulator("C65", STEP_S, 0.9)
    accumulator.observe(
        visible=True, update=RouteUpdate(route("C65", "S01", "G_MUR"), RouteEvent.KEPT)
    )
    accumulator.observe(
        visible=True,
        update=RouteUpdate(
            route("C65", "S01", "G_MUR"), RouteEvent.KEPT, backup=route("C65", "S02", "G_MUR")
        ),
    )
    accumulator.observe(visible=False, update=lost(NoRouteReason.NO_VISIBLE_SATELLITE))
    metrics = accumulator.finalise(reroute_count=1, path_change_count=3, lifetimes_s=[120])

    assert metrics.margin_levels == [1, 2, 0]
    assert metrics.backup_fraction == pytest.approx(1 / 3)


def test_reroute_and_path_change_counts_are_independent_fields():
    """`ClientAccumulator` сам не отличает ремонт от перестроения — оба
    счётчика ему передаёт вызывающий код (`RouteTracker`, см. task-6-brief).
    Здесь числа заведомо разные и не кратны друг другу, чтобы тест не мог
    пройти при перепутанных местами аргументах или подмене одного счётчика
    другим."""
    metrics = build([(True, connected())] * 4, reroute_count=2, path_change_count=5)

    assert metrics.reroute_count == 2
    assert metrics.path_change_count == 5
    assert metrics.path_change_count != metrics.reroute_count

    as_dict = metrics.as_dict()
    assert as_dict["reroute_count"] == 2
    assert as_dict["path_change_count"] == 5


def test_mean_route_lifetime_and_hops_are_none_without_any_connection():
    """Показатели, зависящие от наличия хоть одного маршрута/времени жизни,
    обязаны быть `None`, а не 0.0 или ошибкой деления на ноль, если связи не
    было вовсе — включая `mean_route_lifetime_s`, для чего сюда передаётся
    заведомо пустой `lifetimes_s` (раньше `build()` жёстко прошивал
    `lifetimes_s=[240]`, и эта ветка была непроверяема в принципе, хотя тест
    её называл в своём имени)."""
    metrics = build([(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))] * 3, lifetimes_s=[])

    assert metrics.mean_hops is None
    assert metrics.mean_latency_ms is None
    assert metrics.mean_route_lifetime_s is None
    assert metrics.backup_fraction == 0.0


def test_as_dict_rounds_fractions_and_keeps_all_fields():
    """`as_dict()` — сериализуемое представление для отчёта/API: обязано
    нести все поля `ClientMetrics` (включая оба счётчика изменения маршрута),
    а дроби в нём — округлёнными, а не сырым float. 1/3 и 401/3 не
    представимы точно двоичным float, поэтому сравнение сырого значения с
    округлённым доказывает, что `round()` реально применяется внутри
    `as_dict()`, а не просто совпадает с уже круглым числом."""
    accumulator = ClientAccumulator("C65", STEP_S, 0.9)
    accumulator.observe(visible=True, update=connected())
    accumulator.observe(visible=True, update=lost(NoRouteReason.ISL_NETWORK_SPLIT))
    accumulator.observe(visible=True, update=lost(NoRouteReason.ISL_NETWORK_SPLIT))
    metrics = accumulator.finalise(
        reroute_count=3, path_change_count=7, lifetimes_s=[100, 150, 151]
    )

    payload = metrics.as_dict()
    expected_keys = {f.name for f in dataclasses.fields(ClientMetrics)}
    assert expected_keys, "у ClientMetrics не оказалось ни одного поля — дальше нечего проверять"
    assert set(payload) == expected_keys

    assert metrics.availability_fraction != round(metrics.availability_fraction, 6)
    assert payload["availability_fraction"] == round(metrics.availability_fraction, 6)
    assert metrics.mean_route_lifetime_s != round(metrics.mean_route_lifetime_s, 1)
    assert payload["mean_route_lifetime_s"] == round(metrics.mean_route_lifetime_s, 1)
    assert payload["reroute_count"] == 3
    assert payload["path_change_count"] == 7


def test_visible_flag_cannot_undercount_a_step_with_a_found_route():
    """Инвариант `availability_fraction <= visibility_fraction`
    обязан держаться структурно, а не на честном слове вызывающего кода.
    Здесь вызывающий код ошибочно передаёт `visible=False` вместе с уже
    найденным маршрутом — без поправки в `observe()` это дало бы
    `visibility_fraction == 0.0` при `availability_fraction == 1.0` и сломало
    бы инвариант; эффективная видимость обязана учесть сам факт
    наличия маршрута."""
    accumulator = ClientAccumulator("C65", STEP_S, 0.9)
    accumulator.observe(visible=False, update=connected())
    metrics = accumulator.finalise(reroute_count=1, path_change_count=1, lifetimes_s=[STEP_S])

    assert metrics.visibility_fraction == 1.0, "найденный маршрут обязан засчитаться как видимость"
    assert metrics.availability_fraction <= metrics.visibility_fraction


def test_missing_route_without_reason_is_still_counted_in_reason_counts():
    """`RouteUpdate.reason` типизирован как `NoRouteReason |
    None`, и `observe()` не должен полагаться на то, что трекер всегда
    передаёт причину. Здесь передан `reason=None` при отсутствующем
    маршруте — отсчёт обязан попасть в отдельную видимую корзину
    `UNSPECIFIED_REASON`, а не потеряться: сумма по `reason_counts` обязана
    остаться равной числу отсчётов без маршрута."""
    metrics = build(
        [(True, connected())]
        + [(True, lost(None))]
        + [(True, lost(NoRouteReason.ISL_NETWORK_SPLIT))]
    )

    without_route = metrics.steps - round(metrics.availability_fraction * metrics.steps)
    assert sum(metrics.reason_counts.values()) == without_route
    assert metrics.reason_counts[UNSPECIFIED_REASON] == 1


def test_finalise_without_any_observation_is_well_defined():
    """Вырожденный вход — `finalise()` вызван без единого
    предшествующего `observe()`. Показатели обязаны быть определены (без
    деления на ноль и без исключений), доли — нулевыми, а цель — не
    достигнутой."""
    accumulator = ClientAccumulator("C65", STEP_S, 0.9)
    metrics = accumulator.finalise(reroute_count=0, path_change_count=0, lifetimes_s=[])

    assert metrics.steps == 0
    assert metrics.visibility_fraction == 0.0
    assert metrics.availability_fraction == 0.0
    assert metrics.backup_fraction == 0.0
    assert metrics.max_gap_s == 0
    assert metrics.gap_count == 0
    assert metrics.leading_gap_s == 0
    assert metrics.trailing_gap_s == 0
    assert metrics.mean_hops is None
    assert metrics.mean_latency_ms is None
    assert metrics.mean_route_lifetime_s is None
    assert metrics.reason_counts == {}
    assert metrics.margin_levels == []
    assert metrics.target_met is False
