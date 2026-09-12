/**
 * Геометрия для экрана «Сеть»: чистые функции без React.
 *
 * Система координат аппаратов и наземных пунктов связана с Землёй (см.
 * backend/orbitlink/core/geometry.py: `x = R·cos(lat)·cos(lon)`,
 * `y = R·cos(lat)·sin(lon)`, `z = R·sin(lat)`), поэтому перевод в широту и
 * долготу не зависит от радиуса — работает как для земной поверхности, так
 * и для орбитальной высоты (широта/долгота подспутниковой точки).
 */

export interface LatLon {
  latDeg: number;
  lonDeg: number;
}

/** Декартовы координаты (км, СК связана с Землёй) -> широта/долгота (град). */
export function cartesianToLatLon(x: number, y: number, z: number): LatLon {
  const radius = Math.sqrt(x * x + y * y + z * z);
  if (radius === 0) {
    return { latDeg: 0, lonDeg: 0 };
  }
  const latDeg =
    (Math.asin(Math.max(-1, Math.min(1, z / radius))) * 180) / Math.PI;
  const lonDeg = (Math.atan2(y, x) * 180) / Math.PI;
  return { latDeg, lonDeg };
}

/** Обратное преобразование: широта/долгота (град) + радиус (км) -> декартовы координаты. */
export function latLonToCartesian(
  latDeg: number,
  lonDeg: number,
  radiusKm: number,
): [number, number, number] {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  return [
    radiusKm * Math.cos(lat) * Math.cos(lon),
    radiusKm * Math.cos(lat) * Math.sin(lon),
    radiusKm * Math.sin(lat),
  ];
}

export interface PolarProjectionOptions {
  /** Центр проекции на холсте, px. */
  centerX: number;
  centerY: number;
  /** Радиус холста, px — этому радиусу соответствует `southernBoundaryDeg`. */
  canvasRadius: number;
  /**
   * Южная граница проекции, ° с.ш. — параллель, которая ложится точно на
   * край холста. По умолчанию 40° с.ш. (вид с северного полюса).
   */
  southernBoundaryDeg?: number;
}

export interface CanvasPoint {
  x: number;
  y: number;
}

const DEFAULT_SOUTHERN_BOUNDARY_DEG = 40;

/** Во сколько раз растягивать безразмерный стереографический радиус до пикселей холста. */
function stereographicScale(
  southernBoundaryDeg: number,
  canvasRadius: number,
): number {
  const boundaryColatitudeRad = ((90 - southernBoundaryDeg) * Math.PI) / 180;
  const boundaryRho = 2 * Math.tan(boundaryColatitudeRad / 2);
  return canvasRadius / boundaryRho;
}

/**
 * Полярная стереографическая проекция, вид с северного полюса: полюс —
 * центр холста, параллель `southernBoundaryDeg` — край холста. Долгота 0°
 * направлена вверх (на экране), возрастает по часовой стрелке (восток — вправо).
 */
export function latLonToPolarCanvas(
  latDeg: number,
  lonDeg: number,
  options: PolarProjectionOptions,
): CanvasPoint {
  const { centerX, centerY, canvasRadius } = options;
  const southernBoundaryDeg =
    options.southernBoundaryDeg ?? DEFAULT_SOUTHERN_BOUNDARY_DEG;
  const scale = stereographicScale(southernBoundaryDeg, canvasRadius);

  const colatitudeRad = ((90 - latDeg) * Math.PI) / 180;
  const rho = 2 * Math.tan(colatitudeRad / 2);
  const pixelR = rho * scale;

  const lonRad = (lonDeg * Math.PI) / 180;
  return {
    x: centerX + pixelR * Math.sin(lonRad),
    y: centerY - pixelR * Math.cos(lonRad),
  };
}

/** Обратное преобразование к {@link latLonToPolarCanvas}. */
export function polarCanvasToLatLon(
  point: CanvasPoint,
  options: PolarProjectionOptions,
): LatLon {
  const { centerX, centerY, canvasRadius } = options;
  const southernBoundaryDeg =
    options.southernBoundaryDeg ?? DEFAULT_SOUTHERN_BOUNDARY_DEG;
  const scale = stereographicScale(southernBoundaryDeg, canvasRadius);

  const dx = point.x - centerX;
  const dy = point.y - centerY;
  const pixelR = Math.sqrt(dx * dx + dy * dy);

  const rho = pixelR / scale;
  const colatitudeRad = 2 * Math.atan(rho / 2);
  const latDeg = 90 - (colatitudeRad * 180) / Math.PI;

  const lonRad = Math.atan2(dx, -dy);
  const lonDeg = (lonRad * 180) / Math.PI;

  return { latDeg, lonDeg };
}
