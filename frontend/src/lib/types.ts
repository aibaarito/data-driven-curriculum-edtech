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

export type GainDirection = "increase" | "decline" | "inconclusive" | "insufficient";

export interface Gain {
  /** Optional only for older stored report snapshots; current API responses always include it. */
  direction?: GainDirection;
  ci_level: number;
  family_size: number;
  p_value_adjusted: number | null;
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
  class_mean: number | null;
  sd: number | null;
  ci_low: number | null;
  ci_high: number | null;
  student_count: number;
  class_count: number;
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
  /** Grades whose pupils sat this assessment (absent in report snapshots created before this field existed). */
  grades?: number[];
  comparison_group?: string | null;
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
  type: "difficult_topic" | "watch_topic" | "hours_review" | "decline";
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
  gain_class_mean: number | null;
  descriptive_note: string;
  gain_ci_low: number | null;
  gain_ci_high: number | null;
  gain_students: number;
}

export interface Estimate {
  diff: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_value: number | null;
  df?: number;
  se?: number;
  ci_level?: number;
  method?: string;
}

export interface TextbookPair extends Verdict {
  textbook_a: number;
  textbook_b: number;
  common_items: number;
  raw: (Estimate & { hedges_g: number | null; n_a: number; n_b: number; student_level_diff: number | null }) | null;
  adjusted: (Estimate & { n: number; n_classes: number; df: number }) | null;
  baseline_diff: number | null;
  hours_diff: number | null;
  gain: (Estimate & { mean_a: number; mean_b: number; n_a: number; n_b: number }) | null;
  inference_unit: "class";
  ci_level: number;
  pairs_in_family: number;
  classes_a: number;
  classes_b: number;
  excluded_small_classes: number;
  evidence_level: "insufficient" | "exploratory" | "observational";
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
  /** False when validation stopped at the table structure before individual records were checked. */
  records_validated?: boolean;
  /** Distinct source rows with at least one error. */
  rows_with_errors?: number;
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
  status: "preview" | "committed" | "discarded" | "expired";
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
  gain_direction: GainDirection | null;
  class_hours_mean: number | null;
  class_hours_min: number | null;
  class_hours_max: number | null;
  classes_with_hours: number;
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
  gain_direction: GainDirection | null;
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
  relaxed_policies: string[];
  policy_checks: { policy: string; name: string; status: "applied" | "relaxed"; affected_topics: string[] }[];
  plan_scope: "grade";
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
  entity?: string;
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
  /** not_configured | rejected | provider_error; null for model output (absent from older stored reports). */
  fallback_kind?: "not_configured" | "rejected" | "provider_error" | null;
  /** Technical detail (exception class) for support; never shown as the primary message. */
  fallback_detail?: string | null;
  optimizer_status: "proposed" | "accepted" | "rejected" | null;
}

export interface ReportListItem {
  id: number;
  title: string;
  created_at: string;
  filters: Record<string, unknown>;
  labels: Record<string, string> | null;
}

export interface DiscussionPoint {
  kind: "observation" | "recommendation" | "limitation";
  text: string;
  topic_id?: string;
}

export interface Report extends Omit<ReportListItem, "labels"> {
  /** Derived by the server from the stored snapshot only. */
  discussion?: DiscussionPoint[];
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
    optimizer_scope_note: string | null;
    insights: InsightsResponse | null;
    limitations: string[];
    trend: TrendPoint[];
  };
}

export interface SettingsResponse {
  analysis: AnalysisSettings;
  notices: string[];
  llm: { enabled: boolean; provider: string | null; model: string | null };
  limits: { max_upload_mb: number; max_upload_rows: number; preview_ttl_minutes: number };
  access: { mode: "token" | "local_only"; reset_enabled: boolean };
}

// ----------------------------------------------------------------------------- guided import

export interface ImportFieldInfo {
  field: string;
  label: string;
  description: string;
  required: boolean;
  shared_allowed: boolean;
  none_allowed: boolean;
  wide_result?: boolean;
  wide_per_column?: boolean;
}

export interface SheetSummary {
  name: string;
  hidden: boolean;
  empty: boolean;
  non_empty_rows: number;
  columns: number;
  problem: string | null;
  known_headers: number;
}

export interface ColumnProfile {
  numeric: number;
  percent_text: number;
  date: number;
  distinct: string[];
  distinct_count: number;
  binary?: boolean;
  integers?: boolean;
  min: number | null;
  max: number | null;
}

export interface SourceColumn {
  id: string;
  letter: string;
  header: string;
  label: string;
  group?: string;
  sub?: string;
  samples: string[];
  empty: boolean;
  profile?: ColumnProfile;
}

export interface LayoutNotice {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  rows?: number[];
}

export type Layout = "long" | "wide" | "aggregate" | "general";

export interface RegionSelection {
  header_row: number;
  header_rows: 1 | 2;
  first_col: number;
  last_col: number | null;
  last_row: number | null;
  exclude: string[];
}

export interface WideSuggestionColumn { column: string; topic_name: string; item_hint: string }

