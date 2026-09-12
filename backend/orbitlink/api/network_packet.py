"""Компактная передача состояния сети на всей сетке времени.

Перемотка времени должна быть мгновенной, поэтому фронтенд получает
позиции и связи одним пакетом и работает локально. Числа передаются
как float32: для отображения этого достаточно, а объём втрое меньше,
чем у JSON с той же информацией.
"""

from __future__ import annotations

import json
import struct

import numpy as np

from orbitlink.core.geometry import ConstellationModel
from orbitlink.core.simulate import GeometryCache


def build_network_packet(scenario: dict) -> bytes:
    """Собирает бинарный пакет позиций и связей по всей сетке времени."""
    model = ConstellationModel(scenario)
    cache = GeometryCache(model)

    node_ids = list(model.satellite_ids) + [site["id"] for site in model.ground_sites]
    node_index = {name: position for position, name in enumerate(node_ids)}

    positions = np.zeros((len(cache.times), len(model.satellite_ids), 3), dtype="<f4")
    edge_blocks: list[bytes] = []
    edge_counts: list[int] = []
    active_flags: list[list[bool]] = []

    for index in range(len(cache.times)):
        snapshot = cache.snapshot_at(index, model)
        positions[index] = snapshot.positions_km.astype("<f4")
        active_flags.append([bool(flag) for flag in snapshot.active])

        pairs = np.array(
            [[node_index[a], node_index[b]] for a, b, _ in snapshot.edges], dtype="<u2"
        ).reshape(-1, 2)
        lengths = np.array([d for _, _, d in snapshot.edges], dtype="<f4")

        edge_counts.append(len(snapshot.edges))
        edge_blocks.append(pairs.tobytes() + lengths.tobytes())

    header = {
        "satellite_ids": list(model.satellite_ids),
        "node_ids": node_ids,
        "ground_sites": [
            {"id": site["id"], "role": site["role"], "name": site.get("name", site["id"])}
            for site in model.ground_sites
        ],
        "times": list(cache.times),
        "step_s": model.step_s,
        "edge_counts": edge_counts,
        "active": active_flags,
    }
    encoded = json.dumps(header, ensure_ascii=False).encode("utf-8")
    # Массив позиций (float32) должен начинаться на смещении, кратном четырём
    # байтам, иначе `new Float32Array(buffer, offset, n)` во фронтенде бросает
    # RangeError — а длина JSON-заголовка произвольна и зависит от сценария.
    # Добиваем заголовок пробелами (JSON игнорирует конечные пробелы при
    # разборе) до длины, кратной четырём; длина в первых четырёх байтах
    # пакета учитывает добивку, поэтому разбор остаётся однозначным. Блоки
    # рёбер выровнены относительно начала позиций сами по себе: каждый блок
    # («пары» uint16 + «длины» float32) занимает количество байт, кратное
    # четырём, поэтому выравнивать нужно только заголовок один раз.
    encoded += b" " * ((-len(encoded)) % 4)
    return struct.pack("<I", len(encoded)) + encoded + positions.tobytes() + b"".join(edge_blocks)


def parse_network_packet(blob: bytes) -> dict:
    """Разбор пакета. Используется тестами и служит описанием формата."""
    (header_length,) = struct.unpack_from("<I", blob, 0)
    offset = 4
    meta = json.loads(blob[offset : offset + header_length].decode("utf-8"))
    offset += header_length

    steps = len(meta["times"])
    satellites = len(meta["satellite_ids"])
    size = steps * satellites * 3 * 4
    positions = np.frombuffer(blob, dtype="<f4", count=steps * satellites * 3, offset=offset)
    positions = positions.reshape(steps, satellites, 3)
    offset += size

    edges: list[list[tuple[int, int, float]]] = []
    for count in meta["edge_counts"]:
        pairs = np.frombuffer(blob, dtype="<u2", count=count * 2, offset=offset)
        offset += count * 2 * 2
        lengths = np.frombuffer(blob, dtype="<f4", count=count, offset=offset)
        offset += count * 4
        pairs = pairs.reshape(-1, 2)
        edges.append([(int(a), int(b), float(d)) for (a, b), d in zip(pairs, lengths, strict=True)])

    return {"meta": meta, "positions": positions, "edges": edges}
