"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type RequestSummary } from "../../lib/api";

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return <span className="pill state">—</span>;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane}</span>;
}

export default function Inbox() {
  const [rows, setRows] = useState<RequestSummary[]>([]);
  const [filter, setFilter] = useState<"all" | "needs">("all");

  const load = () => api.listRequests().then(setRows).catch(() => setRows([]));
  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  const shown = filter === "needs" ? rows.filter((r) => r.open_steps > 0 || r.state === "APPROVED") : rows;

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

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button className={`btn ${filter === "all" ? "primary" : "ghost"}`} onClick={() => setFilter("all")}>
          All
        </button>
        <button className={`btn ${filter === "needs" ? "primary" : "ghost"}`} onClick={() => setFilter("needs")}>
          Needs action
        </button>
        <span style={{ flex: 1 }} />
        <Link href="/new" className="btn">+ New request</Link>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="inbox">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Counterparty</th>
                <th>Type</th>
                <th>Purpose</th>
                <th>Lane</th>
                <th>State</th>
                <th>To do</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} onClick={() => (window.location.href = `/review/${r.id}`)}>
                  <td className="ref">{r.ref}</td>
                  <td className="cp">{r.counterparty_name}</td>
                  <td>{r.nda_type === "MUTUAL" ? "Mutual" : "One-way"}</td>
                  <td className="muted">{r.purpose.replace(/_/g, " ")}</td>
                  <td><LanePill lane={r.lane} /></td>
                  <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                  <td>
                    {r.open_steps > 0 ? (
                      <span style={{ color: "var(--warn)", fontWeight: 650 }}>{r.open_steps} approval{r.open_steps > 1 ? "s" : ""}</span>
                    ) : r.state === "APPROVED" ? (
                      <span style={{ color: "var(--accent)", fontWeight: 650 }}>ready to send</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={7} className="muted" style={{ padding: 26, textAlign: "center" }}>
                  No requests yet. <Link href="/new" style={{ color: "var(--accent)" }}>File one →</Link>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
