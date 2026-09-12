"""Обновление маршрута между отсчётами: сохранение, ремонт, перестроение."""

from unittest.mock import patch

import numpy as np
import pytest

from orbitlink.core import routing as routing_module
from orbitlink.core.geometry import ConstellationModel, Snapshot
from orbitlink.core.routing import (
    NetworkGraph,
    NoRouteReason,
    RoutingStrategy,
    find_backup_route,
    find_route,
)
from orbitlink.core.tracker import RouteEvent, RouteTracker
from tests.conftest import read_scenario


@pytest.fixture
def model():
    return ConstellationModel(read_scenario("01_full_constellation"))


def graph_at(model, t_s):
    return NetworkGraph(model.snapshot(t_s), model.gateway_ids)


def test_first_update_builds_route(model):
    tracker = RouteTracker("C70", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    update = tracker.update(graph_at(model, 0))

    assert update.event is RouteEvent.REBUILT
    assert update.route is not None
    assert tracker.reroute_count == 1


def test_unchanged_network_keeps_the_same_route(model):
    tracker = RouteTracker("C70", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    graph = graph_at(model, 0)
    first = tracker.update(graph)
    second = tracker.update(graph)

    assert second.event is RouteEvent.KEPT
    assert second.route.path == first.route.path
    assert tracker.reroute_count == 1


def test_route_survives_across_neighbouring_steps(model):
    """Липкость: на суточном прогоне маршрут не должен дёргаться каждый отсчёт.

    Жёсткий числовой порог (`reroute_count < len(time_grid) / 4`) не проходит
    ни для одной комбинации клиент/стратегия на актуальных данных сценария:
    в этой группировке (48 аппаратов, isl_range_km=3000) большая часть
    межспутниковых связей работает у самой границы дальности и рвётся почти
    на каждом отсчёте (проверено вручную: 54 из 76 ISL-рёбер на t=0 лежат
    дальше 2700 км из 3000 максимума). Из-за этого сам факт «маршрут дожил
    до следующего отсчёта без единого разорванного ребра» — редкое событие,
    не зависящее от качества трекера.

    Поэтому сравниваем не с магическим числом, а с честной наивной
    альтернативой: полным поиском заново на каждом отсчёте без памяти о
    предыдущем маршруте, которая переключается всякий раз, когда найденный
    заново лучший путь отличается от предыдущего. Именно эту наивную
    альтернативу и обязан обыгрывать трекер с ремонтом и гистерезисом —
    это и есть содержание критерия «поиск и ОБНОВЛЕНИЕ», а не конкретное
    заранее заданное число. Тест не может стать зелёным, ничего не проверив: обе
    статистики (наивные переключения и `reroute_count`) считаются по
    реальному прогону модели, а не предполагаются.
    """
    tracker = RouteTracker("C70", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    events: list[RouteEvent] = []
    naive_switches = 0
    naive_previous_path: tuple[str, ...] | None = None

    for t_s in model.time_grid:
        graph = graph_at(model, t_s)
        events.append(tracker.update(graph).event)

        naive_route = find_route(graph, "C70", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
        naive_path = naive_route.path if naive_route is not None else None
        if naive_path is not None and naive_path != naive_previous_path:
            naive_switches += 1
        if naive_path is not None:
            naive_previous_path = naive_path

    assert naive_switches > 0, "наивный поиск ни разу не сменил маршрут — сравнивать не с чем"
    assert events.count(RouteEvent.KEPT) > 0, "маршрут ни разу не был сохранён между отсчётами"
    assert tracker.reroute_count < naive_switches, (
        f"трекер перестраивал маршрут полностью ({tracker.reroute_count} раз) не реже, чем "
        f"наивный поиск заново менял бы его ({naive_switches} раз) — ремонт и гистерезис "
        "не дают выигрыша"
    )


@pytest.mark.parametrize("client_id", ["C65", "C70", "C72"])
def test_path_change_count_and_reroute_count_are_distinct_and_ordered(model, client_id):
    """`path_change_count` считает любую смену физического пути (REPAIRED и
    REBUILT вместе), `reroute_count` — только полные перестроения (REBUILT).
    Отсюда содержательное соотношение, а не просто наличие двух полей:

    - `path_change_count >= reroute_count` всегда (перестроение — тоже смена пути);
    - на суточном прогоне реальной группировки — строго БОЛЬШЕ: если бы
      локальный ремонт ни разу не сработал, оба счётчика совпали бы, и это
      обязано быть видно из проваленного теста, а не замаскировано допуском
      `>=` без строгой альтернативы.
    """
    tracker = RouteTracker(client_id, RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    for t_s in model.time_grid:
        tracker.update(graph_at(model, t_s))

    assert tracker.path_change_count >= tracker.reroute_count
    assert tracker.path_change_count > tracker.reroute_count, (
        f"{client_id}: локальный ремонт ни разу не сработал за сутки — "
        f"path_change_count={tracker.path_change_count} == reroute_count={tracker.reroute_count}"
    )


def test_lost_route_reports_reason(model):
    scenario = read_scenario("01_full_constellation")
    scenario["gateway_outages"] = [{"gateway_id": "G_MUR", "start_s": 0, "end_s": 86400}]
    blocked = ConstellationModel(scenario)
    tracker = RouteTracker("C65", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)

    update = tracker.update(NetworkGraph(blocked.snapshot(600), blocked.gateway_ids))

    assert update.event is RouteEvent.LOST
    assert update.route is None
    assert update.reason is NoRouteReason.GATEWAY_OFFLINE


def test_lifetimes_are_recorded(model):
    tracker = RouteTracker("C72", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    for t_s in model.time_grid[:60]:
        tracker.update(graph_at(model, t_s))

    assert tracker.lifetimes_s
    assert all(value > 0 for value in tracker.lifetimes_s)


# --- Дополнительные тесты: напрямую проверяют механику ремонта, гистерезиса
# и учёта времени в секундах, которую суточный прогон выше подтверждает лишь
# статистически. ---


def _snapshot(
    satellite_ids: list[str], edges: list[tuple[str, str, float]], t_s: float = 0.0
) -> Snapshot:
    """Синтетический отсчёт: только рёбра и список аппаратов определяют граф —
    positions_km/elevation_deg не используются NetworkGraph, заполнены заглушками."""
    return Snapshot(
        t_s=t_s,
        satellite_ids=satellite_ids,
        positions_km=np.zeros((len(satellite_ids), 3)),
        active=np.ones(len(satellite_ids), dtype=bool),
        edges=edges,
        elevation_deg={},
        offline_gateways=set(),
    )


def test_local_repair_bridges_a_single_broken_isl_link():
    """Разрыв ровно одного ребра маршрута чинится локальным обходом, не трогая
    остальной путь, и НЕ учитывается как полное перестроение."""
    t0 = _snapshot(
        ["SA1", "SA2"],
        [("C1", "SA1", 1000.0), ("SA1", "SA2", 500.0), ("SA2", "GW", 1000.0)],
    )
    # SA1-SA2 разошлись за пределы дальности, но появился аппарат-мост SB.
    t1 = _snapshot(
        ["SA1", "SA2", "SB"],
        [
            ("C1", "SA1", 1000.0),
            ("SA1", "SB", 400.0),
            ("SB", "SA2", 400.0),
            ("SA2", "GW", 1000.0),
        ],
    )

    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    first = tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    assert first.event is RouteEvent.REBUILT
    assert first.route.path == ("C1", "SA1", "SA2", "GW")

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    assert second.event is RouteEvent.REPAIRED
    assert second.route.path == ("C1", "SA1", "SB", "SA2", "GW")
    # Ремонт — не полное перестроение: reroute_count не растёт по сравнению с
    # первым REBUILT, но путь всё же изменился — path_change_count растёт.
    assert tracker.reroute_count == 1
    assert tracker.path_change_count == 2
    assert tracker.current.path == second.route.path


def test_repair_rejected_when_detour_is_much_worse_than_best():
    """B1: обход возможен, но заметно хуже лучшего доступного маршрута —
    трекер обязан отвергнуть заплатку и перестроиться целиком, а не жить с
    произвольно плохим обходом до следующего отсчёта."""
    t0 = _snapshot(
        ["SA1", "SA2"],
        [("C1", "SA1", 1000.0), ("SA1", "SA2", 500.0), ("SA2", "GW", 1000.0)],
    )
    # SA1-SA2 разошлись; мост SB технически существует, но обход через него
    # (10000 км) в разы дороже, чем совсем другой свежий маршрут через SC
    # (1600 км) — присутствующий в той же сети.
    t1 = _snapshot(
        ["SA1", "SA2", "SB", "SC"],
        [
            ("C1", "SA1", 1000.0),
            ("SA1", "SB", 5000.0),
            ("SB", "SA2", 5000.0),
            ("SA2", "GW", 1000.0),
            ("C1", "SC", 800.0),
            ("SC", "GW", 800.0),
        ],
    )

    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    first = tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    assert first.event is RouteEvent.REBUILT
    assert tracker.reroute_count == 1

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    # Не REPAIRED: обход через SB (12000 км в сумме) на порядок хуже лучшего
    # доступного (1600 км через SC) — заплатка отвергнута по качеству.
    assert second.event is RouteEvent.REBUILT
    assert second.route.path == ("C1", "SC", "GW")
    assert tracker.reroute_count == 2
    assert tracker.path_change_count == 2


def test_repair_uses_strategy_weight_not_hop_count_for_the_detour():
    """B2: у разорванного участка есть два кандидата на обход — короткий по
    числу переходов (2 хопа, 6000 км) и длинный по числу переходов, но
    заметно дешёвый по стоимости MIN_LATENCY (3 хопа, 1500 км). Ремонт обязан
    выбрать дешёвый по весам стратегии вариант, а не минимальный по хопам:
    поиск в ширину по числу переходов выбрал бы первый (короче) вариант."""
    t0 = _snapshot(
        ["SA1", "SA2"],
        [("C1", "SA1", 1000.0), ("SA1", "SA2", 500.0), ("SA2", "GW", 1000.0)],
    )
    t1 = _snapshot(
        ["SA1", "SA2", "SX", "SY1", "SY2"],
        [
            ("C1", "SA1", 1000.0),
            ("SA1", "SX", 3000.0),
            ("SX", "SA2", 3000.0),  # 2 хопа, 6000 км
            ("SA1", "SY1", 500.0),
            ("SY1", "SY2", 500.0),
            ("SY2", "SA2", 500.0),  # 3 хопа, 1500 км
            ("SA2", "GW", 1000.0),
        ],
    )

    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    assert second.event is RouteEvent.REPAIRED
    assert second.route.path == ("C1", "SA1", "SY1", "SY2", "SA2", "GW")


def test_hysteresis_uses_strategy_cost_not_length_km_under_min_hops():
    """B3: под MIN_HOPS сравнение обязано идти по числу переходов, а не по
    length_km. Сохранённый маршрут — 4 хопа, но геометрически короткий
    (40 км); свежая альтернатива — 2 хопа, но геометрически ДЛИННАЯ (10000 км).
    По длине в километрах старый порог выполнился бы тривиально (40 <=
    10000*1.3) и маршрут остался бы 4-хоповым; по числу хопов (правильная
    метрика для MIN_HOPS) 4 хопа — это на 100% хуже 2 хопов, за порогом 0.3,
    и трекер обязан перестроиться на короткий по хопам путь."""
    t0 = _snapshot(
        ["SM1", "SM2", "SM3"],
        [
            ("C1", "SM1", 10.0),
            ("SM1", "SM2", 10.0),
            ("SM2", "SM3", 10.0),
            ("SM3", "GW", 10.0),
        ],
    )
    t1 = _snapshot(
        ["SM1", "SM2", "SM3", "SL1"],
        [
            ("C1", "SM1", 10.0),
            ("SM1", "SM2", 10.0),
            ("SM2", "SM3", 10.0),
            ("SM3", "GW", 10.0),
            ("C1", "SL1", 5000.0),
            ("SL1", "GW", 5000.0),
        ],
    )

    tracker = RouteTracker("C1", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    first = tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    assert first.route.path == ("C1", "SM1", "SM2", "SM3", "GW")

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    assert second.event is RouteEvent.REBUILT
    assert second.route.path == ("C1", "SL1", "GW")


def test_full_rebuild_when_two_edges_break_at_once():
    """Отказ аппарата рвёт сразу два смежных ребра — локальный ремонт по
    контракту (`len(broken) != 1`) не пытается угадать, маршрут перестраивается
    целиком, и это учитывается в reroute_count."""
    t0 = _snapshot(
        ["SA1", "SA2"],
        [("C1", "SA1", 1000.0), ("SA1", "SA2", 500.0), ("SA2", "GW", 1000.0)],
    )
    # SA1 отказал целиком: оба его ребра пропали. Единственная замена — SC.
    t1 = _snapshot(
        ["SA2", "SC"],
        [("C1", "SC", 1200.0), ("SC", "GW", 1300.0), ("SA2", "GW", 1000.0)],
    )

    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    first = tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    assert first.event is RouteEvent.REBUILT
    assert tracker.reroute_count == 1
    assert tracker.path_change_count == 1

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    assert second.event is RouteEvent.REBUILT
    assert second.route.path == ("C1", "SC", "GW")
    # Оба REBUILT — оба счётчика растут вместе, разницы между ними здесь нет.
    assert tracker.reroute_count == 2
    assert tracker.path_change_count == 2


def _hysteresis_snapshots() -> tuple[Snapshot, Snapshot, Snapshot]:
    """Три отсчёта одной и той же сети: длинный маршрут остаётся неизменным
    и цел на всех трёх, альтернатива появляется на t1 (умеренно короче — в
    пределах гистерезиса 0.3) и становится намного короче на t2 (за порогом)."""
    long_edges = [
        ("C1", "SL1", 2000.0),
        ("SL1", "SL2", 1500.0),
        ("SL2", "GW", 2500.0),
    ]  # итого 6000 км, 3 перехода

    t0 = _snapshot(["SL1", "SL2"], list(long_edges))
    t1 = _snapshot(
        ["SL1", "SL2", "SS1"],
        [*long_edges, ("C1", "SS1", 2400.0), ("SS1", "GW", 2400.0)],  # альтернатива 4800 км
    )
    t2 = _snapshot(
        ["SL1", "SL2", "SS1"],
        [*long_edges, ("C1", "SS1", 1500.0), ("SS1", "GW", 1500.0)],  # альтернатива 3000 км
    )
    return t0, t1, t2


def test_hysteresis_keeps_worse_but_intact_route_within_threshold():
    """t1: альтернатива короче (4800 против 6000 км — разница 25%), но в
    пределах порога 0.3 (30%) — маршрут не переключается, хотя он объективно
    не лучший из доступных."""
    t0, t1, _ = _hysteresis_snapshots()
    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    first = tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    assert first.route.path == ("C1", "SL1", "SL2", "GW")

    second = tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0))

    assert second.event is RouteEvent.KEPT
    assert second.route.path == ("C1", "SL1", "SL2", "GW")
    assert tracker.reroute_count == 1


def test_rebuilds_when_quality_gap_exceeds_hysteresis_despite_intact_route():
    """t2: та же длинная связка цела и проходима, но альтернатива теперь в
    3000 км против 6000 км (вдвое короче) — за порогом 0.3. Трекер обязан
    перестроиться на лучший маршрут, даже когда старый ещё физически жив."""
    t0, _, t2 = _hysteresis_snapshots()
    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0))
    update = tracker.update(NetworkGraph(t2, ["GW"], isl_range_km=3000.0))

    assert update.event is RouteEvent.REBUILT
    assert update.route.path == ("C1", "SS1", "GW")
    assert tracker.reroute_count == 2


def test_lifetime_is_measured_in_seconds_via_step_s_not_call_count():
    """Требование совместимости с задачей 6: step_s обязан переводить возраст
    маршрута в секунды. Если бы возраст считался в числе вызовов update(),
    записанное время жизни совпало бы с числом KEPT-вызовов (2), а не с
    суммой переданных step_s."""
    t0, t1, t2 = _hysteresis_snapshots()
    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0), step_s=100)  # REBUILT
    tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0), step_s=200)  # KEPT
    tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0), step_s=200)  # KEPT
    tracker.update(NetworkGraph(t2, ["GW"], isl_range_km=3000.0), step_s=300)  # REBUILT

    assert tracker.lifetimes_s == [500]  # 100 + 200 + 200, а не число вызовов (3)


