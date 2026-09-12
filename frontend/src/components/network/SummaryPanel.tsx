import { useRef, useState, type ChangeEvent } from "react";
import { ChevronDownIcon, ScenarioIcon, SummaryIcon } from "../icons";
import { formatClock } from "../../lib/format";
import { downloadJson } from "../../lib/download";
import { routeKey, useWorkspace } from "../../store/workspace";
import type { NetworkFrame } from "../../store/useNetworkFrame";
import { api, ApiError } from "../../api/client";
import type { Scenario, ValidationIssue } from "../../api/types";
import { generateUploadScenarioId } from "../../store/scenarioEdit";

/**
 * Правая колонка экрана «Сеть»: выбор сценария сверху + сводка по модели и
 * текущему отсчёту. Раньше эти же величины были размазаны — выбор сценария
 * жил в верхней строке меню, а сводка — в нижней статусной строке. Здесь обе
 * части собраны в одну самостоятельную панель того же визуального языка, что
 * и левая колонка (заголовок группы, строки «подпись — значение», числа
 * моноширинным шрифтом).
 */

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

/** Строка с потенциально длинным значением (маршрут) — переносится, не режется. */
function WideField({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: "6px 0 8px" }}>
      <label
        style={{
          fontSize: 12,
          color: "var(--fg-2)",
          display: "block",
          marginBottom: 5,
        }}
      >
        {label}
      </label>
      <div
        className="mono"
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius)",
          background: "#15171c",
          padding: "5px 7px",
          fontSize: 12,
          lineHeight: 1.4,
          wordBreak: "break-word",
        }}
      >
        {value}
      </div>
    </div>
  );
}

interface SummaryPanelProps {
  frame: NetworkFrame | null;
}

