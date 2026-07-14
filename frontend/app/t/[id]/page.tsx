"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type RequestDetail, type SlaLegs } from "../../../lib/api";
import { ChainLog, RiskBadge } from "../../components/Workflow";
import { SlaLegsPanel, WorkflowStepper } from "../../components/Intake";

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return null;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane}</span>;
}
function humanMs(ms: number): string {
  const m = Math.round(ms / 60000);
  if (m < 60) return `${Math.max(m, 0)}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export default function TicketDetail({ params }: { params: { id: string } }) {
  const [r, setR] = useState<RequestDetail | null>(null);
  const [legs, setLegs] = useState<SlaLegs | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    api.getRequest(params.id).then(setR).catch((e) => setErr(String(e)));
    api.slaLegs(params.id).then(setLegs).catch(() => setLegs(null));
  }, [params.id]);
  useEffect(() => { load(); }, [load]);

  if (err) return <div className="container"><div className="notice warn">{err}</div></div>;
  if (!r) return <div className="container muted">Loading…</div>;

  const advice = r.category === "ADVICE";
  const pctElapsed = legs && legs.sla_ms > 0 ? Math.round((legs.total_elapsed_ms / legs.sla_ms) * 100) : null;
  const overdue = !!legs?.breached && !legs?.closed;
  const clockColor = overdue ? "var(--crit)" : legs?.closed ? "var(--good)" : pctElapsed && pctElapsed > 75 ? "var(--warn)" : "var(--ink)";

  return (
    <div className="container">
      <Link href="/inbox" className="mono" style={{ fontSize: 12, color: "var(--teal)" }}>← Back to Inbox</Link>

      {/* header strip: pills + SLA clock */}
      <div className="card card-pad" style={{ marginTop: 12, borderLeft: `3px solid ${overdue ? "var(--crit)" : "var(--accent)"}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <span className="mono" style={{ color: "var(--accent-ink)", fontWeight: 600, fontSize: 13 }}>{r.ref}</span>
              {!advice && <LanePill lane={r.lane} />}
              {!advice && <RiskBadge risk={r.risk} />}
              <span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span>
              {r.type_label && <span className="pill accent">{r.type_label.split(" / ")[0]}</span>}
              {r.round > 1 && <span className="pill accent">↺ round {r.round}</span>}
            </div>
            <h1 className="h-serif" style={{ fontSize: 24, margin: "2px 0 6px" }}>
              {advice ? (r.type_label || "Legal request") : r.counterparty_name}
            </h1>
            <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
              From {r.requester_name} · Submitted {new Date(r.created_at).toISOString().slice(0, 19).replace("T", " ")}Z
              {r.assigned_to_name ? ` · Assigned to ${r.assigned_to_name}` : ""}
            </div>
          </div>
          {legs && (
            <div style={{ textAlign: "right" }}>
              <div className="mono" style={{ fontSize: 9, letterSpacing: "0.14em", color: overdue ? "var(--crit)" : "var(--faint)" }}>
                {overdue ? "SLA OVERDUE" : legs.closed ? "SLA MET" : "SLA WINDOW"}
              </div>
              <div className="h-serif" style={{ fontSize: 34, color: clockColor, lineHeight: 1.1 }}>{humanMs(legs.total_elapsed_ms)}</div>
              <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)" }}>of {legs.sla_hours} hrs window</div>
              {pctElapsed !== null && (
                <div className="mono" style={{ fontSize: 9.5, color: overdue ? "var(--crit)" : "var(--muted)", marginTop: 2 }}>{pctElapsed}% elapsed</div>
              )}
            </div>
          )}
        </div>
        {!advice && (
          <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link href={`/review/${r.id}`} className="btn primary sm">Open redline cockpit →</Link>
            <Link href={`/r/${r.id}`} className="btn ghost sm">Requester status view</Link>
          </div>
        )}
      </div>

      {/* Request Workflow stepper */}
      <div className="card card-pad" style={{ marginTop: 14 }}>
        <WorkflowStepper r={r} />
      </div>

      {/* two columns: SLA custody legs + chain-sealed timeline */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 14, alignItems: "start" }}>
        <SlaLegsPanel requestId={r.id} />
        <ChainLog events={r.timeline} />
      </div>
    </div>
  );
}
