/**
 * Общий узор «пусто / грузится / ошибка с повтором» для экранов, которые
 * запускают расчёт по кнопке (Устойчивость, Сравнение, Проверка) — вместо
 * пустого экрана до первого прогона.
 */
interface AsyncStateProps {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  tone?: "empty" | "error";
}

export function AsyncState({
  message,
  actionLabel,
  onAction,
  tone = "empty",
}: AsyncStateProps) {
  return (
    <div className={tone === "error" ? "load-state error" : "load-state"}>
      <div>{message}</div>
      {actionLabel && onAction ? (
        <button type="button" className="btn primary" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
