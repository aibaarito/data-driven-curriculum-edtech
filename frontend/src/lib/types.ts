// Types mirror the FastAPI responses (backend/app/api/routes.py).

export type TopicStatus = "difficult" | "watch" | "ok" | "insufficient_data" | "no_outcome_data";
export type AssessmentKind = "pre" | "post" | "current";

export interface Meta {
  subjects: { id: number; name: string }[];
  grades: number[];
  classes: { id: number; name: string; grade: number }[];
  textbooks: { id: number; code: string; name: string; subject_id: number }[];
  date_from: string | null;
  date_to: string | null;
  synthetic: boolean;
  has_data: boolean;
}

export interface Overview {
  has_data: boolean;
  students: number;
  assessments: number;
  results: number;
  classes: number;
  topics: number;
  textbooks: number;
  average_mastery: number | null;
  date_from: string | null;
  date_to: string | null;
}

export interface AnalysisSettings {
  difficult_threshold: number;
  watch_threshold: number;
  target_mastery: number;
  min_students_topic: number;
  min_students_textbook: number;
  min_classes_textbook: number;
  max_change_pct: number;
}

export interface Gain {
  n_paired: number;
  pre_mean: number | null;
  post_mean: number | null;
  mean_gain: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_value: number | null;
  normalized_gain: number | null;
  significant: boolean;
  groups: string[];
}

export interface Bin {
  bin: string;
  from: number;
  to: number;
  count: number;
}

export interface TopicStat {
  topic_id: number;
  code: string;
  name: string;
  order: number;
  grade: number;
  mastery: number | null;
  mean: number | null;
  median: number | null;
  sd: number | null;
  ci_low: number | null;
  ci_high: number | null;
  student_count: number;
  assessment_count: number;
  result_count: number;
  distribution: Bin[];
  gain: Gain | null;
  status: TopicStatus;
  interpretation_code: string;
  interpretation: string;
  hours: number | null;
}

export interface TrendPoint {
  assessment: string;
  date: string;
  kind: AssessmentKind;
  mastery: number | null;
  students: number;
  topics: number;
}

export interface TopicTrendPoint {
  assessment_id: number;
  assessment: string;
  date: string;
  kind: AssessmentKind;
  topic_id: number;
  mastery: number | null;
  students: number;
}

export interface Opportunity {
  type: "difficult_topic" | "watch_topic" | "hours_review";
  topic_id: number;
  severity: "high" | "medium" | "low";
  text: string;
}

export interface Verdict {
  name_a: string;
  name_b: string;
  verdict: "insufficient_evidence" | "observed_difference";
  verdict_text: string;
}

export interface OverviewResponse {
  overview: Overview;
  settings: AnalysisSettings;
  synthetic: boolean;
  topics: Pick<TopicStat, "topic_id" | "code" | "name" | "mastery" | "student_count" | "status" | "hours">[];
  difficult_topics: TopicStat[];
  trend: TrendPoint[];
  textbooks: { textbook_id: number; name: string; students: number; classes: number; mean: number | null; baseline_mean: number | null }[];
  textbook_verdicts: Verdict[];
  opportunities: Opportunity[];
}

export interface TopicsResponse {
  topics: TopicStat[];
  trends: TopicTrendPoint[];
  settings: AnalysisSettings;
}

export interface TextbookSummary {
  textbook_id: number;
  code: string;
  name: string;
  students: number;
  classes: number;
  class_names: string[];
  grades: number[];
  outcome_students: number;
  mean: number | null;
  median: number | null;
  sd: number | null;
  ci_low: number | null;
  ci_high: number | null;
  distribution: Bin[];
  baseline_mean: number | null;
  baseline_students: number;
  mean_hours_per_class: number | null;
  mean_class_size: number | null;
  gain_mean: number | null;
  gain_ci_low: number | null;
  gain_ci_high: number | null;
  gain_students: number;
}

export interface Estimate {
  diff: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_value: number | null;
}

export interface TextbookPair extends Verdict {
  textbook_a: number;
  textbook_b: number;
  common_items: number;
  raw: (Estimate & { hedges_g: number | null; n_a: number; n_b: number }) | null;
  adjusted: (Estimate & { se?: number; n: number; clusters: number; df: number }) | null;
  baseline_diff: number | null;
  hours_diff: number | null;
  gain: { mean_a: number; mean_b: number; n_a: number; n_b: number; diff: number | null; ci_low: number | null;
    ci_high: number | null; p_value: number | null; method: string } | null;
  reasons: string[];
  confounders: string[];
}

