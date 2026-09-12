import type {
  CompareRequest,
  CompareResult,
  Preset,
  Project,
  ProjectSummary,
  RunRequest,
  RunResult,
  Scenario,
  SelfTestResult,
  Snapshot,
  ValidationReport,
  Variant,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`Запрос к API завершился ошибкой ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // тело не JSON — оставляем null
    }
    throw new ApiError(response.status, body);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function requestBinary(path: string): Promise<ArrayBuffer> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new ApiError(response.status, null);
  }
  return response.arrayBuffer();
}

export const api = {
  getPresets: () => request<Preset[]>("/presets"),

  validateScenario: (scenario: Scenario) =>
    request<ValidationReport>("/scenarios/validate", {
      method: "POST",
      body: JSON.stringify({ scenario }),
    }),

  createProject: (title: string, scenario: Scenario) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ title, scenario }),
    }),

  listProjects: () => request<ProjectSummary[]>("/projects"),

  getProject: (id: string) => request<Project>(`/projects/${id}`),

  createVariant: (projectId: string, title: string, scenario: Scenario) =>
    request<Variant>(`/projects/${projectId}/variants`, {
      method: "POST",
      body: JSON.stringify({ title, scenario }),
    }),

  getVariant: (id: string) => request<Variant>(`/variants/${id}`),

  patchVariant: (id: string, patch: { title?: string; scenario?: Scenario }) =>
    request<Variant>(`/variants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  runVariant: (id: string, payload: RunRequest = {}) =>
    request<RunResult>(`/variants/${id}/run`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getVariantNetwork: (id: string) => requestBinary(`/variants/${id}/network`),

  getVariantSnapshot: (id: string, tS: number) =>
    request<Snapshot>(
      `/variants/${id}/snapshot?t_s=${encodeURIComponent(String(tS))}`,
    ),

  exportVariant: (id: string, strategy?: string) =>
    request<unknown>(
      `/variants/${id}/export${strategy ? `?strategy=${strategy}` : ""}`,
    ),

  compare: (payload: CompareRequest) =>
    request<CompareResult>("/compare", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  selftest: () => request<SelfTestResult>("/selftest"),
};
