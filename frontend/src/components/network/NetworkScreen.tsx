import { useState } from "react";
import { useWorkspace } from "../../store/workspace";
import { useNetworkFrame } from "../../store/useNetworkFrame";
import { formatClock } from "../../lib/format";
import { ChevronDownIcon } from "../icons";
import { Globe3D } from "./Globe3D";
import { Polar2D } from "./Polar2D";
import { Timeline } from "./Timeline";
import { Outliner } from "./Outliner";
import { PropertiesPanel } from "./PropertiesPanel";
import { SummaryPanel } from "./SummaryPanel";
import { DEFAULT_OVERLAYS, OVERLAY_LABELS, type Overlays } from "./overlays";

export function NetworkScreen() {
  const {
    presetsError,
    variantError,
    networkError,
    runError,
    scenario,
    networkPacket,
    networkLoading,
    currentTS,
    viewMode,
    setViewMode,
    clientIds,
    focusClientId,
    setFocusClientId,
  } = useWorkspace();
  const frame = useNetworkFrame();
  const [overlays, setOverlays] = useState<Overlays>(DEFAULT_OVERLAYS);
  const [textureStatus, setTextureStatus] = useState<
    "loading" | "ok" | "error"
  >("loading");

  const fatalError = presetsError ?? variantError ?? networkError ?? runError;

  return (
    <div className="app">
      <div className="panels">
        <Outliner />
        <PropertiesPanel />
      </div>

      <div className="center">
        <div className="view">
          <div className="vtools">
            <div className="seg" role="group" aria-label="Вид проекции">
              <button
                type="button"
                aria-pressed={viewMode === "3d"}
                onClick={() => setViewMode("3d")}
              >
                3D
              </button>
              <button
                type="button"
                aria-pressed={viewMode === "2d"}
                onClick={() => setViewMode("2d")}
              >
                2D полярная
              </button>
            </div>
            {clientIds.length > 0 && (
              <label className="pick">
                <select
                  aria-label="Клиентский пункт для подсветки маршрута"
                  value={focusClientId ?? ""}
                  onChange={(event) => setFocusClientId(event.target.value)}
                  style={{
                    background: "transparent",
                    border: 0,
                    color: "inherit",
                    font: "inherit",
                  }}
                >
                  {clientIds.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
                <ChevronDownIcon />
              </label>
            )}
          </div>

          <div className="vtools r">
            <details>
              <summary
                className="pick"
                style={{ listStyle: "none", cursor: "pointer" }}
              >
                Оверлеи
                <ChevronDownIcon />
              </summary>
              <div
                style={{
                  marginTop: 6,
                  background: "var(--panel)",
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius)",
                  padding: "8px 10px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  minWidth: 190,
                }}
              >
                {(Object.keys(OVERLAY_LABELS) as Array<keyof Overlays>).map(
                  (key) => (
                    <label
                      key={key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 12,
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={overlays[key]}
                        onChange={(event) =>
                          setOverlays((prev) => ({
                            ...prev,
                            [key]: event.target.checked,
                          }))
                        }
                      />
                      {OVERLAY_LABELS[key]}
                    </label>
                  ),
                )}
              </div>
            </details>
          </div>

          {fatalError ? (
            <div className="load-state error">Ошибка: {fatalError}</div>
          ) : !scenario || networkLoading || !networkPacket ? (
            <div className="load-state">Загрузка сценария и пакета сети…</div>
          ) : viewMode === "3d" ? (
            <Globe3D overlays={overlays} onTextureStatus={setTextureStatus} />
          ) : (
            <Polar2D overlays={overlays} />
          )}

          {scenario && networkPacket ? (
            <div className="vfoot">
              <div>{formatClock(currentTS, true)} · сутки расчёта</div>
              {frame?.routeText ? <div>маршрут {frame.routeText}</div> : null}
            </div>
          ) : null}

          {viewMode === "3d" && textureStatus === "error" ? (
            <div className="view-note">
              Текстура Земли не загрузилась — показана затенённая сфера с сеткой
              параллелей и меридианов.
            </div>
          ) : null}
        </div>

        <Timeline />
      </div>

      <div className="right">
        <SummaryPanel frame={frame} />
      </div>
    </div>
  );
}
