"""Бинарный пакет состояния сети."""

import struct

import numpy as np
import pytest
from fastapi.testclient import TestClient

from orbitlink.api.app import create_app
from orbitlink.api.network_packet import build_network_packet, parse_network_packet
from orbitlink.core.geometry import ConstellationModel
from orbitlink.core.scenario import load_scenario
from tests.conftest import SCENARIO_NAMES, read_scenario


@pytest.fixture
def scenario():
    return load_scenario(read_scenario("01_full_constellation"))


def test_packet_round_trips(scenario):
    parsed = parse_network_packet(build_network_packet(scenario))

    assert parsed["meta"]["satellite_ids"] == ConstellationModel(scenario).satellite_ids
    assert parsed["meta"]["step_s"] == 120
    assert len(parsed["meta"]["times"]) == 720
    assert parsed["positions"].shape == (720, 48, 3)


def test_positions_match_direct_computation(scenario):
    parsed = parse_network_packet(build_network_packet(scenario))
    model = ConstellationModel(scenario)

    _, expected = model.positions(3600)
    index = parsed["meta"]["times"].index(3600)

    assert np.max(np.abs(parsed["positions"][index] - expected.astype(np.float32))) < 1.0


def test_edges_match_snapshot(scenario):
    parsed = parse_network_packet(build_network_packet(scenario))
    model = ConstellationModel(scenario)

    index = parsed["meta"]["times"].index(3600)
    names = parsed["meta"]["node_ids"]
    ours = {
        (min(names[a], names[b]), max(names[a], names[b])) for a, b, _ in parsed["edges"][index]
    }
    expected = {(min(a, b), max(a, b)) for a, b, _ in model.snapshot(3600).edges}

    assert expected, "пустое множество рёбер ничего не доказывает — два пустых совпали бы всегда"
    assert ours == expected


def test_packet_is_small_enough_for_one_request(scenario):
    assert len(build_network_packet(scenario)) < 4 * 1024 * 1024


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_positions_start_is_four_byte_aligned_on_every_organizer_scenario(name):
    """C2: массив позиций обязан начинаться на смещении, кратном четырём

    байтам, — иначе `new Float32Array(buffer, offset, n)` на фронтенде
    бросает RangeError. Длина заголовка (а значит и смещение начала
    позиций) произвольна и зависит от сценария, поэтому проверяем на всех
    четырёх сценариях организаторов, а не только на дефолтном.
    """
    loaded = load_scenario(read_scenario(name))
    blob = build_network_packet(loaded)

    (header_length,) = struct.unpack_from("<I", blob, 0)
    positions_offset = 4 + header_length
    assert positions_offset % 4 == 0

    # Круговой оборот пакета по-прежнему сходится после выравнивания заголовка.
    parsed = parse_network_packet(blob)
    model = ConstellationModel(loaded)
    assert parsed["meta"]["satellite_ids"] == model.satellite_ids
    assert parsed["positions"].shape == (len(parsed["meta"]["times"]), len(model.satellite_ids), 3)


def test_endpoint_returns_binary():
    with TestClient(create_app("sqlite://")) as client:
        project = client.post(
            "/api/projects",
            json={"title": "Проект", "scenario": read_scenario("01_full_constellation")},
        ).json()
        variant_id = project["variants"][0]["id"]

        response = client.get(f"/api/variants/{variant_id}/network")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert parse_network_packet(response.content)["positions"].shape == (720, 48, 3)
