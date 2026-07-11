export const TEST_CASE_TYPE_OPTIONS = [
  { value: "functional", label: "功能" },
  { value: "boundary", label: "边界" },
  { value: "exception", label: "异常" },
  { value: "permission", label: "权限" },
  { value: "compatibility", label: "兼容" },
  { value: "performance", label: "性能" },
  { value: "security", label: "安全" }
] as const;

export type TestCaseType = (typeof TEST_CASE_TYPE_OPTIONS)[number]["value"];

export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type RecordStatus = "success" | "failed";
export type GateStatus = "pending" | "approved" | "rejected";
export type ReviewGrade = "excellent" | "good" | "fair" | "poor";

export interface TestCase {
  id: string;
  title: string;
  precondition: string;
  steps: string[];
  expected: string[];
  type: TestCaseType;
}

export interface KnowledgeChunk {
  content: string;
  source: string;
  score: number | null;
  document_type: string | null;
  module: string | null;
  chunk: number | null;
  tags: string[];
}

export interface GenerationUsage {
  prompt_characters: number;
  completion_characters: number;
  total_characters: number;
  prompt_tokens_estimate: number;
  completion_tokens_estimate: number;
  total_tokens_estimate: number;
  estimated_cost: number | null;
  currency: string | null;
}

export interface GenerationReview {
  passed: boolean;
  score: number;
  grade: ReviewGrade;
  warnings: string[];
  recommendations: string[];
  missing_target_types: TestCaseType[];
  missing_acceptance_keywords: string[];
  retry_recommended: boolean;
}

export interface GenerationGateDetail {
  code: string;
  gate: string;
  message: string;
  action_required: string;
  usage: GenerationUsage | null;
  review: GenerationReview | null;
}

export interface GenerationGateResolution {
  status: GateStatus;
  resolved_at: string | null;
  resolved_by: string | null;
  comment: string | null;
}

export interface WorkflowStep {
  name: string;
  status: "success" | "failed" | "skipped";
  summary: string;
  duration_ms: number;
  backend: string | null;
  trace: Record<string, unknown>;
}

export interface GenerationMetadata {
  model: string;
  attempts: number;
  retrieved_chunks: number;
  retrieved_sources: string[];
  prompt_version: string;
  workflow_backend: string | null;
  usage: GenerationUsage;
  review: GenerationReview | null;
  workflow_steps: WorkflowStep[];
}

export interface GenerateRequest {
  description: string;
  max_cases: number;
  knowledge_top_k: number;
  include_context: boolean;
  focus_types: TestCaseType[] | null;
}

export interface GenerateResponse {
  cases: TestCase[];
  metadata: GenerationMetadata;
  retrieved_context: KnowledgeChunk[];
}

export interface GenerationJobError {
  code: string;
  message: string;
  status_code: number;
  gate: GenerationGateDetail | null;
}

export interface GenerationJobSummary {
  id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  record_id: string | null;
  error: GenerationJobError | null;
}

export interface GenerationJobDetail extends GenerationJobSummary {
  request: GenerateRequest;
  response: GenerateResponse | null;
}

export interface GenerationJobListResponse {
  jobs: GenerationJobSummary[];
  limit: number;
  offset: number;
}

export interface GenerationQualityReport {
  score: number;
  grade: ReviewGrade;
  case_count: number;
  duplicate_title_count: number;
  duplicate_title_rate: number;
  covered_types: TestCaseType[];
  missing_target_types: TestCaseType[];
  type_coverage_rate: number;
  average_steps: number;
  average_expected: number;
  knowledge_grounded: boolean;
  missing_acceptance_keywords: string[];
  warnings: string[];
  recommendations: string[];
}

export interface GenerationRecordSummary {
  id: string;
  created_at: string;
  request_id: string | null;
  status: RecordStatus;
  description: string;
  duration_ms: number;
  model: string | null;
  attempts: number | null;
  retrieved_chunks: number | null;
  retrieved_sources: string[];
  case_count: number;
  error: string | null;
  usage: GenerationUsage;
  gate: GenerationGateDetail | null;
  gate_resolution: GenerationGateResolution | null;
}

export interface GenerationRecordDetail extends GenerationRecordSummary {
  request: GenerateRequest;
  response: GenerateResponse | null;
  quality: GenerationQualityReport | null;
}

export interface GenerationRecordListResponse {
  records: GenerationRecordSummary[];
  limit: number;
  offset: number;
}

export interface KnowledgeDocument {
  source: string;
  content: string;
  document_type: string;
  module: string;
  tags: string[];
}

export interface KnowledgeDocumentSummary {
  source: string;
  document_type: string;
  module: string;
  tags: string[];
  version: number;
  chunk_count: number;
  content_hash: string | null;
  updated_at: string | null;
}

export interface KnowledgeDocumentListResponse {
  documents: KnowledgeDocumentSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface KnowledgeDocumentUpsertResponse {
  source: string;
  version: number;
  added_chunks: number;
  replaced_chunks: number;
}

export interface KnowledgeDocumentDeleteResponse {
  source: string;
  deleted_chunks: number;
}

export interface QueryResponse {
  chunks: KnowledgeChunk[];
}

export interface RequirementPoint {
  id: string;
  title: string;
  description: string;
  keywords: string[];
  priority: "low" | "medium" | "high" | "critical";
  source: string | null;
}

export interface RequirementCoverageItem {
  requirement: RequirementPoint;
  covered: boolean;
  coverage_score: number;
  matched_case_ids: string[];
  matched_case_titles: string[];
  matched_keywords: string[];
  missing_keywords: string[];
}

export interface CoverageEvaluationResponse {
  total_requirements: number;
  covered_requirements: number;
  coverage_rate: number;
  total_keywords: number;
  matched_keywords: number;
  keyword_coverage_rate: number;
  uncovered_requirement_ids: string[];
  items: RequirementCoverageItem[];
  warnings: string[];
  recommendations: string[];
}

export interface CoverageGapKnowledgeUpsertResponse {
  source: string;
  version: number;
  added_chunks: number;
  replaced_chunks: number;
  gap_count: number;
  document_type: string;
  module: string;
  tags: string[];
}
