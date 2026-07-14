"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type RequestSummary } from "../../lib/api";

const CLOSED = new Set(["SIGNED", "FILED", "EXECUTED", "CANCELLED"]);

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return <span className="pill state">—</span>;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane.toLowerCase()}</span>;
}

function ageDays(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}
const needsMe = (r: RequestSummary) => r.open_steps > 0 || r.state === "APPROVED";
const isOverdue = (r: RequestSummary) => ageDays(r.created_at) >= 5 && !CLOSED.has(r.state);

type Filter = "all" | "needs" | "inbound" | "overdue";

export default function Inbox() {
  const [rows, setRows] = useState<RequestSummary[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const load = () => api.listRequests().then(setRows).catch(() => setRows([]));
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => ({
    all: rows.length,
    needs: rows.filter(needsMe).length,
    inbound: rows.filter((r) => r.direction === "INBOUND").length,
    overdue: rows.filter(isOverdue).length,
  }), [rows]);

  const shown = useMemo(() => {
    let out = rows;
    if (filter === "needs") out = out.filter(needsMe);
    else if (filter === "inbound") out = out.filter((r) => r.direction === "INBOUND");
    else if (filter === "overdue") out = out.filter(isOverdue);
    const needle = q.trim().toLowerCase();
    if (needle) out = out.filter((r) => r.counterparty_name.toLowerCase().includes(needle) || r.ref.toLowerCase().includes(needle));
    return out;
  }, [rows, filter, q]);

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
            <p className="kicker">Legal inbox</p>
            <h1>Triage queue</h1>
          </div>
          <span className="muted tnum" style={{ fontSize: 13 }}>{rows.length} requests</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <div className="seg">
          {seg("all", "All")}
          {seg("needs", "Needs me")}
          {seg("inbound", "Inbound")}
          {seg("overdue", "Overdue")}
        </div>
        <span style={{ flex: 1 }} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search counterparty or ref…"
          style={{ width: 240 }} />
        <Link href="/new" className="btn primary">+ New request</Link>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Counterparty</th>
                <th>Type</th>
                <th>Dir</th>
                <th>Lane</th>
                <th>State</th>
                <th>Age</th>
                <th>To do</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const inbound = r.direction === "INBOUND";
                const over = isOverdue(r);
                const age = ageDays(r.created_at);
                return (
                  <tr key={r.id} className={needsMe(r) || over ? "sev" : ""} style={{ cursor: "pointer" }}
                    onClick={() => (window.location.href = `/review/${r.id}`)}>
                    <td className="ref">{r.ref}</td>
                    <td className="cp">{r.counterparty_name}{inbound && <span className="sub">their paper</span>}</td>
                    <td className="muted">{r.nda_type === "MUTUAL" ? "Mutual" : "One-way"}</td>
                    <td><span className={`dir-b ${inbound ? "in" : ""}`}>{inbound ? "↓ in" : "↑ out"}</span></td>
                    <td><LanePill lane={r.lane} /></td>
                    <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                    <td><span className={`age ${over ? "over" : ""}`}>{age === 0 ? "today" : `${age}d`}{over && " ⚠"}</span></td>
                    <td>
                      {r.open_steps > 0 ? (
                        <span className="todo-act">{inbound ? `${r.open_steps} to decide` : `${r.open_steps} approval${r.open_steps > 1 ? "s" : ""}`} →</span>
                      ) : r.state === "APPROVED" ? (
                        <span className="todo-ready">ready to send</span>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {shown.length === 0 && (
                <tr><td colSpan={8} className="muted" style={{ padding: 30, textAlign: "center" }}>
                  {rows.length === 0 ? <>No requests yet. <Link href="/new" style={{ color: "var(--accent)" }}>File one →</Link></> : "Nothing matches this filter."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
