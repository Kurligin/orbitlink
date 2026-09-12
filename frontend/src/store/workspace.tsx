import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import { parseNetworkPacket, type NetworkPacket } from "../api/networkPacket";
import type {
  Preset,
  RouteRecord,
  RoutingStrategy,
  RunResult,
  Scenario,
} from "../api/types";

export function routeKey(clientId: string, tS: number): string {
  return `${clientId}|${tS}`;
}

export type ViewMode = "3d" | "2d";

export type Selection =
  | { kind: "plane"; planeId: string }
  | { kind: "satellite"; satelliteId: string }
  | null;

/**
 * Сценарий, добавленный пользователем в этой сессии (правка панели параметров
 * или загрузка файла) — не приходит с бэкенда как пресет, но живёт в том же
 * едином списке (см. `presets` в WorkspaceState), поэтому экраны «Сеть» и
 * «Сравнение» работают с ним без специального кода.
 */
export interface UserScenarioEntry {
  scenario: Scenario;
  /**
   * meta.id сценария, из которого этот получен правкой («Пересчитать как
   * вариант») — используется экраном «Сравнение» для сравнения по умолчанию.
   * `null` для сценариев, загруженных из файла — у них нет «предыдущего».
   */
  originId: string | null;
}

interface WorkspaceState {
  /** Пресеты с бэкенда + пользовательские сценарии этой сессии — единый список. */
  presets: Preset[] | null;
  presetsError: string | null;
  userScenarios: UserScenarioEntry[];
  /** Добавляет сценарий в список пользовательских и делает его текущим. */
  addUserScenario: (scenario: Scenario, originId: string | null) => void;

  currentPresetId: string | null;
  scenario: Scenario | null;
  setCurrentPresetId: (id: string) => void;

  variantId: string | null;
  variantError: string | null;

  strategy: RoutingStrategy;
  setStrategy: (strategy: RoutingStrategy) => void;

  networkPacket: NetworkPacket | null;
  networkLoading: boolean;
  networkError: string | null;

  runResult: RunResult | null;
  runLoading: boolean;
  runError: string | null;
  routeIndex: Map<string, RouteRecord>;
  clientIds: string[];

  stepIndex: number;
  setStepIndex: (index: number) => void;
  playing: boolean;
  setPlaying: (playing: boolean) => void;
  currentTS: number;

  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;

  selection: Selection;
  setSelection: (selection: Selection) => void;

  focusClientId: string | null;
  setFocusClientId: (id: string | null) => void;

  /**
   * Возвращает id варианта под сценарий (создавая проект-обёртку при первом
   * обращении, дальше — из кэша). Нужен экранам, которым требуется вариант
   * не только под ТЕКУЩИЙ выбранный сценарий (например «Сравнение» — там
   * оба сравниваемых варианта берутся по своим пресетам).
   */
  ensureVariantId: (scenario: Scenario) => Promise<string>;
}

const WorkspaceContext = createContext<WorkspaceState | null>(null);

