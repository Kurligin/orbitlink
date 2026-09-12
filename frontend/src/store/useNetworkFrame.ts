import { useMemo } from "react";
import { cartesianToLatLon } from "../geo/projection";
import { EARTH_RADIUS_KM } from "../geo/orbit";
import { satellitePositionAt } from "../api/networkPacket";
import { routeKey, useWorkspace } from "./workspace";

export interface FrameSatellite {
  id: string;
  latDeg: number;
  lonDeg: number;
  active: boolean;
  selected: boolean;
  onRoute: boolean;
}

export interface FrameGroundSite {
  id: string;
  name: string;
  role: "gateway" | "client" | string;
  latDeg: number;
  lonDeg: number;
  focused: boolean;
}

export interface FrameEdge {
  aId: string;
  bId: string;
  lengthKm: number;
  onRoute: boolean;
}

export interface NodePosition {
  latDeg: number;
  lonDeg: number;
  /** Высота над поверхностью, доля радиуса Земли (0 — наземный пункт). */
  altitudeFraction: number;
}

export interface NetworkFrame {
  satellites: FrameSatellite[];
  groundSites: FrameGroundSite[];
  edges: FrameEdge[];
  /** Координаты + высота каждого узла сети (аппараты и наземные пункты) по id. */
  nodePositions: Map<string, NodePosition>;
  /** Высота орбиты, доля радиуса Земли — для отрисовки аппаратов и колец орбит. */
  satelliteAltitudeFraction: number;
  /** Узлы текущего маршрута выбранного клиентского пункта, по порядку. */
  routeNodeIds: string[];
  routeText: string | null;
}

/**
 * Собирает всё, что нужно для отрисовки одного кадра сети (3D-глобус и
 * 2D-полярная проекция потребляют один и тот же кадр), из бинарного пакета
 * + сценария (координаты наземных пунктов в пакете НЕ передаются — только
 * id/role/name, поэтому lat/lon берутся из `scenario.ground_sites`).
 */
export function useNetworkFrame(): NetworkFrame | null {
  const {
    scenario,
    networkPacket,
    stepIndex,
    selection,
    focusClientId,
    routeIndex,
    currentTS,
  } = useWorkspace();

  return useMemo(() => {
    if (!scenario || !networkPacket) return null;
    const stepEdges = networkPacket.edgesByStep[stepIndex] ?? [];
    const activeFlags = networkPacket.activeByStep[stepIndex] ?? [];
    const satelliteAltitudeFraction =
      scenario.environment.altitude_km / EARTH_RADIUS_KM;

    const route = focusClientId
      ? routeIndex.get(routeKey(focusClientId, currentTS))
      : undefined;
    const routeNodeIds = route?.path ?? [];
    const routeEdgeKeys = new Set<string>();
    for (let i = 0; i + 1 < routeNodeIds.length; i += 1) {
      const a = routeNodeIds[i]!;
      const b = routeNodeIds[i + 1]!;
      routeEdgeKeys.add(a < b ? `${a}|${b}` : `${b}|${a}`);
    }

    const nodePositions = new Map<string, NodePosition>();

    const satellites: FrameSatellite[] = networkPacket.satelliteIds.map(
      (id, index) => {
        const [x, y, z] = satellitePositionAt(networkPacket, stepIndex, index);
        const { latDeg, lonDeg } = cartesianToLatLon(x, y, z);
        nodePositions.set(id, {
          latDeg,
          lonDeg,
          altitudeFraction: satelliteAltitudeFraction,
        });
        return {
          id,
          latDeg,
          lonDeg,
          active: activeFlags[index] ?? false,
          selected:
            selection?.kind === "satellite" && selection.satelliteId === id,
          onRoute: routeNodeIds.includes(id),
        };
      },
    );

    const groundSites: FrameGroundSite[] = scenario.ground_sites.map((site) => {
      nodePositions.set(site.id, {
        latDeg: site.lat_deg,
        lonDeg: site.lon_deg,
        altitudeFraction: 0,
      });
      return {
        id: site.id,
        name: site.name,
        role: site.role,
        latDeg: site.lat_deg,
        lonDeg: site.lon_deg,
        focused: site.role === "client" && site.id === focusClientId,
      };
    });

    const edges: FrameEdge[] = stepEdges.map((edge) => {
      const aId = networkPacket.nodeIds[edge.a] ?? String(edge.a);
      const bId = networkPacket.nodeIds[edge.b] ?? String(edge.b);
      const key = aId < bId ? `${aId}|${bId}` : `${bId}|${aId}`;
      return {
        aId,
        bId,
        lengthKm: edge.lengthKm,
        onRoute: routeEdgeKeys.has(key),
      };
    });

    const routeText = routeNodeIds.length > 0 ? routeNodeIds.join(" → ") : null;

    return {
      satellites,
      groundSites,
      edges,
      nodePositions,
      satelliteAltitudeFraction,
      routeNodeIds,
      routeText,
    };
  }, [
    scenario,
    networkPacket,
    stepIndex,
    selection,
    focusClientId,
    routeIndex,
    currentTS,
  ]);
}
