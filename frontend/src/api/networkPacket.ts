/**
 * Разбор бинарного пакета `GET /api/variants/{id}/network`.
 *
 * Формат (little-endian), см. backend/orbitlink/api/network_packet.py:
 *   [uint32 длина заголовка]
 *   [заголовок JSON, UTF-8, ровно указанной длины]
 *   [float32 позиции аппаратов, форма (отсчёты, аппараты, 3), км, СК связана с Землёй]
 *   затем для каждого отсчёта подряд:
 *     [uint16 * edge_count * 2 — пары индексов узлов]
 *     [float32 * edge_count — длины рёбер, км]
 * `edge_count` для отсчёта k — это `header.edge_counts[k]`.
 *
 * Индексы узлов в парах рёбер — это индексы в `node_ids` (сначала аппараты
 * в порядке `satellite_ids`, затем наземные пункты), а НЕ в `satellite_ids`.
 *
 * Выравнивание: длина заголовка произвольна (бэкенд может дополнительно
 * добивать её пробелами до кратности 4 байтам — `JSON.parse` завершающие
 * пробелы игнорирует), поэтому смещение, с которого начинаются позиции и
 * рёбра, не гарантированно кратно 4 байтам. Прямое построение
 * `Float32Array`/`Uint16Array` поверх исходного `ArrayBuffer` по такому
 * смещению бросает `RangeError`. Поэтому ниже везде сначала делается
 * `buffer.slice(...)` (копия среза в новый `ArrayBuffer`, начинающийся с 0),
 * и только потом поверх среза строится типизированный массив — это работает
 * при любом исходном смещении. См. тест на паддинг заголовка 0..3 байта.
 */

export interface NetworkGroundSite {
  id: string;
  role: "gateway" | "client" | string;
  name: string;
}

/** Ребро отсчёта: `a`/`b` — индексы в `NetworkPacket.nodeIds`. */
export interface NetworkEdge {
  a: number;
  b: number;
  lengthKm: number;
}

export interface NetworkPacket {
  satelliteIds: string[];
  nodeIds: string[];
  groundSites: NetworkGroundSite[];
  times: number[];
  stepS: number;
  steps: number;
  satelliteCount: number;
  /** Плоский Float32Array формы (steps, satelliteCount, 3), км. */
  positions: Float32Array;
  edgesByStep: NetworkEdge[][];
  activeByStep: boolean[][];
}

interface NetworkPacketHeader {
  satellite_ids: string[];
  node_ids: string[];
  ground_sites: NetworkGroundSite[];
  times: number[];
  step_s: number;
  edge_counts: number[];
  active: boolean[][];
}

export function parseNetworkPacket(buffer: ArrayBuffer): NetworkPacket {
  const view = new DataView(buffer);
  const headerLength = view.getUint32(0, true);
  let offset = 4;

  const headerBytes = new Uint8Array(buffer, offset, headerLength);
  const header = JSON.parse(
    new TextDecoder("utf-8").decode(headerBytes),
  ) as NetworkPacketHeader;
  offset += headerLength;

  const steps = header.times.length;
  const satelliteCount = header.satellite_ids.length;
  const positionsCount = steps * satelliteCount * 3;
  const positions = new Float32Array(
    buffer.slice(offset, offset + positionsCount * 4),
  );
  offset += positionsCount * 4;

  const edgesByStep: NetworkEdge[][] = [];
  for (const edgeCount of header.edge_counts) {
    const pairsBytes = edgeCount * 2 * 2; // uint16 * 2 индекса на ребро
    const pairs = new Uint16Array(buffer.slice(offset, offset + pairsBytes));
    offset += pairsBytes;

    const lengthsBytes = edgeCount * 4;
    const lengths = new Float32Array(
      buffer.slice(offset, offset + lengthsBytes),
    );
    offset += lengthsBytes;

    const edges: NetworkEdge[] = new Array(edgeCount);
    for (let k = 0; k < edgeCount; k += 1) {
      edges[k] = {
        a: pairs[2 * k]!,
        b: pairs[2 * k + 1]!,
        lengthKm: lengths[k]!,
      };
    }
    edgesByStep.push(edges);
  }

  return {
    satelliteIds: header.satellite_ids,
    nodeIds: header.node_ids,
    groundSites: header.ground_sites,
    times: header.times,
    stepS: header.step_s,
    steps,
    satelliteCount,
    positions,
    edgesByStep,
    activeByStep: header.active,
  };
}

/** Позиция аппарата `satIndex` на отсчёте `stepIndex`, км, СК связана с Землёй. */
export function satellitePositionAt(
  packet: NetworkPacket,
  stepIndex: number,
  satIndex: number,
): [number, number, number] {
  const base = (stepIndex * packet.satelliteCount + satIndex) * 3;
  return [
    packet.positions[base]!,
    packet.positions[base + 1]!,
    packet.positions[base + 2]!,
  ];
}

/** Индекс отсчёта времени, ближайший к `tS` (без выхода за пределы массива). */
export function nearestStepIndex(packet: NetworkPacket, tS: number): number {
  if (packet.steps === 0) return 0;
  const raw = Math.round(tS / packet.stepS);
  return Math.min(Math.max(raw, 0), packet.steps - 1);
}
