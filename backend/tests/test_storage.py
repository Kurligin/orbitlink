"""Хранилище проектов, вариантов и кэша прогонов."""

import copy

import pytest

from orbitlink.storage.models import create_engine_and_tables, session_factory
from orbitlink.storage.repository import (
    create_project,
    create_variant,
    find_run,
    fingerprint,
    get_project,
    get_variant,
    list_projects,
    save_run,
    update_variant_scenario,
    variant_changes,
)
from tests.conftest import read_scenario


@pytest.fixture
def session():
    engine = create_engine_and_tables("sqlite://")
    factory = session_factory(engine)
    with factory() as active:
        yield active


def test_project_creation_makes_base_variant(session):
    scenario = read_scenario("01_full_constellation")
    project = create_project(session, title="Полная группировка", scenario=scenario)

    assert project.id
    assert len(project.variants) == 1
    assert project.variants[0].scenario == scenario


def test_projects_are_listed(session):
    create_project(session, title="Первый", scenario=read_scenario("01_full_constellation"))
    create_project(session, title="Второй", scenario=read_scenario("02_first_launch"))

    assert {project.title for project in list_projects(session)} == {"Первый", "Второй"}


def test_variant_survives_reload(session):
    project = create_project(
        session, title="Проект", scenario=read_scenario("01_full_constellation")
    )
    variant = create_variant(
        session, project=project, title="Вариант", scenario=read_scenario("02_first_launch")
    )

    assert get_variant(session, variant.id).title == "Вариант"
    assert get_project(session, project.id).id == project.id


def test_variant_changes_are_computed_against_base(session):
    scenario = read_scenario("01_full_constellation")
    project = create_project(session, title="Проект", scenario=scenario)

    modified = copy.deepcopy(scenario)
    modified["design"]["launch_stage"] = 1
    variant = create_variant(session, project=project, title="Первая очередь", scenario=modified)

    assert "Очередь запуска: 3 → 1" in [change.label for change in variant_changes(variant)]


def test_updating_scenario_recomputes_changes(session):
    scenario = read_scenario("01_full_constellation")
    project = create_project(session, title="Проект", scenario=scenario)
    variant = create_variant(
        session, project=project, title="Вариант", scenario=copy.deepcopy(scenario)
    )
    assert variant_changes(variant) == []

    modified = copy.deepcopy(scenario)
    modified["environment"]["isl_range_km"] = 2000.0
    update_variant_scenario(session, variant, modified)

    assert len(variant_changes(variant)) == 1


def test_run_cache_hits_on_identical_configuration(session):
    scenario = read_scenario("01_full_constellation")
    project = create_project(session, title="Проект", scenario=scenario)
    variant = project.variants[0]

    key = fingerprint(scenario, "min_hops", 0.3, True)
    assert find_run(session, variant, key) is None

    save_run(session, variant, fingerprint=key, strategy="min_hops", payload={"clients": {}})
    assert find_run(session, variant, key) is not None


def test_fingerprint_depends_on_scenario_and_strategy():
    scenario = read_scenario("01_full_constellation")
    other = copy.deepcopy(scenario)
    other["design"]["launch_stage"] = 1

    assert fingerprint(scenario, "min_hops", 0.3, True) == fingerprint(
        copy.deepcopy(scenario), "min_hops", 0.3, True
    )
    assert fingerprint(scenario, "min_hops", 0.3, True) != fingerprint(other, "min_hops", 0.3, True)
    assert fingerprint(scenario, "min_hops", 0.3, True) != fingerprint(
        scenario, "min_latency", 0.3, True
    )


def test_fingerprint_depends_on_hysteresis_and_backup_flag():
    """C1: `with_backup` подавляет поиск резерва и реально меняет ответ

    (`has_backup`, `backup_fraction`, `margin_levels`) — отпечаток обязан
    зависеть от него наравне со сценарием, стратегией и гистерезисом, иначе
    кэш прогонов отдаёт чужой результат.
    """
    scenario = read_scenario("01_full_constellation")
    base = fingerprint(scenario, "min_hops", 0.3, True)

    assert fingerprint(scenario, "min_hops", 0.6, True) != base
    assert fingerprint(scenario, "min_hops", 0.3, False) != base
    assert fingerprint(scenario, "min_hops", 0.6, False) != fingerprint(
        scenario, "min_hops", 0.3, False
    )
