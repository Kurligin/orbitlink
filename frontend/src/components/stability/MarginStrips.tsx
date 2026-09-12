import { useCallback, useMemo } from "react";
import { formatClock, formatPercent } from "../../lib/format";
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

function Strip({
  clientId,
  metrics,
}: {
  clientId: string;
  metrics: ClientMetrics;
}) {
  const { setStepIndex, setPlaying } = useWorkspace();
  const segments = useMemo(
    () => toSegments(metrics.margin_levels),
    [metrics.margin_levels],
  );
  const total = metrics.margin_levels.length || 1;

  const onClick = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const raw = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
      const fraction = Math.min(1, Math.max(0, raw));
      setPlaying(false);
      setStepIndex(Math.round(fraction * (total - 1)));
    },
    [setStepIndex, setPlaying, total],
  );

  return (
    <div className="mstrip-row">
      <span className="n">{clientId}</span>
      <button
        type="button"
        className="mstrip"
        onClick={onClick}
        aria-label={`Лента запаса связности пункта ${clientId} — клик переводит таймлайн в этот момент`}
        title="Клик — перейти к этому моменту на таймлайне"
      >
        {segments.map((segment, index) => (
          <i
            key={index}
            className={LEVEL_CLASS[segment.level] ?? "s0"}
            style={{ width: `${(segment.count / total) * 100}%` }}
          />
        ))}
      </button>
      <span className="mstrip-p">
        {formatPercent(metrics.availability_fraction)}
      </span>
    </div>
  );
}

export function MarginStrips() {
  const { clientIds, runResult, currentTS } = useWorkspace();

  return (
    <div>
      <div className="block-head">
        <h2>Запас связности по клиентским пунктам</h2>
        <span className="mstrip-legend">
          <span>
            <i className="sw s2" />
            есть резерв
          </span>
          <span>
            <i className="sw s1" />
            связь есть, резерва нет
          </span>
          <span>
            <i className="sw s0" />
            связи нет
          </span>
        </span>
      </div>
      <div className="block-note">
        720 отсчётов за расчёт, по одному клиентскому пункту в строке. Уровни
        различаются цветом и штриховкой. Клик по ленте — перейти к этому моменту
        на таймлайне; текущий момент:{" "}
        <span className="mono">{formatClock(currentTS, true)}</span>.
      </div>
      <div className="mstrips">
        {clientIds.map((clientId) => {
          const metrics = runResult?.clients[clientId];
          if (!metrics) {
            return (
              <div className="mstrip-row" key={clientId}>
                <span className="n">{clientId}</span>
                <span className="mstrip" />
                <span className="mstrip-p">—</span>
              </div>
            );
          }
          return <Strip key={clientId} clientId={clientId} metrics={metrics} />;
        })}
      </div>
    </div>
  );
}
