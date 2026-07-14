"use client";
import { useEffect, useState } from "react";
import { api, type RequestDetail, type SlaLeg, type SlaLegs } from "../../lib/api";

/* ───────── SLA custody legs — one window, partitioned by the hand-off ledger ───────── */
const HOLDER_COLOR: Record<string, string> = { queue: "var(--muted)", agent: "var(--purple)", human: "var(--teal)" };
const HOLDER_ICON: Record<string, string> = { queue: "◍", agent: "🤖", human: "◉" };

function humanMs(ms: number): string {
  const m = Math.round(ms / 60000);
  if (m < 1) return "<1m";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function SlaLegsPanel({ requestId }: { requestId: string }) {
  const [data, setData] = useState<SlaLegs | null>(null);
  useEffect(() => { api.slaLegs(requestId).then(setData).catch(() => setData(null)); }, [requestId]);
  if (!data || !data.legs?.length) return null;
  const { legs, sla_ms, total_elapsed_ms, breached, closed } = data;
  const scaleMs = Math.max(total_elapsed_ms, sla_ms, 1);
  const breachLeftPct = Math.min((sla_ms / scaleMs) * 100, 100);

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
        <span className="kicker" style={{ color: "var(--teal)" }}>◔ SLA Custody Legs</span>
        <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.08em", color: breached ? "var(--crit)" : "var(--faint)" }}>
          {breached ? "WINDOW BREACHED" : closed ? "CLOCK STOPPED" : "CLOCK RUNNING"} · {humanMs(total_elapsed_ms)} elapsed
        </span>
      </div>

      {/* proportional custody bar, breach marker pinned at 100% of the window */}
      <div style={{ position: "relative", height: 14, background: "var(--surface-2)", borderRadius: 3, overflow: "hidden", marginBottom: 4 }}>
        <div style={{ display: "flex", height: "100%" }}>
          {legs.map((l, i) => (
            <div key={i} title={`${l.holder_label} · ${humanMs(l.elapsed_ms)} (${l.pct_of_sla}% of window)`}
              style={{
                width: `${(l.elapsed_ms / scaleMs) * 100}%`,
                background: HOLDER_COLOR[l.holder] ?? "var(--muted)",
                opacity: l.active ? 1 : 0.6,
                borderRight: i < legs.length - 1 ? "1px solid var(--surface)" : "none",
                minWidth: l.elapsed_ms > 0 ? 3 : 0,
              }} />
          ))}
        </div>
        {breachLeftPct < 100 && (
          <div title="SLA window expires here" style={{ position: "absolute", top: 0, bottom: 0, left: `${breachLeftPct}%`, width: 2, background: "var(--crit)" }} />
        )}
      </div>
      <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 8.5, color: "var(--faint)", marginBottom: 12 }}>
        <span>SUBMITTED</span>
        <span style={{ color: breached ? "var(--crit)" : "var(--faint)" }}>SLA {Math.round(sla_ms / 3600000)}h</span>
        <span>{closed ? "CLOSED" : "NOW"}</span>
      </div>

      {legs.map((l: SlaLeg, i) => (
        <div key={i} style={{
          display: "flex", alignItems: "center", gap: 8, padding: "5px 8px",
          background: l.active ? "var(--surface-2)" : "transparent", borderRadius: 4,
          borderLeft: `3px solid ${HOLDER_COLOR[l.holder] ?? "var(--muted)"}`, marginBottom: 3,
        }}>
          <span style={{ fontSize: 11, width: 18, textAlign: "center" }}>{HOLDER_ICON[l.holder] ?? "◍"}</span>
          <span style={{ fontSize: 12, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {l.holder_label}
            {l.active && <span className="mono" style={{ fontSize: 8.5, color: "var(--good)", marginLeft: 6, letterSpacing: "0.1em" }}>HOLDING NOW</span>}
            {l.breached_during_leg && <span className="mono" style={{ fontSize: 8.5, color: "var(--crit)", marginLeft: 6, letterSpacing: "0.1em" }}>⚠ BREACH HAPPENED HERE</span>}
          </span>
          <span className="mono" style={{ fontSize: 10.5, color: l.pct_of_sla >= 70 ? "var(--warn)" : "var(--ink-2)" }}>{humanMs(l.elapsed_ms)}</span>
          <span className="mono" style={{ fontSize: 9.5, color: "var(--faint)", width: 78, textAlign: "right" }}>{l.pct_of_sla}% of window</span>
        </div>
      ))}
      <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", marginTop: 10, lineHeight: 1.5 }}>
        Legs derive from the hand-off ledger — every baton pass starts a new clock segment. One window, no resets.
      </div>
    </div>
  );
}

/* ───────── Request Workflow stepper ───────── */
type Stage = { label: string; state: "done" | "active" | "todo" };

function stagesFor(r: RequestDetail): Stage[] {
  const s = r.state;
  const order = ["NEW", "CLASSIFIED", "ROUTED", "DRAFTED", "IN_REVIEW", "RETURNED", "APPROVED",
    "WITH_COUNTERPARTY", "OUT_FOR_SIGNATURE", "EXECUTED", "FILED"];
  const idx = order.indexOf(s);
  const at = (from: string) => idx >= order.indexOf(from);
  const advice = r.category === "ADVICE";
  const stages: [string, "done" | "active" | "todo"][] = [
    ["Submitted", idx >= 0 ? "done" : "active"],
    // agent analysis: classification / drafting / redline / risk score
    ["Agent Analysis", at("DRAFTED") || (advice && at("IN_REVIEW")) ? "done" : at("CLASSIFIED") ? "active" : "todo"],
    // attorney review: the human review + approvals
    ["Attorney Review", s === "APPROVED" || at("WITH_COUNTERPARTY") ? "done"
      : (s === "IN_REVIEW" || s === "RETURNED") ? "active" : "todo"],
    // close: signed & filed (or the advice answer approved)
    ["Close", s === "FILED" || s === "EXECUTED" || (advice && s === "APPROVED") ? "done"
      : (s === "OUT_FOR_SIGNATURE" || s === "APPROVED" || s === "WITH_COUNTERPARTY") ? "active" : "todo"],
  ];
  return stages.map(([label, state]) => ({ label, state }));
}

export function WorkflowStepper({ r }: { r: RequestDetail }) {
  const stages = stagesFor(r);
  return (
    <div>
      <div className="kicker" style={{ marginBottom: 10 }}>Request Workflow</div>
      <div style={{ display: "flex", gap: 3 }}>
        {stages.map((st, i) => {
          const color = st.state === "done" ? "var(--good)" : st.state === "active" ? "var(--warn)" : "var(--faint)";
          const bg = st.state === "done" ? "var(--good-bg)" : st.state === "active" ? "var(--warn-bg)" : "var(--surface-2)";
          return (
            <div key={i} style={{
              flex: 1, padding: "12px 8px", textAlign: "center", borderRadius: 6,
              background: bg, border: `1px solid ${st.state === "todo" ? "var(--line)" : color}`,
            }}>
              <div style={{ fontSize: 14, color, lineHeight: 1 }}>{st.state === "done" ? "✓" : st.state === "active" ? "⏳" : "○"}</div>
              <div style={{ fontSize: 11.5, color: st.state === "todo" ? "var(--faint)" : "var(--ink)", marginTop: 5, fontWeight: 500 }}>{st.label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
