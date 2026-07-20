"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type ContractRegistry,
  type Decision,
  type DecisionFeed,
  type OpsSummary,
  type RequestSummary,
} from "../lib/api";
import { useAuth } from "../lib/auth";

/* ─────────────── shared bits ─────────────── */
const KIND: Record<string, { icon: string; color: string; label: string }> = {
  advice_answer: { icon: "◈", color: "var(--teal)", label: "Advice answer" },
  redlines: { icon: "▤", color: "var(--accent)", label: "Redlines" },
  ready_to_send: { icon: "➤", color: "var(--good)", label: "Ready to send" },
  renewal: { icon: "↻", color: "var(--amber)", label: "Renewal" },
};
const sevColor = (s: string) => (s === "critical" ? "var(--crit)" : s === "warn" ? "var(--warn)" : "var(--teal)");
const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
const firstName = (n: string) => (n || "").trim().split(/\s+/)[0] || "there";
const fmtH = (h: number | null) => h === null ? "—" : h < 1 ? `${Math.round(h * 60)}m` : h < 72 ? `${h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h)}h` : `${(h / 24).toFixed(1)}d`;
const pct = (r: number | null) => (r === null ? null : Math.round(r * 100));

function brief(f: DecisionFeed): string {
  const k = f.summary.by_kind;
  if (f.summary.total === 0) return "Nothing awaits your decision — the AI is caught up. Inbox zero.";
  const parts: string[] = [];
  if (k.redlines) parts.push(`${k.redlines} set${k.redlines > 1 ? "s" : ""} of redlines to clear`);
  if (k.ready_to_send) parts.push(`${k.ready_to_send} cleared to send`);
  if (k.advice_answer) parts.push(`${k.advice_answer} drafted answer${k.advice_answer > 1 ? "s" : ""} to approve`);
  if (k.renewal) parts.push(`${k.renewal} renewal${k.renewal > 1 ? "s" : ""} due`);
  const lead = f.summary.critical > 0 ? `${f.summary.critical} need${f.summary.critical === 1 ? "s" : ""} you first — ` : "";
  return lead + parts.join(" · ") + ".";
}

function Sparkline({ data }: { data: number[] }) {
  const W = 120, H = 34, max = Math.max(1, ...data);
  const pts = data.map((v, i) => [(i / Math.max(1, data.length - 1)) * W, H - (v / max) * (H - 4) - 2] as const);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: W, height: H }} aria-hidden="true">
      <defs><linearGradient id="dashg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity="0.22" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
      <path d={`${line} L${W},${H} L0,${H} Z`} fill="url(#dashg)" />
      <path d={line} fill="none" style={{ stroke: "var(--accent)" }} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* pipeline buckets — the Ops board, collapsed to a stage strip */
const STAGES: { key: string; label: string; states: string[] }[] = [
  { key: "intake", label: "Intake", states: ["NEW", "CLASSIFIED", "ROUTED"] },
  { key: "drafting", label: "Drafting", states: ["DRAFTED"] },
  { key: "review", label: "In review", states: ["IN_REVIEW", "RETURNED"] },
  { key: "counterparty", label: "With counterparty", states: ["WITH_COUNTERPARTY", "OUT_FOR_SIGNATURE"] },
  { key: "approved", label: "Ready / signed", states: ["APPROVED", "EXECUTED"] },
];
const TERMINAL = new Set(["FILED", "EXECUTED", "CLOSED", "CANCELLED", "DONE"]);
const CSTATUS: Record<string, string> = { active: "good", expiring: "warn", expired: "crit", renewed: "accent" };

