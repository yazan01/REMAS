const BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8010/api/v1";

const TOKEN_KEY = "remas.token";

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* non-fatal */
  }
}

/**
 * Errors from the API carry both languages, so the caller can render whichever
 * one is active without re-issuing the request.
 */
export class ApiError extends Error {
  code: string;
  messageAr: string;
  messageEn: string;
  status: number;
  details: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    const ar = typeof body.message_ar === "string" ? body.message_ar : "حدث خطأ غير متوقع.";
    const en = typeof body.message_en === "string" ? body.message_en : "Something went wrong.";
    super(en);
    this.name = "ApiError";
    this.status = status;
    this.code = typeof body.code === "string" ? body.code : "server.error";
    this.messageAr = ar;
    this.messageEn = en;
    this.details = (body.details as Record<string, unknown>) ?? {};
  }

  localised(locale: "ar" | "en") {
    return locale === "ar" ? this.messageAr : this.messageEn;
  }
}

type Options = {
  method?: string;
  body?: unknown;
  auth?: boolean;
  raw?: BodyInit;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, auth = true, raw } = options;
  const headers: Record<string, string> = {};

  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const parsed = text ? JSON.parse(text) : {};

  if (!res.ok) throw new ApiError(res.status, parsed);
  return parsed as T;
}

/* ---------- API shapes ---------- */

export type Bilingual = Record<string, unknown>;

export type Layer = {
  key: string;
  name_ar: string;
  name_en: string;
  summary_ar: string;
  summary_en: string;
  includes_ar: string[];
  includes_en: string[];
  output_ar: string;
  output_en: string;
};

export type Question = {
  id: string;
  code: string;
  order_index: number;
  text_ar: string;
  text_en: string;
  guidance_ar: string | null;
  guidance_en: string | null;
  evidence_hint_ar: string | null;
  evidence_hint_en: string | null;
  weight: number;
  is_mandatory: boolean;
  evidence_required: boolean;
  allow_not_applicable: boolean;
  response_type: string;
  /** FR-08 - what each level of the 1-5 scale means for this question. */
  criteria: Record<string, { ar: string; en: string }> | null;
};

export type Axis = {
  id: string;
  code: string;
  order_index: number;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  weight: number;
  questions: Question[];
};

export type MaturityLevel = {
  score: number;
  label_ar: string;
  label_en: string;
  description_ar: string | null;
  description_en: string | null;
};

export type FrameworkVersion = {
  id: string;
  version: string;
  status: string;
  framework_code: string;
  name_ar: string;
  name_en: string;
  description_ar: string | null;
  description_en: string | null;
  scoring_config: Record<string, unknown>;
  maturity_levels: MaturityLevel[];
  axes: Axis[];
  question_count: number;
  axis_count: number;
};

export type Me = {
  user: {
    id: string;
    email: string;
    full_name: string;
    role: string;
    locale: string;
    organization_id: string;
  };
  organization_name_ar: string;
  organization_name_en: string;
  organization_slug: string;
  profile_completeness: number;
};

export type Assessment = {
  id: string;
  name: string;
  layer: string;
  status: string;
  locked: boolean;
  created_at: string;
  submitted_at: string | null;
  framework_version_id: string;
  completion: number;
  overall_score: number | null;
  maturity_level: number | null;
  selected_axis_ids?: string[];
};

export type ResponseRow = {
  id: string;
  question_id: string;
  score: number | null;
  is_not_applicable: boolean;
  na_rationale: string | null;
  comment: string | null;
  override_score: number | null;
  override_reason: string | null;
  effective_score: number | null;
  assigned_to_id: string | null;
  due_at: string | null;
};

export type AxisProgress = {
  axis_id: string;
  code: string;
  name_ar: string;
  name_en: string;
  total_questions: number;
  answered_questions: number;
  unanswered_mandatory: number;
  missing_evidence: number;
  completion: number;
};

export type Progress = {
  assessment_id: string;
  status: string;
  total_questions: number;
  answered_questions: number;
  unanswered_mandatory: number;
  completion: number;
  can_submit: boolean;
  overdue: number;
  axes: AxisProgress[];
};

