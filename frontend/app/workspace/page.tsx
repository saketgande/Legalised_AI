"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type AssignableUser, type RequestSummary, type RequestTypeInfo, type RoutingRuleOut } from "../../lib/api";

/* ————— shared helpers ————— */
const CLOSED = new Set(["SIGNED", "FILED", "EXECUTED", "CANCELLED"]);
const isOpen = (r: RequestSummary) => !CLOSED.has(r.state);
function ageLabel(iso: string): string {
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  return d === 0 ? "today" : `${d}d`;
}
const prioColor = (p: string) => p === "URGENT" ? "var(--crit)" : p === "HIGH" ? "var(--warn)" : p === "LOW" ? "var(--faint)" : "var(--teal)";
const bandColor = (b: string | null) => !b ? "var(--faint)" : b === "LOW" ? "var(--good)" : b === "MEDIUM" ? "var(--warn)" : "var(--crit)";

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return null;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane.toLowerCase()}</span>;
}

/* ═════════════ Board — pipeline Kanban (read-only; state is engine-governed) ═════════════ */
const COLUMNS: { id: string; label: string; c: string; states: string[]; desc: string }[] = [
  { id: "intake", label: "Intake", c: "var(--blue)", states: ["NEW", "CLASSIFIED", "ROUTED"], desc: "Classified & routed" },
  { id: "drafting", label: "Drafting", c: "var(--amber)", states: ["DRAFTED"], desc: "Assembled from playbook" },
  { id: "review", label: "In Review", c: "var(--teal)", states: ["IN_REVIEW", "RETURNED"], desc: "Attorney governing" },
  { id: "negotiation", label: "Negotiation / Signing", c: "var(--purple)", states: ["APPROVED", "WITH_COUNTERPARTY", "OUT_FOR_SIGNATURE"], desc: "Out & converging" },
  { id: "closed", label: "Closed", c: "var(--good)", states: ["EXECUTED", "FILED", "SIGNED", "CANCELLED"], desc: "Filed & tracked" },
];

