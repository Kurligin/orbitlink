import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { ChevronDownIcon, PropertiesIcon } from "../icons";
import { formatClock } from "../../lib/format";
import { useWorkspace } from "../../store/workspace";
import { api, ApiError } from "../../api/client";
import type {
  RoutingStrategy,
  Scenario,
  ValidationIssue,
} from "../../api/types";
import {
  deriveVariantTitle,
  failureFromHours,
  generateVariantScenarioId,
  isDraftEqual,
  withEnvironment,
  withFailureAdded,
  withFailureRemoved,
  withLaunchStage,
  withPlane,
} from "../../store/scenarioEdit";

const STRATEGY_LABELS: Record<RoutingStrategy, string> = {
  min_hops: "мин. переходов",
  min_latency: "задержка",
  load_aware: "учёт нагрузки",
  robust: "запас по дальности",
};

function formatRu(value: number, maxDigits = 3): string {
  return value.toLocaleString("ru-RU", { maximumFractionDigits: maxDigits });
}

function Field({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="f">
      <label>{label}</label>
      <div className="v mono">
        {value}
        {unit ? <u>{unit}</u> : null}
      </div>
    </div>
  );
}

/** Числовое поле в том же визуальном стиле ячейки, что и Field, только редактируемое. */
function NumberField({
  label,
  value,
  unit,
  onChange,
  step,
}: {
  label: string;
  value: number;
  unit?: string;
  onChange: (next: number) => void;
  step?: number;
}) {
  const [text, setText] = useState(() => String(value));
  const id = useId();

  // Синхронизация с внешним значением: после сброса черновика или смены
  // сценария поле должно показать актуальное число, а не то, что успел
  // напечатать пользователь.
  useEffect(() => {
    setText(String(value));
  }, [value]);

  return (
    <div className="f">
      <label htmlFor={id}>{label}</label>
      <div className="v">
        <input
          id={id}
          className="mono"
          type="number"
          inputMode="decimal"
          step={step ?? "any"}
          value={text}
          onChange={(event) => {
            const raw = event.target.value;
            setText(raw);
            const n = Number(raw);
            if (raw.trim() !== "" && Number.isFinite(n)) {
              onChange(n);
            }
          }}
          style={{
            flex: 1,
            minWidth: 0,
            border: 0,
            background: "transparent",
            color: "var(--fg)",
            font: "inherit",
            padding: 0,
          }}
        />
        {unit ? <u>{unit}</u> : null}
      </div>
    </div>
  );
}

const inputStyle: CSSProperties = {
  height: 26,
  border: "1px solid var(--line)",
  borderRadius: 4,
  background: "#15171c",
  color: "var(--fg)",
  font: "400 12px var(--font-mono)",
  padding: "0 7px",
  width: "100%",
};

