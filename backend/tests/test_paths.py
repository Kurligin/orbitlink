"""Разрешение пути к каталогу сценариев и эталонному модулю организаторов.

`find_repo_root()` вызывается на уровне модуля в `api/app.py` и
`api/selftest.py` — при неподходящем рабочем каталоге падает импорт всего
приложения, а не два эндпоинта, поэтому здесь важно закрыть все три пути
разрешения: через переменную окружения, через рабочий каталог (когда путь
от расположения файла не подходит) и понятную ошибку, когда не найдено
ничего.
"""

from __future__ import annotations

import pytest

import orbitlink.paths as paths
from tests.conftest import REPO_ROOT


def test_resolves_via_environment_variable(monkeypatch):
    monkeypatch.setenv("ORBITLINK_REPO_ROOT", str(REPO_ROOT))
    assert paths.find_repo_root() == REPO_ROOT


def test_environment_variable_pointing_nowhere_useful_fails_clearly(monkeypatch, tmp_path):
    """Фикс C-I2: неверно заданная переменная должна давать понятную ошибку

    сразу, а не молчаливо приниматься — иначе сервис падает позже и в другом
    месте (например, `FileNotFoundError` при чтении `/api/presets`), где
    настоящая причина уже не видна.
    """
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.setenv("ORBITLINK_REPO_ROOT", str(empty))

    with pytest.raises(RuntimeError, match="ORBITLINK_REPO_ROOT") as excinfo:
        paths.find_repo_root()
    assert str(empty) in str(excinfo.value)


def test_falls_back_to_working_directory_when_file_location_does_not_fit(monkeypatch, tmp_path):
    """Обычная установка (см. `deploy/backend.Dockerfile`): исходники лежат в

    site-packages, подъём от `__file__` ничего не находит, поэтому сервис
    обязан подняться по дереву рабочего каталога процесса и найти `data/` и
    `docs/reference_geometry.py`, которые Dockerfile кладёт рядом с ним.
    """
    monkeypatch.delenv("ORBITLINK_REPO_ROOT", raising=False)
    # Имитация обычной установки: `__file__` указывает на путь без соседних
    # data/ и docs/reference_geometry.py вообще (в отличие от editable-
    # установки, где `here.parents[2]` — настоящий корень репозитория).
    fake_file = tmp_path / "site-packages" / "orbitlink" / "paths.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("# заглушка для теста\n", encoding="utf-8")
    monkeypatch.setattr(paths, "__file__", str(fake_file))

    workdir = tmp_path / "work"
    (workdir / "data").mkdir(parents=True)
    (workdir / "docs").mkdir()
    (workdir / "docs" / "reference_geometry.py").write_text("# заглушка\n", encoding="utf-8")
    monkeypatch.chdir(workdir)

    assert paths.find_repo_root() == workdir


def test_gives_clear_error_when_nothing_is_found(monkeypatch, tmp_path):
    monkeypatch.delenv("ORBITLINK_REPO_ROOT", raising=False)
    fake_file = tmp_path / "site-packages" / "orbitlink" / "paths.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.write_text("# заглушка для теста\n", encoding="utf-8")
    monkeypatch.setattr(paths, "__file__", str(fake_file))

    empty_workdir = tmp_path / "empty-work"
    empty_workdir.mkdir()
    monkeypatch.chdir(empty_workdir)

    with pytest.raises(RuntimeError, match="ORBITLINK_REPO_ROOT"):
        paths.find_repo_root()
