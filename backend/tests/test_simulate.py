"""Прогон по сетке времени: сверка с опорными значениями разведки."""

import copy
import time

import pytest

from orbitlink.core.geometry import ConstellationModel
from orbitlink.core.metrics import ClientAccumulator
from orbitlink.core.routing import RoutingStrategy
from orbitlink.core.scenario import load_scenario
from orbitlink.core.simulate import GeometryCache, simulate
from orbitlink.core.tracker import RouteTracker
from tests.conftest import read_scenario

TOLERANCE = 0.002

EXPECTED_AVAILABILITY = {
    "01_full_constellation": {"C65": 0.967, "C70": 0.988, "C72": 0.989},
    "02_first_launch": {"C65": 0.272, "C70": 0.158, "C72": 0.126},
    "03_satellite_outages": {"C65": 0.793, "C70": 0.808, "C72": 0.825},
    "04_link_range": {"C65": 0.775, "C70": 0.622, "C72": 0.651},
}

EXPECTED_VISIBILITY = {
    "04_link_range": {"C65": 0.978, "C70": 0.999, "C72": 1.0},
}

# Замер MIN_LATENCY/LOAD_AWARE/ROBUST/MIN_HOPS на 01_full_constellation — фактический
# прогон (детерминированный: геометрия + Дейкстра без случайности), см. таблицу и
# разбор гипотезы про ROBUST в task-6-report.md. Числа зафиксированы как регрессия:
# если поиск или сопровождение маршрута изменятся, тест укажет, что именно и где.
EXPECTED_STABILITY = {
    RoutingStrategy.MIN_HOPS: {"C65": (308, 371), "C70": (350, 480), "C72": (493, 563)},
    RoutingStrategy.MIN_LATENCY: {"C65": (301, 372), "C70": (368, 483), "C72": (461, 562)},
    RoutingStrategy.LOAD_AWARE: {"C65": (301, 372), "C70": (360, 483), "C72": (422, 546)},
    RoutingStrategy.ROBUST: {"C65": (305, 376), "C70": (395, 502), "C72": (527, 602)},
}


@pytest.mark.parametrize("name", sorted(EXPECTED_AVAILABILITY))
def test_availability_matches_reconnaissance(name):
    result = simulate(load_scenario(read_scenario(name)), strategy=RoutingStrategy.MIN_HOPS)

    for client_id, expected in EXPECTED_AVAILABILITY[name].items():
        actual = result.clients[client_id].availability_fraction
        assert actual == pytest.approx(expected, abs=TOLERANCE), f"{name}/{client_id}"


def test_visibility_stays_high_when_isl_range_shrinks():
    """Ключевой вывод кейса: видимость почти полная, а сквозной связи нет."""
    result = simulate(
        load_scenario(read_scenario("04_link_range")), strategy=RoutingStrategy.MIN_HOPS
    )

    for client_id, expected in EXPECTED_VISIBILITY["04_link_range"].items():
        metrics = result.clients[client_id]
        assert metrics.visibility_fraction == pytest.approx(expected, abs=TOLERANCE)
        assert metrics.availability_fraction < metrics.visibility_fraction - 0.1


def test_isl_split_dominates_reasons_in_link_range_scenario():
    result = simulate(
        load_scenario(read_scenario("04_link_range")), strategy=RoutingStrategy.MIN_HOPS
    )
    reasons = result.clients["C70"].reason_counts
    assert reasons.get("isl_network_split", 0) > sum(
        count for key, count in reasons.items() if key != "isl_network_split"
    )


def test_max_gap_in_full_constellation():
    result = simulate(
        load_scenario(read_scenario("01_full_constellation")),
        strategy=RoutingStrategy.MIN_HOPS,
    )
    assert result.clients["C65"].max_gap_s == 480
    assert result.clients["C70"].max_gap_s == 120
    assert result.clients["C72"].max_gap_s == 120


def test_route_records_cover_every_step_and_client():
    scenario = load_scenario(read_scenario("01_full_constellation"))
    result = simulate(scenario)

    clients = [g["id"] for g in scenario["ground_sites"] if g["role"] == "client"]
    assert len(result.routes) == len(result.times) * len(clients)

    pairs = {(record.t_s, record.client_id) for record in result.routes}
    assert len(pairs) == len(result.routes)


def test_records_without_route_carry_reason_and_empty_path():
    result = simulate(load_scenario(read_scenario("02_first_launch")))
    disconnected = [record for record in result.routes if not record.path]

    assert disconnected
    for record in disconnected:
        assert record.reason is not None
        assert record.hops is None


def test_cache_reuse_matches_direct_run():
    scenario = load_scenario(read_scenario("03_satellite_outages"))
    model = ConstellationModel(scenario)
    cache = GeometryCache(model)

    cached = simulate(scenario, cache=cache, strategy=RoutingStrategy.MIN_HOPS)
    direct = simulate(scenario, strategy=RoutingStrategy.MIN_HOPS)

    assert direct.clients, "в сценарии нет клиентских пунктов — сравнивать нечего"
    for client_id, metrics in direct.clients.items():
        assert cached.clients[client_id].availability_fraction == pytest.approx(
            metrics.availability_fraction
        )


