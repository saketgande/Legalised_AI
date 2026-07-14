"use client";
import { useEffect, useMemo, useState } from "react";
import { api, type OpsRow, type OpsSummary } from "../../lib/api";

/* Format an hour count compactly: 3h, 0.5h, or 2.1d once it passes 3 days.
   Stays in hours through 71h so every SLA target (max 48h) reads as "Nh",
   matching the target legend, instead of a 48h target showing as "2.0d". */
function fmtH(h: number | null): string {
  if (h === null) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 72) return `${h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h)}h`;
  return `${(h / 24).toFixed(1)}d`;
}

const STATUS_LABEL: Record<string, string> = {
  breached: "Breached", at_risk: "At risk", on_track: "On track",
  missed: "Missed", met: "Met", cancelled: "Cancelled",
};
// map an SLA status to a pill colour class
const STATUS_PILL: Record<string, string> = {
  breached: "crit", at_risk: "warn", on_track: "good",
  missed: "crit", met: "good", cancelled: "state",
};

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return <span className="pill state">inbound</span>;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane.toLowerCase()}</span>;
}

/* SLA clock as a track: fill = progress toward target; colour = posture.
   In-flight rows show elapsed/target; resolved rows show cycle/target. */
function SlaBar({ row }: { row: OpsRow }) {
  const resolved = row.cycle_hours !== null;
  const used = resolved ? row.cycle_hours! : (row.elapsed_hours ?? 0);
  const pct = Math.max(0.02, Math.min(1, used / row.target_hours));
  const fill = row.status && ["breached", "missed"].includes(row.status) ? "crit"
    : row.status === "at_risk" ? "warn" : "good";
  return (
    <div className="sla-clock">
      <div className="sla-bar"><span className={`fill ${fill}`} style={{ width: `${pct * 100}%` }} /></div>
      <div className="sla-num tnum">
        <b>{fmtH(used)}</b> <span className="faint">of {fmtH(row.target_hours)}</span>
      </div>
    </div>
  );
}

function Sparkline({ data }: { data: number[] }) {
  const W = 150, H = 40, n = Math.max(2, data.length);
  const max = Math.max(1, ...data);
  const pts = data.map((v, i) => [(i / (n - 1)) * W, H - 4 - (v / max) * (H - 10)] as const);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const [ex, ey] = pts[pts.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true" style={{ width: W }}>
      <defs>
        <linearGradient id="slag" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: "var(--accent)", stopOpacity: 0.18 }} />
          <stop offset="1" style={{ stopColor: "var(--accent)", stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      <path d={`${line} L${W},${H} L0,${H} Z`} fill="url(#slag)" />
      <path d={line} fill="none" style={{ stroke: "var(--accent)" }} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={ex} cy={ey} r={3.5} fill="var(--surface)" style={{ stroke: "var(--accent)" }} strokeWidth={2} />
    </svg>
  );
}

type Filter = "all" | "in_flight" | "at_risk" | "breached" | "resolved";
const IN_FLIGHT = new Set(["on_track", "at_risk", "breached"]);
const RESOLVED = new Set(["met", "missed"]);

