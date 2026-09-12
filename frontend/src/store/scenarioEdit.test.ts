import { describe, expect, it } from "vitest";
import type { Scenario } from "../api/types";
import {
  deriveVariantTitle,
  failureFromHours,
  generateUploadScenarioId,
  generateVariantScenarioId,
  isDraftEqual,
  normalizeAngleDeg,
  withEnvironment,
  withFailureAdded,
  withFailureRemoved,
  withLaunchStage,
  withPlane,
} from "./scenarioEdit";

function makeScenario(): Scenario {
  return {
    schema_version: "cosmo-A-1.0",
    meta: { id: "full", title: "Полная группировка" },
    environment: {
      altitude_km: 550,
      inclination_deg: 53,
      earth_angle0_deg: 0,
      horizon_s: 86400,
      step_s: 60,
      min_elevation_deg: 10,
      isl_range_km: 5000,
      target_availability: 0.95,
    },
    design: {
      launch_stage: 3,
      planes: [
        { id: "P1", raan_deg: 10, phase_deg: 0 },
        { id: "P2", raan_deg: 130, phase_deg: 20 },
      ],
      satellites: [
        { id: "SA-1", plane_id: "P1", slot_deg: 0, launch_batch: 1 },
      ],
    },
    ground_sites: [],
    failures: [],
    gateway_outages: [],
  };
}

describe("normalizeAngleDeg", () => {
  it("оставляет угол внутри [0, 360) без изменений", () => {
    expect(normalizeAngleDeg(0)).toBe(0);
    expect(normalizeAngleDeg(45.5)).toBe(45.5);
    expect(normalizeAngleDeg(359.9)).toBeCloseTo(359.9);
  });

  it("сворачивает угол >= 360 и отрицательный угол в диапазон", () => {
    expect(normalizeAngleDeg(360)).toBe(0);
    expect(normalizeAngleDeg(400)).toBe(40);
    expect(normalizeAngleDeg(720 + 15)).toBe(15);
    expect(normalizeAngleDeg(-10)).toBe(350);
    expect(normalizeAngleDeg(-370)).toBe(350);
  });

  it("не конечные значения приводит к 0", () => {
    expect(normalizeAngleDeg(NaN)).toBe(0);
    expect(normalizeAngleDeg(Infinity)).toBe(0);
    expect(normalizeAngleDeg(-Infinity)).toBe(0);
  });
});

describe("применение правки к черновику", () => {
  it("withLaunchStage меняет только очередь запуска, остальное не трогает", () => {
    const scenario = makeScenario();
    const next = withLaunchStage(scenario, 1);
    expect(next.design.launch_stage).toBe(1);
    expect(next.design.planes).toBe(scenario.design.planes); // структурное разделение
    expect(scenario.design.launch_stage).toBe(3); // исходный сценарий не мутирован
  });

  it("withEnvironment точечно обновляет поля окружения", () => {
    const scenario = makeScenario();
    const next = withEnvironment(scenario, {
      altitude_km: 600,
      target_availability: 0.9,
    });
    expect(next.environment.altitude_km).toBe(600);
    expect(next.environment.target_availability).toBe(0.9);
    expect(next.environment.inclination_deg).toBe(
      scenario.environment.inclination_deg,
    );
    expect(scenario.environment.altitude_km).toBe(550);
  });

  it("withPlane обновляет RAAN и фазирование выбранной плоскости и приводит угол к диапазону", () => {
    const scenario = makeScenario();
    const next = withPlane(scenario, "P2", { raan_deg: 400, phase_deg: -10 });
    const plane = next.design.planes.find((p) => p.id === "P2")!;
    expect(plane.raan_deg).toBe(40);
    expect(plane.phase_deg).toBe(350);
    // другая плоскость не задета
    expect(next.design.planes.find((p) => p.id === "P1")).toEqual(
      scenario.design.planes[0],
    );
  });

  it("withFailureAdded/withFailureRemoved добавляют и удаляют период недоступности", () => {
    const scenario = makeScenario();
    const withFailure = withFailureAdded(scenario, {
      satellite_id: "SA-1",
      start_s: 3600,
      end_s: 7200,
    });
    expect(withFailure.failures).toHaveLength(1);
    expect(scenario.failures).toHaveLength(0);

    const withTwo = withFailureAdded(withFailure, {
      satellite_id: "SA-1",
      start_s: 10000,
      end_s: 20000,
    });
    const removedFirst = withFailureRemoved(withTwo, 0);
    expect(removedFirst.failures).toHaveLength(1);
    expect(removedFirst.failures[0]!.start_s).toBe(10000);
  });
});

