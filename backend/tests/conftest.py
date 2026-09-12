"""Общие фикстуры: сценарии организаторов и эталонный расчётный модуль."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
REFERENCE_PATH = REPO_ROOT / "docs" / "reference_geometry.py"

SCENARIO_NAMES = [
    "01_full_constellation",
    "02_first_launch",
    "03_satellite_outages",
    "04_link_range",
]


@pytest.fixture(scope="session")
def reference():
    """Эталонный модуль организаторов, загруженный по пути."""
    spec = importlib.util.spec_from_file_location("reference_geometry", REFERENCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["reference_geometry"] = module
    spec.loader.exec_module(module)
    return module


def read_scenario(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(params=SCENARIO_NAMES)
def scenario_name(request) -> str:
    return request.param


@pytest.fixture
def scenario(scenario_name: str) -> dict:
    return read_scenario(scenario_name)
