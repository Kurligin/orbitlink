"""Определение путей к каталогу сценариев и эталонному модулю организаторов.

При editable-установке (`pip install -e`, локальная разработка) `__file__`
указывает внутрь самого репозитория — тогда `data/` и `docs/` находятся
подъёмом по дереву от расположения этого файла. При обычной установке
(как в Docker-образе, см. `deploy/backend.Dockerfile`) исходники копируются
в site-packages, где подъём от `__file__` уже ничего не находит — Dockerfile
кладёт `data/` и `docs/` рядом с рабочим каталогом процесса, поэтому в этом
случае каталоги ищутся от текущего рабочего каталога и его родителей.
`ORBITLINK_REPO_ROOT` перекрывает оба способа явно.
"""

from __future__ import annotations

import os
from pathlib import Path


def find_repo_root() -> Path:
    """Возвращает каталог, где рядом лежат `data/` и `docs/reference_geometry.py`."""
    override = os.environ.get("ORBITLINK_REPO_ROOT")
    if override:
        candidate = Path(override)
        has_data = (candidate / "data").is_dir()
        has_reference = (candidate / "docs" / "reference_geometry.py").is_file()
        if has_data and has_reference:
            return candidate
        # Явная и понятная ошибка сразу, а не молчаливое принятие неверного
        # пути: без этой проверки сервис падал бы позже и в другом месте —
        # например, FileNotFoundError при чтении /api/presets — там, где
        # причину (неверно заданную переменную окружения) уже не видно.
        raise RuntimeError(
            f"Переменная ORBITLINK_REPO_ROOT указывает на «{candidate}», но там нет "
            "data/ и/или docs/reference_geometry.py — проверьте путь."
        )

    here = Path(__file__).resolve()
    candidates = [here.parents[2], Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        has_data = (candidate / "data").is_dir()
        has_reference = (candidate / "docs" / "reference_geometry.py").is_file()
        if has_data and has_reference:
            return candidate

    raise RuntimeError(
        "Не удалось найти каталоги data/ и docs/reference_geometry.py рядом ни с "
        "расположением пакета, ни с рабочим каталогом процесса — задайте "
        "переменную окружения ORBITLINK_REPO_ROOT явно."
    )