function BoardTab({ rows }: { rows: RequestSummary[] }) {
  const colFor = (s: string) => COLUMNS.find((c) => c.states.includes(s))?.id ?? "intake";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
          Live pipeline · {rows.length} requests · cards placed by governed state — not drag-reordered
        </div>
        <div className="mono" style={{ display: "flex", gap: 10, fontSize: 10, color: "var(--faint)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
          <span><span style={{ color: "var(--good)" }}>●</span> Low</span>
          <span><span style={{ color: "var(--warn)" }}>●</span> Med</span>
          <span><span style={{ color: "var(--crit)" }}>●</span> High+</span>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(200px, 1fr))", gap: 10, minWidth: 1050, height: "calc(100vh - 300px)", minHeight: 480 }}>
          {COLUMNS.map((col) => {
            const cards = rows.filter((r) => colFor(r.state) === col.id);
            return (
              <div key={col.id} style={{ background: "var(--surface)", border: "1px solid var(--line)", borderTop: `3px solid ${col.c}`, borderRadius: "0 0 8px 8px", display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
                <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div className="mono" style={{ fontSize: 11, fontWeight: 700, color: col.c, letterSpacing: "0.1em", textTransform: "uppercase" }}>{col.label}</div>
                    <div style={{ fontSize: 9, color: "var(--faint)", marginTop: 1 }}>{col.desc}</div>
                  </div>
                  <span className="mono" style={{ padding: "2px 8px", background: "var(--surface-2)", color: col.c, fontSize: 11, fontWeight: 700, borderRadius: 4 }}>{cards.length}</span>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: 8, display: "flex", flexDirection: "column", gap: 7 }}>
                  {cards.length === 0
                    ? <div className="mono" style={{ fontSize: 10, color: "var(--faint)", textAlign: "center", padding: "28px 8px", letterSpacing: "0.05em" }}>— empty —</div>
                    : cards.map((r) => {
                      const advice = r.category === "ADVICE";
                      return (
                        <Link key={r.id} href={`/t/${r.id}`} style={{ textDecoration: "none",
                          padding: 10, background: "var(--surface-2)", border: "1px solid var(--line)",
                          borderLeft: `3px solid ${prioColor(r.priority)}`, borderRadius: 6, display: "block" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                            <span className="mono" style={{ fontSize: 9.5, color: "var(--accent-ink)", fontWeight: 600 }}>{r.ref}</span>
                            {r.risk_band && r.category === "CONTRACT" && (
                              <span title={`risk ${r.risk_score}/100`} style={{ width: 7, height: 7, borderRadius: "50%", background: bandColor(r.risk_band), alignSelf: "center" }} />
                            )}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--ink)", lineHeight: 1.4, marginBottom: 6, fontWeight: 500, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                            {advice ? (r.purpose || r.type_label || "Legal question") : r.counterparty_name}
                          </div>
                          <div style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap" }}>
                            <LanePill lane={r.lane} />
                            <span className="pill accent">{(r.type_label || r.type).split(" / ")[0]}</span>
                            {r.round > 1 && <span className="pill accent">↺{r.round}</span>}
                          </div>
                          <div className="mono" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 9, color: "var(--faint)", borderTop: "1px solid var(--line)", paddingTop: 5 }}>
                            <span>{r.assigned_to_name || "unassigned"}</span>
                            <span>{ageLabel(r.created_at)}</span>
                          </div>
                        </Link>
                      );
                    })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ═════════════ Pool Ops — capacity & utilization per assignee ═════════════ */
function PoolOpsTab({ rows, staff }: { rows: RequestSummary[]; staff: AssignableUser[] }) {
  const openRows = rows.filter(isOpen);
  const unassigned = openRows.filter((r) => !r.assigned_to_user_id);
  const byUser = useMemo(() => {
    const m = new Map<string, RequestSummary[]>();
    openRows.forEach((r) => { if (r.assigned_to_user_id) { const a = m.get(r.assigned_to_user_id) || []; a.push(r); m.set(r.assigned_to_user_id, a); } });
    return m;
  }, [rows]);
  const maxLoad = Math.max(1, ...staff.map((u) => (byUser.get(u.id) || []).length));

  const mixOf = (list: RequestSummary[], lane: string) => list.filter((r) => r.lane === lane).length;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 16 }}>
        <Stat label="Open in flight" value={openRows.length} />
        <Stat label="Assigned" value={openRows.length - unassigned.length} color="var(--teal)" />
        <Stat label="Unassigned" value={unassigned.length} color={unassigned.length ? "var(--warn)" : "var(--good)"} />
        <Stat label="Reviewers" value={staff.length} />
      </div>

      <div className="card card-pad">
        <div className="kicker" style={{ marginBottom: 12 }}>Reviewer utilization — open requests carried now</div>
        {staff.map((u) => {
          const list = byUser.get(u.id) || [];
          const pct = Math.round((list.length / maxLoad) * 100);
          const load = list.length;
          const barColor = load >= maxLoad && maxLoad > 2 ? "var(--crit)" : load >= Math.ceil(maxLoad * 0.7) ? "var(--warn)" : "var(--good)";
          return (
            <div key={u.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
              <div style={{ flex: "0 0 200px", minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.name}</div>
                <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{u.role.replace(/_/g, " ")}</div>
              </div>
              <div style={{ flex: 1, height: 7, background: "var(--surface-2)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${pct}%`, height: "100%", background: barColor, transition: "width .3s" }} />
              </div>
              <div style={{ flex: "0 0 190px", display: "flex", gap: 5, justifyContent: "flex-end", flexWrap: "wrap" }}>
                {mixOf(list, "ESCALATED") > 0 && <span className="pill escalated">{mixOf(list, "ESCALATED")} esc</span>}
                {mixOf(list, "ASSISTED") > 0 && <span className="pill assisted">{mixOf(list, "ASSISTED")} ast</span>}
                {mixOf(list, "AUTO") > 0 && <span className="pill auto">{mixOf(list, "AUTO")} auto</span>}
                <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: barColor, minWidth: 22, textAlign: "right" }}>{load}</span>
              </div>
            </div>
          );
        })}
        {staff.length === 0 && <div className="muted" style={{ fontSize: 13 }}>No reviewers available.</div>}
      </div>

      {unassigned.length > 0 && (
        <div className="card card-pad" style={{ marginTop: 12, borderLeft: "3px solid var(--warn)" }}>
          <div className="kicker" style={{ marginBottom: 8 }}>⚠ {unassigned.length} unassigned — overflow pressure</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {unassigned.slice(0, 24).map((r) => (
              <Link key={r.id} href={`/t/${r.id}`} className="pill state" style={{ textDecoration: "none" }}>{r.ref}</Link>
            ))}
            {unassigned.length > 24 && <span className="faint" style={{ fontSize: 12 }}>+{unassigned.length - 24} more</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═════════════ Smart Routing — rules (read-only; edit at /admin/routing) ═════════════ */
function RoutingTab({ rules, canManage, forbidden }: { rules: RoutingRuleOut[]; canManage: boolean; forbidden: boolean }) {
  if (forbidden) {
    return (
      <div className="card card-pad muted" style={{ textAlign: "center", padding: 34, borderLeft: "3px solid var(--purple)" }}>
        <div className="h-serif" style={{ fontSize: 20, color: "var(--ink)", marginBottom: 6 }}>Routing is legal-ops managed</div>
        <p style={{ fontSize: 13 }}>Viewing and editing smart-routing rules needs the <span className="mono">intake:manage</span> permission.</p>
      </div>
    );
  }
  const conds = (r: RoutingRuleOut) => {
    const c: string[] = [];
    if (r.match_type_key) c.push(`type = ${r.match_type_key}`);
    if (r.match_direction) c.push(`direction = ${r.match_direction.toLowerCase()}`);
    if (r.match_keyword) c.push(`keyword ~ "${r.match_keyword}"`);
    if (r.match_jurisdiction) c.push(`jurisdiction = ${r.match_jurisdiction}`);
    return c.length ? c : ["any request"];
  };
  const acts = (r: RoutingRuleOut) => {
    const a: string[] = [];
    if (r.set_assignee_name) a.push(`assign → ${r.set_assignee_name}`);
    if (r.set_priority) a.push(`priority → ${r.set_priority.toLowerCase()}`);
    if (r.set_sla_hours != null) a.push(`SLA → ${r.set_sla_hours}h`);
    if (r.escalate) a.push("escalate");
    return a.length ? a : ["(no action)"];
  };
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{rules.length} rule{rules.length === 1 ? "" : "s"} · evaluated in order after intake & classification</div>
        {canManage && <Link href="/admin/routing" className="btn sm primary">Edit rules →</Link>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rules.map((r) => (
          <div key={r.id} className="card card-pad" style={{ borderLeft: `3px solid ${r.active ? "var(--purple)" : "var(--line)"}`, opacity: r.active ? 1 : 0.55 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>#{r.ordinal}</span>
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>{r.name}</span>
              {!r.active && <span className="pill state">paused</span>}
              {r.stop_on_match && <span className="pill accent" title="Stop evaluating further rules on match">stop-on-match</span>}
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div className="mono" style={{ fontSize: 9, color: "var(--faint)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4 }}>When</div>
                {conds(r).map((c, i) => <div key={i} className="mono" style={{ fontSize: 12, color: "var(--teal)" }}>{c}</div>)}
              </div>
              <div style={{ alignSelf: "center", color: "var(--faint)" }}>→</div>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div className="mono" style={{ fontSize: 9, color: "var(--faint)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4 }}>Then</div>
                {acts(r).map((a, i) => <div key={i} className="mono" style={{ fontSize: 12, color: "var(--accent-ink)" }}>{a}</div>)}
              </div>
            </div>
          </div>
        ))}
        {rules.length === 0 && (
          <div className="card card-pad muted" style={{ textAlign: "center", padding: 30 }}>
            No routing rules yet.{canManage && <> <Link href="/admin/routing" style={{ color: "var(--accent)" }}>Create one →</Link></>}
          </div>
        )}
      </div>
    </div>
  );
}

/* ═════════════ Teams — the reviewer roster grouped by role ═════════════ */
function TeamsTab({ rows, staff }: { rows: RequestSummary[]; staff: AssignableUser[] }) {
  const openRows = rows.filter(isOpen);
  const loadOf = (uid: string) => openRows.filter((r) => r.assigned_to_user_id === uid).length;
  const groups = useMemo(() => {
    const m = new Map<string, AssignableUser[]>();
    staff.forEach((u) => { const a = m.get(u.role) || []; a.push(u); m.set(u.role, a); });
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [staff]);
  const roleColor = (role: string) => role.includes("gc") ? "var(--crit)" : role.includes("vp") ? "var(--purple)" : role.includes("attorney") ? "var(--teal)" : role.includes("paralegal") ? "var(--blue)" : "var(--amber)";

  return (
    <div>
      <div className="mono" style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
        {staff.length} people across {groups.length} role pools · load = open requests assigned now
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
        {groups.map(([role, members]) => {
          const total = members.reduce((n, u) => n + loadOf(u.id), 0);
          return (
            <div key={role} className="card card-pad" style={{ borderTop: `3px solid ${roleColor(role)}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                <span className="h-serif" style={{ fontSize: 17, textTransform: "capitalize" }}>{role.replace(/_/g, " ")}</span>
                <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>{members.length} · {total} open</span>
              </div>
              {members.map((u) => {
                const load = loadOf(u.id);
                return (
                  <div key={u.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                    <span style={{ fontSize: 13, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{u.name}</span>
                    <span className="mono" style={{ fontSize: 11, color: load === 0 ? "var(--faint)" : load >= 4 ? "var(--warn)" : "var(--teal)", flexShrink: 0 }}>{load} open</span>
                  </div>
                );
              })}
            </div>
          );
        })}
        {groups.length === 0 && <div className="muted">No people to show.</div>}
      </div>
    </div>
  );
}

/* ═════════════ Request Types — the intake catalog ═════════════ */
function RequestTypesTab({ types, rows }: { types: RequestTypeInfo[]; rows: RequestSummary[] }) {
  const countOf = (key: string) => rows.filter((r) => r.type === key).length;
  const contract = types.filter((t) => t.category === "CONTRACT");
  const advice = types.filter((t) => t.category === "ADVICE");
  const Section = ({ label, list, color }: { label: string; list: RequestTypeInfo[]; color: string }) => (
    <div style={{ marginBottom: 18 }}>
      <div className="kicker" style={{ marginBottom: 10, color }}>{label} · {list.length}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
        {list.map((t) => (
          <div key={t.key} className="card card-pad" style={{ borderLeft: `3px solid ${color}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>{t.label}</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--faint)", flexShrink: 0 }}>{countOf(t.key)} filed</span>
            </div>
            <div className="mono" style={{ fontSize: 10, color: "var(--faint)", marginBottom: 6 }}>{t.key} · SLA {t.default_sla_hours}h</div>
            <p style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.5, margin: 0 }}>{t.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
  return (
    <div>
      <div className="mono" style={{ fontSize: 11, color: "var(--muted)", marginBottom: 14 }}>
        {types.length} request types · CONTRACT types run a drafting/redline engine · ADVICE types run the resolution engine
      </div>
      <Section label="Contract engines" list={contract} color="var(--accent)" />
      <Section label="Advice engines" list={advice} color="var(--teal)" />
      {types.length === 0 && <div className="muted">No request types configured.</div>}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="card card-pad" style={{ padding: "12px 14px" }}>
      <div className="mono" style={{ fontSize: 9, color: "var(--faint)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
      <div className="h-serif" style={{ fontSize: 26, color: color || "var(--ink)", lineHeight: 1 }}>{value}</div>
    </div>
  );
}

/* ═════════════ shell ═════════════ */
type TabId = "board" | "poolops" | "routing" | "teams" | "types";
const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "board", label: "Board", icon: "▦" },
  { id: "poolops", label: "Pool Ops", icon: "◉" },
  { id: "routing", label: "Smart Routing", icon: "▶" },
  { id: "teams", label: "Teams", icon: "◈" },
  { id: "types", label: "Request Types", icon: "◆" },
];

export default function Workspace() {
  const [tab, setTab] = useState<TabId>("board");
  const [rows, setRows] = useState<RequestSummary[]>([]);
  const [staff, setStaff] = useState<AssignableUser[]>([]);
  const [rules, setRules] = useState<RoutingRuleOut[]>([]);
  const [types, setTypes] = useState<RequestTypeInfo[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [routingForbidden, setRoutingForbidden] = useState(false);

  useEffect(() => {
    const load = () => api.listRequests().then(setRows).catch(() => {});
    load();
    api.assignableUsers().then(setStaff).catch(() => {});
    api.requestTypes().then(setTypes).catch(() => {});
    // routing rules need intake:manage — a 403 means "not permitted to view", NOT "no rules exist"
    api.me().then((u) => {
      const manage = u.permissions.includes("intake:manage");
      setCanManage(manage);
      if (manage) api.listRoutingRules().then(setRules).catch(() => setRoutingForbidden(true));
      else setRoutingForbidden(true);
    }).catch(() => setRoutingForbidden(true));
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <div className="page-head">
        <div className="page-head-row">
          <div>
            <p className="kicker">Legal operations</p>
            <h1>Intake workspace</h1>
          </div>
          <Link href="/cockpit" className="btn sm">Open Triage Cockpit →</Link>
        </div>
      </div>

      <nav className="ws-tabs" aria-label="Workspace sections">
        {TABS.map((t) => (
          <button key={t.id} className={`ws-tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)} aria-current={tab === t.id ? "page" : undefined}>
            <span style={{ fontSize: 12 }}>{t.icon}</span> {t.label}
          </button>
        ))}
      </nav>

      {tab === "board" && <BoardTab rows={rows} />}
      {tab === "poolops" && <PoolOpsTab rows={rows} staff={staff} />}
      {tab === "routing" && <RoutingTab rules={rules} canManage={canManage} forbidden={routingForbidden} />}
      {tab === "teams" && <TeamsTab rows={rows} staff={staff} />}
      {tab === "types" && <RequestTypesTab types={types} rows={rows} />}
    </div>
  );
}
