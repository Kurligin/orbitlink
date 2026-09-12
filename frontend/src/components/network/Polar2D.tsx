import { useCallback, useEffect, useRef } from "react";
import { computeOrbitRing } from "../../geo/orbit";
import {
  latLonToPolarCanvas,
  type PolarProjectionOptions,
} from "../../geo/projection";
import { useNetworkFrame } from "../../store/useNetworkFrame";
import { useWorkspace } from "../../store/workspace";
import type { Overlays } from "./overlays";

const ACCENT = "#4a8cff";
const WARN = "#c9a227";
const SAT_ACTIVE = "#cfd6e0";
const SAT_INACTIVE = "#4c5561";
const EDGE_DIM = "rgba(154,160,170,0.28)";
const ORBIT_LINE = "rgba(154,160,170,0.38)";
const GRID_LINE = "#2a2e37";
const LABEL_TEXT = "#9aa0aa";

interface HitTarget {
  x: number;
  y: number;
  kind: "satellite" | "client" | "gateway";
  id: string;
}

interface Props {
  overlays: Overlays;
}

export function Polar2D({ overlays }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hitTargets = useRef<HitTarget[]>([]);
  const { scenario, currentTS, setSelection, setFocusClientId } =
    useWorkspace();
  const frame = useNetworkFrame();

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !scenario) return;

    const dpr = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const height = container.clientHeight;
    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(height * dpr));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const centerX = width / 2;
    const centerY = height / 2;
    const canvasRadius = Math.max(20, Math.min(width, height) / 2 - 28);
    const projOpts: PolarProjectionOptions = { centerX, centerY, canvasRadius };

    hitTargets.current = [];

    ctx.save();
    ctx.beginPath();
    ctx.arc(centerX, centerY, canvasRadius, 0, Math.PI * 2);
    ctx.clip();

    // Сетка параллелей (в четверть шага до границы) и меридианов каждые 45°.
    ctx.strokeStyle = GRID_LINE;
    ctx.lineWidth = 1;
    for (const frac of [0.25, 0.5, 0.75, 1]) {
      ctx.beginPath();
      ctx.arc(centerX, centerY, canvasRadius * frac, 0, Math.PI * 2);
      ctx.stroke();
    }
    for (let deg = 0; deg < 360; deg += 45) {
      const rad = (deg * Math.PI) / 180;
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(
        centerX + canvasRadius * Math.sin(rad),
        centerY - canvasRadius * Math.cos(rad),
      );
      ctx.stroke();
    }

    if (!frame) {
      ctx.restore();
      return;
    }

    const project = (latDeg: number, lonDeg: number) =>
      latLonToPolarCanvas(latDeg, lonDeg, projOpts);

    // Кольца орбит.
    if (overlays.orbits) {
      ctx.strokeStyle = ORBIT_LINE;
      ctx.lineWidth = 1;
      for (const plane of scenario.design.planes) {
        const ring = computeOrbitRing(
          scenario.environment,
          plane,
          currentTS,
          96,
        );
        ctx.beginPath();
        ring.forEach((p, index) => {
          const { x, y } = project(p.latDeg, p.lonDeg);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
    }

    // Инстантные связи сети (кроме отрезков выделенного маршрута — те поверх).
    if (overlays.edges) {
      ctx.strokeStyle = EDGE_DIM;
      ctx.lineWidth = 1;
      for (const edge of frame.edges) {
        if (edge.onRoute) continue;
        const a = frame.nodePositions.get(edge.aId);
        const b = frame.nodePositions.get(edge.bId);
        if (!a || !b) continue;
        const pa = project(a.latDeg, a.lonDeg);
        const pb = project(b.latDeg, b.lonDeg);
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
      }
    }

    // Выделенный маршрут.
    if (overlays.route && frame.routeNodeIds.length > 1) {
      ctx.strokeStyle = ACCENT;
      ctx.lineWidth = 2;
      ctx.beginPath();
      frame.routeNodeIds.forEach((id, index) => {
        const pos = frame.nodePositions.get(id);
        if (!pos) return;
        const { x, y } = project(pos.latDeg, pos.lonDeg);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.textBaseline = "middle";

    // Аппараты. Подпись каждого из 40+ спутников на стандартном приближении
    // не читается — по умолчанию подписан только выбранный аппарат и те,
    // что входят в текущий маршрут; «Подписи аппаратов (все)» — опция.
    for (const sat of frame.satellites) {
      const { x, y } = project(sat.latDeg, sat.lonDeg);
      const onHighlightedRoute = sat.onRoute && overlays.route;
      const color = sat.selected
        ? ACCENT
        : onHighlightedRoute
          ? ACCENT
          : sat.active
            ? SAT_ACTIVE
            : SAT_INACTIVE;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, sat.selected ? 3 : 2, 0, Math.PI * 2);
      ctx.fill();
      if (sat.selected || onHighlightedRoute || overlays.labels) {
        ctx.fillStyle = LABEL_TEXT;
        ctx.font =
          sat.selected || onHighlightedRoute
            ? "600 11px 'JetBrains Mono', monospace"
            : "9px 'JetBrains Mono', monospace";
        ctx.fillText(sat.id, x + 5, y);
        ctx.font = "9px 'JetBrains Mono', monospace";
      }
      hitTargets.current.push({ x, y, kind: "satellite", id: sat.id });
    }

    // Наземные пункты: шлюз — ромб, клиент — кружок. Они важнее аппаратов —
    // подпись читается всегда, независимо от оверлея «Подписи аппаратов».
    for (const site of frame.groundSites) {
      const { x, y } = project(site.latDeg, site.lonDeg);
      const isGateway = site.role === "gateway";
      ctx.fillStyle = isGateway ? ACCENT : site.focused ? WARN : "#d8b354";
      if (isGateway) {
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(Math.PI / 4);
        ctx.fillRect(-3.2, -3.2, 6.4, 6.4);
        ctx.restore();
      } else {
        ctx.beginPath();
        ctx.arc(x, y, site.focused ? 4 : 3.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = "#e8eaed";
      ctx.font = isGateway
        ? "700 12px 'JetBrains Mono', monospace"
        : "600 11px 'JetBrains Mono', monospace";
      ctx.fillText(site.id, x + 7, y);
      ctx.font = "9px 'JetBrains Mono', monospace";
      hitTargets.current.push({
        x,
        y,
        kind: isGateway ? "gateway" : "client",
        id: site.id,
      });
    }

    ctx.restore();
  }, [scenario, currentTS, frame, overlays]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => draw());
    observer.observe(container);
    return () => observer.disconnect();
  }, [draw]);

  const onClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let best: HitTarget | null = null;
    let bestDist = 12; // px — радиус попадания
    for (const target of hitTargets.current) {
      const d = Math.hypot(target.x - x, target.y - y);
      if (d < bestDist) {
        bestDist = d;
        best = target;
      }
    }
    if (!best) return;
    if (best.kind === "satellite")
      setSelection({ kind: "satellite", satelliteId: best.id });
    else if (best.kind === "client") setFocusClientId(best.id);
  };

  return (
    <div ref={containerRef} className="viewport-surface">
      <canvas
        ref={canvasRef}
        onClick={onClick}
        role="img"
        aria-label="Полярная стереографическая проекция сети"
        style={{
          display: "block",
          width: "100%",
          height: "100%",
          cursor: "pointer",
        }}
      />
    </div>
  );
}
