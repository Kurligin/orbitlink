"""Выгрузка результата и её пригодность к повторной загрузке.

Круговой оборот — самая важная проверка файла: жюри выгружает наш результат,
меняет параметры и загружает файл обратно, чтобы повторить эксперимент. Если
`effective_scenario` не проходит собственный входной контроль сервиса, узнать
это на приёмке уже нельзя — поэтому тест кругового оборота должен закрывать
не только форму словаря Python, но и настоящий путь файла: JSON-текст на
диске -> разбор -> входной контроль -> новый прогон.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from orbitlink.core.export import build_result_document
from orbitlink.core.routing import RoutingStrategy
from orbitlink.core.scenario import RESULT_SCHEMA_VERSION, load_scenario, validate_scenario
from orbitlink.core.simulate import simulate
from tests.conftest import SCENARIO_NAMES, read_scenario


def build(name: str = "01_full_constellation") -> dict:
    return build_result_document(simulate(load_scenario(read_scenario(name))))


def test_document_declares_result_schema():
    assert build()["schema_version"] == RESULT_SCHEMA_VERSION
    assert RESULT_SCHEMA_VERSION == "cosmo-A-result-1.0"


def test_document_has_all_required_top_level_keys():
    """Контракт интерфейса задачи: пять обязательных ключей документа."""
    document = build()
    assert set(document) >= {
        "schema_version",
        "effective_scenario",
        "routes",
        "summary",
        "notes",
    }


def test_effective_scenario_can_be_loaded_back():
    """Круговой оборот: жюри должно суметь повторно загрузить нашу выгрузку."""
    document = build()
    report = validate_scenario(document["effective_scenario"])
    assert report.ok, [issue.as_dict() for issue in report.issues]


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_effective_scenario_round_trips_through_json_on_every_organizer_scenario(name: str):
    """Круговой оборот проверяется на всех четырёх сценариях организаторов и
    сквозь настоящий JSON-текст, а не только на словаре Python в памяти:
    сериализация -> разбор -> входной контроль -> новый прогон расчёта.

    Одной валидации мало: она доказывает лишь, что документ ФОРМАЛЬНО похож
    на сценарий. Повторный прогон доказывает, что жюри реально сможет
    повторить эксперимент — ради этого и существует круговой оборот.
    """
    document = build(name)
    document_text = json.dumps(document, ensure_ascii=False, allow_nan=False)
    reloaded = json.loads(document_text)

    report = validate_scenario(reloaded["effective_scenario"])
    assert report.ok, (name, [issue.as_dict() for issue in report.issues])

    resimulated = simulate(load_scenario(reloaded["effective_scenario"]))
    assert resimulated.times, "повторный прогон не дал ни одного отсчёта времени"
    assert resimulated.routes, "повторный прогон не дал ни одной маршрутной записи"


def test_one_record_per_step_and_client():
    document = build()
    scenario = document["effective_scenario"]
    clients = [g["id"] for g in scenario["ground_sites"] if g["role"] == "client"]
    steps = scenario["environment"]["horizon_s"] // scenario["environment"]["step_s"]

    assert steps > 0
    assert clients, "в сценарии нет ни одного клиентского пункта — считать нечего"

    assert len(document["routes"]) == steps * len(clients)
    assert {(r["t_s"], r["client_id"]) for r in document["routes"]}.__len__() == len(
        document["routes"]
    )


def test_record_shape_matches_specification():
    routes = build()["routes"]
    assert routes, "нет ни одной маршрутной записи — форму проверить не на чем"
    record = routes[0]
    assert set(record) >= {"t_s", "client_id", "path"}
    assert isinstance(record["path"], list)


def test_missing_route_is_an_empty_path():
    document = build("02_first_launch")
    empty = [r for r in document["routes"] if not r["path"]]
    assert empty, "на сценарии первого запуска не встретилось ни одного пропуска связи"


def test_path_runs_from_client_to_gateway():
    document = build()
    scenario = document["effective_scenario"]
    gateways = {g["id"] for g in scenario["ground_sites"] if g["role"] == "gateway"}
    assert gateways, "в сценарии нет ни одного шлюза — проверять не на чем"

    checked = 0
    for record in document["routes"]:
        if record["path"]:
            assert record["path"][0] == record["client_id"]
            assert record["path"][-1] in gateways
            checked += 1
    assert checked, "не встретилось ни одной записи с непустым путём — проверка не состоялась"


def test_document_is_json_serialisable():
    json.dumps(build(), ensure_ascii=False, allow_nan=False)


def _assert_json_safe(value: Any, path: str) -> None:
    """Рекурсивно проверяет, что значение состоит только из типов, которые
    JSON понимает без потерь. Явный запрет: ни NaN/бесконечностей, ни
    объектов NumPy — они маскируются под числа и молча портят выгрузку,
    потому что `numpy.float64` формально является подклассом `float`, а
    `numpy.int64`/`numpy.bool_` не сериализуются стандартным `json` вовсе.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"{path}: ключ {key!r} не строка"
            _assert_json_safe(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_safe(item, f"{path}[{index}]")
        return
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        assert type(value) is int, f"{path}: {value!r} — целое число не встроенного типа int"
        return
    if isinstance(value, float):
        assert type(value) is float, f"{path}: {value!r} — вещественное число не типа float"
        assert math.isfinite(value), f"{path}: {value!r} не конечно (NaN или бесконечность)"
        return
    pytest.fail(f"{path}: значение {value!r} типа {type(value)} JSON не сериализует без потерь")


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_document_contains_no_nan_infinity_or_numpy_values(name: str):
    """Явный запрет на нечисловые значения — по всем четырём сценариям, а не
    только по умолчанию, потому что источник опасных значений (задержки,
    углы) зависит от геометрии конкретного сценария.
    """
    document = build(name)
    _assert_json_safe(document, "document")


def test_summary_carries_client_metrics():
    summary = build()["summary"]
    assert set(summary["clients"]) == {"C65", "C70", "C72"}
    assert summary["target_availability"] == 0.9


def test_summary_environment_fields_match_effective_scenario():
    """Сводка не должна расходиться со сценарием, из которого выгружена."""
    document = build()
    summary = document["summary"]
    environment = document["effective_scenario"]["environment"]
    assert summary["step_s"] == environment["step_s"]
    assert summary["horizon_s"] == environment["horizon_s"]
    assert summary["target_availability"] == environment["target_availability"]


def test_summary_strategy_is_a_valid_routing_strategy_value():
    strategy = build()["summary"]["strategy"]
    assert strategy in {s.value for s in RoutingStrategy}


def test_notes_default_to_none():
    run = simulate(load_scenario(read_scenario("01_full_constellation")))
    assert build_result_document(run)["notes"] is None


def test_notes_pass_through_when_given():
    run = simulate(load_scenario(read_scenario("01_full_constellation")))
    document = build_result_document(run, notes="контрольный прогон")
    assert document["notes"] == "контрольный прогон"
