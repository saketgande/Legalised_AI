// Thin typed client over the FastAPI backend.
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export type Clause = {
  id: string;
  ordinal: number;
  section_no: string;
  clause_type: string | null;
  heading: string;
  body_text: string;
  source_rule_key: string | null;
};

export type DocumentOut = {
  id: string;
  title: string;
  origin: string;
  version_no: number;
  content_hash: string;
  body_markdown: string;
  clauses: Clause[];
};

export type ApprovalStep = {
  id: string;
  ordinal: number;
  rung: string;
  reason: string;
  status: string;
  assignee_name: string | null;
  decided_by: string | null;
  decided_at: string | null;
};

export type Ladder = { id: string; status: string; steps: ApprovalStep[] };

export type TimelineEvent = {
  chain_position: number;
  action: string;
  actor_type: string;
  actor_label: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RequestSummary = {
  id: string;
  ref: string;
  type: string;
  direction: string;
  nda_type: string;
  state: string;
  lane: string | null;
  counterparty_name: string;
  requester_name: string;
  purpose: string;
  jurisdiction: string;
  term_months: number;
  created_at: string;
  open_steps: number;
};

export type Check = { kind: string; name: string; passed: boolean; detail: string; model?: string };

export type ProposedChange = {
  id: string;
  ordinal: number;
  section_no: string;
  heading: string;
  finding: "DEVIATION" | "MISSING" | "NOVEL" | "ACCEPTABLE_FALLBACK";
  rule_key: string | null;
  before_text: string;
  after_text: string;
  rationale: string;
  checks: Check[];
  confidence: number | null;
  triggered_rung: string;
  decision: "PENDING" | "APPROVED" | "APPROVED_WITH_EDIT" | "REJECTED";
};

export type Review = {
  id: string;
  status: string;
  summary: Record<string, number>;
  changes: ProposedChange[];
  counter_markdown: string;
  required_rungs: string[];
};

export type RequestDetail = RequestSummary & {
  triage_reasons: string[];
  document: DocumentOut | null;
  ladder: Ladder | null;
  review: Review | null;
  timeline: TimelineEvent[];
};

export type RequesterStatus = {
  ref: string;
  counterparty_name: string;
  nda_type: string;
  purpose: string;
  stage: string;
  stage_index: number;
  needs_you: boolean;
  headline: string;
  detail: string;
  document_ready: boolean;
  timeline: TimelineEvent[];
};

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  rank: number;
  permissions: string[];
  suspended: boolean;
};

// ——— token handling ———
const TOKEN_KEY = "fd_token";
let _token: string | null = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
export function setToken(t: string | null) {
  _token = t;
  if (typeof window !== "undefined") {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  }
}
export function getToken() {
  return _token;
}
function H(extra: Record<string, string> = {}): Record<string, string> {
  return _token ? { ...extra, authorization: `Bearer ${_token}` } : extra;
}

export class AuthError extends Error {}

async function j<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new AuthError("unauthenticated");
  if (!res.ok) {
    const text = await res.text();
    // surface FastAPI's {"detail": "..."} nicely
    let msg = text;
    try { msg = JSON.parse(text).detail ?? text; } catch {}
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const JSON_POST = (body: unknown) => ({
  method: "POST",
  headers: H({ "content-type": "application/json" }),
  body: JSON.stringify(body),
});

export const api = {
  login: (email: string, password: string) =>
    fetch(`${BASE}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).then(j<{ token: string; user: AuthUser }>),

  me: () => fetch(`${BASE}/api/auth/me`, { headers: H(), cache: "no-store" }).then(j<AuthUser>),

  createRequest: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/requests`, JSON_POST(body)).then(j<RequestDetail>),

  createInbound: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/requests/inbound`, JSON_POST(body)).then(j<RequestDetail>),

  createInboundUpload: (fields: { counterparty_name: string; nda_type: string; purpose: string }, file: File) => {
    const fd = new FormData();
    fd.append("counterparty_name", fields.counterparty_name);
    fd.append("nda_type", fields.nda_type);
    fd.append("purpose", fields.purpose);
    fd.append("file", file);
    return fetch(`${BASE}/api/requests/inbound/upload`, { method: "POST", headers: H(), body: fd }).then(j<RequestDetail>);
  },

  decideChange: (changeId: string, action: "approve" | "reject" | "edit", edited_after_text?: string) =>
    fetch(`${BASE}/api/changes/${changeId}/decide`, JSON_POST({ action, edited_after_text })).then(j<RequestDetail>),

  listRequests: (q: { state?: string; lane?: string } = {}) => {
    const p = new URLSearchParams(q as Record<string, string>).toString();
    return fetch(`${BASE}/api/requests${p ? "?" + p : ""}`, { cache: "no-store", headers: H() }).then(j<RequestSummary[]>);
  },

  getRequest: (id: string) =>
    fetch(`${BASE}/api/requests/${id}`, { cache: "no-store", headers: H() }).then(j<RequestDetail>),

  requesterStatus: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/status`, { cache: "no-store", headers: H() }).then(j<RequesterStatus>),

  approveStep: (stepId: string) =>
    fetch(`${BASE}/api/approvals/steps/${stepId}/approve`, JSON_POST({})).then(j<RequestDetail>),

  send: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/send`, { method: "POST", headers: H() }).then(j<RequestDetail>),

  simulateSignature: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/simulate-signature`, { method: "POST", headers: H() }).then(j<RequestDetail>),

  verifyAudit: () =>
    fetch(`${BASE}/api/audit/verify`, { cache: "no-store", headers: H() }).then(
      j<{ intact: boolean; broken_at: number | null; count: number }>,
    ),

  // intake channels
  chatIntake: (message: string) =>
    fetch(`${BASE}/api/intake/chat`, JSON_POST({ message })).then(
      j<{ reply: string; created: { id: string; ref: string; lane: string | null; state: string; counterparty: string } | null; extracted: Record<string, unknown> }>,
    ),

  emailWebhook: (payload: { from_email: string; from_name?: string; subject?: string; body: string }) =>
    fetch(`${BASE}/api/intake/email-webhook`, JSON_POST(payload)).then(
      j<{ created: boolean; classified: string; request?: RequestSummary; reply?: string }>,
    ),

  // admin
  listUsers: () => fetch(`${BASE}/api/admin/users`, { cache: "no-store", headers: H() }).then(j<AuthUser[]>),
  changeUserRole: (userId: string, role: string) =>
    fetch(`${BASE}/api/admin/users/${userId}/role`, { method: "PATCH", headers: H({ "content-type": "application/json" }), body: JSON.stringify({ role }) }).then(j<AuthUser>),
};

// rung rank must mirror the backend so the UI can pre-check approval ability
export const RUNG_RANK: Record<string, number> = { none: 0, requesting_manager: 3, vp_legal: 5, gc: 6 };

export const PURPOSES = [
  { value: "sales_evaluation", label: "Sales evaluation" },
  { value: "vendor_evaluation", label: "Vendor evaluation" },
  { value: "hiring", label: "Hiring / recruiting" },
  { value: "partnership_exploration", label: "Partnership exploration" },
  { value: "litigation_support", label: "Litigation support" },
  { value: "other", label: "Other" },
];

export const STAGES = ["Requested", "Drafting", "In review", "Sent", "Signed"];
