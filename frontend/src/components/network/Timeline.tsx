import { useCallback, useRef } from "react";
import { PauseIcon, PlayIcon } from "../icons";
import { formatClock } from "../../lib/format";
import { useWorkspace } from "../../store/workspace";
import { AvailabilityStrips } from "./AvailabilityStrips";

const TICK_COUNT = 4; // 5 отметок: 0, 1/4, 2/4, 3/4, 4/4 горизонта

export function Timeline() {
  const {
    scenario,
    networkPacket,
    stepIndex,
    setStepIndex,
    playing,
    setPlaying,
    currentTS,
  } = useWorkspace();
  const railRef = useRef<HTMLDivElement>(null);

  const steps = networkPacket?.steps ?? 0;
  const horizonS = scenario?.environment.horizon_s ?? 0;
  const stepS = scenario?.environment.step_s ?? 0;
  const fraction = steps > 1 ? stepIndex / (steps - 1) : 0;

  const seekToClientX = useCallback(
    (clientX: number) => {
      const rail = railRef.current;
      if (!rail || steps === 0) return;
      const rect = rail.getBoundingClientRect();
      const raw = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
      const clamped = Math.min(1, Math.max(0, raw));
      setStepIndex(Math.round(clamped * (steps - 1)));
    },
    [steps, setStepIndex],
  );

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    setPlaying(false);
    seekToClientX(event.clientX);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.buttons !== 1) return;
    seekToClientX(event.clientX);
  };

  const ticks = Array.from(
    { length: TICK_COUNT + 1 },
    (_, i) => (horizonS * i) / TICK_COUNT,
  );

  return (
    <div className="tl">
      <div className="tl-head">
        <button
          type="button"
          className="play"
          onClick={() => setPlaying(!playing)}
          disabled={steps === 0}
          aria-label={playing ? "Остановить воспроизведение" : "Воспроизвести"}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <span className="t mono">{formatClock(currentTS, true)}</span>
        <span className="s mono">
          {" "}
          / {formatClock(horizonS)} · шаг {stepS} с · отсчёт{" "}
          {steps === 0 ? 0 : stepIndex + 1} из {steps}
        </span>
      </div>
      <div
        className="rail"
        ref={railRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        role="slider"
        aria-label="Перемотка времени"
        aria-valuemin={0}
        aria-valuemax={Math.max(steps - 1, 0)}
        aria-valuenow={stepIndex}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft")
            setStepIndex(Math.max(0, stepIndex - 1));
          if (event.key === "ArrowRight")
            setStepIndex(Math.min(steps - 1, stepIndex + 1));
        }}
      >
        <div className="fill" style={{ width: `${fraction * 100}%` }} />
        <div className="k" style={{ left: `${fraction * 100}%` }} />
      </div>
      <div className="rail-t mono">
        {ticks.map((t, i) => (
          // Ключ — позиция в шкале, а не сама метка времени: пока горизонт
          // ещё не загружен, все отметки равны 0 и совпадающий key={t}
          // ломает согласование React между кадрами (лишние узлы остаются
          // в DOM после того как реальный горизонт приходит).
          <span key={i}>{formatClock(t)}</span>
        ))}
      </div>
      <AvailabilityStrips />
    </div>
  );
}
