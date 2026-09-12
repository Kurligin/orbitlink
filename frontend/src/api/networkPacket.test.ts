import { describe, expect, it } from "vitest";
import {
  nearestStepIndex,
  parseNetworkPacket,
  satellitePositionAt,
} from "./networkPacket";

/**
 * Собирает бинарный пакет вручную, байт в байт по формату из
 * backend/orbitlink/api/network_packet.py, чтобы проверить разбор
 * независимо от какого-либо кода кодирования на фронтенде.
 *
 * `headerPadding` — число пробелов, дописанных в конец JSON заголовка (JSON
 * допускает завершающие пробелы, `JSON.parse` их игнорирует). Параметр нужен,
 * чтобы намеренно двигать смещение, с которого начинаются позиции/рёбра, и
 * проверять оба случая: когда оно кратно 4 байтам и когда нет — см. тест
 * ниже про выравнивание.
 */
function buildPacketByHand(headerPadding = 0): ArrayBuffer {
  const header = {
    satellite_ids: ["SA", "SB"],
    node_ids: ["SA", "SB", "G1"],
    ground_sites: [{ id: "G1", role: "gateway", name: "Gateway 1" }],
    times: [0, 120],
    step_s: 120,
    edge_counts: [2, 1],
    active: [
      [true, true],
      [true, false],
    ],
  };
  const headerBytes = new TextEncoder().encode(
    JSON.stringify(header) + " ".repeat(headerPadding),
  );

  // 2 отсчёта x 2 аппарата x 3 координаты
  const positions = new Float32Array([
    1,
    2,
    3,
    4,
    5,
    6, // отсчёт 0: SA, SB
    7,
    8,
    9,
    10,
    11,
    12, // отсчёт 1: SA, SB
  ]);

  // отсчёт 0: два ребра (SA-SB) и (SA-G1)
  const pairs0 = new Uint16Array([0, 1, 0, 2]);
  const lengths0 = new Float32Array([111.5, 222.25]);
  // отсчёт 1: одно ребро (SB-G1)
  const pairs1 = new Uint16Array([1, 2]);
  const lengths1 = new Float32Array([333.75]);

  const totalLength =
    4 +
    headerBytes.byteLength +
    positions.byteLength +
    pairs0.byteLength +
    lengths0.byteLength +
    pairs1.byteLength +
    lengths1.byteLength;

  const buffer = new ArrayBuffer(totalLength);
  const view = new DataView(buffer);
  let offset = 0;

  view.setUint32(offset, headerBytes.byteLength, true);
  offset += 4;

  new Uint8Array(buffer, offset, headerBytes.byteLength).set(headerBytes);
  offset += headerBytes.byteLength;

  new Uint8Array(buffer, offset, positions.byteLength).set(
    new Uint8Array(positions.buffer),
  );
  offset += positions.byteLength;

  for (const chunk of [pairs0, lengths0, pairs1, lengths1]) {
    new Uint8Array(buffer, offset, chunk.byteLength).set(
      new Uint8Array(chunk.buffer),
    );
    offset += chunk.byteLength;
  }

  return buffer;
}

describe("parseNetworkPacket", () => {
  it("разбирает вручную собранный пакет и восстанавливает исходные данные", () => {
    const buffer = buildPacketByHand();
    const packet = parseNetworkPacket(buffer);

    expect(packet.satelliteIds).toEqual(["SA", "SB"]);
    expect(packet.nodeIds).toEqual(["SA", "SB", "G1"]);
    expect(packet.groundSites).toEqual([
      { id: "G1", role: "gateway", name: "Gateway 1" },
    ]);
    expect(packet.times).toEqual([0, 120]);
    expect(packet.stepS).toBe(120);
    expect(packet.steps).toBe(2);
    expect(packet.satelliteCount).toBe(2);
    expect(packet.activeByStep).toEqual([
      [true, true],
      [true, false],
    ]);

    expect(satellitePositionAt(packet, 0, 0)).toEqual([1, 2, 3]);
    expect(satellitePositionAt(packet, 0, 1)).toEqual([4, 5, 6]);
    expect(satellitePositionAt(packet, 1, 0)).toEqual([7, 8, 9]);
    expect(satellitePositionAt(packet, 1, 1)).toEqual([10, 11, 12]);

    expect(packet.edgesByStep).toHaveLength(2);
    expect(packet.edgesByStep[0]).toEqual([
      { a: 0, b: 1, lengthKm: 111.5 },
      { a: 0, b: 2, lengthKm: 222.25 },
    ]);
    expect(packet.edgesByStep[1]).toEqual([{ a: 1, b: 2, lengthKm: 333.75 }]);
  });

  it("nearestStepIndex округляет ко времени и держит границы", () => {
    const packet = parseNetworkPacket(buildPacketByHand());
    expect(nearestStepIndex(packet, 0)).toBe(0);
    expect(nearestStepIndex(packet, 61)).toBe(1);
    expect(nearestStepIndex(packet, 59)).toBe(0);
    expect(nearestStepIndex(packet, 1e6)).toBe(1);
    expect(nearestStepIndex(packet, -50)).toBe(0);
  });

  it.each([0, 1, 2, 3])(
    "разбирает пакет независимо от выравнивания заголовка (паддинг=%d байт)",
    (padding) => {
      const buffer = buildPacketByHand(padding);
      // Смещение позиций = 4 (длина) + длина заголовка. Перебор паддинга 0..3
      // гарантированно проходит и по кратному 4, и по некратным случаям —
      // именно так на бэкенде воспроизводится баг с произвольной длиной
      // заголовка (в реальном пакете полной группировки остаток был 3).
      const packet = parseNetworkPacket(buffer);
      expect(satellitePositionAt(packet, 0, 0)).toEqual([1, 2, 3]);
      expect(satellitePositionAt(packet, 1, 1)).toEqual([10, 11, 12]);
      expect(packet.edgesByStep[0]).toEqual([
        { a: 0, b: 1, lengthKm: 111.5 },
        { a: 0, b: 2, lengthKm: 222.25 },
      ]);
      expect(packet.edgesByStep[1]).toEqual([{ a: 1, b: 2, lengthKm: 333.75 }]);
    },
  );
});