export type AxisResult = {
  axis_id: string;
  code: string;
  weight: number;
  score: number | null;
  maturity_level: number | null;
  total_questions: number;
  applicable_questions: number;
  answered_questions: number;
  not_applicable_questions: number;
  coverage: number;
  evidence_completeness: number;
  is_scored: boolean;
  exclusion_reason: string | null;
};

export type Scoring = {
  overall_score: number | null;
  maturity_level: number | null;
  completeness: number;
  evidence_completeness: number;
  axes: AxisResult[];
  strengths: string[];
  gaps: string[];
  priorities: Array<{
    axis_id: string;
    code: string;
    score: number;
    maturity_gap: number;
    evidence_gap: number;
    priority_score: number;
    rank: number;
  }>;
  config: Record<string, unknown>;
  warnings: string[];
};

/* ---------- phase-2 API shapes ---------- */

export type DocumentRow = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  version: number;
  category: string | null;
  description: string | null;
  created_at: string;
};

export type EvidenceLink = {
  id: string;
  document_id: string;
  question_id: string;
  status: string;
  reviewer_note: string | null;
  filename: string | null;
  created_at: string;
};

export type QuestionRow = {
  question_id: string;
  code: string;
  axis_id: string;
  axis_code: string;
  text_ar: string;
  text_en: string;
  evidence_hint_ar: string | null;
  evidence_hint_en: string | null;
  is_mandatory: boolean;
  evidence_required: boolean;
  answered: boolean;
  score: number | null;
  effective_score: number | null;
  is_not_applicable: boolean;
  evidence_status: string;
  evidence_count: number;
  flagged: boolean;
};

export type AIFinding = {
  id: string;
  kind: string;
  severity: string | null;
  axis_id: string | null;
  question_id: string | null;
  document_id: string | null;
  title_ar: string | null;
  title_en: string | null;
  body_ar: string | null;
  body_en: string | null;
  citation: Record<string, unknown> | null;
  confidence: number | null;
  review_status: string;
  reviewer_note: string | null;
  created_at: string;
};

export type AIJobRow = {
  id: string;
  stage: string;
  status: string;
  provider: string | null;
  model: string | null;
  summary: Record<string, number> | null;
  error: string | null;
  created_at: string;
};

export type InitiativeRow = {
  id: string;
  axis_id: string | null;
  title_ar: string;
  title_en: string;
  objective_ar: string | null;
  objective_en: string | null;
  rationale_ar: string | null;
  rationale_en: string | null;
  owner_function_ar: string | null;
  owner_function_en: string | null;
  dependencies_ar: string | null;
  dependencies_en: string | null;
  linked_gap: string | null;
  horizon_code: string | null;
  priority: number;
  order_index: number;
  source: string;
  is_included: boolean;
};

export type Roadmap = {
  horizons: Array<{
    code: string;
    name_ar: string;
    name_en: string;
    months_from: number;
    months_to: number;
    initiatives: InitiativeRow[];
  }>;
  unassigned: InitiativeRow[];
  total: number;
};

export type LayerFeatures = {
  layer: string;
  features: string[];
  all_layers: Record<string, string[]>;
};

export type ReviewView = {
  assessment: {
    id: string;
    name: string;
    layer: string;
    status: string;
    organization_id: string;
    submitted_at: string | null;
  };
  progress: Progress;
  score_deltas: Array<{
    question_id: string;
    question_code: string;
    axis_id: string;
    axis_code: string | null;
    customer_score: number;
    reviewer_score: number;
    delta: number;
    reason: string | null;
    is_material: boolean;
  }>;
  clarifications: Array<{
    question_id: string;
    question_code: string | null;
    axis_id: string | null;
    document_id: string;
    filename: string | null;
    status: string;
    reviewer_note: string | null;
  }>;
};

export type AdminFramework = {
  id: string;
  code: string;
  name_ar: string;
  name_en: string;
  is_active: boolean;
  versions: Array<{
    id: string;
    version: string;
    status: string;
    published_at: string | null;
    axis_count: number;
    question_count: number;
  }>;
};

