"""Сверка расчётного ядра с эталонным модулем организаторов.

Вынесена в сервис намеренно: на вопрос эксперта о корректности расчёта
ответом служит запуск проверки при нём, а не устное заверение.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from typing import Any

import numpy as np

from orbitlink.core.geometry import ConstellationModel
from orbitlink.paths import find_repo_root

REPO_ROOT = find_repo_root()
DATA_DIR = REPO_ROOT / "data"
REFERENCE_PATH = REPO_ROOT / "docs" / "reference_geometry.py"

SCENARIO_NAMES = [
    "01_full_constellation",
    "02_first_launch",
    "03_satellite_outages",
    "04_link_range",
]
CONTROL_TIMES = [0, 3600, 21600, 43200, 86280]


def _reference():
    spec = importlib.util.spec_from_file_location("reference_geometry", REFERENCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["reference_geometry"] = module
    spec.loader.exec_module(module)
    return module


def run_selftest() -> dict[str, Any]:
    """Сверяет координаты, состав рёбер и углы возвышения с эталоном на контрольных точках."""
    reference = _reference()
    checks: list[dict[str, Any]] = []

    for name in SCENARIO_NAMES:
        scenario = json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        model = ConstellationModel(scenario)

        for t_s in CONTROL_TIMES:
            ours = model.snapshot(t_s)
            theirs = reference.snapshot(scenario, t_s)

            _, _, their_positions = reference.positions(scenario, t_s)
            position_error = float(np.max(np.abs(ours.positions_km - their_positions)))

            our_edges = {(min(a, b), max(a, b)) for a, b, _ in ours.edges}
            their_edges = {(min(a, b), max(a, b)) for a, b, _ in theirs["edges"]}

            elevation_error = 0.0
            for site_id, angles in theirs["elevation_deg"].items():
                for sat_id, angle in angles.items():
                    elevation_error = max(
                        elevation_error, abs(ours.elevation_deg[site_id][sat_id] - angle)
                    )

            checks.append(
                {
                    "scenario": name,
                    "t_s": t_s,
                    "max_position_error_km": position_error,
                    "edges_match": our_edges == their_edges,
                    "our_edge_count": len(our_edges),
                    "reference_edge_count": len(their_edges),
                    "max_elevation_error_deg": elevation_error,
                }
            )

    ok = all(
        check["edges_match"]
        and check["max_position_error_km"] < 1e-9
        and check["max_elevation_error_deg"] < 1e-9
        for check in checks
    )
    return {"ok": ok, "checks": checks, "reference": str(REFERENCE_PATH.name)}