const PLAYBACK_INTERVAL_MS = 220;

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [apiPresets, setApiPresets] = useState<Preset[] | null>(null);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [userScenarios, setUserScenarios] = useState<UserScenarioEntry[]>([]);
  const [currentPresetId, setCurrentPresetIdState] = useState<string | null>(
    null,
  );

  const [variantId, setVariantId] = useState<string | null>(null);
  const [variantError, setVariantError] = useState<string | null>(null);
  // Кэш ПРОМИСОВ (не готовых id): под StrictMode эффект монтируется дважды
  // подряд (mount -> cleanup -> mount) ещё до того, как первый запрос
  // успевает ответить, — кэш только готовых значений не спас бы от двойного
  // POST /api/projects. Второй проход находит уже начатый промис и ждёт его.
  const variantCache = useRef(new Map<string, Promise<string>>());

  const [strategy, setStrategy] = useState<RoutingStrategy>("min_latency");

  const [networkPacket, setNetworkPacket] = useState<NetworkPacket | null>(
    null,
  );
  const [networkLoading, setNetworkLoading] = useState(false);
  const [networkError, setNetworkError] = useState<string | null>(null);

  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  const [viewMode, setViewMode] = useState<ViewMode>("3d");
  const [selection, setSelection] = useState<Selection>(null);
  const [focusClientId, setFocusClientId] = useState<string | null>(null);

  // Загрузка поставленных сценариев при старте приложения.
  useEffect(() => {
    let cancelled = false;
    api
      .getPresets()
      .then((items) => {
        if (cancelled) return;
        setApiPresets(items);
        if (items.length > 0) {
          setCurrentPresetIdState(items[0]!.id);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPresetsError(
          error instanceof Error
            ? error.message
            : "Не удалось загрузить сценарии",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Единый список для потребителей (выбор сценария в правой колонке, экран
  // «Сравнение»): пресеты с бэкенда + пользовательские сценарии этой сессии
  // (правки панели параметров, загруженные файлы). Пользовательский сценарий
  // не отличается для остального приложения ничем, кроме происхождения id —
  // пакет сети, прогон и дифф параметров заводятся под него как под любой
  // другой пресет, через `ensureVariantId` по `scenario.meta.id`.
  const presets = useMemo<Preset[] | null>(() => {
    if (!apiPresets) return null;
    if (userScenarios.length === 0) return apiPresets;
    const extra: Preset[] = userScenarios.map((entry) => ({
      id: entry.scenario.meta.id,
      title: entry.scenario.meta.title,
      scenario: entry.scenario,
    }));
    return [...apiPresets, ...extra];
  }, [apiPresets, userScenarios]);

  const scenario = useMemo<Scenario | null>(() => {
    if (!presets || !currentPresetId) return null;
    return presets.find((p) => p.id === currentPresetId)?.scenario ?? null;
  }, [presets, currentPresetId]);

  const clientIds = useMemo<string[]>(
    () =>
      scenario
        ? scenario.ground_sites
            .filter((s) => s.role === "client")
            .map((s) => s.id)
        : [],
    [scenario],
  );

  const routeIndex = useMemo<Map<string, RouteRecord>>(() => {
    const index = new Map<string, RouteRecord>();
    if (!runResult) return index;
    for (const record of runResult.routes) {
      index.set(routeKey(record.client_id, record.t_s), record);
    }
    return index;
  }, [runResult]);

  // Автовыбор клиентского пункта для подсветки маршрута при смене сценария.
  useEffect(() => {
    if (clientIds.length === 0) {
      setFocusClientId(null);
      return;
    }
    setFocusClientId((prev) =>
      prev && clientIds.includes(prev) ? prev : clientIds[0]!,
    );
  }, [clientIds]);

  // Заводит (или переиспользует из кэша) проект-обёртку под сценарий и
  // возвращает id его базового варианта. Кэш общий на все вызовы — под
  // StrictMode эффект монтируется дважды подряд (mount -> cleanup -> mount)
  // ещё до того, как первый запрос успевает ответить, поэтому кэшируем сам
  // ПРОМИС, а не только готовое значение: второй проход находит уже
  // начатый промис и ждёт его вместо повторного POST /api/projects.
  const ensureVariantId = useCallback(
    (forScenario: Scenario): Promise<string> => {
      let pending = variantCache.current.get(forScenario.meta.id);
      if (!pending) {
        pending = api
          .createProject(forScenario.meta.title, forScenario)
          .then((project) => {
            const base = project.variants[0];
            if (!base) throw new Error("Проект создан без базового варианта");
            return base.id;
          });
        variantCache.current.set(forScenario.meta.id, pending);
        // Не запоминаем провалившуюся попытку — следующий вызов должен иметь
        // возможность попробовать заново, а не повторять ту же ошибку вечно.
        pending.catch(() => {
          if (variantCache.current.get(forScenario.meta.id) === pending) {
            variantCache.current.delete(forScenario.meta.id);
          }
        });
      }
      return pending;
    },
    [],
  );

  // На выбранный сценарий заводим вариант — нужен, чтобы получить бинарный
  // пакет сети и прогон маршрутов для экрана «Сеть».
  useEffect(() => {
    if (!scenario) return;
    let cancelled = false;
    setVariantError(null);
    ensureVariantId(scenario)
      .then((id) => {
        if (!cancelled) setVariantId(id);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setVariantError(
            error instanceof Error
              ? error.message
              : "Не удалось создать проект",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [scenario, ensureVariantId]);

  // Бинарный пакет сети — один раз на вариант, дальше время листается локально.
  useEffect(() => {
    if (!variantId) return;
    let cancelled = false;
    setNetworkLoading(true);
    setNetworkError(null);
    api
      .getVariantNetwork(variantId)
      .then((buffer) => {
        if (cancelled) return;
        setNetworkPacket(parseNetworkPacket(buffer));
        setStepIndex(0);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setNetworkError(
          error instanceof Error
            ? error.message
            : "Не удалось загрузить пакет сети",
        );
      })
      .finally(() => {
        if (!cancelled) setNetworkLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [variantId]);

  // Прогон маршрутизации — при смене варианта или стратегии.
  useEffect(() => {
    if (!variantId) return;
    let cancelled = false;
    setRunLoading(true);
    setRunError(null);
    api
      .runVariant(variantId, { strategy })
      .then((result) => {
        if (cancelled) return;
        setRunResult(result);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setRunError(
          error instanceof Error ? error.message : "Не удалось прогнать расчёт",
        );
      })
      .finally(() => {
        if (!cancelled) setRunLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [variantId, strategy]);

  // Воспроизведение таймлайна — локальная перемотка индекса отсчёта.
  useEffect(() => {
    if (!playing || !networkPacket || networkPacket.steps === 0) return;
    const id = window.setInterval(() => {
      setStepIndex((prev) => (prev + 1) % networkPacket.steps);
    }, PLAYBACK_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, networkPacket]);

  const setCurrentPresetId = useCallback((id: string) => {
    setCurrentPresetIdState(id);
    setSelection(null);
    setFocusClientId(null);
    setPlaying(false);
  }, []);

  // Кладёт сценарий (правку или загруженный файл) в список пользовательских
  // и делает его текущим — дальше вариант, пакет сети и прогон заводятся сами
  // через уже существующие эффекты выше, ровно как для любого пресета.
  const addUserScenario = useCallback(
    (newScenario: Scenario, originId: string | null) => {
      setUserScenarios((prev) => [
        ...prev,
        { scenario: newScenario, originId },
      ]);
      setCurrentPresetId(newScenario.meta.id);
    },
    [setCurrentPresetId],
  );

  const currentTS =
    networkPacket?.times[stepIndex] ??
    stepIndex * (scenario?.environment.step_s ?? 0);

  const value: WorkspaceState = {
    presets,
    presetsError,
    userScenarios,
    addUserScenario,
    currentPresetId,
    scenario,
    setCurrentPresetId,
    variantId,
    variantError,
    strategy,
    setStrategy,
    networkPacket,
    networkLoading,
    networkError,
    runResult,
    runLoading,
    runError,
    routeIndex,
    clientIds,
    stepIndex,
    setStepIndex,
    playing,
    setPlaying,
    currentTS,
    viewMode,
    setViewMode,
    selection,
    setSelection,
    focusClientId,
    setFocusClientId,
    ensureVariantId,
  };

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceState {
  const ctx = useContext(WorkspaceContext);
  if (!ctx)
    throw new Error("useWorkspace должен вызываться внутри WorkspaceProvider");
  return ctx;
}