def test_full_run_is_fast_enough_for_interactive_use():
    scenario = load_scenario(read_scenario("01_full_constellation"))
    started = time.perf_counter()
    simulate(scenario)
    assert time.perf_counter() - started < 5.0


def test_cache_built_without_failure_still_applies_failure_of_passed_scenario():
    """Регрессия на дефект, из-за которого кэш геометрии игнорировал переданный сценарий.

    Кэш строится по сценарию БЕЗ отказов, а прогоняется сценарий с одним аппаратом,
    отказавшим на весь горизонт. Если бы `GeometryCache.snapshot_at`/`graph_at` брали
    маску активности из модели, зашитой в кэш при создании, а не из модели, переданной
    им аргументом (построенной по прогоняемому сценарию), — добавленный отказ был бы
    молча проигнорирован, и результат совпал бы с прогоном без отказа. Тест ловит
    именно это: сначала убеждается, что отказ вообще меняет доступность (иначе
    сравнение ниже прошло бы, даже полностью игнорируя отказ), затем — что прогон с
    чужим кэшем даёт тот же результат, что и прогон без кэша вовсе.
    """
    baseline = load_scenario(read_scenario("01_full_constellation"))
    cache_from_baseline = GeometryCache(ConstellationModel(baseline))

    failing_satellite = baseline["design"]["satellites"][0]["id"]
    with_failure = copy.deepcopy(baseline)
    with_failure["failures"] = [
        {
            "satellite_id": failing_satellite,
            "start_s": 0,
            "end_s": with_failure["environment"]["horizon_s"],
        }
    ]
    with_failure = load_scenario(with_failure)

    baseline_run = simulate(baseline, strategy=RoutingStrategy.MIN_HOPS)
    direct_with_failure = simulate(with_failure, strategy=RoutingStrategy.MIN_HOPS)
    cached_with_failure = simulate(
        with_failure, cache=cache_from_baseline, strategy=RoutingStrategy.MIN_HOPS
    )

    # Предпосылка теста: отказ аппарата должен реально повлиять на доступность —
    # иначе тест ничего бы не различал.
    assert any(
        direct_with_failure.clients[cid].availability_fraction
        != pytest.approx(baseline_run.clients[cid].availability_fraction)
        for cid in direct_with_failure.clients
    ), "отказ спутника не повлиял на доступность — сценарий для теста непоказателен"

    for client_id, metrics in direct_with_failure.clients.items():
        assert cached_with_failure.clients[client_id].availability_fraction == pytest.approx(
            metrics.availability_fraction
        ), f"{client_id}: чужой кэш геометрии проигнорировал отказ переданного сценария"


def test_load_aware_route_choice_differs_from_min_latency_on_some_steps():
    """Обязательный тест производителя занятости линий (иначе LOAD_AWARE == MIN_LATENCY).

    Клиентские пункты обслуживаются на каждом отсчёте последовательно, и маршрут
    очередного пункта видит рёбра, уже занятые предыдущими. Если производитель не
    подключён (словарь занятости остаётся пустым), выбор маршрута LOAD_AWARE ничем
    не отличается от MIN_LATENCY ни на одном отсчёте.
    """
    scenario = load_scenario(read_scenario("01_full_constellation"))
    load_aware = simulate(scenario, strategy=RoutingStrategy.LOAD_AWARE)
    min_latency = simulate(scenario, strategy=RoutingStrategy.MIN_LATENCY)

    load_aware_paths = {(r.t_s, r.client_id): tuple(r.path) for r in load_aware.routes}
    min_latency_paths = {(r.t_s, r.client_id): tuple(r.path) for r in min_latency.routes}
    assert load_aware_paths.keys() == min_latency_paths.keys()

    differing = sum(
        1 for key in load_aware_paths if load_aware_paths[key] != min_latency_paths[key]
    )
    assert (
        differing > 0
    ), "LOAD_AWARE совпал с MIN_LATENCY на каждом отсчёте — занятость не читается"


def test_route_stability_measured_across_all_strategies():
    """Замер: полная группировка, все 4 стратегии, оба счётчика по каждому клиенту.

    Числа перенесены в таблицу отчёта (task-6-report.md) как есть, без подгонки.
    """
    scenario = load_scenario(read_scenario("01_full_constellation"))

    for strategy, per_client in EXPECTED_STABILITY.items():
        result = simulate(scenario, strategy=strategy)
        for client_id, (reroute, path_change) in per_client.items():
            metrics = result.clients[client_id]
            actual = (metrics.reroute_count, metrics.path_change_count)
            assert actual == (reroute, path_change), f"{strategy.value}/{client_id}: {actual}"


