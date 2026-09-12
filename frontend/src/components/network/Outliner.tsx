import { useMemo, useState } from "react";
import { ChevronDownIcon, OutlinerIcon, SatelliteDotIcon } from "../icons";
import { useWorkspace } from "../../store/workspace";
import type { SatelliteDesign } from "../../api/types";

// Сколько аппаратов плоскости показывать сразу — список плотный, дальше
// не молчаливая прокрутка, а явная строка «ещё N» (см. .tree .more).
const VISIBLE_SATS = 8;

export function Outliner() {
  const { scenario, selection, setSelection } = useWorkspace();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [fullyShown, setFullyShown] = useState<Set<string>>(new Set());
  const [initializedFor, setInitializedFor] = useState<string | null>(null);

  const planes = scenario?.design.planes ?? [];
  const satellitesByPlane = useMemo(() => {
    const map = new Map<string, SatelliteDesign[]>();
    if (!scenario) return map;
    for (const sat of scenario.design.satellites) {
      const list = map.get(sat.plane_id) ?? [];
      list.push(sat);
      map.set(sat.plane_id, list);
    }
    return map;
  }, [scenario]);

  // По умолчанию все плоскости развёрнуты — при смене сценария раскрываем заново.
  if (scenario && initializedFor !== scenario.meta.id) {
    setInitializedFor(scenario.meta.id);
    setExpanded(new Set(planes.map((p) => p.id)));
    setFullyShown(new Set());
  }

  const togglePlane = (planeId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(planeId)) next.delete(planeId);
      else next.add(planeId);
      return next;
    });
  };

  const showAllSats = (planeId: string) => {
    setFullyShown((prev) => new Set(prev).add(planeId));
  };

  return (
    <section className="sec">
      <h2>
        <OutlinerIcon />
        Состав группировки
      </h2>
      <div className="tree" role="tree" aria-label="Плоскости и аппараты">
        {planes.map((plane) => {
          const isExpanded = expanded.has(plane.id);
          const satellites = satellitesByPlane.get(plane.id) ?? [];
          return (
            <div key={plane.id} role="group">
              <button
                type="button"
                className="g"
                role="treeitem"
                aria-expanded={isExpanded}
                onClick={() => togglePlane(plane.id)}
              >
                <ChevronDownIcon className="chev" />
                {plane.id} · RAAN {plane.raan_deg}°
              </button>
              {isExpanded &&
                (() => {
                  const showAll =
                    fullyShown.has(plane.id) ||
                    satellites.length <= VISIBLE_SATS;
                  const visible = showAll
                    ? satellites
                    : satellites.slice(0, VISIBLE_SATS);
                  const hidden = satellites.length - visible.length;
                  return (
                    <>
                      {visible.map((sat) => (
                        <button
                          key={sat.id}
                          type="button"
                          className="i"
                          role="treeitem"
                          aria-selected={
                            selection?.kind === "satellite" &&
                            selection.satelliteId === sat.id
                          }
                          onClick={() =>
                            setSelection({
                              kind: "satellite",
                              satelliteId: sat.id,
                            })
                          }
                        >
                          <SatelliteDotIcon />
                          {sat.id}
                        </button>
                      ))}
                      {hidden > 0 && (
                        <button
                          type="button"
                          className="more"
                          onClick={() => showAllSats(plane.id)}
                        >
                          ещё {hidden}
                        </button>
                      )}
                    </>
                  );
                })()}
            </div>
          );
        })}
      </div>
    </section>
  );
}
