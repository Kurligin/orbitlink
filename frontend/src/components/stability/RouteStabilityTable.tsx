import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { formatNumber } from "../../lib/format";
import type { RoutingStrategy } from "../../api/types";

const STRATEGIES: RoutingStrategy[] = [
  "min_hops",
  "min_latency",
  "load_aware",
  "robust",
];

const STRATEGY_LABELS: Record<RoutingStrategy, string> = {
  min_hops: "мин. переходов",
  min_latency: "задержка",
  load_aware: "учёт нагрузки",
  robust: "запас по дальности",
};

interface StrategyRow {
  rerouteCount: number;
  pathChangeCount: number;
}

type Status = "idle" | "running" | "done" | "error";

export function RouteStabilityTable({
  variantId,
}: {
  variantId: string | null;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [rows, setRows] = useState<
    Partial<Record<RoutingStrategy, StrategyRow>>
  >({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(0);

  const run = useCallback(async () => {
    if (!variantId) return;
    setStatus("running");
    setError(null);
    setRows({});
    setDone(0);
    for (const strategy of STRATEGIES) {
      try {
        const result = await api.runVariant(variantId, { strategy });
        let reroute = 0;
        let pathChange = 0;
        for (const metrics of Object.values(result.clients)) {
          reroute += metrics.reroute_count;
          pathChange += metrics.path_change_count;
        }
        setRows((prev) => ({
          ...prev,
          [strategy]: { rerouteCount: reroute, pathChangeCount: pathChange },
        }));
        setDone((d) => d + 1);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : `Не удалось прогнать стратегию «${STRATEGY_LABELS[strategy]}»`,
        );
        setStatus("error");
        return;
      }
    }
    setStatus("done");
  }, [variantId]);

  return (
    <div>
      <div className="block-head">
        <h2>Устойчивость маршрута по стратегиям</h2>
        <button
          type="button"
          className="btn primary"
          disabled={!variantId || status === "running"}
          onClick={run}
        >
          {status === "idle" ? "Прогнать все стратегии" : "Прогнать заново"}
        </button>
      </div>
      <div className="block-note">
        Для каждой стратегии — прогон варианта заново: число перепоисков
        маршрута, число реальных смен пути и разность между ними как результат,
        погашенный локальным ремонтом (перепоиск нашёл, что действующий путь всё
        ещё годится).
      </div>

      {status === "running" ? (
        <div className="progress-note mono">
          Прогон {done + 1} из {STRATEGIES.length}…
        </div>
      ) : null}
      {status === "error" && error ? (
        <div
          className="load-state error"
          style={{ flex: "none", padding: "10px 0" }}
        >
          <div>Ошибка: {error}</div>
          <button type="button" className="btn" onClick={run}>
            Повторить
          </button>
        </div>
      ) : null}

      {status === "idle" && Object.keys(rows).length === 0 ? (
        <div className="block-note">Расчёт ещё не запускался.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Стратегия</th>
                <th className="num">Перепоисков</th>
                <th className="num">Смен пути</th>
                <th className="num">Погашено локальным ремонтом</th>
              </tr>
            </thead>
            <tbody>
              {STRATEGIES.map((strategy) => {
                const row = rows[strategy];
                return (
                  <tr key={strategy}>
                    <td>{STRATEGY_LABELS[strategy]}</td>
                    <td className="num">
                      {row ? formatNumber(row.rerouteCount) : "—"}
                    </td>
                    <td className="num">
                      {row ? formatNumber(row.pathChangeCount) : "—"}
                    </td>
                    <td className="num">
                      {row
                        ? formatNumber(row.rerouteCount - row.pathChangeCount)
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
