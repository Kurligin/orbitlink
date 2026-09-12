import { useWorkspace } from "../../store/workspace";
import { AsyncState } from "../common/AsyncState";
import { MarginStrips } from "./MarginStrips";
import { ReasonBreakdown } from "./ReasonBreakdown";
import { RouteStabilityTable } from "./RouteStabilityTable";

export function StabilityScreen() {
  const {
    scenario,
    presetsError,
    variantError,
    networkError,
    runError,
    runLoading,
    runResult,
    variantId,
    clientIds,
  } = useWorkspace();

  const fatalError = presetsError ?? variantError ?? networkError;

  if (fatalError) {
    return <AsyncState tone="error" message={`Ошибка: ${fatalError}`} />;
  }
  if (!scenario) {
    return <AsyncState message="Загрузка сценария…" />;
  }
  if (runError) {
    return (
      <AsyncState
        tone="error"
        message={`Не удалось прогнать расчёт: ${runError}`}
      />
    );
  }
  if (runLoading || !runResult) {
    return <AsyncState message="Считаем доступность и маршруты…" />;
  }
  if (clientIds.length === 0) {
    return <AsyncState message="В сценарии нет клиентских пунктов." />;
  }

  return (
    <div className="screen">
      <div className="screen-head">
        <h1>Устойчивость</h1>
        <span className="hint">
          {scenario.meta.title} · стратегия текущего прогона видна и правится на
          экране «Сеть»
        </span>
      </div>

      <div className="block">
        <MarginStrips />
      </div>

      <div className="block">
        <div className="block-head">
          <h2>Причины отсутствия связи</h2>
        </div>
        <ReasonBreakdown />
      </div>

      <div className="block">
        <RouteStabilityTable variantId={variantId} />
      </div>
    </div>
  );
}
