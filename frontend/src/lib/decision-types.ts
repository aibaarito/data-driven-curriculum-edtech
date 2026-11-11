// Types of the decision-intelligence API (backend/app/api/decision_routes.py).
import type { TopicStatus } from "./types";

export type EvidenceCategory = "supported" | "exploratory" | "insufficient" | "incomparable" | "stale";

export interface EvidenceAssessment {
  category: EvidenceCategory;
  label: string;
  hint?: string;
  reasons: string[];
  allows_action: boolean;
  dimensions?: Record<string, unknown>;
}

export interface Revision {
  hash: string;
  results: number;
  students: number;
  assessments: number;
  topics: number;
  prerequisites: number;
  hours_records: number;
}

export interface AnalysisContext {
  fingerprint: string;
  revision: Revision;
  scope: Record<string, unknown>;
  algorithm_version: string;
  synthetic: boolean;
  generated_at: string;
}

export interface Passport {
  subject_kind: "topic" | "textbook_pair";
  subject_id: number | string;
  title: string;
  observation: string[];
  interpretation: string | null;
  statistics: Record<string, unknown>;
  method: string;
  dataset: { fingerprint: string; revision: Revision; scope: Record<string, unknown>; algorithm_version: string; synthetic: boolean };
  sample: { students?: number | null; classes?: number | null; paired?: number | null };
  uncertainty: string[];
  gate: EvidenceAssessment;
  strengthen: string[];
  limitations: string[];
  winner_allowed?: boolean;
  graph?: { prerequisites: number[]; dependents: number[]; downstream_count: number; weak_downstream: number[]; foundational_gap: boolean; priority: Priority };
  decision?: { id: string; action: ActionRef; problem: { code: string; label: string }; required_review: string };
}

export interface ActionRef {
  code: string;
  label: string;
}

export interface Priority {
  score: number;
  components: Partial<Record<"gap" | "curriculum" | "dependency" | "evidence", number>>;
  formula?: string;
}

export interface DecisionCandidate {
  id: string;
  kind: "topic" | "textbook";
  topic_id?: number;
  topic_code?: string;
  topic_name: string | null;
  title?: string;
  status?: TopicStatus;
  problem: { code: string; label: string; severity: number };
  evidence: EvidenceAssessment;
  action: ActionRef;
  secondary_actions: ActionRef[];
  rejected_alternatives: (ActionRef & { reason: string })[];
  observations: string[];
  interpretation: string | null;
  hypothesis: string | null;
  limitations: string[];
  required_review: string;
  constraint_impact: {
    balanced_delta: number | null;
    balanced_proposed: number | null;
    current_hours: number | null;
    explanation: string | null;
    sensitivity: { minus_2h: number | null; plus_2h: number | null } | null;
  } | null;
  priority: Priority;
  why_topic: string[];
  related_topics: { weak_prerequisites?: { topic_id: number; name: string }[]; weak_dependents?: { topic_id: number; name: string }[] };
}

export interface RunSummary {
  run_id: number;
  status: "proposed" | "accepted" | "rejected";
  created_at: string;
  grade: number;
  subject_id: number;
  total_hours: number;
  scenario_key: string | null;
  changed_topics: number;
  decided_at: string | null;
  review_note: string | null;
  evidence_status: "current" | "stale" | "unknown";
}

export type InterventionStatus = "planned" | "implemented" | "awaiting_outcome" | "evaluated" | "cancelled";

export interface EvaluationTopic {
  topic_id: number;
  name: string;
  frozen_mastery: number | null;
  recomputed_before: number | null;
  after: number | null;
  descriptive_change: number | null;
  students_before: number;
  students_after: number;
  paired_students: number;
  lost_to_follow_up: number | null;
  new_students: number | null;
  baseline_consistent: boolean;
  paired: { mean_gain: number; ci_low: number | null; ci_high: number | null; ci_level: number; p_value_adjusted: number | null; n_paired: number } | null;
  direction: string;
}

