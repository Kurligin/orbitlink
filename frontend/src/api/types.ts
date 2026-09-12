/**
 * Типы контракта бэкенда OrbitLink (схема сценария cosmo-A-1.0 и ответы API).
 * Список полей и форм — по спеке задачи; при расхождении с реальным
 * бэкендом типы стоит свести через `npx tsc --noEmit` + ручную проверку.
 */

export interface OrbitPlane {
  id: string;
  raan_deg: number;
  phase_deg: number;
}

export interface SatelliteDesign {
  id: string;
  plane_id: string;
  slot_deg: number;
  launch_batch: number;
}

export interface GroundSite {
  id: string;
  name: string;
  role: "gateway" | "client";
  lat_deg: number;
  lon_deg: number;
}

export interface SatelliteFailure {
  satellite_id: string;
  start_s: number;
  end_s: number;
}

export interface GatewayOutage {
  gateway_id: string;
  start_s: number;
  end_s: number;
}

export interface ScenarioEnvironment {
  altitude_km: number;
  inclination_deg: number;
  earth_angle0_deg: number;
  horizon_s: number;
  step_s: number;
  min_elevation_deg: number;
  isl_range_km: number;
  target_availability: number;
}

export interface ScenarioDesign {
  launch_stage: number;
  planes: OrbitPlane[];
  satellites: SatelliteDesign[];
}

export interface ScenarioMeta {
  id: string;
  title: string;
}

export interface Scenario {
  schema_version: string;
  meta: ScenarioMeta;
  environment: ScenarioEnvironment;
  design: ScenarioDesign;
  ground_sites: GroundSite[];
  failures: SatelliteFailure[];
  gateway_outages: GatewayOutage[];
}

export interface Preset {
  id: string;
  title: string;
  scenario: Scenario;
}

export interface ValidationIssue {
  path: string;
  message: string;
}

export interface ValidationReport {
  ok: boolean;
  issues: ValidationIssue[];
}

export interface ScenarioChange {
  path: string;
  before: unknown;
  after: unknown;
  label: string;
}

export interface Variant {
  id: string;
  project_id: string;
  title: string;
  scenario: Scenario;
  changes: ScenarioChange[];
}

export interface Project {
  id: string;
  title: string;
  base_scenario?: Scenario;
  variants: Variant[];
}

export interface ProjectSummary {
  id: string;
  title: string;
  variant_count: number;
}

export type RoutingStrategy =
  "min_hops" | "min_latency" | "load_aware" | "robust";

export interface RunRequest {
  strategy?: RoutingStrategy;
  hysteresis?: number;
  with_backup?: boolean;
}

export interface ClientMetrics {
  client_id: string;
  steps: number;
  step_s: number;
  visibility_fraction: number;
  availability_fraction: number;
  max_gap_s: number;
  gap_count: number;
  leading_gap_s: number;
  trailing_gap_s: number;
  mean_hops: number;
  mean_latency_ms: number;
  backup_fraction: number;
  reroute_count: number;
  path_change_count: number;
  mean_route_lifetime_s: number;
  reason_counts: Record<string, number>;
  margin_levels: number[];
  target_met: boolean;
}

export interface RouteRecord {
  t_s: number;
  client_id: string;
  path: string[];
  event: string;
  reason: string | null;
  hops: number;
  latency_ms: number;
  has_backup: boolean;
}

export interface RunResult {
  strategy: RoutingStrategy;
  times: number[];
  clients: Record<string, ClientMetrics>;
  routes: RouteRecord[];
  cached: boolean;
}

export interface CompareClientDelta {
  availability_before: number | null;
  availability_after: number | null;
  availability_delta: number | null;
  max_gap_s_before: number | null;
  max_gap_s_after: number | null;
  max_gap_s_delta: number | null;
}

export interface CompareRequest {
  base_variant_id: string;
  variant_id: string;
  strategy?: RoutingStrategy;
  hysteresis?: number;
  with_backup?: boolean;
}

export interface CompareResult {
  base_variant_id: string;
  variant_id: string;
  strategy: RoutingStrategy;
  clients: Record<string, CompareClientDelta>;
  changes: ScenarioChange[];
}

export interface SelfTestCheck {
  scenario: string;
  t_s: number;
  max_position_error_km: number;
  edges_match: boolean;
  our_edge_count: number;
  reference_edge_count: number;
  max_elevation_error_deg: number;
}

export interface SelfTestResult {
  ok: boolean;
  checks: SelfTestCheck[];
  reference: string;
}

export interface SnapshotSatellite {
  id: string;
  x_km: number;
  y_km: number;
  z_km: number;
  active: boolean;
}

export interface Snapshot {
  t_s: number;
  satellites: SnapshotSatellite[];
  edges: [string, string, number][];
  elevation_deg: Record<string, Record<string, number>>;
}
