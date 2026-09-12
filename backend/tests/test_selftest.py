"""Сверка с эталонным модулем, запускаемая из сервиса."""

from fastapi.testclient import TestClient

from orbitlink.api.app import create_app
from orbitlink.api.selftest import run_selftest


def test_selftest_reports_success():
    report = run_selftest()

    assert report["ok"] is True
    assert report["checks"]
    for check in report["checks"]:
        assert check["max_position_error_km"] < 1e-9
        assert check["edges_match"] is True
        assert check["max_elevation_error_deg"] < 1e-9


def test_selftest_covers_all_supplied_scenarios():
    names = {check["scenario"] for check in run_selftest()["checks"]}
    assert names == {
        "01_full_constellation",
        "02_first_launch",
        "03_satellite_outages",
        "04_link_range",
    }


def test_selftest_endpoint():
    with TestClient(create_app("sqlite://")) as client:
        response = client.get("/api/selftest")
        assert response.status_code == 200
        assert response.json()["ok"] is True