export interface SheetInspection {
  sheet: string;
  hidden: boolean;
  problem: string | null;
  width: number;
  header_suggestion: { row: number | null; confidence: "high" | "low" | "none"; reason: string; header_rows?: number };
  preview: { row: number; cells: string[] }[];
  header_rows_allowed: number[];
  header_row: number | null;
  selection?: RegionSelection | null;
  all_columns?: { index: number; letter: string }[];
  columns: SourceColumn[];
  suggestions: {
    suggested: Record<string, { column: string; confidence: "exact" | "alias" }>;
    ambiguous: Record<string, { column: string; reason: string }[]>;
  };
  notices: LayoutNotice[];
  duplicate_headers: { header: string; letters: string[] }[];
  empty_header_columns?: string[];
  flags?: { row: number; kind: string; label: string }[];
  flag_counts?: Record<string, number>;
  layout_suggestion?: { layout: Layout; confidence: string; reason: string } | null;
  wide_suggestion?: { identity: Record<string, { column: string }>; result_columns: WideSuggestionColumn[]; total_columns: WideSuggestionColumn[] } | null;
  aggregate_suggestion?: Record<string, string>;
  type_suggestion?: Record<string, string>;
  data_rows?: number;
  last_data_row?: number | null;
}

export interface CsvInfo {
  encoding: string;
  encoding_confidence: string;
  delimiter: string;
  delimiter_label: string;
  delimiter_confidence: string;
  delimiter_alternatives: { value: string; label: string }[];
}

export interface ImportCatalog {
  layouts: { value: Layout; label: string }[];
  aggregate_roles: { value: string; label: string }[];
  types: { value: string; label: string }[];
  flags: { value: string; label: string }[];
  date_formats: string[];
  encodings: string[];
  delimiters: { value: string; label: string }[];
}

export interface ImportSource {
  batch_id: number;
  session_key: string;
  filename: string;
  kind: "csv" | "xlsx";
  expires_at: string;
  sheets: SheetSummary[];
  csv_info?: CsvInfo | null;
  sheet_suggestion: { name: string | null; reason: string };
  inspection: SheetInspection | null;
  auto_ready: boolean;
  fields: ImportFieldInfo[];
  catalog?: ImportCatalog;
  limits: { max_upload_mb: number; max_rows: number; max_columns: number; max_sheets: number; header_scan_rows: number; preview_ttl_minutes: number; max_dataset_rows?: number };
}

export type FieldChoice =
  | { source: "column"; column: string }
  | { source: "value"; value: string }
  | { source: "none" };

export interface ConfigIssue {
  code: string;
  message: string;
  field: string | null;
  column: string | null;
}

export interface Capability {
  key: string;
  title: string;
  available: boolean;
  partial: boolean;
  level: string;
  missing: string[];
  limitations: string[];
  link: string | null;
}

export interface ImportCounts {
  source_rows: number;
  excluded_rows: number;
  excluded_by_kind?: Record<string, number>;
  excluded_row_numbers?: number[];
  records: number;
  valid_records: number;
  invalid_records: number;
  cross_record_errors: number;
  existing_duplicates: number;
  eligible: number;
  missing_results?: number;
  empty_result_cells?: number;
  result_columns?: number;
  wide_explanation?: string;
}

export interface ImportConfigSummary {
  sheet: string;
  sheet_hidden: boolean;
  header_row: number;
  header_rows?: number;
  range?: { first_col: string; last_col: string | null; last_row: number | null };
  excluded_kinds?: string[];
  layout?: Layout;
  layout_label?: string;
  kind?: "assessment" | "dataset";
  csv?: { encoding?: string; delimiter?: string };
  mapped: { field: string; label: string; column: string; letter: string; header: string }[];
  shared: { field: string; label: string; value: string }[];
  not_in_file: { field: string; label: string }[];
  result_columns?: ({ letter: string; header: string } & Record<string, string>)[];
  roles?: { letter: string; header: string; role: string; role_label: string }[];
  metric?: Record<string, string>;
  types?: { letter: string; header: string; type: string; type_label: string }[];
  dataset_name?: string;
  rules?: string[];
  ignored_columns: string[];
}

export interface GuidedValidation extends ImportPreview {
  config_hash: string;
  config: ImportConfigSummary;
  expires_at: string;
  counts?: ImportCounts;
  capabilities?: Capability[];
  capabilities_scope?: "file" | "dataset";
}

export interface DatasetColumn { id: string; letter: string; label: string; type?: string; role?: string | null }

export interface DatasetMeta {
  id: number;
  kind: "general" | "aggregate";
  name: string;
  source_filename: string;
  sheet: string;
  created_at: string;
  row_count: number;
  columns: DatasetColumn[];
  metric: Record<string, string> | null;
}

export interface ColumnSummary {
  id: string;
  letter: string;
  label: string;
  type: string;
  missing: number;
  missing_pct: number;
  distinct: number;
  mismatched?: number;
  numeric?: { count: number; mean: number; median: number; min: number; max: number; sd: number | null };
  histogram?: { from: number; to: number; count: number }[];
  date_range?: { from: string; to: string };
  frequencies?: { value: string; count: number }[];
  other_count?: number;
  avg_length?: number | null;
}

export interface AggregateGroup {
  group: string;
  rows: number;
  mean_of_groups_pct: number;
  min_pct: number;
  max_pct: number;
  weighted_pct: number | null;
  students_total: number | null;
}

export interface DatasetDetail extends DatasetMeta {
  profile: { rows: number; columns: number; duplicate_rows: number; column_profiles: ColumnSummary[] };
  capabilities: Capability[];
  aggregate?: { by_topic: AggregateGroup[]; by_class: AggregateGroup[]; by_textbook: AggregateGroup[]; records: number; note: string };
}

export interface DatasetRowsPage { total: number; page: number; page_size: number; rows: { source_row: number; values: string[] }[] }
