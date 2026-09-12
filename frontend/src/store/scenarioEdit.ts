/**
 * Чистые функции редактирования сценария — вынесены отдельно от React-кода
 * (PropertiesPanel, workspace-провайдер), чтобы их можно было проверить
 * модульными тестами без рендера компонентов и без бэкенда.
 *
 * Все правки возвращают НОВЫЙ объект сценария (иммутабельно, со структурным
 * разделением неизменных веток) — это и держит компонент простым (просто
 * `setDraft(withX(draft, ...))`), и делает состояние «черновик отличается от
 * текущего сценария» дешёвым для сравнения через `isDraftEqual`.
 */
import type { Scenario, SatelliteFailure } from "../api/types";

/** Приводит угол в градусах к диапазону [0, 360). NaN/±Infinity -> 0. */
export function normalizeAngleDeg(angle: number): number {
  if (!Number.isFinite(angle)) return 0;
  const mod = angle % 360;
  return mod < 0 ? mod + 360 : mod;
}

/** Очередь запуска (design.launch_stage). */
export function withLaunchStage(scenario: Scenario, stage: number): Scenario {
  return { ...scenario, design: { ...scenario.design, launch_stage: stage } };
}

/** Точечная правка полей окружения (высота, наклонение, мин. возвышение, ISL, целевая доступность). */
export function withEnvironment(
  scenario: Scenario,
  patch: Partial<Scenario["environment"]>,
): Scenario {
  return { ...scenario, environment: { ...scenario.environment, ...patch } };
}

/** RAAN и/или фазирование одной плоскости — угол приводится к [0, 360). */
export function withPlane(
  scenario: Scenario,
  planeId: string,
  patch: { raan_deg?: number; phase_deg?: number },
): Scenario {
  return {
    ...scenario,
    design: {
      ...scenario.design,
      planes: scenario.design.planes.map((plane) => {
        if (plane.id !== planeId) return plane;
        return {
          ...plane,
          raan_deg:
            patch.raan_deg !== undefined
              ? normalizeAngleDeg(patch.raan_deg)
              : plane.raan_deg,
          phase_deg:
            patch.phase_deg !== undefined
              ? normalizeAngleDeg(patch.phase_deg)
              : plane.phase_deg,
        };
      }),
    },
  };
}

export function withFailureAdded(
  scenario: Scenario,
  failure: SatelliteFailure,
): Scenario {
  return { ...scenario, failures: [...scenario.failures, failure] };
}

export function withFailureRemoved(
  scenario: Scenario,
  index: number,
): Scenario {
  return {
    ...scenario,
    failures: scenario.failures.filter((_, i) => i !== index),
  };
}

export interface FailureHoursInput {
  satelliteId: string;
  startHours: number;
  endHours: number;
}

export type FailureConversionResult =
  { ok: true; failure: SatelliteFailure } | { ok: false; error: string };

/**
 * Часы от начала расчёта -> секунды, с проверкой границ: аппарат выбран, оба
 * значения конечны, начало строго меньше конца, оба внутри горизонта расчёта.
 */
export function failureFromHours(
  input: FailureHoursInput,
  horizonS: number,
): FailureConversionResult {
  const { satelliteId, startHours, endHours } = input;
  if (!satelliteId) {
    return { ok: false, error: "Не выбран аппарат" };
  }
  if (!Number.isFinite(startHours) || !Number.isFinite(endHours)) {
    return { ok: false, error: "Начало и конец периода должны быть числами" };
  }
  const startS = startHours * 3600;
  const endS = endHours * 3600;
  if (startS >= endS) {
    return { ok: false, error: "Начало периода должно быть раньше конца" };
  }
  if (startS < 0 || endS > horizonS) {
    return {
      ok: false,
      error: `Период должен быть внутри горизонта расчёта (0–${(horizonS / 3600).toFixed(1)} ч)`,
    };
  }
  return {
    ok: true,
    failure: { satellite_id: satelliteId, start_s: startS, end_s: endS },
  };
}

/**
 * Уникальный id для варианта, произведённого правкой существующего сценария:
 * `<корень>__v2`, `__v3`, ... Если сам baseId уже несёт суффикс `__vN` (правка
 * уже отредактированного варианта), суффикс сначала снимается — иначе id рос
 * бы цепочкой `__v2__v2__v3`.
 */
export function generateVariantScenarioId(
  baseId: string,
  existingIds: Iterable<string>,
): string {
  const existing = new Set(existingIds);
  const root = baseId.replace(/__v\d+$/, "");
  let n = 2;
  let candidate = `${root}__v${n}`;
  while (existing.has(candidate)) {
    n += 1;
    candidate = `${root}__v${n}`;
  }
  return candidate;
}

/** Уникальный id для сценария, загруженного из файла: `upload__1`, `upload__2`, ... */
export function generateUploadScenarioId(
  existingIds: Iterable<string>,
): string {
  const existing = new Set(existingIds);
  let n = 1;
  let candidate = `upload__${n}`;
  while (existing.has(candidate)) {
    n += 1;
    candidate = `upload__${n}`;
  }
  return candidate;
}

/** Заголовок нового варианта по заголовку исходного: снимает « · вариант N», если он уже был. */
export function deriveVariantTitle(baseTitle: string, newId: string): string {
  const cleanTitle = baseTitle.replace(/ · вариант \d+$/, "");
  const match = newId.match(/__v(\d+)$/);
  const n = match ? match[1] : "2";
  return `${cleanTitle} · вариант ${n}`;
}

/**
 * Дешёвая проверка «черновик отличается от текущего сценария» — только по
 * полям, которые реально редактируются в панели параметров (остальные поля
 * сценария в этом экране не меняются, сравнивать их незачем).
 */
export function isDraftEqual(a: Scenario, b: Scenario): boolean {
  if (a === b) return true;
  const envKeys: Array<keyof Scenario["environment"]> = [
    "altitude_km",
    "inclination_deg",
    "min_elevation_deg",
    "isl_range_km",
    "target_availability",
  ];
  for (const key of envKeys) {
    if (a.environment[key] !== b.environment[key]) return false;
  }
  if (a.design.launch_stage !== b.design.launch_stage) return false;
  if (a.design.planes.length !== b.design.planes.length) return false;
  for (let i = 0; i < a.design.planes.length; i++) {
    const pa = a.design.planes[i]!;
    const pb = b.design.planes[i]!;
    if (
      pa.id !== pb.id ||
      pa.raan_deg !== pb.raan_deg ||
      pa.phase_deg !== pb.phase_deg
    )
      return false;
  }
  if (a.failures.length !== b.failures.length) return false;
  for (let i = 0; i < a.failures.length; i++) {
    const fa = a.failures[i]!;
    const fb = b.failures[i]!;
    if (
      fa.satellite_id !== fb.satellite_id ||
      fa.start_s !== fb.start_s ||
      fa.end_s !== fb.end_s
    )
      return false;
  }
  return true;
}
