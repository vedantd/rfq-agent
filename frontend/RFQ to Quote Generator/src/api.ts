// Client for the QuotePilot API (api/app.py). Contract: docs/frontend.md.
// Calls go to /v1/* on this origin; vite.config.ts proxies them to the API.

export const DEMO_API_KEY = "rudco-demo-key";

export type LineStatus = "extracted" | "ready_for_approval" | "approved" | "needs_clarification" | "needs_review" | "blocked_compliance";

export interface Clarification { field: string; question: string }

export interface Line {
  id: string;
  raw_text: string;
  status: LineStatus;
  approval_status?: string;
  material?: string | null;
  form?: string | null;
  grade?: string | null;
  thickness_in?: number | null;
  width_in?: number | null;
  length_in?: number | null;
  quantity?: number | null;
  unit?: string | null;
  standard_required?: string | null;
  required_certificates?: string[];
  blockers: string[];
  clarifications: Clarification[];
  match: null | { sku: string; supplier: string; matched_grade: string; supplier_standard: string; reason: string };
  match_candidates?: string[];
  pricing: null | {
    supplier_cost_usd: number; markup_pct: number; unit_price_usd: number; quantity: number; line_total_usd: number;
    benchmark_unit_usd: number; benchmark_source: string; benchmark_as_of: string; below_benchmark_pct: number | null;
    explanation: string; data_is_synthetic: boolean;
  };
  compliance: { status: string; issues: string[]; available_certificates?: string[]; country_of_origin?: string | null; supplier_standard?: string; note?: string };
}

export interface RFQ {
  rfq_id: string;
  buyer_id: string;
  buyer_email?: string | null;
  status: "needs_clarification" | "review_required" | "approved";
  parser_mode: string;
  gateway: {
    gateway?: string; model?: string; latency_ms?: number; validation?: string;
    // present when the upload was an image: transcribed by a vision model first (api/app.py create_rfq)
    vision_model?: string; vision_latency_ms?: number; extract_latency_ms?: number; source?: string;
  } | null;
  line_count: number;
  ready_for_approval: number;
  needs_clarification: number;
  approved: number;
  lines: Line[];
  events: { at: string; type: string; detail: string }[];
  created_at: string;
}

export interface Quote {
  id: string; rfq_id: string; status: string; ready_to_send: boolean; currency: string;
  grand_total_usd: number; warnings: string[]; created_at: string;
  lines: { line_id: string; sku: string; description: string; quantity: number; unit_price_usd: number; line_total_usd: number; standard: string; certifications: string[] }[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { "X-API-Key": DEMO_API_KEY };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;
    const msg = typeof d === "string" ? d : d && typeof d === "object" && "message" in d ? String((d as { message: string }).message) : `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, d);
  }
  return data as T;
}

export const api = {
  health: () => fetch("/health").then((r) => r.json()),
  createRfq: (text: string, buyer_id: string, buyer_email?: string, source_type = "text") =>
    call<RFQ>("POST", "/v1/rfqs", { text, buyer_id, buyer_email: buyer_email || null, source_type }),
  uploadRfq: (file: File, buyer_id: string, buyer_email?: string, deferAnalysis = false) => {
    const fd = new FormData();
    if (deferAnalysis) fd.append("defer_analysis", "true");   // step 1 only: extracted lines
    fd.append("file", file);
    fd.append("buyer_id", buyer_id);
    if (buyer_email) fd.append("buyer_email", buyer_email);
    return call<RFQ>("POST", "/v1/rfqs/upload", undefined, fd);
  },
  getRfq: (id: string) => call<RFQ>("GET", `/v1/rfqs/${id}`),
  analyze: (id: string) => call<RFQ>("POST", `/v1/rfqs/${id}/analyze`),   // steps 2-4: match, compliance, price
  clarify: (id: string, lineId: string, fields: Record<string, string | number>) => call<Line>("PATCH", `/v1/rfqs/${id}/lines/${lineId}`, fields),
  approve: (id: string, lineId: string) => call<Line>("POST", `/v1/rfqs/${id}/lines/${lineId}/approve`),
  emailDraft: (id: string) => call<{ to: string | null; subject: string; body: string; delivery_status: string }>("GET", `/v1/rfqs/${id}/clarifications/email-draft`),
  draftQuote: (id: string) => call<Quote>("POST", `/v1/rfqs/${id}/quotes/draft`),
};

export const money = (v?: number | null) =>
  v == null ? "—" : "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