export interface Intervention {
  id: number;
  run_id: number;
  status: InterventionStatus;
  status_label: string;
  description: string;
  reviewer: string | null;
  planned_on: string | null;
  implemented_on: string | null;
  synthetic: boolean;
  allowed_transitions: InterventionStatus[];
  baseline: {
    fingerprint: string;
    captured_at: string;
    topics: { topic_id: number; name: string; mastery: number | null; status: string | null }[];
    hour_changes: { topic_id: number; name: string; from: number; to: number; delta: number }[];
  };
  evaluation: {
    ready: boolean;
    ci_level: number;
    comparison_group: null;
    topics: EvaluationTopic[];
    statements: Record<string, string>;
    evaluated_at: string;
    synthetic: boolean;
  } | null;
  baseline_status: "current" | "superseded" | null;
}

export interface GraphNode {
  topic_id: number;
  code: string;
  name: string;
  grade: number;
  order: number;
  curriculum_priority: number;
  in_scope: boolean;
  depth: number;
  mastery: number | null;
  student_count: number;
  status: TopicStatus;
  gain_direction: string | null;
  hours: number | null;
  evidence: EvidenceAssessment;
  prerequisites: number[];
  dependents: number[];
  ancestors: number[];
  descendants: number[];
  downstream_count: number;
  weak_downstream: number[];
  foundational_gap: boolean;
  priority: Priority;
  why: string[];
}

export interface GraphEdge {
  id: number | null;
  prerequisite_id: number;
  topic_id: number;
  origin: "import" | "expert" | "suggested";
  review_status: "approved" | "pending" | "rejected";
  weak_link: boolean;
}

export interface CurriculumGraph {
  context: AnalysisContext;
  nodes: GraphNode[];
  edges: GraphEdge[];
  valid: boolean;
  issues: { code: string; message: string }[];
  ranking: { topic_id: number; name: string; score: number; foundational_gap: boolean }[];
  chains: { path: number[]; names: string[]; weak: number[]; weak_count: number }[];
  foundational_gaps: number[];
  layers: number;
  heuristic: { formula: string; note: string };
}

export interface DecisionOverview {
  context: AnalysisContext;
  readiness: Record<EvidenceCategory, number>;
  candidates: DecisionCandidate[];
  actionable: number;
  graph: {
    valid: boolean;
    issues: { code: string; message: string }[];
    foundational_gaps: { topic_id: number; name: string }[];
    chains: CurriculumGraph["chains"];
    ranking: CurriculumGraph["ranking"];
  };
  plan: { available: boolean; total_hours?: number; constraints_ok?: boolean; reason?: unknown; sensitivity_notes?: string[] };
  pending_approvals: RunSummary[];
  approved: RunSummary[];
  rejected: RunSummary[];
  interventions: Intervention[];
}

export type ScenarioKey = "conservative" | "balanced" | "gap_focused";

export interface ScenarioRow {
  topic_id: number;
  name: string;
  current_hours: number;
  proposed_hours: number;
  delta: number;
  min_hours: number;
  max_hours: number;
  locked: boolean;
  mastery: number | null;
  explanation: string;
  evidence: EvidenceCategory;
}

export interface Scenario {
  key: ScenarioKey;
  label: string;
  goal: string;
  parameters: { max_change_pct: number; held_for_evidence: string[]; need_weights: Record<string, number> };
  ok: boolean;
  result: {
    total_hours: number;
    proposed_total: number;
    rows: ScenarioRow[];
    constraints: { name: string; ok: boolean; detail: string }[];
    policy_checks: { policy: string; name: string; status: "applied" | "relaxed"; affected_topics: string[] }[];
    relaxed_policies: string[];
    warnings: string[];
  } | null;
  error: { code: string; message: string; details: string[] } | null;
  identical_to: ScenarioKey[];
  identical_note?: string;
  diff: { changed_topics: number; hours_moved: number; hours_released: number; max_abs_change: number } | null;
}

export interface ScenarioPreview {
  context: AnalysisContext;
  fingerprint: string;
  persisted: false;
  baseline: { total_hours: number; requested_total: number; target_mastery: number; max_change_pct: number };
  scenarios: Scenario[];
  comparison: {
    topic_id: number;
    name: string;
    current_hours: number;
    min_hours: number;
    max_hours: number;
    locked: boolean;
    mastery: number | null;
    evidence: EvidenceCategory;
    scenarios: Partial<Record<ScenarioKey, { proposed: number; delta: number }>>;
  }[];
  graph: { foundational_gaps: number[]; chains: CurriculumGraph["chains"] };
}