export default function Home() {
  const { user } = useAuth();
  const [feed, setFeed] = useState<DecisionFeed | null>(null);
  const [reqs, setReqs] = useState<RequestSummary[] | null>(null);
  const [ops, setOps] = useState<OpsSummary | null>(null);
  const [contracts, setContracts] = useState<ContractRegistry | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const loadFeed = useCallback(() => api.decisions().then(setFeed).catch(() => setFeed({ decisions: [], summary: { total: 0, critical: 0, by_kind: {} } })), []);
  const loadRest = useCallback(() => {
    api.listRequests().then(setReqs).catch(() => setReqs([]));
    api.opsSummary().then(setOps).catch(() => setOps(null));
    api.contracts().then(setContracts).catch(() => setContracts(null));
  }, []);
  useEffect(() => { loadFeed(); loadRest(); const t = setInterval(loadFeed, 12000); return () => clearInterval(t); }, [loadFeed, loadRest]);

  async function act(d: Decision, key: string) {
    if (key === "open") { window.location.href = `/t/${d.request_id}`; return; }
    if (key === "review") { window.location.href = `/review/${d.request_id}`; return; }
    if (key === "edit") { setEditing(d.id); setDraft(String(d.meta.draft || "")); return; }
    setBusy(d.id);
    try {
      if (key === "approve") await api.resolveAdvice(d.request_id, String(d.meta.draft || ""));
      else if (key === "send") await api.send(d.request_id);
      else if (key === "renew") await api.renewContract(d.request_id);
      await loadFeed(); loadRest();
    } catch {} finally { setBusy(null); }
  }
  async function saveEdit(d: Decision) {
    if (!draft.trim()) return;
    setBusy(d.id);
    try { await api.resolveAdvice(d.request_id, draft); setEditing(null); await loadFeed(); } catch {} finally { setBusy(null); }
  }

  const open = useMemo(() => (reqs ?? []).filter((r) => !TERMINAL.has(r.state)), [reqs]);
  const queue = useMemo(() => {
    const rank = { URGENT: 0, HIGH: 1, NORMAL: 2, LOW: 3 } as Record<string, number>;
    return [...open].sort((a, b) => (rank[a.priority] ?? 2) - (rank[b.priority] ?? 2) || +new Date(a.created_at) - +new Date(b.created_at)).slice(0, 7);
  }, [open]);
  const stageCounts = useMemo(() => STAGES.map((s) => ({ ...s, n: open.filter((r) => s.states.includes(r.state)).length })), [open]);
  const reviewers = useMemo(() => {
    const m = new Map<string, number>();
    let unassigned = 0;
    for (const r of open) { if (r.assigned_to_name) m.set(r.assigned_to_name, (m.get(r.assigned_to_name) ?? 0) + 1); else unassigned++; }
    const rows = [...m.entries()].map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n).slice(0, 5);
    return { rows, unassigned, max: Math.max(1, ...rows.map((r) => r.n), unassigned) };
  }, [open]);
  const dueContracts = useMemo(() => (contracts?.rows ?? []).filter((r) => r.status === "expiring" || r.status === "expired").slice(0, 4), [contracts]);
  const decisions = feed?.decisions ?? [];
  const shownDecisions = decisions.slice(0, 6);

  return (
    <div>
      {/* header + brief */}
      <div className="page-head" style={{ marginBottom: 6 }}>
        <p className="kicker">Operations · your legal day at a glance</p>
        <h1 className="h-serif" style={{ fontSize: 30 }}>{greeting()}, {firstName(user?.name || "")}</h1>
      </div>
      {feed && (
        <div className="brief-strip">
          <span style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.5 }}>{brief(feed)}</span>
        </div>
      )}

      {/* KPI tiles */}
      <div className="stat-grid" style={{ margin: "16px 0" }}>
        <div className="stat"><div className="lbl">Needs you</div><div className="val accent">{feed ? feed.summary.total : "—"}</div><div className="mono" style={{ fontSize: 11, color: feed && feed.summary.critical ? "var(--crit)" : "var(--faint)", marginTop: 2 }}>{feed?.summary.critical ? `${feed.summary.critical} critical` : "nothing critical"}</div></div>
        <div className="stat"><div className="lbl">Open in pipeline</div><div className="val">{reqs ? open.length : "—"}</div><div className="mono" style={{ fontSize: 11, color: "var(--faint)", marginTop: 2 }}>{reqs ? `${reqs.length} all-time` : ""}</div></div>
        <div className="stat"><div className="lbl">Deflection</div><div className="val accent">{ops ? `${pct(ops.deflection_rate)}%` : "—"}</div><div className="mono" style={{ fontSize: 11, color: "var(--faint)", marginTop: 2 }}>{ops ? `${ops.totals.auto_resolved} auto-resolved` : ""}</div></div>
        <div className="stat"><div className="lbl">SLA compliance</div><div className="val">{ops ? (pct(ops.sla.compliance_rate) === null ? "—" : `${pct(ops.sla.compliance_rate)}%`) : "—"}</div><div className="mono" style={{ fontSize: 11, color: ops && ops.sla.breached ? "var(--crit)" : "var(--faint)", marginTop: 2 }}>{ops ? `${ops.sla.breached} breached · ${ops.sla.at_risk} at risk` : ""}</div></div>
        <div className="stat"><div className="lbl">Avg cycle time</div><div className="val">{ops ? fmtH(ops.sla.avg_cycle_hours) : "—"}</div><div className="mono" style={{ fontSize: 11, color: "var(--faint)", marginTop: 2 }}>resolution clock</div></div>
        <div className="stat"><div className="lbl">Contracts due</div><div className="val" style={{ color: contracts && (contracts.totals.expiring + contracts.totals.expired) ? "var(--warn)" : undefined }}>{contracts ? contracts.totals.expiring + contracts.totals.expired : "—"}</div><div className="mono" style={{ fontSize: 11, color: "var(--faint)", marginTop: 2 }}>{contracts ? `${contracts.totals.active} active · ${contracts.totals.expired} expired` : ""}</div></div>
      </div>

      {/* pipeline strip (the Ops board, collapsed) */}
      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span className="kicker">Pipeline</span>
          <Link href="/workspace" className="linkish" style={{ fontSize: 11.5 }}>Ops workspace →</Link>
        </div>
        <div className="pipe-row">
          {stageCounts.map((s, i) => (
            <div key={s.key} className="pipe-stage">
              <div className="pipe-n tnum">{reqs ? s.n : "—"}</div>
              <div className="pipe-lbl">{s.label}</div>
              {i < stageCounts.length - 1 && <span className="pipe-arrow">→</span>}
            </div>
          ))}
        </div>
      </div>

      {/* main grid: decisions + queue | rail */}
      <div className="dash-grid">
        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Decisions awaiting you */}
          <section>
            <div className="dash-sec-head">
              <span className="kicker">Decisions awaiting you {feed && <span className="faint">· {feed.summary.total}</span>}</span>
              {decisions.length > shownDecisions.length && <Link href="/inbox" className="linkish" style={{ fontSize: 11.5 }}>see all in queue →</Link>}
            </div>
            {!feed ? <div className="muted" style={{ padding: 16 }}>Loading…</div>
              : decisions.length === 0 ? (
                <div className="card card-pad" style={{ textAlign: "center", padding: 32, borderLeft: "3px solid var(--good)" }}>
                  <div style={{ fontSize: 26, marginBottom: 6 }}>✓</div>
                  <div className="h-serif" style={{ fontSize: 19, marginBottom: 4 }}>Inbox zero</div>
                  <p className="muted" style={{ fontSize: 12.5 }}>The AI is caught up — nothing needs your decision right now.</p>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {shownDecisions.map((d) => {
                    const meta = KIND[d.kind] || { icon: "•", color: "var(--muted)", label: d.kind };
                    const isEditing = editing === d.id;
                    return (
                      <div key={d.id} className="card card-pad decision-card" style={{ borderLeft: `3px solid ${sevColor(d.severity)}` }}>
                        <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                          <span className="dec-ic" style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 14%, transparent)` }}>{meta.icon}</span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 3 }}>
                              <span className="mono" style={{ fontSize: 9.5, color: "var(--faint)", letterSpacing: "0.06em" }}>{d.actor}</span>
                              <Link href={`/t/${d.request_id}`} className="mono" style={{ fontSize: 11.5, color: "var(--accent-ink)", fontWeight: 600, textDecoration: "none" }}>{d.ref}</Link>
                              <span style={{ fontSize: 13, color: "var(--ink)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.title}</span>
                            </div>
                            <div style={{ fontSize: 13, color: "var(--ink)", marginBottom: 2 }}>{d.headline}</div>
                            <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>{d.detail}</div>
                            {isEditing ? (
                              <div style={{ marginTop: 10 }}>
                                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} style={{ width: "100%", fontSize: 13, lineHeight: 1.5 }} />
                                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                                  <button className="btn primary sm" disabled={busy === d.id || !draft.trim()} onClick={() => saveEdit(d)}>Save &amp; approve</button>
                                  <button className="btn ghost sm" onClick={() => setEditing(null)}>Cancel</button>
                                </div>
                              </div>
                            ) : (
                              <div style={{ display: "flex", gap: 7, marginTop: 9, flexWrap: "wrap" }}>
                                {d.actions.map((a) => (
                                  <button key={a.key} disabled={busy === d.id} className={`btn sm ${a.primary ? "primary" : a.key === "reject" ? "ghost" : ""}`} onClick={() => act(d, a.key)}>{a.label}</button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
          </section>

          {/* Live intake queue */}
          <section>
            <div className="dash-sec-head">
              <span className="kicker">Intake queue {reqs && <span className="faint">· {open.length} open</span>}</span>
              <span style={{ display: "flex", gap: 12 }}>
                <Link href="/cockpit" className="linkish" style={{ fontSize: 11.5 }}>Triage in cockpit →</Link>
                <Link href="/inbox" className="linkish" style={{ fontSize: 11.5 }}>see all →</Link>
              </span>
            </div>
            <div className="card" style={{ overflow: "hidden" }}>
              {!reqs ? <div className="muted" style={{ padding: 16 }}>Loading…</div>
                : queue.length === 0 ? <div className="muted" style={{ padding: 20, fontSize: 13 }}>Queue is clear — no open requests.</div>
                : (
                  <table className="tbl">
                    <thead><tr><th>Ref</th><th>Counterparty / subject</th><th>Lane</th><th>Priority</th><th>State</th></tr></thead>
                    <tbody>
                      {queue.map((r) => (
                        <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => (window.location.href = `/t/${r.id}`)}>
                          <td className="ref">{r.ref}</td>
                          <td><span className="cp">{r.category === "ADVICE" ? (r.purpose || "Advice request") : r.counterparty_name}</span></td>
                          <td>{r.lane ? <span className="pill state">{r.lane}</span> : <span className="faint">—</span>}</td>
                          <td><span className={`pill ${r.priority === "URGENT" || r.priority === "HIGH" ? "crit" : r.priority === "NORMAL" ? "state" : "state"}`} style={{ textTransform: "capitalize" }}>{r.priority.toLowerCase()}</span></td>
                          <td><span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </div>
          </section>
        </div>

        {/* rail */}
        <aside style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* SLA health */}
          <div className="card card-pad">
            <div className="dash-sec-head" style={{ margin: 0 }}>
              <span className="kicker">SLA health</span>
              <Link href="/sla" className="linkish" style={{ fontSize: 11.5 }}>see all →</Link>
            </div>
            {!ops ? <div className="muted" style={{ padding: "12px 0", fontSize: 12.5 }}>—</div> : (
              <>
                <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 10 }}>
                  <div><div className="val tnum" style={{ fontSize: 26, fontWeight: 680 }}>{pct(ops.sla.compliance_rate) === null ? "—" : `${pct(ops.sla.compliance_rate)}%`}</div><div className="mono" style={{ fontSize: 10.5, color: "var(--faint)" }}>compliance</div></div>
                  <Sparkline data={ops.volume_7d} />
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
                  <span className="pill crit">{ops.sla.breached} breached</span>
                  <span className="pill warn">{ops.sla.at_risk} at risk</span>
                  <span className="pill good">{ops.sla.on_track} on track</span>
                </div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 10 }}>avg cycle {fmtH(ops.sla.avg_cycle_hours)} · {ops.volume_7d.reduce((a, b) => a + b, 0)} in 7d</div>
              </>
            )}
          </div>

          {/* Reviewer pool */}
          <div className="card card-pad">
            <div className="dash-sec-head" style={{ margin: 0 }}>
              <span className="kicker">Reviewer pool</span>
              <Link href="/workspace" className="linkish" style={{ fontSize: 11.5 }}>see all →</Link>
            </div>
            {!reqs ? <div className="muted" style={{ padding: "12px 0", fontSize: 12.5 }}>—</div>
              : reviewers.rows.length === 0 && !reviewers.unassigned ? <div className="muted" style={{ padding: "10px 0", fontSize: 12.5 }}>No open work assigned.</div>
              : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
                  {reviewers.rows.map((r) => (
                    <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 12.5, color: "var(--ink)", minWidth: 96, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                      <span className="pool-bar"><span style={{ display: "block", height: "100%", width: `${(r.n / reviewers.max) * 100}%`, background: "var(--accent)", borderRadius: 4 }} /></span>
                      <span className="tnum" style={{ fontSize: 12, color: "var(--muted)", minWidth: 18, textAlign: "right" }}>{r.n}</span>
                    </div>
                  ))}
                  {reviewers.unassigned > 0 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 12.5, color: "var(--warn)", minWidth: 96 }}>Unassigned</span>
                      <span className="pool-bar"><span style={{ display: "block", height: "100%", width: `${(reviewers.unassigned / reviewers.max) * 100}%`, background: "var(--warn)", borderRadius: 4 }} /></span>
                      <span className="tnum" style={{ fontSize: 12, color: "var(--warn)", minWidth: 18, textAlign: "right" }}>{reviewers.unassigned}</span>
                    </div>
                  )}
                </div>
              )}
          </div>

          {/* Contracts due */}
          <div className="card card-pad">
            <div className="dash-sec-head" style={{ margin: 0 }}>
              <span className="kicker">Contracts due</span>
              <Link href="/contracts" className="linkish" style={{ fontSize: 11.5 }}>see all →</Link>
            </div>
            {!contracts ? <div className="muted" style={{ padding: "12px 0", fontSize: 12.5 }}>—</div>
              : dueContracts.length === 0 ? <div className="muted" style={{ padding: "10px 0", fontSize: 12.5 }}>Nothing expiring soon.</div>
              : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
                  {dueContracts.map((c) => (
                    <Link key={c.id} href="/contracts" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, textDecoration: "none" }}>
                      <span style={{ minWidth: 0 }}>
                        <span className="mono" style={{ fontSize: 11, color: "var(--accent-ink)", fontWeight: 600 }}>{c.ref}</span>
                        <span style={{ fontSize: 12.5, color: "var(--ink)", marginLeft: 6 }}>{c.counterparty}</span>
                      </span>
                      <span className={`pill ${CSTATUS[c.status]}`} style={{ flexShrink: 0 }}>{c.days_left != null ? (c.days_left <= 0 ? "expired" : `${c.days_left}d`) : c.status}</span>
                    </Link>
                  ))}
                </div>
              )}
          </div>
        </aside>
      </div>
    </div>
  );
}
