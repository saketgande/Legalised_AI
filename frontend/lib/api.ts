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

export type Check = { kind: string; name: string; passed: boolean; detail: string };

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

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  createRequest: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/requests`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<RequestDetail>),

  createInbound: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/requests/inbound`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<RequestDetail>),

  decideChange: (changeId: string, action: "approve" | "reject" | "edit", edited_after_text?: string) =>
    fetch(`${BASE}/api/changes/${changeId}/decide`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action, edited_after_text }),
    }).then(j<RequestDetail>),

  listRequests: (q: { state?: string; lane?: string } = {}) => {
    const p = new URLSearchParams(q as Record<string, string>).toString();
    return fetch(`${BASE}/api/requests${p ? "?" + p : ""}`, { cache: "no-store" }).then(
      j<RequestSummary[]>,
    );
  },

  getRequest: (id: string) =>
    fetch(`${BASE}/api/requests/${id}`, { cache: "no-store" }).then(j<RequestDetail>),

  requesterStatus: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/status`, { cache: "no-store" }).then(j<RequesterStatus>),

  approveStep: (stepId: string) =>
    fetch(`${BASE}/api/approvals/steps/${stepId}/approve`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    }).then(j<RequestDetail>),

  send: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/send`, { method: "POST" }).then(j<RequestDetail>),

  simulateSignature: (id: string) =>
    fetch(`${BASE}/api/requests/${id}/simulate-signature`, { method: "POST" }).then(
      j<RequestDetail>,
    ),

  verifyAudit: () =>
    fetch(`${BASE}/api/audit/verify`, { cache: "no-store" }).then(
      j<{ intact: boolean; broken_at: number | null; count: number }>,
    ),
};

export const PURPOSES = [
  { value: "sales_evaluation", label: "Sales evaluation" },
  { value: "vendor_evaluation", label: "Vendor evaluation" },
  { value: "hiring", label: "Hiring / recruiting" },
  { value: "partnership_exploration", label: "Partnership exploration" },
  { value: "litigation_support", label: "Litigation support" },
  { value: "other", label: "Other" },
];

export const STAGES = ["Requested", "Drafting", "In review", "Sent", "Signed"];
