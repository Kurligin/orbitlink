import { useMemo } from "react";
import { formatPercent } from "../../lib/format";
import { useWorkspace } from "../../store/workspace";
import type { ClientMetrics } from "../../api/types";

interface Segment {
  level: number;
  count: number;
}

/** Сжимает массив уровней запаса связности в отрезки одинакового уровня подряд. */
function toSegments(levels: number[]): Segment[] {
  const segments: Segment[] = [];
  for (const level of levels) {
    const last = segments[segments.length - 1];
    if (last && last.level === level) {
      last.count += 1;
    } else {
      segments.push({ level, count: 1 });
    }
  }
  return segments;
}

const LEVEL_CLASS: Record<number, string> = { 2: "s2", 1: "s1", 0: "s0" };

function Strip({ metrics }: { metrics: ClientMetrics }) {
  const segments = useMemo(
    () => toSegments(metrics.margin_levels),
    [metrics.margin_levels],
  );
  const total = metrics.margin_levels.length || 1;
  return (
    <div className="strip-row">
      <span className="n">{metrics.client_id}</span>
      <span
        className="strip"
        role="img"
        aria-label={`Запас связности пункта ${metrics.client_id}`}
      >
        {segments.map((segment, index) => (
          <i
            key={index}
            className={LEVEL_CLASS[segment.level] ?? "s0"}
            style={{ width: `${(segment.count / total) * 100}%` }}
          />
        ))}
      </span>
      <span className="p mono">
        {formatPercent(metrics.availability_fraction)}
      </span>
    </div>
  );
}

export function AvailabilityStrips() {
  const { clientIds, runResult, runLoading } = useWorkspace();

  return (
    <div className="av">
      <div className="av-h">
        <b>Запас связности по пунктам</b>
        <span className="lg">
          <span>
            <i className="s2" />
            резервный маршрут
          </span>
          <span>
            <i className="s1" />
            маршрут без резерва
          </span>
          <span>
            <i className="s0" />
            связи нет
          </span>
        </span>
      </div>
      {clientIds.map((clientId) => {
        const metrics = runResult?.clients[clientId];
        if (!metrics) {
          return (
            <div className="strip-row" key={clientId}>
              <span className="n">{clientId}</span>
              <span className="strip" />
              <span className="p mono">{runLoading ? "…" : "—"}</span>
            </div>
          );
        }
        return <Strip key={clientId} metrics={metrics} />;
      })}
    </div>
  );
}
