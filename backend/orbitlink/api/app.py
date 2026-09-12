"""HTTP-сервис OrbitLink."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from orbitlink.api.deps import require_variant
from orbitlink.api.network_packet import build_network_packet
from orbitlink.api.schemas import (
    CompareRequest,
    ProjectCreate,
    RunRequest,
    ScenarioPayload,
    VariantCreate,
    VariantPatch,
)
from orbitlink.api.selftest import run_selftest
from orbitlink.core.diff import diff_scenarios
from orbitlink.core.export import build_result_document
from orbitlink.core.geometry import ConstellationModel
from orbitlink.core.routing import RoutingStrategy
from orbitlink.core.scenario import normalize_scenario, validate_scenario
from orbitlink.core.simulate import run_result_from_payload, simulate
from orbitlink.paths import find_repo_root
from orbitlink.storage.models import Variant, create_engine_and_tables, session_factory
from orbitlink.storage.repository import (
    create_project,
    create_variant,
    find_run,
    fingerprint,
    get_project,
    list_projects,
    save_run,
    update_variant_scenario,
    variant_changes,
)

DATA_DIR = find_repo_root() / "data"
PRESET_IDS = [
    "01_full_constellation",
    "02_first_launch",
    "03_satellite_outages",
    "04_link_range",
]


def _validated(raw: dict[str, Any]) -> dict[str, Any]:
    report = validate_scenario(raw)
    if not report.ok:
        raise HTTPException(status_code=422, detail=report.as_dict())
    return normalize_scenario(raw)


def _variant_payload(variant: Variant) -> dict[str, Any]:
    return {
        "id": variant.id,
        "project_id": variant.project_id,
        "title": variant.title,
        "scenario": variant.scenario,
        "changes": [change.as_dict() for change in variant_changes(variant)],
    }


def create_app(database_url: str = "sqlite:///orbitlink.db") -> FastAPI:
    """Собирает приложение FastAPI с собственным движком БД."""
    engine = create_engine_and_tables(database_url)
    factory = session_factory(engine)
    app = FastAPI(title="OrbitLink", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_session():
        with factory() as session:
            yield session

    @app.get("/api/presets")
    def presets() -> list[dict[str, Any]]:
        items = []
        for preset_id in PRESET_IDS:
            scenario = json.loads((DATA_DIR / f"{preset_id}.json").read_text(encoding="utf-8"))
            items.append(
                {"id": preset_id, "title": scenario["meta"]["title"], "scenario": scenario}
            )
        return items

    @app.post("/api/scenarios/validate")
    def validate(payload: ScenarioPayload) -> dict[str, Any]:
        return validate_scenario(payload.scenario).as_dict()

    @app.post("/api/projects", status_code=201)
    def post_project(payload: ProjectCreate, session: Session = Depends(get_session)):
        project = create_project(
            session, title=payload.title, scenario=_validated(payload.scenario)
        )
        return {
            "id": project.id,
            "title": project.title,
            "variants": [_variant_payload(v) for v in project.variants],
        }

    @app.get("/api/projects")
    def get_projects(session: Session = Depends(get_session)):
        return [
            {"id": p.id, "title": p.title, "variant_count": len(p.variants)}
            for p in list_projects(session)
        ]

    @app.get("/api/projects/{project_id}")
    def get_one_project(project_id: str, session: Session = Depends(get_session)):
        project = get_project(session, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Проект не найден")
        return {
            "id": project.id,
            "title": project.title,
            "base_scenario": project.base_scenario,
            "variants": [_variant_payload(v) for v in project.variants],
        }

    @app.post("/api/projects/{project_id}/variants", status_code=201)
    def post_variant(
        project_id: str, payload: VariantCreate, session: Session = Depends(get_session)
    ):
        project = get_project(session, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Проект не найден")
        variant = create_variant(
            session,
            project=project,
            title=payload.title,
            scenario=_validated(payload.scenario),
        )
        return _variant_payload(variant)

    @app.get("/api/variants/{variant_id}")
    def get_one_variant(variant_id: str, session: Session = Depends(get_session)):
        return _variant_payload(require_variant(variant_id, session))

    @app.patch("/api/variants/{variant_id}")
    def patch_variant(
        variant_id: str, payload: VariantPatch, session: Session = Depends(get_session)
    ):
        variant = require_variant(variant_id, session)
        if payload.title is not None:
            variant.title = payload.title
        if payload.scenario is not None:
            update_variant_scenario(session, variant, _validated(payload.scenario))
        session.commit()
        return _variant_payload(variant)

    @app.post("/api/variants/{variant_id}/run")
    def run_variant(variant_id: str, payload: RunRequest, session: Session = Depends(get_session)):
        variant = require_variant(variant_id, session)
        key = fingerprint(
            variant.scenario, payload.strategy.value, payload.hysteresis, payload.with_backup
        )

        cached = find_run(session, variant, key)
        if cached is not None:
            return {**cached.payload, "cached": True}

        result = simulate(
            variant.scenario,
            strategy=payload.strategy,
            hysteresis=payload.hysteresis,
            with_backup=payload.with_backup,
        ).as_dict()
        save_run(
            session,
            variant,
            fingerprint=key,
            strategy=payload.strategy.value,
            payload=result,
        )
        return {**result, "cached": False}

    @app.get("/api/variants/{variant_id}/export")
    def export_variant(
        variant_id: str,
        strategy: RoutingStrategy = Query(default=RoutingStrategy.MIN_LATENCY),
        hysteresis: float = Query(default=0.3, ge=0.0, le=5.0),
        with_backup: bool = Query(default=True),
        session: Session = Depends(get_session),
    ):
        """Выгрузка обязана считать те же числа, что видел пользователь на экране:

        принимает те же параметры, что и прогон, и сначала ищет готовый
        результат в кэше по тому же отпечатку конфигурации — только если его
        там нет, считает заново (и кладёт в кэш, как это делает сам прогон).
        """
        variant = require_variant(variant_id, session)
        key = fingerprint(variant.scenario, strategy.value, hysteresis, with_backup)

        cached = find_run(session, variant, key)
        if cached is not None:
            run = run_result_from_payload(variant.scenario, strategy, cached.payload)
        else:
            run = simulate(
                variant.scenario, strategy=strategy, hysteresis=hysteresis, with_backup=with_backup
            )
            save_run(
                session,
                variant,
                fingerprint=key,
                strategy=strategy.value,
                payload=run.as_dict(),
            )
        return build_result_document(run, notes=f"Вариант «{variant.title}»")

    @app.get("/api/variants/{variant_id}/snapshot")
    def snapshot_variant(
        variant_id: str, t_s: float = Query(...), session: Session = Depends(get_session)
    ):
        variant = require_variant(variant_id, session)
        return ConstellationModel(variant.scenario).snapshot(t_s).as_dict()

    @app.get("/api/variants/{variant_id}/network")
    def network_packet(variant_id: str, session: Session = Depends(get_session)):
        variant = require_variant(variant_id, session)
        return Response(
            content=build_network_packet(variant.scenario),
            media_type="application/octet-stream",
        )

    @app.post("/api/compare")
    def compare_variants(payload: CompareRequest, session: Session = Depends(get_session)):
        """Сравнение доступности «до/после» между базовым вариантом и вариантом.

        Сверх плана: нужно фронтенду для экрана сравнения — доступность и
        максимальный перерыв каждого клиентского пункта до/после, дельты и
        список изменённых параметров сценария (`diff_scenarios`).
        """
        base_variant = require_variant(payload.base_variant_id, session)
        variant = require_variant(payload.variant_id, session)

        base_result = simulate(
            base_variant.scenario,
            strategy=payload.strategy,
            hysteresis=payload.hysteresis,
            with_backup=payload.with_backup,
        )
        variant_result = simulate(
            variant.scenario,
            strategy=payload.strategy,
            hysteresis=payload.hysteresis,
            with_backup=payload.with_backup,
        )

        client_ids = sorted(set(base_result.clients) | set(variant_result.clients))
        clients_payload: dict[str, Any] = {}
        for client_id in client_ids:
            before = base_result.clients.get(client_id)
            after = variant_result.clients.get(client_id)
            before_availability = before.availability_fraction if before else None
            after_availability = after.availability_fraction if after else None
            before_gap = before.max_gap_s if before else None
            after_gap = after.max_gap_s if after else None
            clients_payload[client_id] = {
                "availability_before": before_availability,
                "availability_after": after_availability,
                "availability_delta": (
                    round(after_availability - before_availability, 6)
                    if before_availability is not None and after_availability is not None
                    else None
                ),
                "max_gap_s_before": before_gap,
                "max_gap_s_after": after_gap,
                "max_gap_s_delta": (
                    after_gap - before_gap
                    if before_gap is not None and after_gap is not None
                    else None
                ),
            }

        return {
            "base_variant_id": payload.base_variant_id,
            "variant_id": payload.variant_id,
            "strategy": payload.strategy.value,
            "clients": clients_payload,
            "changes": [
                change.as_dict()
                for change in diff_scenarios(base_variant.scenario, variant.scenario)
            ],
        }

    @app.get("/api/selftest")
    def selftest():
        return run_selftest()

    return app


app = create_app(os.environ.get("ORBITLINK_DB", "sqlite:///orbitlink.db"))
