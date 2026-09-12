import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { formatClock, formatPercent } from "../../lib/format";
import { useWorkspace } from "../../store/workspace";
import { AsyncState } from "../common/AsyncState";
import type { CompareResult, RoutingStrategy } from "../../api/types";

const STRATEGY_LABELS: Record<RoutingStrategy, string> = {
  min_hops: "мин. переходов",
  min_latency: "задержка",
  load_aware: "учёт нагрузки",
  robust: "запас по дальности",
};
const STRATEGIES = Object.keys(STRATEGY_LABELS) as RoutingStrategy[];

function signedPercentPoints(delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  return `${sign}${Math.abs(delta * 100).toFixed(1)} п.п.`;
}

function signedDuration(delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  return `${sign}${formatClock(Math.abs(delta))}`;
}

function deltaClass(delta: number | null, betterWhenPositive: boolean): string {
  if (delta === null || delta === 0) return "delta-flat";
  const positive = delta > 0;
  return positive === betterWhenPositive ? "delta-up" : "delta-down";
}

export function CompareScreen() {
  const {
    presets,
    presetsError,
    ensureVariantId,
    strategy,
    setStrategy,
    userScenarios,
  } = useWorkspace();

  const [baseId, setBaseId] = useState<string | null>(null);
  const [candidateId, setCandidateId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);

  // По умолчанию — и пресеты, и сохранённые пользователем варианты (единый
  // список `presets`, см. workspace.tsx). Если пользователь уже сохранил
  // вариант правкой панели параметров (у него есть originId — сценарий, из
  // которого он получен), по умолчанию сравниваем именно эту пару: самый
  // свежий такой вариант против его исходного сценария. У загруженных из
  // файла сценариев исходного сценария нет (originId === null) — для них
  // этот дефолт не подставляется.
  useEffect(() => {
    if (!presets || presets.length === 0) return;
    const lastDerived = [...userScenarios]
      .reverse()
      .find((entry) => entry.originId !== null);
    setBaseId((prev) => prev ?? lastDerived?.originId ?? presets[0]!.id);
    setCandidateId(
      (prev) =>
        prev ??
        lastDerived?.scenario.meta.id ??
        presets[Math.min(1, presets.length - 1)]!.id,
    );
  }, [presets, userScenarios]);

  const basePreset = useMemo(
    () => presets?.find((p) => p.id === baseId) ?? null,
    [presets, baseId],
  );
  const candidatePreset = useMemo(
    () => presets?.find((p) => p.id === candidateId) ?? null,
    [presets, candidateId],
  );

  const runCompare = async () => {
    if (!basePreset || !candidatePreset) return;
    setStatus("loading");
    setError(null);
    try {
      const [baseVariantId, variantId] = await Promise.all([
        ensureVariantId(basePreset.scenario),
        ensureVariantId(candidatePreset.scenario),
      ]);
      const compareResult = await api.compare({
        base_variant_id: baseVariantId,
        variant_id: variantId,
        strategy,
      });
      setResult(compareResult);
      setStatus("done");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message} (код ${err.status})`
          : err instanceof Error
            ? err.message
            : "Не удалось сравнить варианты",
      );
      setStatus("error");
    }
  };

  if (presetsError) {
    return <AsyncState tone="error" message={`Ошибка: ${presetsError}`} />;
  }
  if (!presets) {
    return <AsyncState message="Загрузка сценариев…" />;
  }

  const targetBefore =
    basePreset?.scenario.environment.target_availability ?? null;
  const targetAfter =
    candidatePreset?.scenario.environment.target_availability ?? null;

  const clientRows = result
    ? Object.entries(result.clients).sort(([a], [b]) => a.localeCompare(b))
    : [];

  return (
    <div className="screen">
      <div className="screen-head">
        <h1>Сравнение вариантов</h1>
        <span className="hint">
          POST /api/compare — доступность и параметры «до/после»
        </span>
      </div>

      <div className="block">
        <div className="field-row">
          <div className="field">
            <label htmlFor="base-variant">Базовый вариант</label>
            <select
              id="base-variant"
              value={baseId ?? ""}
              onChange={(e) => setBaseId(e.target.value)}
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="candidate-variant">Сравниваемый вариант</label>
            <select
              id="candidate-variant"
              value={candidateId ?? ""}
              onChange={(e) => setCandidateId(e.target.value)}
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="compare-strategy">Стратегия маршрутизации</label>
            <select
              id="compare-strategy"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as RoutingStrategy)}
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {STRATEGY_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn primary"
            disabled={!basePreset || !candidatePreset || status === "loading"}
            onClick={runCompare}
          >
            {status === "loading" ? "Считаем…" : "Сравнить"}
          </button>
        </div>
      </div>

      {status === "idle" ? (
        <AsyncState message="Выберите два варианта и нажмите «Сравнить»." />
      ) : status === "error" ? (
        <AsyncState
          tone="error"
          message={`Ошибка: ${error}`}
          actionLabel="Повторить"
          onAction={runCompare}
        />
      ) : status === "loading" && !result ? (
        <AsyncState message="Считаем оба варианта и сверяем результаты…" />
      ) : result ? (
        <>
          <div className="block">
            <div className="block-head">
              <h2>Изменённые параметры</h2>
            </div>
            {result.changes.length === 0 ? (
              <div className="block-note">
                Параметры сценария между вариантами не отличаются.
              </div>
            ) : (
              <ul className="changes-list">
                {result.changes.map((change, index) => (
                  <li key={`${change.path}-${index}`}>{change.label}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="block">
            <div className="block-head">
              <h2>Доступность по клиентским пунктам</h2>
            </div>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Пункт</th>
                    <th className="num">Было</th>
                    <th className="num">Стало</th>
                    <th className="num">Дельта</th>
                    <th className="num">Макс. перерыв — было</th>
                    <th className="num">Макс. перерыв — стало</th>
                    <th className="num">Дельта перерыва</th>
                    <th>Цель (стало)</th>
                  </tr>
                </thead>
                <tbody>
                  {clientRows.map(([clientId, row]) => {
                    const met =
                      row.availability_after !== null && targetAfter !== null
                        ? row.availability_after >= targetAfter
                        : null;
                    return (
                      <tr key={clientId}>
                        <td>{clientId}</td>
                        <td className="num">
                          {row.availability_before === null
                            ? "—"
                            : formatPercent(row.availability_before)}
                        </td>
                        <td className="num">
                          {row.availability_after === null
                            ? "—"
                            : formatPercent(row.availability_after)}
                        </td>
                        <td
                          className={`num ${deltaClass(row.availability_delta, true)}`}
                        >
                          {signedPercentPoints(row.availability_delta)}
                        </td>
                        <td className="num">
                          {row.max_gap_s_before === null
                            ? "—"
                            : formatClock(row.max_gap_s_before)}
                        </td>
                        <td className="num">
                          {row.max_gap_s_after === null
                            ? "—"
                            : formatClock(row.max_gap_s_after)}
                        </td>
                        <td
                          className={`num ${deltaClass(row.max_gap_s_delta, false)}`}
                        >
                          {signedDuration(row.max_gap_s_delta)}
                        </td>
                        <td
                          className={
                            met === null
                              ? undefined
                              : met
                                ? "flag-ok"
                                : "flag-bad"
                          }
                          title={
                            targetBefore !== null && targetAfter !== null
                              ? `Цель было ${formatPercent(targetBefore)}, стало ${formatPercent(targetAfter)}`
                              : undefined
                          }
                        >
                          {met === null ? "—" : met ? "✓ да" : "✗ нет"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
