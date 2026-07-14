"use client";
import { useState } from "react";
import type { RiskAssessment, TimelineEvent, WorkflowInstance, WorkflowRung } from "../../lib/api";

const KIND_LABEL: Record<string, string> = {
  D: "DETERMINISTIC", A: "AI", H: "HUMAN", T: "THIRD PARTY",
};

/* who is working a rung — mirrors the mockup's worker chips */
function workerFor(r: WorkflowRung): string {
  if (r.kind === "A") return "🤖 Agent";
  if (r.kind === "T") return "✉ Counterparty";
  if (r.kind === "H") return r.rung ? `👤 ${r.rung.replace(/_/g, " ")}` : "👤 Reviewer";
  return "⚙ System";
}

export function fmtSpent(seconds: number): string {
  if (!seconds || seconds < 1) return "";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const m = seconds / 60;
  if (m < 90) return `${Math.round(m)}m`;
  const h = m / 60;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${Math.round(h / 24)}d`;
}

/* ————— risk score badge: band pill + score, factor breakdown on click ————— */
export function RiskBadge({ risk }: { risk: RiskAssessment | null }) {
  const [open, setOpen] = useState(false);
  if (!risk) return null;
  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 6 }}>
      <button type="button" className={`rband ${risk.band}`} title="AI risk score — click for the factors"
        onClick={() => setOpen((v) => !v)}>
        ⚠ {risk.band} · {risk.score}/100{risk.round > 1 ? ` · r${risk.round}` : ""}
      </button>
      {open && (
        <div className="card" style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 40,
          width: "min(380px, 90vw)", maxHeight: 380, overflowY: "auto",
          padding: "12px 14px", boxShadow: "var(--shadow-lg)",
        }}>
          <div className="kicker" style={{ marginBottom: 6 }}>
            Risk factors — round {risk.round} · {risk.model === "deterministic" ? "deterministic" : `AI-adjusted (${risk.model})`}
          </div>
          {risk.factors.length === 0 && (
            <div className="muted" style={{ fontSize: 12.5 }}>On-playbook draft — every fact within policy. Nothing raised the score.</div>
          )}
          {risk.factors.map((f, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "4px 0", fontSize: 12.5, borderBottom: "1px dashed var(--line)" }}>
              <span className="tnum" style={{ fontWeight: 700, color: f.kind === "AI" ? "var(--k-a)" : "var(--ink)", minWidth: 34 }}>+{f.points}</span>
              <span style={{ flex: 1 }}>{f.label}</span>
              <span className={`tbadge ${f.kind === "AI" ? "A" : "D"}`}>{f.kind === "AI" ? "AI" : "DET"}</span>
            </div>
          ))}
          <p className="faint" style={{ fontSize: 11.5, margin: "8px 0 0" }}>
            The deterministic factors are the floor — the model may raise this score, never lower it.
          </p>
        </div>
      )}
    </span>
  );
}

/* ————— the matter ladder: node-on-rail, type-coloured, mockup-faithful ————— */
export function WorkflowRail({ wf, round }: { wf: WorkflowInstance | null; round: number }) {
  if (!wf || !wf.rungs?.length) return null;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 12 }}>
        <span className="kicker">Workflow ladder</span>
        <span className="faint mono" style={{ fontSize: 10.5 }}>
          {wf.template_name ?? "template"} · v{wf.version}{round > 1 ? ` · round ${round}` : ""}
        </span>
      </div>
      <div className="mladder">
        <span className="rail" />
        {wf.rungs.map((r) => {
          const spent = fmtSpent(r.spent_seconds);
          const nodeCls = r.status === "done" ? "done" : r.status === "waiting" ? "wait" : r.kind;
          return (
            <div key={r.key} className="rung-row">
              <span className={`rnode ${nodeCls}`}>{r.status === "done" ? "✓" : r.kind}</span>
              <div className={`rung-card ${r.kind} ${r.status === "waiting" ? "wait" : ""} ${r.status === "active" ? "active" : ""}`}>
                <div className="rung-head">
                  <span className="rung-title">{r.name}</span>
                  <span className={`tbadge ${r.kind}`}>{r.kind} · {KIND_LABEL[r.kind]}</span>
                  {r.mode === "pinned" && <span className="faint" style={{ fontSize: 10 }} title="Pinned — can never be removed">🔒</span>}
                  {r.round && r.round > 1 && <span className="rchip round mono">↺ ROUND {r.round}</span>}
                </div>
                {r.desc && <div className="rung-desc">{r.desc}</div>}
                <div className="rung-foot">
                  {r.status === "active" && <span className="rchip active"><span className="live-dot" /> in progress</span>}
                  {(r.status === "active" || r.kind === "H" || r.kind === "T") && r.status !== "done" && (
                    <span className="rchip worker">{workerFor(r)}</span>
                  )}
                  {spent && <span className="rchip time">⏱ {spent}</span>}
                  {r.sla_hours && r.status === "active" && <span className="rchip sla">SLA {r.sla_hours}h</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ————— the dark chain-sealed audit panel (mockup's audit column) ————— */
function actionLabel(a: string): string {
  return a.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
export function ChainLog({ events }: { events: TimelineEvent[] }) {
  const rows = events ?? [];
  return (
    <div className="chainlog">
      <h3>Chain-sealed audit log</h3>
      <div className="sub2">
        Every action hashes over the previous entry. One matter ID threads intake, rules, agents, humans and the counterparty.
      </div>
      {rows.map((e, i) => {
        const last = i === rows.length - 1;
        const meta = e.metadata || {};
        const detail = (meta.band || meta.risk_score) ? ` · risk ${meta.band ?? ""} ${meta.risk_score ?? ""}`.trimEnd()
          : meta.round && Number(meta.round) > 1 ? ` · round ${meta.round}` : "";
        return (
          <div key={i} className="cl-entry">
            <span className={`cl-dot ${last ? "last" : ""}`} />
            {!last && <span className="cl-line" />}
            <div className="cl-meta">
              {new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {e.actor_label}
            </div>
            <div className="cl-action">{actionLabel(e.action)}{detail}</div>
            <div className="cl-hash">#{String(e.chain_position).padStart(4, "0")} ⛓ sealed</div>
          </div>
        );
      })}
      {rows.length === 0 && <div className="cl-action" style={{ opacity: 0.6 }}>No events yet.</div>}
    </div>
  );
}