def test_robust_strategy_does_not_reduce_path_changes_versus_min_latency():
    """Проверка рабочей гипотезы задачи: не подтверждается на этих данных.

    Гипотеза — ROBUST штрафует линии у предела дальности и поэтому должен меньше
    менять путь, чем MIN_LATENCY. Фактический замер (см. EXPECTED_STABILITY и
    разбор в task-6-report.md) показывает обратное на всех трёх клиентских пунктах
    полной группировки: `path_change_count` у ROBUST не меньше, чем у MIN_LATENCY.
    Тест фиксирует фактическое соотношение, а не желаемое, — он обязан упасть, если
    это соотношение неожиданно перевернётся в будущем.
    """
    scenario = load_scenario(read_scenario("01_full_constellation"))
    robust = simulate(scenario, strategy=RoutingStrategy.ROBUST)
    min_latency = simulate(scenario, strategy=RoutingStrategy.MIN_LATENCY)

    for client_id in ("C65", "C70", "C72"):
        assert (
            robust.clients[client_id].path_change_count
            >= min_latency.clients[client_id].path_change_count
        ), f"{client_id}: ROBUST внезапно стал стабильнее MIN_LATENCY — гипотеза подтвердилась"


def test_simulate_rejects_cache_built_for_different_isl_range():
    """Кэш, построенный для одной дальности связи, не должен молча обслуживать другую.

    `01_full_constellation` и `04_link_range` отличаются именно `isl_range_km`
    (3000 против 2000 км). Дальность запекается в состав межспутниковых рёбер
    кэша при постройке (`_potential_links`), поэтому кэш от одного сценария не
    подходит другому: если бы `simulate` не сверял кэш с моделью, состав рёбер
    остался бы от 3000 км, а трекер и штраф ROBUST брали бы 2000 км из
    модели — числа получились бы тихо неверными, а не громко упавшими.
    """
    wide_range_scenario = load_scenario(read_scenario("01_full_constellation"))
    narrow_range_scenario = load_scenario(read_scenario("04_link_range"))
    assert (
        wide_range_scenario["environment"]["isl_range_km"]
        != narrow_range_scenario["environment"]["isl_range_km"]
    ), "сценарии для теста должны отличаться дальностью связи"

    cache = GeometryCache(ConstellationModel(wide_range_scenario))

    with pytest.raises(ValueError):
        simulate(narrow_range_scenario, cache=cache, strategy=RoutingStrategy.MIN_HOPS)


def test_simulate_closes_last_route_lifetime_before_collecting_metrics():
    """Регрессия: `simulate` обязан вызывать `RouteTracker.flush()` перед сбором показателей.

    `RouteTracker.flush()` сам по себе уже проверен на уровне модуля `tracker`
    (`tests/test_tracker.py`) — здесь проверяется другое: что производственный
    код `simulate()` его действительно вызывает, а не просто что `flush()` умеет
    закрывать период жизни. Тест воспроизводит внутренний цикл `simulate()`
    вручную для одного клиентского пункта — один раз без `flush()`, один раз с
    ним — и убеждается, что результат `simulate()` совпадает именно с версией
    "с flush()". Если убрать вызов `flush()` из `simulate()`, эта проверка
    упадёт, потому что тогда `simulate()` начнёт отдавать версию "без flush()".
    """
    scenario = load_scenario(read_scenario("01_full_constellation"))
    model = ConstellationModel(scenario)
    cache = GeometryCache(model)
    client_id = model.client_ids[0]

    tracker = RouteTracker(client_id, RoutingStrategy.MIN_LATENCY, isl_range_km=model.isl_range_km)
    accumulator = ClientAccumulator(client_id, model.step_s, model.target_availability)
    for index in range(len(cache.times)):
        graph = cache.graph_at(index, model)
        update = tracker.update(graph, step_s=model.step_s)
        accumulator.observe(visible=bool(graph.visible_satellites(client_id)), update=update)

    lifetimes_without_flush = list(tracker.lifetimes_s)
    tracker.flush()
    lifetimes_with_flush = list(tracker.lifetimes_s)

    # Предпосылка теста: маршрут этого клиента должен быть ещё жив на последнем
    # отсчёте (иначе flush() closes nothing new, и сравнение ниже ничего бы не показало).
    assert lifetimes_with_flush != lifetimes_without_flush, (
        f"маршрут {client_id} не жив на последнем отсчёте выбранного сценария — "
        "тест для него не показателен"
    )

    metrics_with_flush = accumulator.finalise(
        tracker.reroute_count, tracker.path_change_count, lifetimes_with_flush
    )
    metrics_without_flush = accumulator.finalise(
        tracker.reroute_count, tracker.path_change_count, lifetimes_without_flush
    )
    assert metrics_with_flush.mean_route_lifetime_s != metrics_without_flush.mean_route_lifetime_s

    result = simulate(scenario, strategy=RoutingStrategy.MIN_LATENCY)
    actual = result.clients[client_id].mean_route_lifetime_s
    assert actual == pytest.approx(metrics_with_flush.mean_route_lifetime_s)
    assert actual != pytest.approx(metrics_without_flush.mean_route_lifetime_s)
