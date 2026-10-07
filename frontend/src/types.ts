// 백엔드 app/api/schemas.py · app/domain/results.py 와 같은 계약
import type { FeatureCollection, MultiPolygon } from "geojson";

export type MetricValue = number | null;

export interface RankingItem {
  rank: number;
  unit_key: string;
  unit_name: string;
  parent_name: string | null;
  value: number;
  values: Record<string, MetricValue>;
}

export interface UnitProperties {
  unit_key: string;
  unit_name: string;
  parent_name: string | null;
  null_reason: string | null;
  [metric: string]: MetricValue | string | null;
}

export interface MapLayer {
  type: "choropleth";
  metric: string;
  metric_label: string;
  crs: string;
  classification: { method: "quantile"; class_count: number; breaks: number[]; min: number | null; max: number | null };
  feature_count: number;
  null_count: number;
  geojson: FeatureCollection<MultiPolygon, UnitProperties>;
}

export interface DatasetUsage {
  dataset_id: string;
  title: string;
  provider: string;
  source: string;
  license: string | null;
  reference_date: string | null;
}

export interface FinalResponse {
  run_id: string;
  result_id: string;
  question: string;
  summary: string;
  metric: { name: string; label: string; interpretation: string };
  metric_labels: Record<string, string>;
  rank_metric: string | null;
  ranking: RankingItem[];
  map_layer: MapLayer;
  analysis_method: string[];
  datasets: DatasetUsage[];
  assumptions: string[];
  limitations: string[];
}

export interface ValidationIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
  path: string | null;
}

export interface WorkflowError {
  step: string | null;
  code: string;
  message: string;
  issues: ValidationIssue[];
}

export interface AnalysisResponse {
  run_id: string;
  status: "running" | "succeeded" | "failed";
  result: FinalResponse | null;
  errors: WorkflowError[];
}
