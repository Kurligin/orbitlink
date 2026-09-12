import { useCallback, useState } from "react";
import { api, ApiError } from "../../api/client";
import { formatClock, formatNumber } from "../../lib/format";
import { AsyncState } from "../common/AsyncState";
import type { SelfTestResult } from "../../api/types";

const POSITION_TOLERANCE_KM = 1e-9;
const ELEVATION_TOLERANCE_DEG = 1e-9;

function formatSmall(value: number): string {
  if (value === 0) return "0";
  const abs = Math.abs(value);
  if (abs < 1e-6) return value.toExponential(2);
  return value.toFixed(abs < 1 ? 6 : 3);
}

function checkPasses(check: SelfTestResult["checks"][number]): boolean {
  return (
    check.edges_match &&
    check.max_position_error_km < POSITION_TOLERANCE_KM &&
    check.max_elevation_error_deg < ELEVATION_TOLERANCE_DEG
  );
}

type Status = "idle" | "loading" | "done" | "error";

export function SelftestScreen() {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<SelfTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const data = await api.selftest();
      setResult(data);
      setStatus("done");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message} (код ${err.status})`
          : err instanceof Error
            ? err.message
            : "Не удалось запустить проверку",
      );
      setStatus("error");
    }
  }, []);

  const passedCount = result ? result.checks.filter(checkPasses).length : 0;
  const totalCount = result ? result.checks.length : 0;
  const allPassed = totalCount > 0 && passedCount === totalCount;

  return (
    <div className="screen">
      <div className="screen-head">
        <h1>Проверка расчёта</h1>
        <span className="hint">
          GET /api/selftest — сверка с эталонным модулем организаторов
        </span>
      </div>

      <div className="block">
        <div className="block-head">
          <h2>Сверка на контрольных точках</h2>
          <button
            type="button"
            className="btn primary"
            disabled={status === "loading"}
            onClick={run}
          >
            {status === "idle" ? "Запустить проверку" : "Запустить заново"}
          </button>
        </div>

        {status === "idle" ? (
          <AsyncState message="Проверка ещё не запускалась." />
        ) : status === "error" ? (
          <AsyncState
            tone="error"
            message={`Ошибка: ${error}`}
            actionLabel="Повторить"
            onAction={run}
          />
        ) : status === "loading" && !result ? (
          <AsyncState message="Сверяем координаты, состав связей и углы возвышения…" />
        ) : result ? (
          <>
            <div className="selftest-summary">
              <span className={`headline mono ${allPassed ? "" : "flag-bad"}`}>
                {allPassed ? "✓" : "✗"} сошлось {passedCount} из {totalCount}
              </span>
              <span className="sub">эталон: {result.reference}</span>
            </div>

            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Сценарий</th>
                    <th className="num">Отсчёт</th>
                    <th className="num">Расхождение координат, км</th>
                    <th>Состав связей</th>
                    <th className="num">Расхождение углов возвышения, °</th>
                  </tr>
                </thead>
                <tbody>
                  {result.checks.map((check, index) => {
                    const passed = checkPasses(check);
                    return (
                      <tr key={`${check.scenario}-${check.t_s}-${index}`}>
                        <td>{check.scenario}</td>
                        <td className="num mono">
                          {formatClock(check.t_s, true)}
                        </td>
                        <td className={`num mono ${passed ? "" : "flag-bad"}`}>
                          {formatSmall(check.max_position_error_km)}
                        </td>
                        <td
                          className={check.edges_match ? "flag-ok" : "flag-bad"}
                        >
                          {check.edges_match
                            ? "✓ совпал"
                            : `✗ разошёлся (${formatNumber(check.our_edge_count)} ⁄ ${formatNumber(check.reference_edge_count)})`}
                        </td>
                        <td className={`num mono ${passed ? "" : "flag-bad"}`}>
                          {formatSmall(check.max_elevation_error_deg)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={5}>
                      Сошлось {passedCount} из {totalCount}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
