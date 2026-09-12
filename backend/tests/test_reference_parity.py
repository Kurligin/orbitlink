"""Сверка расчётного ядра с эталонным модулем организаторов."""

import numpy as np
import pytest

from orbitlink.core.geometry import ConstellationModel
from tests.conftest import read_scenario

CONTROL_TIMES = [0, 120, 3600, 21600, 43200, 86280]


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_positions_match_reference(scenario, reference, t_s):
    model = ConstellationModel(scenario)
    _, ours = model.positions(t_s)
    ids, _, theirs = reference.positions(scenario, t_s)

    assert model.satellite_ids == ids
    assert np.max(np.abs(ours - theirs)) < 1e-9


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_edges_match_reference(scenario, reference, t_s):
    ours = ConstellationModel(scenario).snapshot(t_s)
    theirs = reference.snapshot(scenario, t_s)

    def normalize(edges):
        return {(min(a, b), max(a, b)) for a, b, _ in edges}

    assert normalize(ours.edges) == normalize(theirs["edges"])


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_edge_lengths_match_reference(scenario, reference, t_s):
    ours = ConstellationModel(scenario).snapshot(t_s)
    theirs = reference.snapshot(scenario, t_s)

    our_lengths = {(min(a, b), max(a, b)): d for a, b, d in ours.edges}
    their_lengths = {(min(a, b), max(a, b)): d for a, b, d in theirs["edges"]}

    for key, value in their_lengths.items():
        assert abs(our_lengths[key] - value) < 1e-9


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_elevation_matches_reference(scenario, reference, t_s):
    ours = ConstellationModel(scenario).snapshot(t_s)
    theirs = reference.snapshot(scenario, t_s)

    assert set(ours.elevation_deg) == set(theirs["elevation_deg"])
    for site_id, angles in theirs["elevation_deg"].items():
        assert set(ours.elevation_deg[site_id]) == set(angles)
        for sat_id, angle in angles.items():
            assert abs(ours.elevation_deg[site_id][sat_id] - angle) < 1e-9


@pytest.mark.parametrize("t_s", CONTROL_TIMES)
def test_active_mask_matches_reference(scenario, reference, t_s):
    ours = ConstellationModel(scenario).snapshot(t_s)
    theirs = reference.snapshot(scenario, t_s)

    their_active = {s["id"]: s["active"] for s in theirs["satellites"]}
    for index, sat_id in enumerate(ours.satellite_ids):
        assert bool(ours.active[index]) == their_active[sat_id]


def test_time_grid_excludes_right_end():
    scenario = read_scenario("01_full_constellation")
    grid = ConstellationModel(scenario).time_grid

    assert grid[0] == 0
    assert grid[1] == 120
    assert grid[-1] == 86280
    assert len(grid) == 720
    assert 86400 not in grid


def test_failure_window_includes_start_excludes_end():
    scenario = read_scenario("03_satellite_outages")
    model = ConstellationModel(scenario)

    assert "S31" not in model.failed_at(21599)
    assert "S31" in model.failed_at(21600)
    assert "S31" in model.failed_at(86399)