export default function SlaDashboard() {
  const [d, setD] = useState<OpsSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = () => api.opsSummary().then(setD).catch((e) => setErr(String(e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => {
    const rows = d?.rows ?? [];
    return {
      all: rows.length,
      in_flight: rows.filter((r) => IN_FLIGHT.has(r.status ?? "")).length,
      at_risk: rows.filter((r) => r.status === "at_risk" || r.status === "breached").length,
      breached: rows.filter((r) => r.status === "breached").length,
      resolved: rows.filter((r) => RESOLVED.has(r.status ?? "")).length,
    };
  }, [d]);

  const shown = useMemo(() => {
    const rows = d?.rows ?? [];
    if (filter === "all") return rows;
    if (filter === "in_flight") return rows.filter((r) => IN_FLIGHT.has(r.status ?? ""));
    if (filter === "at_risk") return rows.filter((r) => r.status === "at_risk" || r.status === "breached");
    if (filter === "breached") return rows.filter((r) => r.status === "breached");
    return rows.filter((r) => RESOLVED.has(r.status ?? ""));
  }, [d, filter]);

  if (err) return <div style={{ maxWidth: 720 }}><div className="notice warn">{err}</div></div>;
  if (!d) return <div className="muted">Loading…</div>;

  const deflection = Math.round(d.deflection_rate * 100);
  const compliance = d.sla.compliance_rate === null ? null : Math.round(d.sla.compliance_rate * 100);
  // in-flight breakdown reconciles with the tile total: breached + at_risk + on_track === in_flight
  const flight: JSX.Element[] = [];
  if (d.sla.breached > 0) flight.push(<span key="b" className="crit">{d.sla.breached} breached</span>);
  if (d.sla.at_risk > 0) flight.push(<span key="a" className="warn">{d.sla.at_risk} at risk</span>);
  if (d.sla.on_track > 0) flight.push(<span key="o">{d.sla.on_track} on track</span>);
  const seg = (key: Filter, label: string) => (
    <button className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
      {label} <span className="tnum" style={{ opacity: 0.6 }}>{counts[key]}</span>
    </button>
  );

  return (
    <div>
      <div className="page-head">
        <div className="page-head-row">
          <div>
            <p className="kicker">Operations · SLA &amp; deflection</p>
            <h1>How fast is the front door?</h1>
          </div>
          <span className="muted tnum" style={{ fontSize: 13 }}>{d.totals.total} requests all-time</span>
        </div>
      </div>

      {/* headline metrics */}
      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <div className="stat">
          <div className="lbl">Auto-resolved</div>
          <div className="val accent">{deflection}%</div>
          <div className="stat-sub">{d.totals.auto_resolved} of {d.totals.total} never touched a lawyer</div>
        </div>
        <div className="stat">
          <div className="lbl">SLA compliance</div>
          <div className="val">{compliance === null ? "—" : `${compliance}%`}</div>
          <div className="stat-sub">{d.totals.resolved} resolved against target</div>
        </div>
        <div className="stat">
          <div className="lbl">Avg turnaround</div>
          <div className="val">{fmtH(d.sla.avg_cycle_hours)}</div>
          <div className="stat-sub">request filed → legal done</div>
        </div>
        <div className="stat">
          <div className="lbl">In flight</div>
          <div className="val">{d.totals.in_flight}</div>
          <div className="stat-sub">
            {flight.length === 0
              ? "queue clear"
              : flight.map((el, i) => <span key={i}>{i > 0 ? " · " : ""}{el}</span>)}
          </div>
        </div>
        <div className={`stat ${d.sla.breached > 0 ? "stat-crit" : ""}`}>
          <div className="lbl">SLA breached</div>
          <div className={`val ${d.sla.breached > 0 ? "crit" : ""}`}>{d.sla.breached}</div>
          <div className="stat-sub">{d.sla.breached > 0 ? "past target — act now" : "none past target"}</div>
        </div>
      </div>

      {/* volume + target legend strip */}
      <div className="card card-pad" style={{ marginBottom: 26 }}>
        <div className="qhealth">
          <div className="qstats">
            <div className="qstat"><div className="n tnum">{d.totals.total}</div><div className="l">Total</div></div>
            <div className="qstat"><div className="n tnum good">{d.totals.auto_resolved}</div><div className="l">Auto</div></div>
            <div className="qstat"><div className="n tnum">{d.totals.in_flight}</div><div className="l">Open</div></div>
            <div className="qstat"><div className="n tnum">{d.totals.resolved}</div><div className="l">Resolved</div></div>
          </div>
          <div className="spark-wrap">
            <div className="spark-cap">Requests filed · last 7 days</div>
            <Sparkline data={d.volume_7d} />
          </div>
        </div>
        <div className="sla-legend">
          Targets:
          <span className="pill auto">auto {d.targets.AUTO}h</span>
          <span className="pill assisted">assisted {d.targets.ASSISTED}h</span>
          <span className="pill escalated">escalated {d.targets.ESCALATED}h</span>
          <span className="pill state">inbound {d.targets.default}h</span>
        </div>
      </div>

      {/* per-request SLA table */}
      <div style={{ display: "flex", gap: 12, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        <div className="seg">
          {seg("all", "All")}
          {seg("in_flight", "In flight")}
          {seg("at_risk", "At risk")}
          {seg("breached", "Breached")}
          {seg("resolved", "Resolved")}
        </div>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Counterparty</th>
                <th>Requester</th>
                <th>Lane</th>
                <th>State</th>
                <th style={{ width: 200 }}>SLA clock</th>
                <th>Posture</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className={r.status === "breached" ? "sev" : ""} style={{ cursor: "pointer" }}
                  onClick={() => (window.location.href = `/review/${r.id}`)}>
                  <td className="ref">{r.ref}</td>
                  <td className="cp">{r.counterparty}{r.direction === "INBOUND" && <span className="sub">their paper</span>}</td>
                  <td className="muted">{r.requester}</td>
                  <td><LanePill lane={r.lane} /></td>
                  <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                  <td>{r.status === "cancelled" ? <span className="faint">—</span> : <SlaBar row={r} />}</td>
                  <td><span className={`pill ${STATUS_PILL[r.status ?? "cancelled"]}`}>{STATUS_LABEL[r.status ?? "cancelled"]}</span></td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={7} className="muted" style={{ padding: 30, textAlign: "center" }}>
                  Nothing matches this filter.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
