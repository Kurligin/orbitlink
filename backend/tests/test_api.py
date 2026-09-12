"""HTTP-контракт сервиса."""

import copy

import pytest
from fastapi.testclient import TestClient

from orbitlink.api.app import create_app
from tests.conftest import read_scenario


@pytest.fixture
def client():
    with TestClient(create_app("sqlite://")) as active:
        yield active


def make_project(client, name: str = "01_full_constellation") -> dict:
    response = client.post(
        "/api/projects", json={"title": "Проект", "scenario": read_scenario(name)}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_presets_are_available_without_upload(client):
    response = client.get("/api/presets")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        "01_full_constellation",
        "02_first_launch",
        "03_satellite_outages",
        "04_link_range",
    }


def test_valid_scenario_passes_validation(client):
    response = client.post(
        "/api/scenarios/validate", json={"scenario": read_scenario("01_full_constellation")}
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_broken_scenario_returns_field_paths(client):
    scenario = read_scenario("01_full_constellation")
    scenario["design"]["satellites"][7]["plane_id"] = "P9"

    response = client.post("/api/scenarios/validate", json={"scenario": scenario})
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert "design.satellites[7].plane_id" in [issue["path"] for issue in body["issues"]]


def test_creating_project_with_broken_scenario_is_rejected(client):
    scenario = read_scenario("01_full_constellation")
    scenario["environment"]["step_s"] = 0

    response = client.post("/api/projects", json={"title": "Плохой", "scenario": scenario})

    assert response.status_code == 422
    assert response.json()["detail"]["issues"]


def test_project_lifecycle(client):
    project = make_project(client)
    assert len(project["variants"]) == 1

    listing = client.get("/api/projects").json()
    assert project["id"] in [item["id"] for item in listing]

    fetched = client.get(f"/api/projects/{project['id']}").json()
    assert fetched["title"] == "Проект"


def test_variant_creation_reports_changes(client):
    project = make_project(client)
    scenario = copy.deepcopy(project["variants"][0]["scenario"])
    scenario["design"]["launch_stage"] = 1

    response = client.post(
        f"/api/projects/{project['id']}/variants",
        json={"title": "Первая очередь", "scenario": scenario},
    )

    assert response.status_code == 201
    assert "Очередь запуска: 3 → 1" in [c["label"] for c in response.json()["changes"]]


def test_patching_variant_updates_changes(client):
    project = make_project(client)
    variant_id = project["variants"][0]["id"]
    scenario = copy.deepcopy(project["variants"][0]["scenario"])
    scenario["environment"]["isl_range_km"] = 2000.0

    response = client.patch(f"/api/variants/{variant_id}", json={"scenario": scenario})

    assert response.status_code == 200
    assert len(response.json()["changes"]) == 1


def test_run_returns_metrics_for_every_client(client):
    project = make_project(client)
    variant_id = project["variants"][0]["id"]

    response = client.post(f"/api/variants/{variant_id}/run", json={"strategy": "min_hops"})
    body = response.json()

    assert response.status_code == 200
    assert set(body["clients"]) == {"C65", "C70", "C72"}
    assert body["clients"]["C65"]["availability_fraction"] == pytest.approx(0.967, abs=0.002)


def test_run_response_includes_margin_levels_and_reason_counts(client):
    """Нужно фронтенду: компактные временные ряды по каждому клиентскому пункту."""
    project = make_project(client)
    variant_id = project["variants"][0]["id"]

    response = client.post(f"/api/variants/{variant_id}/run", json={"strategy": "min_hops"})
    clients = response.json()["clients"]

    assert clients
    for client_id, metrics in clients.items():
        assert metrics["margin_levels"], client_id
        assert isinstance(metrics["reason_counts"], dict)
        assert all(level in (0, 1, 2) for level in metrics["margin_levels"])


def test_second_run_is_served_from_cache(client):
    project = make_project(client)
    variant_id = project["variants"][0]["id"]

    first = client.post(f"/api/variants/{variant_id}/run", json={"strategy": "min_hops"}).json()
    second = client.post(f"/api/variants/{variant_id}/run", json={"strategy": "min_hops"}).json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["clients"] == second["clients"]


def test_export_returns_result_schema(client):
    project = make_project(client)
    variant_id = project["variants"][0]["id"]
    client.post(f"/api/variants/{variant_id}/run", json={"strategy": "min_hops"})

    response = client.get(f"/api/variants/{variant_id}/export")
    body = response.json()

    assert body["schema_version"] == "cosmo-A-result-1.0"
    assert body["routes"]


def test_export_reuses_cached_run_with_matching_parameters(client):
    """I1: выгрузка должна отдавать те же числа, что показывались на экране —

    прогон с нестандартными параметрами, затем выгрузка с теми же
    параметрами обязаны совпасть, а не тихо взять умолчания.
    """
    project = make_project(client)
    variant_id = project["variants"][0]["id"]
    params = {"strategy": "min_hops", "hysteresis": 1.5, "with_backup": False}

    run_body = client.post(f"/api/variants/{variant_id}/run", json=params).json()
    assert run_body["cached"] is False

    export_body = client.get(
        f"/api/variants/{variant_id}/export",
        params={
            "strategy": params["strategy"],
            "hysteresis": params["hysteresis"],
            "with_backup": params["with_backup"],
        },
    ).json()

    for client_id, metrics in run_body["clients"].items():
        assert export_body["summary"]["clients"][client_id] == metrics

    # Тот же прогон обязан оказаться в кэше — повторный run с теми же
    # параметрами должен вернуться из кэша, а не пересчитаться заново.
    cached_again = client.post(f"/api/variants/{variant_id}/run", json=params).json()
    assert cached_again["cached"] is True


def test_export_with_default_parameters_differs_from_custom_run(client):
    """Отрицательный контроль к тесту выше: без совпадения параметров

    выгрузка не обязана (и не должна тихо) совпадать с посторонним прогоном —
    иначе предыдущий тест ничего бы не проверял.
    """
    project = make_project(client)
    variant_id = project["variants"][0]["id"]

    client.post(
        f"/api/variants/{variant_id}/run",
        json={"strategy": "min_hops", "hysteresis": 1.5, "with_backup": False},
    )
    export_body = client.get(f"/api/variants/{variant_id}/export").json()

    assert export_body["summary"]["strategy"] == "min_latency"


def test_snapshot_returns_network_state_at_moment(client):
    project = make_project(client)
    variant_id = project["variants"][0]["id"]

    response = client.get(f"/api/variants/{variant_id}/snapshot", params={"t_s": 3600})
    body = response.json()

    assert response.status_code == 200
    assert body["t_s"] == 3600
    assert len(body["satellites"]) == 48
    assert body["edges"]


def test_unknown_variant_returns_404(client):
    assert client.get("/api/variants/missing").status_code == 404


def test_cors_allows_arbitrary_origin(client):
    """Нужно фронтенду: фронт ходит с другого порта, CORS должен разрешать любой источник."""
    response = client.get(
        "/api/presets",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_compare_reports_deltas_and_changes(client):
    project = make_project(client)
    base_variant_id = project["variants"][0]["id"]
    scenario = copy.deepcopy(project["variants"][0]["scenario"])
    scenario["environment"]["isl_range_km"] = 2000.0
    variant = client.post(
        f"/api/projects/{project['id']}/variants",
        json={"title": "Меньше дальность", "scenario": scenario},
    ).json()

    response = client.post(
        "/api/compare",
        json={
            "base_variant_id": base_variant_id,
            "variant_id": variant["id"],
            "strategy": "min_hops",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert set(body["clients"]) == {"C65", "C70", "C72"}
    for client_id, comparison in body["clients"].items():
        assert comparison["availability_before"] is not None, client_id
        assert comparison["availability_after"] is not None, client_id
        assert comparison["availability_delta"] == pytest.approx(
            comparison["availability_after"] - comparison["availability_before"], abs=1e-6
        )
    assert "Дальность межспутниковой связи: 3000 → 2000 км" in [
        change["label"] for change in body["changes"]
    ]


def test_compare_with_unknown_variant_returns_404(client):
    project = make_project(client)
    base_variant_id = project["variants"][0]["id"]

    response = client.post(
        "/api/compare",
        json={"base_variant_id": base_variant_id, "variant_id": "missing"},
    )
    assert response.status_code == 404
