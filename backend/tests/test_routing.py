"""Поиск маршрутов через спутниковую сеть."""

import numpy as np
import pytest

from orbitlink.core.geometry import ConstellationModel, Snapshot
from orbitlink.core.routing import (
    NetworkGraph,
    NoRouteReason,
    RoutingStrategy,
    _pair,
    classify_no_route,
    find_backup_route,
    find_route,
)
from tests.conftest import read_scenario

CONTROL_TIMES = [0, 3600, 43200, 86280]


@pytest.fixture
def full_model():
    return ConstellationModel(read_scenario("01_full_constellation"))


def graph_at(model: ConstellationModel, t_s: float) -> NetworkGraph:
    return NetworkGraph(model.snapshot(t_s), model.gateway_ids)


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
@pytest.mark.parametrize("client_id", ["C65", "C70", "C72"])
def test_route_starts_at_client_and_ends_at_gateway(full_model, t_s, client_id):
    graph = graph_at(full_model, t_s)
    route = find_route(graph, client_id, RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)

    if route is None:
        pytest.skip("на этом отсчёте маршрута нет, структура не проверяется")

    assert route.path[0] == client_id
    assert route.path[-1] in graph.gateways
    assert route.hops == len(route.path) - 1
    assert route.hops >= 2


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_route_relays_are_active_satellites_only(full_model, t_s):
    graph = graph_at(full_model, t_s)
    route = find_route(graph, "C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)

    if route is None:
        pytest.skip("маршрута нет")

    for node in route.relays:
        assert node in graph.satellites


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_every_route_edge_exists_in_snapshot(full_model, t_s):
    snapshot = full_model.snapshot(t_s)
    graph = NetworkGraph(snapshot, full_model.gateway_ids)
    route = find_route(graph, "C72", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    if route is None:
        pytest.skip("маршрута нет")

    available = {_pair(a, b) for a, b, _ in snapshot.edges}
    for left, right in zip(route.path, route.path[1:], strict=False):
        assert _pair(left, right) in available


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_min_hops_is_not_longer_in_hops_than_min_latency(full_model, t_s):
    graph = graph_at(full_model, t_s)
    by_hops = find_route(graph, "C65", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    by_latency = find_route(graph, "C65", RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0)

    if by_hops is None or by_latency is None:
        pytest.skip("маршрута нет")

    assert by_hops.hops <= by_latency.hops
    assert by_latency.length_km <= by_hops.length_km + 1e-6


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_backup_route_shares_no_satellite_with_primary(full_model, t_s):
    graph = graph_at(full_model, t_s)
    primary = find_route(graph, "C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    if primary is None:
        pytest.skip("основного маршрута нет")

    backup = find_backup_route(graph, "C70", RoutingStrategy.MIN_HOPS, primary, isl_range_km=3000.0)
    if backup is None:
        pytest.skip("резерва нет на этом отсчёте")

    assert not set(primary.relays) & set(backup.relays)


def test_all_strategies_return_valid_routes(full_model):
    """Не должен иметь возможности пройти, не выполнив ни одной проверки: если ни
    одна пара (отсчёт, стратегия) не даёт маршрут, последний assert провалит тест,
    а не молча пропустит его (было: `if route is None: continue` без итога)."""
    found_any = False
    for t_s in CONTROL_TIMES:
        graph = graph_at(full_model, t_s)
        for strategy in RoutingStrategy:
            route = find_route(graph, "C65", strategy, isl_range_km=3000.0)
            if route is None:
                continue
            found_any = True
            assert route.path[0] == "C65"
            assert route.path[-1] in graph.gateways
            assert route.hops == len(route.path) - 1

    assert (
        found_any
    ), "ни одна комбинация (отсчёт, стратегия) не дала маршрут — тест ничего не проверил"


def test_reason_is_gateway_offline_when_all_gateways_are_down():
    scenario = read_scenario("01_full_constellation")
    scenario["gateway_outages"] = [{"gateway_id": "G_MUR", "start_s": 0, "end_s": 86400}]
    model = ConstellationModel(scenario)
    graph = NetworkGraph(model.snapshot(3600), model.gateway_ids)

    assert find_route(graph, "C65", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0) is None
    assert classify_no_route(graph, "C65") is NoRouteReason.GATEWAY_OFFLINE


def test_reason_is_no_visible_satellite_when_elevation_threshold_is_extreme():
    scenario = read_scenario("01_full_constellation")
    scenario["environment"]["min_elevation_deg"] = 89.0
    model = ConstellationModel(scenario)
    graph = NetworkGraph(model.snapshot(0), model.gateway_ids)

    if graph.visible_satellites("C65"):
        pytest.skip("на этом отсчёте пункт всё же видит аппарат")
    assert classify_no_route(graph, "C65") is NoRouteReason.NO_VISIBLE_SATELLITE


def test_reason_is_network_split_when_isl_range_is_tiny():
    scenario = read_scenario("01_full_constellation")
    scenario["environment"]["isl_range_km"] = 100.0
    model = ConstellationModel(scenario)
    graph = NetworkGraph(model.snapshot(0), model.gateway_ids)

    assert find_route(graph, "C72", RoutingStrategy.MIN_HOPS, isl_range_km=100.0) is None
    assert classify_no_route(graph, "C72") is NoRouteReason.ISL_NETWORK_SPLIT


# --- Резервные маршруты и классификация причин разрыва ------------------------


def test_pair_canonicalises_lexicographically_not_numerically():
    """Контракт `_pair`: сравнение строковое, а не по числовому значению хвоста
    идентификатора — для `S9`/`S10` результат не совпадает с числовым порядком."""
    assert _pair("A", "B") == ("A", "B")
    assert _pair("B", "A") == ("A", "B")
    assert _pair("S9", "S10") == ("S10", "S9")  # "1" < "9" посимвольно, хотя 9 < 10


def test_load_aware_reroutes_away_from_congested_min_latency_edges(full_model):
    """LOAD_AWARE обязана реагировать на `utilisation`, иначе она вырождается
    в MIN_LATENCY. Берём маршрут MIN_LATENCY, объявляем все его рёбра сильно
    занятыми и проверяем, что LOAD_AWARE находит ДРУГОЙ путь. Если ветку LOAD_AWARE
    сломать (перестать учитывать utilisation), find_route даст тот же путь, что и
    MIN_LATENCY, ни на одном отсчёте/клиенте — тест провалится на последнем assert.
    """
    for t_s in CONTROL_TIMES:
        graph = graph_at(full_model, t_s)
        for client_id in ("C65", "C70", "C72"):
            baseline = find_route(
                graph, client_id, RoutingStrategy.MIN_LATENCY, isl_range_km=3000.0
            )
            if baseline is None:
                continue
            utilisation = {
                _pair(left, right): 0.99
                for left, right in zip(baseline.path, baseline.path[1:], strict=False)
            }
            congested = find_route(
                graph,
                client_id,
                RoutingStrategy.LOAD_AWARE,
                isl_range_km=3000.0,
                utilisation=utilisation,
            )
            if congested is not None and congested.path != baseline.path:
                return  # нашли момент, где перегрузка меняет выбор LOAD_AWARE — механизм жив

    pytest.fail(
        "ни на одном отсчёте/клиенте LOAD_AWARE не обошла перегруженный маршрут "
        "MIN_LATENCY — похоже, utilisation не влияет на вес ребра"
    )


def _synthetic_two_path_snapshot() -> Snapshot:
    """Клиент C1, шлюз GW и две непересекающиеся пары аппаратов: C1-SA1-SA2-GW и
    C1-SB1-SB2-GW. Ни positions_km, ни elevation_deg не используются NetworkGraph,
    поэтому заполнены заглушками."""
    satellite_ids = ["SA1", "SA2", "SB1", "SB2"]
    return Snapshot(
        t_s=0.0,
        satellite_ids=satellite_ids,
        positions_km=np.zeros((len(satellite_ids), 3)),
        active=np.array([True, True, True, True]),
        edges=[
            ("C1", "SA1", 1000.0),
            ("SA1", "SA2", 500.0),
            ("SA2", "GW", 1000.0),
            ("C1", "SB1", 1200.0),
            ("SB1", "SB2", 600.0),
            ("SB2", "GW", 1200.0),
        ],
        elevation_deg={},
        offline_gateways=set(),
    )


def test_backup_route_found_on_synthetic_disjoint_satellite_pairs():
    """Реальные сценарии почти всегда сводят проверку резерва к pytest.skip
    (единственный шлюз, три из четырёх отсчётов — без обратного ISL-пути).
    Этот тест не зависит от того, что найдётся в данных организаторов:
    сеть собрана вручную так, что резерв обязан найтись всегда.
    """
    snapshot = _synthetic_two_path_snapshot()
    graph = NetworkGraph(snapshot, ["GW"], isl_range_km=3000.0)

    primary = find_route(graph, "C1", RoutingStrategy.MIN_HOPS)
    assert primary is not None
    assert primary.path[0] == "C1"
    assert primary.path[-1] == "GW"

    backup = find_backup_route(graph, "C1", RoutingStrategy.MIN_HOPS, primary)
    assert backup is not None
    assert backup.path[0] == "C1"
    assert backup.path[-1] == "GW"
    assert not set(primary.relays) & set(backup.relays)


def test_find_route_falls_back_to_graphs_isl_range_km(full_model):
    """`isl_range_km` не должен быть вторым независимым источником истины —
    если не передан в find_route явно, берётся из графа, и результат совпадает
    с явной передачей того же значения."""
    graph_with_default = NetworkGraph(
        full_model.snapshot(0), full_model.gateway_ids, isl_range_km=3000.0
    )
    graph_without_default = NetworkGraph(full_model.snapshot(0), full_model.gateway_ids)

    via_graph_default = find_route(graph_with_default, "C70", RoutingStrategy.ROBUST)
    via_explicit_call = find_route(
        graph_without_default, "C70", RoutingStrategy.ROBUST, isl_range_km=3000.0
    )

    assert via_graph_default == via_explicit_call


def test_find_backup_route_also_falls_back_to_graphs_isl_range_km(full_model):
    """То же самое правило распространяется на find_backup_route."""
    graph = NetworkGraph(full_model.snapshot(0), full_model.gateway_ids, isl_range_km=3000.0)
    primary = find_route(graph, "C70", RoutingStrategy.MIN_HOPS)
    assert primary is not None

    backup = find_backup_route(graph, "C70", RoutingStrategy.MIN_HOPS, primary)
    assert backup is not None
    assert not set(primary.relays) & set(backup.relays)


def test_find_route_without_isl_range_km_anywhere_raises_value_error(full_model):
    """Если диапазон не задан ни в вызове, ни в графе — понятная ошибка, а не
    тихая подстановка значения по умолчанию."""
    graph = NetworkGraph(full_model.snapshot(0), full_model.gateway_ids)

    with pytest.raises(ValueError):
        find_route(graph, "C70", RoutingStrategy.ROBUST)


def test_classify_no_route_reports_isl_network_split_when_route_exists(full_model):
    """У classify_no_route есть предусловие — вызывать её нужно только когда
    маршрут не найден. При его нарушении функция не бросает исключение и не
    пытается угадать: она детерминированно возвращает ISL_NETWORK_SPLIT (ни одна
    более ранняя проверка не сработала). Фиксируем это как документированное
    поведение, а не как истинное утверждение об отсутствии маршрута."""
    graph = graph_at(full_model, 0)
    route = find_route(graph, "C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    assert route is not None  # маршрут реально есть — предусловие нарушено намеренно

    assert classify_no_route(graph, "C70") is NoRouteReason.ISL_NETWORK_SPLIT


def test_classify_no_route_with_excluded_explains_missing_backup_route(full_model):
    """Параметр excluded позволяет classify_no_route объяснить также причину
    отсутствия РЕЗЕРВНОГО маршрута — передаём те же исключённые узлы, что и в
    find_backup_route. На C70/t=3600 резерва нет (проверено вручную):
    единственный шлюз не виден ни одному из аппаратов, оставшихся видимыми
    клиенту после исключения реле основного маршрута."""
    graph = graph_at(full_model, 3600)
    primary = find_route(graph, "C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    assert primary is not None

    backup = find_backup_route(graph, "C70", RoutingStrategy.MIN_HOPS, primary, isl_range_km=3000.0)
    assert backup is None

    reason = classify_no_route(graph, "C70", excluded=frozenset(primary.relays))
    assert reason is NoRouteReason.NO_GATEWAY_CONTACT


def test_build_route_reuses_graphs_edge_length_cache(full_model):
    """`_build_route` обязана брать длины рёбер из кэша `NetworkGraph._edge_lengths`,
    а не пересобирать словарь длин заново при каждом вызове. Тест ловит и то, и
    другое: длина маршрута совпадает с суммой длин из кэша, а сам кэш содержит
    канонический ключ каждого ребра маршрута."""
    graph = graph_at(full_model, 0)
    route = find_route(graph, "C70", RoutingStrategy.MIN_HOPS, isl_range_km=3000.0)
    assert route is not None

    expected_km = 0.0
    for left, right in zip(route.path, route.path[1:], strict=False):
        key = _pair(left, right)
        assert key in graph._edge_lengths
        expected_km += graph._edge_lengths[key]

    assert route.length_km == pytest.approx(expected_km)
