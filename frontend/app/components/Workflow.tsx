"use client";
import { useState } from "react";
import type { RiskAssessment, WorkflowInstance, WorkflowRung } from "../../lib/api";

/* ————— risk band colors (matches the pill classes in globals.css) ————— */
export const BAND_PILL: Record<string, string> = {
  LOW: "good", MEDIUM: "warn", HIGH: "crit", CRITICAL: "crit",
};
const KIND_LABEL: Record<string, string> = {
  D: "DETERMINISTIC", A: "AI", H: "HUMAN", T: "THIRD PARTY",
};
const KIND_COLOR: Record<string, string> = {
  D: "var(--warn-ink, #9E6D12)", A: "#3E6FB0", H: "#6C4E9E", T: "#2E7D74",
};

export function fmtSpent(seconds: number): string {
  if (!seconds || seconds < 1) return "";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const m = seconds / 60;
  if (m < 90) return `${Math.round(m)}m`;
  const h = m / 60;
  if (h < 48) return `${h.toFixed(1)}h`;
  return `${Math.round(h / 24)}d`;
}

/* ————— the risk score badge: band pill + score, factors on toggle ————— */
export function RiskBadge({ risk, compact = false }: { risk: RiskAssessment | null; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!risk) return null;
  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 6 }}>
      <button
        type="button"
        className={`pill ${BAND_PILL[risk.band] ?? "state"}`}
        style={{ cursor: "pointer" }}
        title="AI risk score — click for the factors"
        onClick={() => setOpen((v) => !v)}
      >
        ⚠ {risk.band} · {risk.score}/100{risk.round > 1 ? ` · r${risk.round}` : ""}
      </button>
      {open && (
        <div className="card" style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 40,
          width: "min(360px, 90vw)", maxHeight: 380, overflowY: "auto",
          padding: "12px 14px", boxShadow: "0 12px 32px rgba(0,0,0,.18)",
        }}>
          <div className="kicker" style={{ marginBottom: 6 }}>
            Risk factors — round {risk.round} · {risk.model === "deterministic" ? "deterministic" : `AI-adjusted (${risk.model})`}
          </div>
          {risk.factors.length === 0 && (
            <div className="muted" style={{ fontSize: 12.5 }}>On-playbook draft — all facts within policy. Nothing raised the score.</div>
          )}
          {risk.factors.map((f, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "3px 0", fontSize: 12.5, borderBottom: "1px dashed var(--hairline)" }}>
              <span className="tnum" style={{ fontWeight: 700, color: f.kind === "AI" ? "#3E6FB0" : "var(--ink)", minWidth: 34 }}>+{f.points}</span>
              <span style={{ flex: 1 }}>{f.label}</span>
              <span className="faint" style={{ fontSize: 10 }}>{f.kind === "AI" ? "AI" : "DET"}</span>
            </div>
          ))}
          <p className="faint" style={{ fontSize: 11.5, margin: "8px 0 0" }}>
            The deterministic factors are the floor — the model can raise this score, never lower it.
          </p>
        </div>
      )}
      {!compact && risk.ai_adjustment > 0 && (
        <span className="faint" style={{ fontSize: 11 }}>+{risk.ai_adjustment} AI</span>
      )}
    </span>
  );
}

/* ————— the matter ladder rail: every stage, who holds it, how long ————— */
function RungDot({ r }: { r: WorkflowRung }) {
  const bg = r.status === "done" ? "var(--good, #1F6F54)"
    : r.status === "active" ? "var(--warn, #9E6D12)" : "var(--hairline)";
  return (
    <span style={{
      width: 26, height: 26, borderRadius: "50%", flexShrink: 0, zIndex: 1,
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      background: r.status === "done" ? bg : "var(--surface)",
      border: `2px solid ${bg}`,
      color: r.status === "done" ? "#fff" : KIND_COLOR[r.kind],
      fontSize: 10.5, fontWeight: 700, fontFamily: "var(--mono)",
    }}>
      {r.status === "done" ? "✓" : r.kind}
    </span>
  );
}

export function WorkflowRail({ wf, round }: { wf: WorkflowInstance | null; round: number }) {
  if (!wf || !wf.rungs?.length) return null;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <span className="kicker">Workflow ladder</span>
        <span className="faint" style={{ fontSize: 11 }}>
          {wf.template_name ?? "template"} · v{wf.version}{round > 1 ? ` · round ${round}` : ""}
        </span>
      </div>
      <div style={{ position: "relative" }}>
        <span style={{ position: "absolute", left: 12, top: 10, bottom: 10, width: 2, background: "var(--hairline)" }} />
        {wf.rungs.map((r) => {
          const spent = fmtSpent(r.spent_seconds);
          return (
            <div key={r.key} style={{ display: "flex", gap: 10, position: "relative", padding: "4px 0", alignItems: "flex-start" }}>
              <RungDot r={r} />
              <div style={{ flex: 1, minWidth: 0, opacity: r.status === "waiting" ? 0.55 : 1 }}>
                <div style={{ display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12.5, fontWeight: 620 }}>{r.name}</span>
                  <span className="mono faint" style={{ fontSize: 9, letterSpacing: ".04em", color: KIND_COLOR[r.kind] }}>
                    {KIND_LABEL[r.kind]}
                  </span>
                  {r.mode === "pinned" && <span className="faint" style={{ fontSize: 10 }} title="Pinned — this rung can never be removed">🔒</span>}
                  {r.status === "active" && <span className="pill warn" style={{ fontSize: 9.5, padding: "1px 7px" }}>in progress</span>}
                  {r.round && r.round > 1 && <span className="pill accent" style={{ fontSize: 9.5, padding: "1px 7px" }}>↺ round {r.round}</span>}
                  {spent && <span className="faint tnum" style={{ fontSize: 10.5 }}>⏱ {spent}</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
