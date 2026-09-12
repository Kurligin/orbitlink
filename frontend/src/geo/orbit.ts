/**
 * Форма кольца орбиты плоскости в системе, связанной с Землёй, на момент
 * времени `tS` — только для отрисовки дуг орбит на глобусе/2D-проекции.
 * Формулы намеренно зеркалят backend/orbitlink/core/geometry.py
 * (`ConstellationModel.positions`), чтобы кольцо совпадало с реальными
 * положениями аппаратов пакета сети; независимый запрос к бэкенду не нужен.
 */

import { cartesianToLatLon, type LatLon } from "./projection";

export const EARTH_RADIUS_KM = 6371.0;
const EARTH_MU = 398600.435507;
const EARTH_ROTATION_PERIOD_S = 86164.09054;
const EARTH_ANGULAR_RATE = (2 * Math.PI) / EARTH_ROTATION_PERIOD_S;

export interface OrbitRingEnvironment {
  altitude_km: number;
  inclination_deg: number;
  earth_angle0_deg: number;
}

export interface OrbitRingPlane {
  raan_deg: number;
}

const toRad = (deg: number) => (deg * Math.PI) / 180;

/** Радиус орбиты (км от центра Земли) для заданной высоты. */
export function orbitRadiusKm(altitudeKm: number): number {
  return EARTH_RADIUS_KM + altitudeKm;
}

/** Средняя угловая скорость обращения (рад/с) — для справки/будущих расчётов. */
export function meanMotion(altitudeKm: number): number {
  return Math.sqrt(EARTH_MU / orbitRadiusKm(altitudeKm) ** 3);
}

/**
 * Сэмплирует полное кольцо орбиты плоскости на момент `tS`: широта/долгота
 * `samples + 1` точек (последняя точка совпадает с первой — кольцо замкнуто).
 */
export function computeOrbitRing(
  environment: OrbitRingEnvironment,
  plane: OrbitRingPlane,
  tS: number,
  samples = 96,
): LatLon[] {
  const radius = orbitRadiusKm(environment.altitude_km);
  const inclination = toRad(environment.inclination_deg);
  const raan = toRad(plane.raan_deg);
  const theta = toRad(environment.earth_angle0_deg) + EARTH_ANGULAR_RATE * tS;

  const cosRaan = Math.cos(raan);
  const sinRaan = Math.sin(raan);
  const cosInc = Math.cos(inclination);
  const sinInc = Math.sin(inclination);
  const cosT = Math.cos(theta);
  const sinT = Math.sin(theta);

  const points: LatLon[] = [];
  for (let k = 0; k <= samples; k += 1) {
    const u = (2 * Math.PI * k) / samples;
    const cosU = Math.cos(u);
    const sinU = Math.sin(u);

    const ix = radius * (cosRaan * cosU - sinRaan * sinU * cosInc);
    const iy = radius * (sinRaan * cosU + cosRaan * sinU * cosInc);
    const iz = radius * (sinU * sinInc);

    // Поворот вокруг оси Z на угол вращения Земли theta (та же матрица, что в
    // ConstellationModel.positions: fixed = inertial @ R(theta)).
    const fx = ix * cosT + iy * sinT;
    const fy = -ix * sinT + iy * cosT;
    const fz = iz;

    points.push(cartesianToLatLon(fx, fy, fz));
  }
  return points;
}
