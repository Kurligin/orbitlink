/** Форматирование времени и чисел для интерфейса. */

/** `t_s` (секунды от начала расчёта) -> `ЧЧ:ММ` или `ЧЧ:ММ:СС`. */
export function formatClock(tS: number, withSeconds = false): string {
  const total = Math.max(0, Math.round(tS));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const hh = String(hours).padStart(2, "0");
  const mm = String(minutes).padStart(2, "0");
  if (!withSeconds) return `${hh}:${mm}`;
  const ss = String(seconds).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

/** Доля [0..1] -> проценты с одним знаком после запятой: 0.9667 -> "96.7%". */
export function formatPercent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