export interface TextbooksResponse {
  textbooks: TextbookSummary[];
  pairs: TextbookPair[];
  topic_matrix: { topic_id: number; name: string; order: number; values: Record<string, { mastery: number; students: number }> }[];
  common_items: number;
  comparable: boolean;
  message: string | null;
  settings: AnalysisSettings;
}

export interface ValidationIssue {
  row: number | null;
  column: string | null;
  code: string;
  message: string;
}

export interface ImportPreview {
  batch_id: number;
  filename: string;
  ok: boolean;
  total_rows: number;
  valid_rows: number;
  error_count: number;
  warning_count: number;
  error_counts: Record<string, number>;
  warning_counts: Record<string, number>;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  summary: {
    students?: number;
    classes?: number;
    subjects?: string[];
    topics?: number;
    assessments?: number;
    textbooks?: string[];
    date_from?: string | null;
    date_to?: string | null;
    item_level?: boolean;
  };
  columns_found: string[];
  preview: Record<string, string | number | null>[];
}

export interface ImportBatch {
  id: number;
  filename: string;
  status: "preview" | "committed" | "discarded";
  created_at: string;
  total_rows: number;
  inserted_rows: number;
  error_count: number;
}

export interface OptimizerTopicInput {
  topic_id: number;
  code: string;
  name: string;
  current_hours: number;
  min_hours: number;
  max_hours: number;
  priority: number;
  prerequisites: number[];
  has_hours_data: boolean;
  mastery: number | null;
  student_count: number;
  status: TopicStatus;
  gain: number | null;
  gain_significant: boolean | null;
}

export interface OptimizerInputs {
  topics: OptimizerTopicInput[];
  total_hours: number;
  target_mastery: number;
  max_change_pct: number;
  min_students: number;
}

export interface ConstraintCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface OptimizerRow {
  topic_id: number;
  name: string;
  current_hours: number;
  proposed_hours: number;
  delta: number;
  min_hours: number;
  max_hours: number;
  priority: number;
  mastery: number | null;
  student_count: number;
  locked: boolean;
  need_score: number | null;
  gain: number | null;
  gain_significant: boolean | null;
  explanation: string;
}

export interface OptimizerResult {
  total_hours: number;
  current_total: number;
  proposed_total: number;
  rows: OptimizerRow[];
  constraints: ConstraintCheck[];
  warnings: string[];
  band_relaxed: boolean;
  method: string;
}

export interface OptimizerRun extends OptimizerResult {
  run_id: number;
  status: "proposed" | "accepted" | "rejected";
}

export interface RunListItem {
  run_id: number;
  status: "proposed" | "accepted" | "rejected";
  created_at: string;
  grade: number;
  subject_id: number;
  total_hours: number;
  changed_topics: number;
  result: OptimizerResult;
}

export interface Finding {
  title: string;
  text: string;
  kind: "observation" | "recommendation" | "limitation";
  metric_keys: string[];
}

export interface InsightsResponse {
  mode: "llm" | "deterministic";
  model: string | null;
  payload: { summary: string; findings: Finding[]; limitations: string[]; next_steps: string[] };
  facts: Record<string, number | string>;
  attempts: number;
  fallback_reason: string | null;
  optimizer_status: "proposed" | "accepted" | "rejected" | null;
}

export interface ReportListItem {
  id: number;
  title: string;
  created_at: string;
  filters: Record<string, unknown>;
  labels: Record<string, string> | null;
}

export interface Report extends Omit<ReportListItem, "labels"> {
  content: {
    filter_labels: Record<string, string>;
    synthetic: boolean;
    settings: AnalysisSettings;
    overview: Overview;
    topics: TopicStat[];
    textbooks: Omit<TextbooksResponse, "settings">;
    optimizer: OptimizerResult | null;
    optimizer_status: string | null;
    optimizer_status_label: string | null;
    insights: InsightsResponse | null;
    limitations: string[];
    trend: TrendPoint[];
  };
}

export interface SettingsResponse {
  analysis: AnalysisSettings;
  llm: { enabled: boolean; provider: string | null; model: string | null };
  limits: { max_upload_mb: number; max_upload_rows: number };
}
