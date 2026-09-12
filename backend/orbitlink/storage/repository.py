"""Операции над проектами и вариантами."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from orbitlink.core.diff import Change, diff_scenarios
from orbitlink.storage.models import Project, Run, Variant


def create_project(session: Session, *, title: str, scenario: dict) -> Project:
    """Создаёт проект и базовый вариант, совпадающий с исходным сценарием."""
    project = Project(title=title, base_scenario=scenario)
    project.variants.append(Variant(title="Базовый", scenario=scenario))
    session.add(project)
    session.commit()
    return project


def list_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at.desc())))


def get_project(session: Session, project_id: str) -> Project | None:
    return session.get(Project, project_id)


def create_variant(session: Session, *, project: Project, title: str, scenario: dict) -> Variant:
    variant = Variant(project_id=project.id, title=title, scenario=scenario)
    session.add(variant)
    session.commit()
    return variant


def get_variant(session: Session, variant_id: str) -> Variant | None:
    return session.get(Variant, variant_id)


def update_variant_scenario(session: Session, variant: Variant, scenario: dict) -> Variant:
    variant.scenario = scenario
    session.commit()
    return variant


def variant_changes(variant: Variant) -> list[Change]:
    """Изменения варианта относительно базового сценария проекта."""
    return diff_scenarios(variant.project.base_scenario, variant.scenario)


def fingerprint(scenario: dict, strategy: str, hysteresis: float, with_backup: bool) -> str:
    """Отпечаток конфигурации: одинаковый вход даёт одинаковый результат.

    `with_backup` обязан входить в отпечаток наравне со сценарием, стратегией
    и гистерезисом: этот флаг передаётся в `simulate()` и реально меняет
    результат (подавляет поиск резервного маршрута — `has_backup` в каждой
    маршрутной записи, `backup_fraction` и `margin_levels` расходятся между
    `with_backup=True/False`). Без него кэш прогонов отдавал бы чужой
    результат на запрос с другим значением флага.
    """
    payload = json.dumps(
        {
            "scenario": scenario,
            "strategy": strategy,
            "hysteresis": hysteresis,
            "with_backup": with_backup,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_run(session: Session, variant: Variant, key: str) -> Run | None:
    return session.scalars(
        select(Run).where(Run.variant_id == variant.id, Run.fingerprint == key).limit(1)
    ).first()


def save_run(
    session: Session, variant: Variant, *, fingerprint: str, strategy: str, payload: dict
) -> Run:
    run = Run(variant_id=variant.id, fingerprint=fingerprint, strategy=strategy, payload=payload)
    session.add(run)
    session.commit()
    return run
