import { useMemo } from "react";
import { formatNumber, formatPercent } from "../../lib/format";
import { useWorkspace } from "../../store/workspace";

const REASON_LABELS: Record<string, string> = {
  isl_network_split: "Разрыв межспутниковой сети",
  no_visible_satellite: "Нет видимого аппарата",
  no_gateway_contact: "Нет контакта со шлюзом",
  gateway_offline: "Шлюз недоступен",
  unspecified: "Причина не указана",
};

const REASON_COLORS: Record<string, string> = {
  isl_network_split: "var(--cat-1)",
  no_visible_satellite: "var(--cat-2)",
  no_gateway_contact: "var(--cat-3)",
  gateway_offline: "var(--cat-4)",
};

const CANONICAL_ORDER = [
  "isl_network_split",
  "no_visible_satellite",
  "no_gateway_contact",
  "gateway_offline",
];

function reasonLabel(key: string): string {
  return REASON_LABELS[key] ?? "Причина не указана";
}

function reasonColor(key: string): string {
  return REASON_COLORS[key] ?? "var(--fg-3)";
}

interface ReasonTotal {
  key: string;
  count: number;
}

export function ReasonBreakdown() {
  const { runResult } = useWorkspace();

  const { totals, total } = useMemo(() => {
    const acc: Record<string, number> = {};
    if (runResult) {
      for (const metrics of Object.values(runResult.clients)) {
        for (const [reason, count] of Object.entries(metrics.reason_counts)) {
          acc[reason] = (acc[reason] ?? 0) + count;
        }
      }
    }
    const knownFirst = CANONICAL_ORDER.filter((key) => acc[key]).map(
      (key): ReasonTotal => ({ key, count: acc[key]! }),
    );
    const rest = Object.entries(acc)
      .filter(([key]) => !CANONICAL_ORDER.includes(key))
      .map(([key, count]): ReasonTotal => ({ key, count }))
      .sort((a, b) => b.count - a.count);
    const list = [...knownFirst, ...rest];
    const sum = list.reduce((acc2, item) => acc2 + item.count, 0);
    return { totals: list, total: sum };
  }, [runResult]);

  if (!runResult) {
    return (
      <div className="block-note">
        Причины отсутствия связи появятся после расчёта.
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="block-note">
        За расчёт причин недоступности не зафиксировано — по всем клиентским
        пунктам связь была доступна на каждом отсчёте.
      </div>
    );
  }

  const top = [...totals].sort((a, b) => b.count - a.count)[0]!;

  return (
    <div>
      <div
        className="reason-bar"
        role="img"
        aria-label="Доли причин отсутствия связи"
      >
        {totals.map((item) => (
          <i
            key={item.key}
            style={{
              width: `${(item.count / total) * 100}%`,
              background: reasonColor(item.key),
            }}
          />
        ))}
      </div>
      <div className="reason-list" style={{ marginTop: 12 }}>
        {totals.map((item) => (
          <div className="reason-row" key={item.key}>
            <span
              className="sw"
              style={{ background: reasonColor(item.key) }}
            />
            <span className="lbl">{reasonLabel(item.key)}</span>
            <span className="cnt mono">{formatNumber(item.count)}</span>
            <span className="pct mono">
              {formatPercent(item.count / total)}
            </span>
          </div>
        ))}
      </div>
      <div className="block-note" style={{ marginTop: 12 }}>
        Всего {formatNumber(total)} отсчётов без связи по всем клиентским
        пунктам суммарно; чаще всего — «{reasonLabel(top.key)}» (
        {formatNumber(top.count)}, {formatPercent(top.count / total)}
        ).
      </div>
    </div>
  );
}