export function PropertiesPanel() {
  const {
    scenario,
    selection,
    strategy,
    setStrategy,
    presets,
    addUserScenario,
  } = useWorkspace();

  const [draft, setDraft] = useState<Scenario | null>(scenario);
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const [failSatelliteId, setFailSatelliteId] = useState<string>("");
  const [failStartH, setFailStartH] = useState<string>("0");
  const [failEndH, setFailEndH] = useState<string>("1");
  const [failError, setFailError] = useState<string | null>(null);

  // Смена сценария (в т.ч. после успешного применения правки, когда новый
  // сценарий сам становится текущим) — черновик снова совпадает с текущим.
  useEffect(() => {
    setDraft(scenario);
    setIssues(null);
    setApplyError(null);
  }, [scenario]);

  // Спутник, выбранный в дереве или на глобусе/полярной проекции — подставляем
  // его в форму отказа по умолчанию (сценарий «выбрать спутник маршрута»).
  useEffect(() => {
    if (!draft) return;
    const ids = draft.design.satellites.map((s) => s.id);
    if (
      selection?.kind === "satellite" &&
      ids.includes(selection.satelliteId)
    ) {
      setFailSatelliteId(selection.satelliteId);
    } else if (!ids.includes(failSatelliteId)) {
      setFailSatelliteId(ids[0] ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, selection]);

  const selectionSummary = useMemo(() => {
    if (!scenario || !selection) return null;
    if (selection.kind === "satellite") {
      const sat = scenario.design.satellites.find(
        (s) => s.id === selection.satelliteId,
      );
      if (!sat) return null;
      const plane = scenario.design.planes.find((p) => p.id === sat.plane_id);
      return `${sat.id} · ${sat.plane_id} · слот ${formatRu(sat.slot_deg, 1)}° · RAAN ${
        plane ? formatRu(plane.raan_deg, 1) : "—"
      }°`;
    }
    const plane = scenario.design.planes.find(
      (p) => p.id === selection.planeId,
    );
    return plane
      ? `${plane.id} · RAAN ${formatRu(plane.raan_deg, 1)}° · фаза ${formatRu(plane.phase_deg, 1)}°`
      : null;
  }, [scenario, selection]);

  if (!scenario || !draft) {
    return (
      <section className="sec" style={{ flex: 1 }}>
        <h2>
          <PropertiesIcon />
          Параметры расчёта
        </h2>
        <div className="props-empty">Загрузка сценария…</div>
      </section>
    );
  }

  const { design, failures } = draft;
  const maxBatch = design.satellites.reduce(
    (max, s) => Math.max(max, s.launch_batch),
    design.launch_stage,
  );
  const stageOptions = Array.from(
    { length: Math.max(maxBatch, design.launch_stage, 1) },
    (_, i) => i + 1,
  );

  const dirty = !isDraftEqual(draft, scenario);

  const handleAddFailure = () => {
    setFailError(null);
    const result = failureFromHours(
      {
        satelliteId: failSatelliteId,
        startHours: Number(failStartH),
        endHours: Number(failEndH),
      },
      draft.environment.horizon_s,
    );
    if (!result.ok) {
      setFailError(result.error);
      return;
    }
    setDraft(withFailureAdded(draft, result.failure));
  };

  const handleReset = () => {
    setDraft(scenario);
    setIssues(null);
    setApplyError(null);
  };

  const handleApply = async () => {
    setApplying(true);
    setApplyError(null);
    setIssues(null);
    try {
      const report = await api.validateScenario(draft);
      if (!report.ok) {
        setIssues(report.issues);
        return;
      }
      const existingIds = presets?.map((p) => p.id) ?? [];
      const newId = generateVariantScenarioId(scenario.meta.id, existingIds);
      const newTitle = deriveVariantTitle(scenario.meta.title, newId);
      const newScenario: Scenario = {
        ...draft,
        meta: { id: newId, title: newTitle },
      };
      addUserScenario(newScenario, scenario.meta.id);
    } catch (error) {
      setApplyError(
        error instanceof ApiError
          ? `${error.message} (код ${error.status})`
          : error instanceof Error
            ? error.message
            : "Не удалось проверить сценарий",
      );
    } finally {
      setApplying(false);
    }
  };

  return (
    <section className="sec" style={{ flex: 1 }}>
      <h2>
        <PropertiesIcon />
        Параметры расчёта
      </h2>
      <div className="props">
        {selectionSummary ? (
          <div
            className="props-empty"
            style={{ padding: "4px 0 10px", color: "var(--fg)" }}
          >
            {selectionSummary}
          </div>
        ) : null}

        <div className="grp">
          <h3>
            <ChevronDownIcon />
            Орбита
          </h3>
          <NumberField
            label="Высота"
            unit="км"
            value={draft.environment.altitude_km}
            onChange={(n) =>
              setDraft(withEnvironment(draft, { altitude_km: n }))
            }
          />
          <NumberField
            label="Наклонение"
            unit="°"
            value={draft.environment.inclination_deg}
            onChange={(n) =>
              setDraft(withEnvironment(draft, { inclination_deg: n }))
            }
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              height: 30,
            }}
          >
            <label style={{ fontSize: 12, color: "var(--fg-2)" }}>
              Очередь запуска
            </label>
            <div className="seg" role="group" aria-label="Очередь запуска">
              {stageOptions.map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-pressed={design.launch_stage === n}
                  onClick={() => setDraft(withLaunchStage(draft, n))}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="grp">
          <h3>
            <ChevronDownIcon />
            Связь
          </h3>
          <NumberField
            label="Мин. возвышение"
            unit="°"
            value={draft.environment.min_elevation_deg}
            onChange={(n) =>
              setDraft(withEnvironment(draft, { min_elevation_deg: n }))
            }
          />
          <NumberField
            label="Дальность ISL"
            unit="км"
            value={draft.environment.isl_range_km}
            onChange={(n) =>
              setDraft(withEnvironment(draft, { isl_range_km: n }))
            }
          />
          <div className="f">
            <label htmlFor="strategy-select">Стратегия</label>
            <div className="v">
              <select
                id="strategy-select"
                value={strategy}
                onChange={(event) =>
                  setStrategy(event.target.value as RoutingStrategy)
                }
                style={{
                  background: "transparent",
                  border: 0,
                  color: "var(--fg)",
                  font: "400 12px var(--font-mono)",
                  width: "100%",
                }}
              >
                {(Object.keys(STRATEGY_LABELS) as RoutingStrategy[]).map(
                  (key) => (
                    <option key={key} value={key}>
                      {STRATEGY_LABELS[key]}
                    </option>
                  ),
                )}
              </select>
            </div>
          </div>
        </div>

        <div className="grp">
          <h3>
            <ChevronDownIcon />
            Расчёт
          </h3>
          <Field
            label="Горизонт"
            value={String(draft.environment.horizon_s)}
            unit="с"
          />
          <Field
            label="Шаг"
            value={String(draft.environment.step_s)}
            unit="с"
          />
          <NumberField
            label="Целевая доступность"
            value={draft.environment.target_availability}
            step={0.01}
            onChange={(n) =>
              setDraft(withEnvironment(draft, { target_availability: n }))
            }
          />
        </div>

        <div className="grp">
          <h3>
            <ChevronDownIcon />
            Плоскости
          </h3>
          {design.planes.map((plane) => (
            <div key={plane.id} style={{ marginBottom: 6 }}>
              <div
                style={{ fontSize: 11, color: "var(--fg-2)", padding: "2px 0" }}
              >
                {plane.id}
              </div>
              <NumberField
                label="RAAN"
                unit="°"
                value={plane.raan_deg}
                onChange={(n) =>
                  setDraft(withPlane(draft, plane.id, { raan_deg: n }))
                }
              />
              <NumberField
                label="Фазирование"
                unit="°"
                value={plane.phase_deg}
                onChange={(n) =>
                  setDraft(withPlane(draft, plane.id, { phase_deg: n }))
                }
              />
            </div>
          ))}
        </div>

        <div className="grp">
          <h3>
            <ChevronDownIcon />
            Отказы
          </h3>
          {failures.length === 0 ? (
            <div className="props-empty" style={{ padding: "2px 0" }}>
              Нет отказов в сценарии
            </div>
          ) : (
            failures.map((failure, index) => (
              <div
                key={`${failure.satellite_id}-${failure.start_s}-${index}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "3px 0",
                }}
              >
                <div
                  className="mono"
                  style={{ flex: 1, fontSize: 11, color: "var(--fg-2)" }}
                >
                  {failure.satellite_id} · {formatClock(failure.start_s)}–
                  {formatClock(failure.end_s)}
                </div>
                <button
                  type="button"
                  className="btn"
                  style={{ padding: "1px 8px" }}
                  aria-label={`Удалить отказ ${failure.satellite_id}`}
                  onClick={() => setDraft(withFailureRemoved(draft, index))}
                >
                  ×
                </button>
              </div>
            ))
          )}

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 5,
              marginTop: 8,
            }}
          >
            <label style={{ fontSize: 12, color: "var(--fg-2)" }}>
              Добавить отказ
            </label>
            <select
              aria-label="Аппарат для отказа"
              value={failSatelliteId}
              onChange={(event) => setFailSatelliteId(event.target.value)}
              style={inputStyle}
            >
              {design.satellites.map((sat) => (
                <option key={sat.id} value={sat.id}>
                  {sat.id}
                </option>
              ))}
            </select>
            <div style={{ display: "flex", gap: 5 }}>
              <input
                aria-label="Начало периода, ч"
                type="number"
                step="any"
                value={failStartH}
                onChange={(event) => setFailStartH(event.target.value)}
                placeholder="начало, ч"
                style={inputStyle}
              />
              <input
                aria-label="Конец периода, ч"
                type="number"
                step="any"
                value={failEndH}
                onChange={(event) => setFailEndH(event.target.value)}
                placeholder="конец, ч"
                style={inputStyle}
              />
              <button
                type="button"
                className="btn"
                style={{ flex: "none" }}
                onClick={handleAddFailure}
              >
                +
              </button>
            </div>
            {failError ? (
              <div style={{ color: "var(--bad)", fontSize: 11 }}>
                Ошибка: {failError}
              </div>
            ) : null}
          </div>
        </div>

        {issues && issues.length > 0 ? (
          <div className="grp">
            <h3>
              <ChevronDownIcon />
              Замечания проверки
            </h3>
            <ul className="issues-list">
              {issues.map((issue, index) => (
                <li key={`${issue.path}-${index}`}>
                  {issue.path} — {issue.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {applyError ? (
          <div
            className="props-empty"
            style={{ color: "var(--bad)", padding: "0 0 8px" }}
          >
            Ошибка: {applyError}
          </div>
        ) : null}

        <div
          style={{ display: "flex", gap: 8, paddingTop: 4, paddingBottom: 6 }}
        >
          <button
            type="button"
            className="btn primary"
            disabled={!dirty || applying}
            style={{ flex: 1 }}
            onClick={handleApply}
          >
            {applying ? "Проверяем…" : "Пересчитать как вариант"}
          </button>
          <button
            type="button"
            className="btn"
            disabled={!dirty || applying}
            onClick={handleReset}
          >
            Сбросить
          </button>
        </div>
      </div>
    </section>
  );
}