export function SummaryPanel({ frame }: SummaryPanelProps) {
  const {
    presets,
    currentPresetId,
    setCurrentPresetId,
    scenario,
    networkPacket,
    stepIndex,
    currentTS,
    focusClientId,
    routeIndex,
    runResult,
    strategy,
    variantId,
    addUserScenario,
  } = useWorkspace();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadIssues, setUploadIssues] = useState<ValidationIssue[] | null>(
    null,
  );
  const [uploading, setUploading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const totalSatellites = scenario?.design.satellites.length ?? 0;
  const activeCount = networkPacket
    ? (networkPacket.activeByStep[stepIndex]?.filter(Boolean).length ?? 0)
    : 0;
  const planesCount = scenario?.design.planes.length ?? 0;
  const design = scenario?.design;
  const maxBatch = design
    ? design.satellites.reduce(
        (max, s) => Math.max(max, s.launch_batch),
        design.launch_stage,
      )
    : 0;

  const route = focusClientId
    ? routeIndex.get(routeKey(focusClientId, currentTS))
    : undefined;
  const hops = route ? route.hops : null;
  const hasBackup = route ? route.has_backup : null;
  const gapCount = focusClientId
    ? (runResult?.clients[focusClientId]?.gap_count ?? null)
    : null;

  const handleFileChosen = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // разрешить повторно выбрать тот же файл
    if (!file) return;

    setUploadError(null);
    setUploadIssues(null);
    setUploading(true);
    try {
      const text = await file.text();
      let parsed: Scenario;
      try {
        parsed = JSON.parse(text) as Scenario;
      } catch (parseError) {
        setUploadError(
          `Файл не является корректным JSON: ${
            parseError instanceof Error
              ? parseError.message
              : String(parseError)
          }`,
        );
        return;
      }

      const report = await api.validateScenario(parsed);
      if (!report.ok) {
        setUploadIssues(report.issues);
        return;
      }

      const existingIds = presets?.map((p) => p.id) ?? [];
      const newId = generateUploadScenarioId(existingIds);
      const uploaded: Scenario = {
        ...parsed,
        meta: { id: newId, title: `Файл: ${file.name}` },
      };
      addUserScenario(uploaded, null);
    } catch (error) {
      setUploadError(
        error instanceof ApiError
          ? `${error.message} (код ${error.status})`
          : error instanceof Error
            ? error.message
            : "Не удалось загрузить сценарий",
      );
    } finally {
      setUploading(false);
    }
  };

  const handleExportScenario = () => {
    if (!scenario) return;
    downloadJson(`${scenario.meta.id}.json`, scenario);
  };

  const handleExportResult = async () => {
    if (!variantId || !scenario) return;
    setExportError(null);
    try {
      const result = await api.exportVariant(variantId, strategy);
      downloadJson(`${scenario.meta.id}-result.json`, result);
    } catch (error) {
      setExportError(
        error instanceof ApiError
          ? `${error.message} (код ${error.status})`
          : error instanceof Error
            ? error.message
            : "Не удалось выгрузить результат",
      );
    }
  };

  return (
    <>
      <section className="sec">
        <h2>
          <ScenarioIcon />
          Сценарий
        </h2>
        <div className="props" style={{ paddingTop: 6 }}>
          {presets ? (
            <select
              aria-label="Сценарий"
              className="scn-select"
              value={currentPresetId ?? ""}
              onChange={(event) => setCurrentPresetId(event.target.value)}
              style={{ width: "100%", border: "1px solid var(--line)" }}
            >
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.title}
                </option>
              ))}
            </select>
          ) : (
            <div className="props-empty" style={{ padding: "4px 0" }}>
              {scenario?.meta.id ?? "загрузка…"}
            </div>
          )}
          {scenario ? (
            <div className="props-empty" style={{ padding: "8px 0 0" }}>
              схема {scenario.schema_version}
            </div>
          ) : null}

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 6,
              paddingTop: 10,
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              hidden
              onChange={handleFileChosen}
            />
            <button
              type="button"
              className="btn"
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploading ? "Проверяем…" : "Загрузить сценарий…"}
            </button>

            {uploadError ? (
              <div
                className="props-empty"
                style={{ color: "var(--bad)", padding: "2px 0" }}
              >
                Ошибка: {uploadError}
              </div>
            ) : null}

            {uploadIssues && uploadIssues.length > 0 ? (
              <div>
                <ul className="issues-list">
                  {uploadIssues.map((issue, index) => (
                    <li key={`${issue.path}-${index}`}>
                      {issue.path} — {issue.message}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  className="btn"
                  style={{ marginTop: 6 }}
                  onClick={() => setUploadIssues(null)}
                >
                  Закрыть
                </button>
              </div>
            ) : null}

            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                className="btn"
                style={{ flex: 1 }}
                disabled={!scenario}
                onClick={handleExportScenario}
              >
                Выгрузить сценарий
              </button>
              <button
                type="button"
                className="btn"
                style={{ flex: 1 }}
                disabled={!variantId}
                onClick={handleExportResult}
              >
                Выгрузить результат
              </button>
            </div>
            {exportError ? (
              <div
                className="props-empty"
                style={{ color: "var(--bad)", padding: "2px 0" }}
              >
                Ошибка: {exportError}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <section className="sec" style={{ flex: 1 }}>
        <h2>
          <SummaryIcon />
          Сводка
        </h2>
        <div className="props">
          <div className="grp">
            <h3>
              <ChevronDownIcon />
              Группировка
            </h3>
            <Field
              label="Активных аппаратов"
              value={`${activeCount}/${totalSatellites}`}
            />
            <Field label="Плоскостей" value={String(planesCount)} />
            <Field
              label="Очередь запуска"
              value={design ? String(design.launch_stage) : "—"}
              unit={design ? `из ${maxBatch}` : undefined}
            />
          </div>

          <div className="grp">
            <h3>
              <ChevronDownIcon />
              Текущий отсчёт
            </h3>
            <Field label="Время" value={formatClock(currentTS)} />
            <WideField label="Маршрут" value={frame?.routeText ?? "—"} />
            <Field
              label="Переходов"
              value={hops === null ? "—" : String(hops)}
            />
            <Field
              label="Резерв"
              value={hasBackup === null ? "—" : hasBackup ? "есть" : "нет"}
            />
            <Field
              label="Перерывов за сутки"
              value={
                gapCount === null || gapCount === undefined
                  ? "—"
                  : String(gapCount)
              }
            />
          </div>
        </div>
      </section>
    </>
  );
}