describe("failureFromHours — перевод часов отказа в секунды с проверкой границ", () => {
  const horizonS = 86400; // 24 часа

  it("корректный период переводится в секунды", () => {
    const result = failureFromHours(
      { satelliteId: "SA-1", startHours: 1, endHours: 2.5 },
      horizonS,
    );
    expect(result).toEqual({
      ok: true,
      failure: { satellite_id: "SA-1", start_s: 3600, end_s: 9000 },
    });
  });

  it("отклоняет без выбранного аппарата", () => {
    const result = failureFromHours(
      { satelliteId: "", startHours: 1, endHours: 2 },
      horizonS,
    );
    expect(result.ok).toBe(false);
  });

  it("отклоняет нечисловые значения", () => {
    const result = failureFromHours(
      { satelliteId: "SA-1", startHours: NaN, endHours: 2 },
      horizonS,
    );
    expect(result.ok).toBe(false);
  });

  it("отклоняет, когда начало не раньше конца", () => {
    const equal = failureFromHours(
      { satelliteId: "SA-1", startHours: 5, endHours: 5 },
      horizonS,
    );
    expect(equal.ok).toBe(false);
    const reversed = failureFromHours(
      { satelliteId: "SA-1", startHours: 6, endHours: 5 },
      horizonS,
    );
    expect(reversed.ok).toBe(false);
  });

  it("отклоняет период за пределами горизонта расчёта", () => {
    const before = failureFromHours(
      { satelliteId: "SA-1", startHours: -1, endHours: 2 },
      horizonS,
    );
    expect(before.ok).toBe(false);
    const after = failureFromHours(
      { satelliteId: "SA-1", startHours: 20, endHours: 25 },
      horizonS,
    );
    expect(after.ok).toBe(false);
  });

  it("принимает период, ровно совпадающий с границами горизонта", () => {
    const result = failureFromHours(
      { satelliteId: "SA-1", startHours: 0, endHours: 24 },
      horizonS,
    );
    expect(result).toEqual({
      ok: true,
      failure: { satellite_id: "SA-1", start_s: 0, end_s: 86400 },
    });
  });
});

describe("генерация уникального meta.id", () => {
  it("generateVariantScenarioId начинает с __v2 и находит следующий свободный номер", () => {
    expect(generateVariantScenarioId("full", [])).toBe("full__v2");
    expect(generateVariantScenarioId("full", ["full", "full__v2"])).toBe(
      "full__v3",
    );
    expect(
      generateVariantScenarioId("full", ["full", "full__v2", "full__v3"]),
    ).toBe("full__v4");
  });

  it("generateVariantScenarioId снимает уже существующий суффикс __vN у базового id", () => {
    expect(generateVariantScenarioId("full__v2", ["full", "full__v2"])).toBe(
      "full__v3",
    );
  });

  it("generateUploadScenarioId начинает с upload__1 и находит следующий свободный номер", () => {
    expect(generateUploadScenarioId([])).toBe("upload__1");
    expect(generateUploadScenarioId(["upload__1"])).toBe("upload__2");
    expect(generateUploadScenarioId(["upload__1", "upload__2"])).toBe(
      "upload__3",
    );
  });

  it("deriveVariantTitle формирует «<заголовок> · вариант N» и не задваивает суффикс", () => {
    expect(deriveVariantTitle("Полная группировка", "full__v2")).toBe(
      "Полная группировка · вариант 2",
    );
    expect(
      deriveVariantTitle("Полная группировка · вариант 2", "full__v3"),
    ).toBe("Полная группировка · вариант 3");
  });
});

describe("isDraftEqual", () => {
  it("одинаковые по значению сценарии равны, даже если это разные объекты", () => {
    const a = makeScenario();
    const b = makeScenario();
    expect(isDraftEqual(a, b)).toBe(true);
  });

  it("замечает изменение поля окружения, плоскости и списка отказов", () => {
    const base = makeScenario();
    expect(
      isDraftEqual(base, withEnvironment(base, { altitude_km: 551 })),
    ).toBe(false);
    expect(isDraftEqual(base, withPlane(base, "P1", { raan_deg: 11 }))).toBe(
      false,
    );
    expect(
      isDraftEqual(
        base,
        withFailureAdded(base, {
          satellite_id: "SA-1",
          start_s: 0,
          end_s: 100,
        }),
      ),
    ).toBe(false);
  });
});
