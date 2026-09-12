"""Выгрузка результата расчёта в схеме cosmo-A-result-1.0.

Документ содержит полный использованный сценарий и по одной записи на
каждую пару «отсчёт — клиентский пункт». Пустой путь означает отсутствие
маршрута. Сверх обязательного состава прикладываются сводные показатели
и пояснения: ТЗ это допускает, а для сравнения вариантов это необходимо.

Круговой оборот — главное требование задачи: `effective_scenario` обязан
быть тем же самым сценарием, что был использован для расчёта (после
проверки и нормализации), без каких-либо усечений или подмен полей.
Именно поэтому раздел строится из `run.scenario` целиком, а не собирается
заново из отдельных значений — так исключается риск молча потерять поле,
которое появится в схеме входных данных позже.
"""

from __future__ import annotations

from orbitlink.core.scenario import RESULT_SCHEMA_VERSION
from orbitlink.core.simulate import RunResult


def build_result_document(run: RunResult, *, notes: str | None = None) -> dict:
    """Собирает документ выгрузки результата прогона в схеме cosmo-A-result-1.0.

    `notes` — необязательное пояснение к прогону (например, какой вариант
    отказов или стратегия сравнивались); в схему организаторов не входит,
    но явно предусмотрено интерфейсом задачи для удобства сравнения вариантов.
    """
    environment = run.scenario["environment"]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "effective_scenario": run.scenario,
        "routes": [
            {
                "t_s": record.t_s,
                "client_id": record.client_id,
                "path": record.path,
                "hops": record.hops,
                "latency_ms": (None if record.latency_ms is None else round(record.latency_ms, 3)),
                "reason": record.reason,
                "has_backup": record.has_backup,
            }
            for record in run.routes
        ],
        "summary": {
            "strategy": run.strategy.value,
            "step_s": environment["step_s"],
            "horizon_s": environment["horizon_s"],
            "target_availability": environment["target_availability"],
            "clients": {cid: metrics.as_dict() for cid, metrics in run.clients.items()},
        },
        "notes": notes,
    }