export type AISettings = {
  provider: string;
  model: string | null;
  enabled: boolean;
  base_url: string | null;
  ocr_provider: string;
  ocr_model: string | null;
  /** The engine an upload would actually be read by right now. */
  ocr_effective: string;
  providers: string[];
  ocr_providers: string[];
  default_models: Record<string, string>;
  /** Last four characters only — the key itself never leaves the server. */
  openai_key_hint: string | null;
  anthropic_key_hint: string | null;
  openai_key_from_env: boolean;
  anthropic_key_from_env: boolean;
  key_present: boolean;
  effective_provider: string;
  secrets_encrypted: boolean;
};

export type AITestResult = {
  ok: boolean;
  provider: string;
  model: string | null;
  detail: string;
  latency_ms: number | null;
};

export type AdminUser = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  mfa_enabled: boolean;
  email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
  organization_id: string;
  organization_name_ar: string | null;
  organization_name_en: string | null;
};

export type AdminUserListing = {
  count: number;
  offset: number;
  roles: string[];
  items: AdminUser[];
};

export type AdminOrganization = {
  id: string;
  slug: string;
  name_ar: string;
  name_en: string;
  is_ivalue: boolean;
  is_active: boolean;
  profile_completeness: number;
  user_count: number;
  assessment_count: number;
  created_at: string;
};

export type AuditRow = {
  id: string;
  created_at: string;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  organization_id: string | null;
  ip_address: string | null;
  payload: Record<string, unknown> | null;
};

/** Multipart upload — the JSON helper cannot carry a file body. */
export async function uploadFile<T>(
  path: string,
  file: File,
  extra: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(extra)) form.append(key, value);

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { method: "POST", headers, body: form });
  const text = await res.text();
  const parsed = text ? JSON.parse(text) : {};
  if (!res.ok) throw new ApiError(res.status, parsed);
  return parsed as T;
}

/** Authenticated download — <a href> cannot carry the bearer token. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { headers });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text ? JSON.parse(text) : {});
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const API_BASE = BASE;

export type OverdueRow = {
  question_id: string;
  question_code: string;
  axis_id: string;
  axis_code: string;
  assigned_to: string | null;
  assigned_to_email: string | null;
  due_at: string | null;
  days_overdue: number | null;
  is_mandatory: boolean;
};

export type UserProgress = {
  user_id: string | null;
  full_name: string | null;
  email: string | null;
  assigned: number;
  answered: number;
  overdue: number;
  completion: number;
};

export type Comparison = {
  previous_assessment_id: string;
  previous_name: string;
  previous_submitted_at: string | null;
  previous_overall: number | null;
  current_overall: number | null;
  overall_delta: number | null;
  axes: Array<{
    axis_id: string;
    code: string;
    previous: number;
    current: number;
    delta: number;
  }>;
};

export type ExpertSessionRow = {
  id: string;
  assessment_id: string;
  status: string;
  preferred_slots: string[];
  scheduled_at: string | null;
  duration_minutes: number;
  meeting_url: string | null;
  agenda: string | null;
  notes: string | null;
  expert_name: string | null;
  completed_at: string | null;
  created_at: string;
};

export type ReportTemplateRow = {
  id: string;
  code: string;
  name_ar: string;
  name_en: string;
  framework_version_id: string | null;
  sections: Array<{
    key: string;
    enabled: boolean;
    order: number;
    title_ar?: string | null;
    title_en?: string | null;
  }>;
  branding: Record<string, unknown>;
  copy_blocks: Record<string, { ar?: string; en?: string }>;
  output_formats: string[];
  maturity_labels: Record<string, { ar?: string; en?: string }>;
  include_comparison: boolean;
  is_default: boolean;
  is_active: boolean;
};

export type DocumentHistoryRow = {
  id: string;
  filename: string;
  version: number;
  size_bytes: number;
  created_at: string;
  superseded: boolean;
};

/** Fetches a protected file and hands back an object URL for inline preview. */
export async function previewUrl(path: string): Promise<{ url: string; type: string }> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, { headers });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text ? JSON.parse(text) : {});
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type };
}
