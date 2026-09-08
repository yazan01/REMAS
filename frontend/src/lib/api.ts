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
