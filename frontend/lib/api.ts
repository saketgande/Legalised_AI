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
  type_label: string | null;
  category: "CONTRACT" | "ADVICE";
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
  priority: "LOW" | "NORMAL" | "HIGH" | "URGENT";
  assigned_to_user_id: string | null;
  assigned_to_name: string | null;
  snoozed_until: string | null;
  sla_target_hours: number | null;
  playbook_id: string | null;
  playbook_name: string | null;
  playbook_version: number | null;
  esign_provider: string | null;
  esign_status: string | null;
  esign_envelope_id: string | null;
};

export type RequestTypeInfo = {
  key: string;
  label: string;
  description: string;
  category: "CONTRACT" | "ADVICE";
  default_sla_hours: number;
};

export type RoutingRuleOut = {
  id: string;
  name: string;
  ordinal: number;
  active: boolean;
  stop_on_match: boolean;
  match_type_key: string | null;
  match_direction: string | null;
  match_keyword: string | null;
  match_jurisdiction: string | null;
  set_assignee_user_id: string | null;
  set_assignee_name: string | null;
  set_priority: string | null;
  set_sla_hours: number | null;
  escalate: boolean;
};

export type RulePreview = {
  evaluated: number;
  matched: number;
  matches: { ref: string; type: string; counterparty: string; state: string; created_at: string }[];
};

export type AssignableUser = { id: string; name: string; role: string };

export type Obligation = {
  id: string;
  kind: string;
  description: string;
  due_at: string | null;
  status: "OPEN" | "DONE" | "WAIVED";
  overdue: boolean;
  source: string;
  resolved_by: string | null;
  resolved_at: string | null;
};

export type PlaybookFallback = { label: string; body: string; rung: string };

export type PlaybookSummary = {
  id: string;
  name: string;
  version: number;
  active: boolean;
  rule_count: number;
};

export type MailboxConfig = {
  configured: boolean;
  imap_host?: string;
  imap_port?: number;
  use_ssl?: boolean;
  username?: string;
  folder?: string;
  active?: boolean;
  default_playbook_id?: string | null;
  last_polled_at?: string | null;
  last_error?: string | null;
  last_result?: { polled?: number; ingested?: number; at?: string };
  ingested_count?: number;
};

export type MailboxTestResult = { ok: boolean; folder?: string; total?: number; unseen?: number; error?: string };

export type PollResult = {
  ok: boolean;
  error?: string | null;
  polled: number;
  ingested: number;
  messages: {
    uid: string; from: string; subject: string; created: boolean;
    classified: string | null; ref: string | null; request_id: string | null;
    direction: string | null; reply: string | null; error: string | null;
  }[];
};

