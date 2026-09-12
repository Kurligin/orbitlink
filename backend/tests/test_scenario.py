"""Проверка входного контроля сценариев."""

import copy

import pytest

from orbitlink.core.scenario import (
    ScenarioError,
    load_scenario,
    normalize_scenario,
    validate_scenario,
)
from tests.conftest import read_scenario


def test_all_supplied_scenarios_are_valid(scenario):
    report = validate_scenario(scenario)
    assert report.ok, [issue.as_dict() for issue in report.issues]


def corrupt(mutate) -> dict:
    scenario = read_scenario("01_full_constellation")
    mutate(scenario)
    return scenario


def paths_of(scenario) -> list[str]:
    return [issue.path for issue in validate_scenario(scenario).issues]


def test_unknown_schema_version_is_rejected():
    scenario = corrupt(lambda s: s.__setitem__("schema_version", "cosmo-A-2.0"))
    assert "schema_version" in paths_of(scenario)


def test_satellite_referencing_missing_plane_names_the_field():
    scenario = corrupt(lambda s: s["design"]["satellites"][7].__setitem__("plane_id", "P9"))
    assert "design.satellites[7].plane_id" in paths_of(scenario)


def test_duplicate_satellite_id_is_reported():
    scenario = corrupt(lambda s: s["design"]["satellites"][5].__setitem__("id", "S01"))
    assert "design.satellites[5].id" in paths_of(scenario)


def test_horizon_not_multiple_of_step_is_reported():
    scenario = corrupt(lambda s: s["environment"].__setitem__("horizon_s", 86401))
    assert "environment.horizon_s" in paths_of(scenario)


def test_outage_beyond_horizon_is_reported():
    scenario = corrupt(
        lambda s: s["failures"].append({"satellite_id": "S01", "start_s": 80000, "end_s": 90000})
    )
    assert "failures[0].end_s" in paths_of(scenario)


def test_outage_referencing_unknown_satellite_is_reported():
    scenario = corrupt(
        lambda s: s["failures"].append({"satellite_id": "S99", "start_s": 0, "end_s": 600})
    )
    assert "failures[0].satellite_id" in paths_of(scenario)


def test_non_string_plane_id_is_reported_without_crashing():
    """I3: `plane_id` — не только неизвестная строка, но и посторонний JSON-тип

    (список, объект, число). Проверка вхождения в множество (`not in
    plane_ids`) без предварительного `isinstance(..., str)` бросала бы
    `TypeError: unhashable type` вместо списка замечаний — вместо ответа
    сервиса пользователь получал бы 500.
    """
    scenario = corrupt(lambda s: s["design"]["satellites"][7].__setitem__("plane_id", ["P1"]))
    assert "design.satellites[7].plane_id" in paths_of(scenario)


def test_non_string_satellite_id_in_failure_is_reported_without_crashing():
    """I3: то же самое для `satellite_id` в `failures` — чужой файл может

    подставить объект на месте идентификатора, сервис обязан назвать
    проблемное поле, а не упасть с `TypeError: unhashable type`.
    """
    scenario = corrupt(
        lambda s: s["failures"].append(
            {"satellite_id": {"nested": "S01"}, "start_s": 0, "end_s": 600}
        )
    )
    assert "failures[0].satellite_id" in paths_of(scenario)


def test_ground_site_id_clashing_with_satellite_is_reported():
    scenario = corrupt(lambda s: s["ground_sites"][1].__setitem__("id", "S01"))
    assert "ground_sites[1].id" in paths_of(scenario)


def test_scenario_without_gateway_is_rejected():
    scenario = corrupt(
        lambda s: s.__setitem__(
            "ground_sites", [g for g in s["ground_sites"] if g["role"] != "gateway"]
        )
    )
    assert "ground_sites" in paths_of(scenario)


def test_validator_collects_all_issues_not_just_first():
    scenario = corrupt(
        lambda s: (
            s["design"]["satellites"][7].__setitem__("plane_id", "P9"),
            s["ground_sites"][1].__setitem__("lat_deg", 200.0),
        )
    )
    report = validate_scenario(scenario)
    assert len(report.issues) >= 2


def test_environment_issues_survive_prior_schema_version_issue():
    """Регрессия: чужое замечание перед environment не должно глушить его проверки."""
    scenario = corrupt(
        lambda s: (
            s.__setitem__("schema_version", "cosmo-A-2.0"),
            s["environment"].__setitem__("altitude_km", 50.0),
        )
    )
    paths = paths_of(scenario)
    assert "schema_version" in paths
    assert "environment.altitude_km" in paths


def test_environment_issues_survive_prior_missing_section_issue():
    """Регрессия: отсутствие соседнего раздела не должно глушить проверки environment."""
    scenario = corrupt(
        lambda s: (
            s.pop("design"),
            s["environment"].__setitem__("altitude_km", 50.0),
        )
    )
    paths = paths_of(scenario)
    assert "design" in paths
    assert "environment.altitude_km" in paths


def test_load_scenario_raises_with_report():
    scenario = corrupt(lambda s: s["environment"].__setitem__("altitude_km", 50.0))
    with pytest.raises(ScenarioError) as info:
        load_scenario(scenario)
    assert not info.value.report.ok


def test_angles_are_wrapped_into_range():
    scenario = read_scenario("01_full_constellation")
    scenario["design"]["planes"][1]["raan_deg"] = 375.0
    scenario["design"]["planes"][2]["phase_deg"] = -30.0

    result = normalize_scenario(scenario)

    assert result["design"]["planes"][1]["raan_deg"] == pytest.approx(15.0)
    assert result["design"]["planes"][2]["phase_deg"] == pytest.approx(330.0)


def test_overlapping_outages_are_merged():
    scenario = read_scenario("01_full_constellation")
    scenario["failures"] = [
        {"satellite_id": "S01", "start_s": 0, "end_s": 3600},
        {"satellite_id": "S01", "start_s": 1800, "end_s": 7200},
        {"satellite_id": "S02", "start_s": 0, "end_s": 600},
    ]

    result = normalize_scenario(scenario)
    windows = [f for f in result["failures"] if f["satellite_id"] == "S01"]

    assert len(windows) == 1
    assert windows[0]["start_s"] == 0
    assert windows[0]["end_s"] == 7200


def test_normalize_does_not_mutate_input():
    scenario = read_scenario("01_full_constellation")
    original = copy.deepcopy(scenario)
    normalize_scenario(scenario)
    assert scenario == original
