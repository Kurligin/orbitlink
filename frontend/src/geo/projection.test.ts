import { describe, expect, it } from "vitest";
import {
  cartesianToLatLon,
  latLonToCartesian,
  latLonToPolarCanvas,
  polarCanvasToLatLon,
  type PolarProjectionOptions,
} from "./projection";

describe("cartesianToLatLon <-> latLonToCartesian", () => {
  const cases: Array<[number, number, number]> = [
    [45, 30, 6371],
    [-10, 170, 6921],
    [0, 0, 6371],
    [89, -60, 6371],
    [-45, -120, 7000],
  ];

  it.each(cases)(
    "восстанавливает исходные широту/долготу (lat=%s, lon=%s, r=%s)",
    (lat, lon, r) => {
      const [x, y, z] = latLonToCartesian(lat, lon, r);
      const back = cartesianToLatLon(x, y, z);
      expect(back.latDeg).toBeCloseTo(lat, 6);
      expect(back.lonDeg).toBeCloseTo(lon, 6);
    },
  );

  it("не зависит от радиуса (подспутниковая точка на высоте орбиты)", () => {
    const surface = latLonToCartesian(55, 37, 6371);
    const orbit = latLonToCartesian(55, 37, 6371 + 550);
    expect(cartesianToLatLon(...surface)).toEqual(cartesianToLatLon(...orbit));
  });
});

describe("полярная стереографическая проекция", () => {
  const opts: PolarProjectionOptions = {
    centerX: 200,
    centerY: 200,
    canvasRadius: 180,
  };

  it("полюс попадает в центр холста", () => {
    const point = latLonToPolarCanvas(90, 123, opts);
    expect(point.x).toBeCloseTo(opts.centerX, 6);
    expect(point.y).toBeCloseTo(opts.centerY, 6);
  });

  it("южная граница (по умолчанию 40° с.ш.) попадает точно на край холста", () => {
    for (const lon of [0, 45, 90, 135, 180, -90]) {
      const point = latLonToPolarCanvas(40, lon, opts);
      const dx = point.x - opts.centerX;
      const dy = point.y - opts.centerY;
      const r = Math.sqrt(dx * dx + dy * dy);
      expect(r).toBeCloseTo(opts.canvasRadius, 6);
    }
  });

  it("настраиваемая южная граница тоже ложится на край", () => {
    const custom: PolarProjectionOptions = { ...opts, southernBoundaryDeg: 20 };
    const point = latLonToPolarCanvas(20, 77, custom);
    const dx = point.x - custom.centerX;
    const dy = point.y - custom.centerY;
    expect(Math.sqrt(dx * dx + dy * dy)).toBeCloseTo(custom.canvasRadius, 6);
  });

  it.each([
    [70, 45],
    [50, -120],
    [41, 170],
    [85, -5],
  ])(
    "прямое и обратное преобразование возвращают исходное (lat=%s, lon=%s)",
    (lat, lon) => {
      const point = latLonToPolarCanvas(lat, lon, opts);
      const back = polarCanvasToLatLon(point, opts);
      expect(back.latDeg).toBeCloseTo(lat, 6);
      expect(back.lonDeg).toBeCloseTo(lon, 6);
    },
  );

  it("Мурманск (68.97° с.ш., 33.07° в.д.) попадает в сектор к северо-востоку от центра, внутри границы", () => {
    const point = latLonToPolarCanvas(68.97, 33.07, opts);
    const dx = point.x - opts.centerX;
    const dy = point.y - opts.centerY;
    const r = Math.sqrt(dx * dx + dy * dy);

    // долгота 0° указывает вверх, восток — вправо: Мурманск чуть восточнее
    // Гринвича должен лечь выше и правее центра холста.
    expect(dx).toBeGreaterThan(0);
    expect(dy).toBeLessThan(0);
    // 68.97° с.ш. заметно севернее границы 40°, поэтому точка внутри холста.
    expect(r).toBeLessThan(opts.canvasRadius);
  });
});
