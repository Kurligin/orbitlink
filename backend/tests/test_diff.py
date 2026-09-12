"""Сравнение параметров базового сценария и варианта."""

import copy

from orbitlink.core.diff import diff_scenarios
from tests.conftest import read_scenario


def pair():
    base = read_scenario("01_full_constellation")
    return base, copy.deepcopy(base)


def labels(base, variant) -> list[str]:
    return [change.label for change in diff_scenarios(base, variant)]


def test_identical_scenarios_have_no_changes():
    base, variant = pair()
    assert diff_scenarios(base, variant) == []


def test_plane_angle_change_is_reported():
    base, variant = pair()
    variant["design"]["planes"][1]["raan_deg"] = 75.0
    assert "P2.raan_deg: 60 → 75" in labels(base, variant)


def test_launch_stage_change_is_reported():
    base, variant = pair()
    variant["design"]["launch_stage"] = 1
    assert "Очередь запуска: 3 → 1" in labels(base, variant)


def test_environment_change_is_reported():
    base, variant = pair()
    variant["environment"]["isl_range_km"] = 2000.0
    assert "Дальность межспутниковой связи: 3000 → 2000 км" in labels(base, variant)


def test_added_failure_is_reported():
    base, variant = pair()
    variant["failures"].append({"satellite_id": "S31", "start_s": 21600, "end_s": 86400})
    assert "Добавлен отказ S31: 21600–86400 с" in labels(base, variant)


def test_removed_failure_is_reported():
    base = read_scenario("03_satellite_outages")
    variant = copy.deepcopy(base)
    variant["failures"] = []
    assert any(label.startswith("Снят отказ S") for label in labels(base, variant))


def test_several_changes_are_all_reported():
    base, variant = pair()
    variant["design"]["launch_stage"] = 2
    variant["design"]["planes"][0]["phase_deg"] = 10.0
    assert len(diff_scenarios(base, variant)) == 2