export type PlaybookRule = {
  id: string;
  rule_key: string;
  clause_type: string;
  heading: string;
  ordinal: number;
  preferred_position: string;
  preferred_body: string;
  rationale: string;
  mandatory: boolean;
  deviation_rung: string;
  nda_type: string | null;
  fallbacks: PlaybookFallback[];
  walk_away_text: string;
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
  details: string | null;
  resolution_draft: string | null;
  resolution_note: string | null;
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
  answer: string | null;
  stages: string[] | null;
  expires_at: string | null;
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

export type OpsRow = {
  id: string;
  ref: string;
  counterparty: string;
  requester: string;
  lane: string | null;
  direction: string;
  state: string;
  target_hours: number;
  elapsed_hours: number | null;
  cycle_hours: number | null;
  status: "breached" | "at_risk" | "on_track" | "missed" | "met" | "cancelled" | null;
};

export type OpsSummary = {
  totals: { total: number; in_flight: number; resolved: number; auto_resolved: number; cancelled: number };
  deflection_rate: number;
  sla: {
    breached: number;
    at_risk: number;
    on_track: number;
    compliance_rate: number | null;
    avg_cycle_hours: number | null;
  };
  targets: Record<string, number>;
  volume_7d: number[];
  rows: OpsRow[];
};

export type ContractRow = {
  id: string;
  ref: string;
  counterparty: string;
  nda_type: string;
  direction: string;
  term_months: number;
  executed_at: string | null;
  expires_at: string | null;
  days_left: number | null;
  status: "active" | "expiring" | "expired" | "renewed";
};

export type ContractRegistry = {
  totals: { total: number; active: number; expiring: number; expired: number; renewed: number };
  expiring_soon_days: number;
  rows: ContractRow[];
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
  if (res.status === 401) {
    // token missing/expired -> drop it and bounce to login (except while logging in)
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new AuthError("unauthenticated");
  }
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

  createInboundUpload: (fields: { counterparty_name: string; nda_type: string; purpose: string; playbook_id?: string }, file: File) => {
    const fd = new FormData();
    fd.append("counterparty_name", fields.counterparty_name);
    fd.append("nda_type", fields.nda_type);
    fd.append("purpose", fields.purpose);
    if (fields.playbook_id) fd.append("playbook_id", fields.playbook_id);
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

  // playbook library (read-only; used by the request forms' picker)
  listPlaybooks: () => fetch(`${BASE}/api/playbooks`, { cache: "no-store", headers: H() })
    .then(j<{ playbooks: PlaybookSummary[] }>).then((r) => r.playbooks),

  // playbook admin
  getPlaybook: (playbookId?: string) => {
    const q = playbookId ? `?playbook_id=${encodeURIComponent(playbookId)}` : "";
    return fetch(`${BASE}/api/admin/playbook${q}`, { cache: "no-store", headers: H() }).then(
      j<{ playbook: { id: string; name: string; version: number; active: boolean }; rules: PlaybookRule[] }>);
  },
  listPlaybooksAdmin: () => fetch(`${BASE}/api/admin/playbook/catalog`, { cache: "no-store", headers: H() })
    .then(j<{ playbooks: PlaybookSummary[] }>).then((r) => r.playbooks),
  createPlaybook: (name: string) => fetch(`${BASE}/api/admin/playbook/catalog`, JSON_POST({ name })).then(j<PlaybookSummary>),
  activatePlaybook: (id: string) => fetch(`${BASE}/api/admin/playbook/catalog/${id}/activate`, { method: "POST", headers: H() }).then(j<PlaybookSummary>),
  createRule: (body: Record<string, unknown>, playbookId?: string) => {
    const q = playbookId ? `?playbook_id=${encodeURIComponent(playbookId)}` : "";
    return fetch(`${BASE}/api/admin/playbook/rules${q}`, JSON_POST(body)).then(j<PlaybookRule>);
  },
  updateRule: (id: string, body: Record<string, unknown>, playbookId?: string) => {
    const q = playbookId ? `?playbook_id=${encodeURIComponent(playbookId)}` : "";
    return fetch(`${BASE}/api/admin/playbook/rules/${id}${q}`, { method: "PUT", headers: H({ "content-type": "application/json" }), body: JSON.stringify(body) }).then(j<PlaybookRule>);
  },
  deleteRule: (id: string, playbookId?: string) => {
    const q = playbookId ? `?playbook_id=${encodeURIComponent(playbookId)}` : "";
    return fetch(`${BASE}/api/admin/playbook/rules/${id}${q}`, { method: "DELETE", headers: H() }).then(j<{ ok: boolean; deleted: string }>);
  },
  learnFromChange: (changeId: string) => fetch(`${BASE}/api/admin/playbook/learn-from-change/${changeId}`, { method: "POST", headers: H() }).then(j<PlaybookRule>),

  // polled email inbox (intake channel)
  getMailbox: () => fetch(`${BASE}/api/admin/intake/mailbox`, { cache: "no-store", headers: H() }).then(j<MailboxConfig>),
  saveMailbox: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/admin/intake/mailbox`, { method: "PUT", headers: H({ "content-type": "application/json" }), body: JSON.stringify(body) }).then(j<MailboxConfig>),
  testMailbox: () => fetch(`${BASE}/api/admin/intake/mailbox/test`, { method: "POST", headers: H() }).then(j<MailboxTestResult>),
  pollMailbox: () => fetch(`${BASE}/api/admin/intake/mailbox/poll`, { method: "POST", headers: H() }).then(j<PollResult>),
  deleteMailbox: () => fetch(`${BASE}/api/admin/intake/mailbox`, { method: "DELETE", headers: H() }).then(j<{ ok: boolean }>),

  // ops metrics (SLA + deflection dashboard)
  opsSummary: () => fetch(`${BASE}/api/ops/summary`, { cache: "no-store", headers: H() }).then(j<OpsSummary>),

  // request-type catalog + the advice engine
  requestTypes: () => fetch(`${BASE}/api/request-types`, { cache: "no-store", headers: H() })
    .then(j<{ types: RequestTypeInfo[] }>).then((r) => r.types),
  createAdvice: (body: { type_key: string; question: string; urgency?: string }) =>
    fetch(`${BASE}/api/requests/advice`, JSON_POST(body)).then(j<RequestDetail>),
  resolveAdvice: (id: string, answer: string) =>
    fetch(`${BASE}/api/requests/${id}/resolve`, JSON_POST({ answer })).then(j<RequestDetail>),

  // queue operations
  assignRequest: (id: string, user_id: string | null) =>
    fetch(`${BASE}/api/requests/${id}/assign`, JSON_POST({ user_id })).then(j<RequestDetail>),
  snoozeRequest: (id: string, hours: number | null) =>
    fetch(`${BASE}/api/requests/${id}/snooze`, JSON_POST({ hours })).then(j<RequestDetail>),
  bulkAction: (body: { ids: string[]; action: "assign" | "snooze" | "unsnooze"; user_id?: string; hours?: number }) =>
    fetch(`${BASE}/api/requests/bulk`, JSON_POST(body)).then(j<{ ok: boolean; done: string[]; skipped: string[] }>),
  assignableUsers: () => fetch(`${BASE}/api/users/assignable`, { cache: "no-store", headers: H() })
    .then(j<{ users: AssignableUser[] }>).then((r) => r.users),

  // routing rules (admin)
  listRoutingRules: () => fetch(`${BASE}/api/admin/routing/rules`, { cache: "no-store", headers: H() })
    .then(j<{ rules: RoutingRuleOut[] }>).then((r) => r.rules),
  createRoutingRule: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/admin/routing/rules`, JSON_POST(body)).then(j<RoutingRuleOut>),
  updateRoutingRule: (id: string, body: Record<string, unknown>) =>
    fetch(`${BASE}/api/admin/routing/rules/${id}`, { method: "PUT", headers: H({ "content-type": "application/json" }), body: JSON.stringify(body) }).then(j<RoutingRuleOut>),
  deleteRoutingRule: (id: string) =>
    fetch(`${BASE}/api/admin/routing/rules/${id}`, { method: "DELETE", headers: H() }).then(j<{ ok: boolean }>),
  previewRoutingRule: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/admin/routing/rules/preview`, JSON_POST(body)).then(j<RulePreview>),

  // obligations (post-signature CLM)
  contractObligations: (contractId: string) =>
    fetch(`${BASE}/api/contracts/${contractId}/obligations`, { cache: "no-store", headers: H() })
      .then(j<{ obligations: Obligation[] }>).then((r) => r.obligations),
  resolveObligation: (obligationId: string, done: boolean) =>
    fetch(`${BASE}/api/contracts/obligations/${obligationId}/resolve`, JSON_POST({ done }))
      .then(j<{ ok: boolean; status: string }>),

  // contract registry (CLM — post-signature renewal tracking)
  contracts: () => fetch(`${BASE}/api/contracts`, { cache: "no-store", headers: H() }).then(j<ContractRegistry>),
  renewContract: (id: string) =>
    fetch(`${BASE}/api/contracts/${id}/renew`, { method: "POST", headers: H() }).then(
      j<{ id: string; ref: string; state: string; lane: string | null; renewed_from_id: string }>,
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