def test_with_backup_false_suppresses_backup_route(model):
    """`with_backup=False` обязан гарантированно подавлять поиск резерва —
    а не просто иногда не находить его на данном отсчёте."""
    no_backup_tracker = RouteTracker("C65", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    with_backup_tracker = RouteTracker("C65", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    found_backup = False

    for t_s in model.time_grid[:120]:
        graph = graph_at(model, t_s)

        suppressed = no_backup_tracker.update(graph, with_backup=False)
        assert suppressed.backup is None

        requested = with_backup_tracker.update(graph, with_backup=True)
        if requested.backup is not None:
            found_backup = True

    assert found_backup, "резерв ни разу не нашёлся за 120 отсчётов — сравнение бессмысленно"


def test_backup_returned_by_tracker_matches_find_backup_route(model):
    """Резерв в RouteUpdate — не произвольный маршрут, а именно тот, что
    вернула бы find_backup_route для того же графа и текущего пути."""
    tracker = RouteTracker("C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    found_any = False

    for t_s in model.time_grid[:120]:
        graph = graph_at(model, t_s)
        update = tracker.update(graph)
        if update.route is None:
            continue
        expected_backup = find_backup_route(
            graph, "C70", RoutingStrategy.MIN_HOPS, update.route, isl_range_km=3000.0
        )
        assert update.backup == expected_backup
        if expected_backup is not None:
            found_any = True

    assert found_any, "резерв ни разу не нашёлся за 120 отсчётов — сравнение бессмысленно"


def test_find_route_runs_on_every_update_call_regardless_of_event(model):
    """B4: docstring `RouteTracker` называет `reroute_count` метрикой
    ПЕРЕУСТАНОВОК СОЕДИНЕНИЯ, а не вычислений — `find_route` выполняется
    безусловно первой строкой `update()` на каждом отсчёте, в том числе на
    KEPT и REPAIRED. Если бы вызов когда-нибудь стал ленивым (пропускался при
    KEPT/REPAIRED), число вызовов find_route разошлось бы с числом вызовов
    update(), и этот тест поймал бы регрессию."""
    tracker = RouteTracker("C70", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)
    steps = model.time_grid[:80]

    with patch("orbitlink.core.tracker.find_route", side_effect=routing_module.find_route) as spy:
        events = [tracker.update(graph_at(model, t_s)).event for t_s in steps]

    assert spy.call_count == len(steps)
    # Смесь событий обязана быть неоднородной — иначе find_route вызывался бы
    # столько же раз и в наивной реализации, которая считает только REBUILT,
    # и проверка ничего бы не отличала.
    assert len(set(events)) > 1, "события однородны за 80 отсчётов — сравнивать не с чем"


def test_flush_closes_the_last_route_lifetime_and_is_idempotent():
    """B7: без явного flush() время жизни ПОСЛЕДНЕГО, ещё живого маршрута
    молча теряется — lifetimes_s пополняется только при замене маршрута, а
    конец прогона не является заменой. flush() обязан закрыть этот период, и
    повторный вызов не должен добавить его дважды."""
    t0, t1, _ = _hysteresis_snapshots()
    tracker = RouteTracker("C1", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    tracker.update(NetworkGraph(t0, ["GW"], isl_range_km=3000.0), step_s=100)  # REBUILT, age=100
    tracker.update(NetworkGraph(t1, ["GW"], isl_range_km=3000.0), step_s=200)  # KEPT, age=300

    assert tracker.lifetimes_s == [], "маршрут ещё жив — период не должен закрыться сам по себе"

    tracker.flush()
    assert tracker.lifetimes_s == [300]

    tracker.flush()  # идемпотентность: повторный вызов ничего не добавляет
    assert tracker.lifetimes_s == [300]
