import { useEffect, useRef, useState } from "react";
import Globe, { type GlobeInstance } from "globe.gl";
import * as THREE from "three";
import { computeOrbitRing } from "../../geo/orbit";
import { useNetworkFrame } from "../../store/useNetworkFrame";
import { useWorkspace } from "../../store/workspace";
import type { Overlays } from "./overlays";

const ACCENT = "#4a8cff";
const WARN = "#c9a227";
const SAT_ACTIVE = "#cfd6e0";
const SAT_INACTIVE = "#4c5561";
const EDGE_DIM = "rgba(154,160,170,0.22)";
const ORBIT_LINE = "rgba(154,160,170,0.32)";
const EARTH_TEXTURE_URL = "/earth-day.jpg";

interface PathPoint {
  lat: number;
  lng: number;
  alt: number;
}
interface PathDatum {
  kind: "orbit" | "route" | "edge";
  points: PathPoint[];
}
interface LabelDatum {
  kind: "satellite" | "gateway" | "client";
  id: string;
  lat: number;
  lng: number;
  alt: number;
  color: string;
  text: string;
  dotRadius: number;
  size: number;
}

/** Проверяет, что текстура реально загружается с собственного origin приложения. */
function useTextureStatus(url: string): "loading" | "ok" | "error" {
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  useEffect(() => {
    let cancelled = false;
    const img = new Image();
    const timeout = window.setTimeout(() => {
      if (!cancelled) setStatus("error");
    }, 6000);
    img.onload = () => {
      if (!cancelled) {
        window.clearTimeout(timeout);
        setStatus("ok");
      }
    };
    img.onerror = () => {
      if (!cancelled) {
        window.clearTimeout(timeout);
        setStatus("error");
      }
    };
    img.src = url;
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [url]);
  return status;
}

interface Props {
  overlays: Overlays;
  onTextureStatus: (status: "loading" | "ok" | "error") => void;
}

export function Globe3D({ overlays, onTextureStatus }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<GlobeInstance | null>(null);
  const initializedRef = useRef(false);
  const { scenario, currentTS, setSelection, setFocusClientId } =
    useWorkspace();
  const frame = useNetworkFrame();
  const textureStatus = useTextureStatus(EARTH_TEXTURE_URL);

  useEffect(() => {
    onTextureStatus(textureStatus);
  }, [textureStatus, onTextureStatus]);

  // Инициализация глобуса — один раз на монтирование.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || initializedRef.current) return;
    initializedRef.current = true;

    const instance = new Globe(el)
      .backgroundColor("rgba(0,0,0,0)")
      .showAtmosphere(true)
      .atmosphereColor(ACCENT)
      .atmosphereAltitude(0.16)
      .pointsTransitionDuration(0)
      .arcsTransitionDuration(0)
      .pathTransitionDuration(0)
      .labelsTransitionDuration(0)
      .labelResolution(2)
      .pointOfView({ lat: 50, lng: 55, altitude: 2.55 }, 0);

    instance.onLabelClick((label: object) => {
      const datum = label as LabelDatum;
      if (datum.kind === "satellite") {
        setSelection({ kind: "satellite", satelliteId: datum.id });
      } else if (datum.kind === "client") {
        setFocusClientId(datum.id);
      }
    });

    globeRef.current = instance;

    const resize = () => {
      if (!containerRef.current) return;
      instance.width(containerRef.current.clientWidth);
      instance.height(containerRef.current.clientHeight);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    return () => {
      observer.disconnect();
      instance._destructor();
      initializedRef.current = false;
      globeRef.current = null;
      el.replaceChildren();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Текстура Земли — при неудаче честная деградация до затенённой сферы с сеткой
  // параллелей/меридианов (showGraticules — встроенная сетка three-globe).
  // globeImageUrl трогаем только при успехе: пустая/некорректная строка
  // заставила бы three.js пытаться загрузить текущую страницу как картинку.
  //
  // Материал без зеркальной составляющей (shininess 0, specular чёрный) —
  // у стандартного MeshPhongMaterial three-globe (shininess 30) блик
  // направленного света вместе со сходящимися к полюсу UV равнопромежуточной
  // текстуры давал у Арктики пересвеченное пятно с расходящимися лучами и
  // забивал видимость наземных пунктов на 65-72° с.ш. Матовый материал убирает
  // блик — сама текстура на полюсе не белая, светлым было только его отражение.
  useEffect(() => {
    const instance = globeRef.current;
    if (!instance || textureStatus === "loading") return;
    if (textureStatus === "ok") {
      instance
        .globeMaterial(
          new THREE.MeshPhongMaterial({ shininess: 0, specular: 0x000000 }),
        )
        .globeImageUrl(EARTH_TEXTURE_URL)
        .showGraticules(false);
    } else {
      instance
        .showGraticules(true)
        .globeMaterial(
          new THREE.MeshPhongMaterial({
            color: "#16324a",
            shininess: 0,
            specular: 0x000000,
          }),
        );
    }
  }, [textureStatus]);

  // Спутники и наземные пункты — единый слой labelsData (точка + подпись),
  // как аппараты, так и наземные пункты в макете нарисованы одинаково.
  useEffect(() => {
    const instance = globeRef.current;
    if (!instance || !frame) return;

    const labels: LabelDatum[] = [
      ...frame.satellites.map((sat): LabelDatum => {
        const onHighlightedRoute = sat.onRoute && overlays.route;
        // На стандартном приближении подпись каждого из 40+ аппаратов не
        // читается — по умолчанию подписан только выбранный аппарат и те,
        // что входят в текущий маршрут; чекбокс «Подписи аппаратов (все)» —
        // осознанное расширение до полного списка.
        const labelVisible =
          sat.selected || onHighlightedRoute || overlays.labels;
        return {
          kind: "satellite",
          id: sat.id,
          lat: sat.latDeg,
          lng: sat.lonDeg,
          alt: frame.satelliteAltitudeFraction,
          color: sat.selected
            ? ACCENT
            : onHighlightedRoute
              ? ACCENT
              : sat.active
                ? SAT_ACTIVE
                : SAT_INACTIVE,
          text: labelVisible ? sat.id : "",
          dotRadius: sat.selected ? 0.45 : 0.28,
          size: sat.selected ? 0.85 : onHighlightedRoute ? 0.75 : 0.62,
        };
      }),
      // Наземные пункты и шлюз важнее аппаратов — подпись должна читаться
      // всегда, независимо от оверлея «Подписи аппаратов», и заметно крупнее.
      ...frame.groundSites.map((site): LabelDatum => ({
        kind: site.role === "gateway" ? "gateway" : "client",
        id: site.id,
        lat: site.latDeg,
        lng: site.lonDeg,
        alt: 0.012,
        color:
          site.role === "gateway" ? ACCENT : site.focused ? WARN : "#d8b354",
        text: site.id,
        dotRadius: site.role === "gateway" ? 0.62 : 0.5,
        size: site.role === "gateway" ? 1.05 : 0.9,
      })),
    ];

    instance
      .labelsData(labels)
      .labelLat((d) => (d as LabelDatum).lat)
      .labelLng((d) => (d as LabelDatum).lng)
      .labelAltitude((d) => (d as LabelDatum).alt)
      .labelText((d) => (d as LabelDatum).text)
      .labelColor((d) => (d as LabelDatum).color)
      .labelDotRadius((d) => (d as LabelDatum).dotRadius)
      .labelSize((d) => (d as LabelDatum).size)
      .labelIncludeDot(true);
  }, [frame, overlays.labels, overlays.route]);

  // Кольца орбит + инстантные рёбра сети + выделенный маршрут — единый слой
  // pathsData: у каждой точки своя высота, поэтому арки (только высота
  // середины дуги) сюда не подходят — нужны полилинии с высотой на каждой точке.
  useEffect(() => {
    const instance = globeRef.current;
    if (!instance || !frame) return;

    const paths: PathDatum[] = [];

    if (overlays.orbits && scenario) {
      for (const plane of scenario.design.planes) {
        const ring = computeOrbitRing(
          scenario.environment,
          plane,
          currentTS,
          90,
        );
        paths.push({
          kind: "orbit",
          points: ring.map((p) => ({
            lat: p.latDeg,
            lng: p.lonDeg,
            alt: frame.satelliteAltitudeFraction,
          })),
        });
      }
    }

    if (overlays.edges) {
      for (const edge of frame.edges) {
        const a = frame.nodePositions.get(edge.aId);
        const b = frame.nodePositions.get(edge.bId);
        if (!a || !b || edge.onRoute) continue; // маршрут рисуем отдельным путём поверх
        paths.push({
          kind: "edge",
          points: [
            { lat: a.latDeg, lng: a.lonDeg, alt: a.altitudeFraction },
            { lat: b.latDeg, lng: b.lonDeg, alt: b.altitudeFraction },
          ],
        });
      }
    }

    if (overlays.route && frame.routeNodeIds.length > 1) {
      const points: PathPoint[] = [];
      for (const id of frame.routeNodeIds) {
        const pos = frame.nodePositions.get(id);
        if (pos)
          points.push({
            lat: pos.latDeg,
            lng: pos.lonDeg,
            alt: pos.altitudeFraction,
          });
      }
      if (points.length > 1) paths.push({ kind: "route", points });
    }

    instance
      .pathsData(paths)
      .pathPoints((d) => (d as PathDatum).points)
      .pathPointLat((p) => (p as PathPoint).lat)
      .pathPointLng((p) => (p as PathPoint).lng)
      .pathPointAlt((p) => (p as PathPoint).alt)
      .pathColor((d: object) => {
        const kind = (d as PathDatum).kind;
        if (kind === "route") return ACCENT;
        if (kind === "orbit") return ORBIT_LINE;
        return EDGE_DIM;
      })
      .pathStroke((d: object) =>
        (d as PathDatum).kind === "route"
          ? 1.3
          : (d as PathDatum).kind === "orbit"
            ? 0.4
            : 0.3,
      )
      .pathResolution(2);
  }, [
    frame,
    overlays.orbits,
    overlays.edges,
    overlays.route,
    scenario,
    currentTS,
  ]);

  return <div ref={containerRef} className="viewport-surface" />;
}
