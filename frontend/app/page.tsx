"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type RequestSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  IconChat, IconInbox, IconMail, IconPlus, IconReview,
} from "./components/Icons";

type Action = { href: string; label: string; desc: string; perm: string | null; Icon: (p: any) => JSX.Element };

const ACTIONS: Action[] = [
  { href: "/new", label: "Request an NDA", desc: "Fill a short form; track it like a package.", perm: "request:create", Icon: IconPlus },
  { href: "/inbound", label: "Review their paper", desc: "Paste a counterparty NDA — the engine redlines it against your playbook.", perm: "request:read_all", Icon: IconReview },
  { href: "/inbox", label: "Legal inbox", desc: "Triage the queue, approve deviations, send.", perm: "request:read_all", Icon: IconInbox },
  { href: "/chat", label: "Ask legal", desc: "Describe what you need in plain language.", perm: "request:create", Icon: IconChat },
  { href: "/email-sim", label: "Email intake", desc: "See how an inbound email becomes a triaged ticket.", perm: "request:read_all", Icon: IconMail },
];

function firstName(name: string) { return name.trim().split(/\s+/)[0] || name; }

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="stat">
      <div className="lbl">{label}</div>
      <div className={`val tnum ${accent ? "accent" : ""}`}>{value}</div>
    </div>
  );
}

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return <span className="pill state">—</span>;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane}</span>;
}

export default function Home() {
  const { user, has } = useAuth();
  const canReadAll = has("request:read_all");
  const [rows, setRows] = useState<RequestSummary[] | null>(null);

  useEffect(() => {
    if (!canReadAll) return;
    api.listRequests().then(setRows).catch(() => setRows([]));
  }, [canReadAll]);

  const stats = useMemo(() => {
    const r = rows ?? [];
    const closed = new Set(["SENT", "SIGNED", "REJECTED", "CLOSED"]);
    return {
      total: r.length,
      open: r.filter((x) => !closed.has(x.state)).length,
      needs: r.filter((x) => x.open_steps > 0 || x.state === "APPROVED").length,
      signed: r.filter((x) => x.state === "SIGNED").length,
    };
  }, [rows]);

  const recent = (rows ?? []).slice(0, 6);
  const actions = ACTIONS.filter((a) => a.perm === null || has(a.perm));

  return (
    <div>
      <div className="page-head">
        <p className="kicker">Legal front door + CLM</p>
        <h1>Welcome back, {user ? firstName(user.name) : "there"}.</h1>
        <p className="sub">
          Request-to-signature for NDAs — classified, drafted from your approved playbook, with only
          the risky terms routed to a lawyer, every step on a tamper-evident audit chain.
        </p>
      </div>

      {canReadAll && (
        <div className="stat-grid" style={{ marginBottom: 26 }}>
          <Stat label="Total requests" value={stats.total} />
          <Stat label="Open" value={stats.open} />
          <Stat label="Needs action" value={stats.needs} accent />
          <Stat label="Signed" value={stats.signed} />
        </div>
      )}

      <div className="kicker" style={{ marginBottom: 12 }}>Quick actions</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14, marginBottom: 30 }}>
        {actions.map((a) => (
          <Link key={a.href} href={a.href} className="card card-pad card-hover" style={{ display: "block" }}>
            <span className="qa-ico"><a.Icon /></span>
            <div style={{ fontWeight: 620, fontSize: 15, margin: "12px 0 4px" }}>{a.label}</div>
            <p className="muted" style={{ fontSize: 13, margin: 0, lineHeight: 1.5 }}>{a.desc}</p>
          </Link>
        ))}
      </div>

      {canReadAll && recent.length > 0 && (
        <>
          <div className="page-head-row" style={{ marginBottom: 12 }}>
            <div className="kicker">Recent requests</div>
            <Link href="/inbox" className="btn sm ghost">View all →</Link>
          </div>
          <div className="card" style={{ overflow: "hidden" }}>
            <div style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr><th>Ref</th><th>Counterparty</th><th>Type</th><th>Lane</th><th>State</th></tr>
                </thead>
                <tbody>
                  {recent.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => (window.location.href = `/review/${r.id}`)}>
                      <td className="ref">{r.ref}</td>
                      <td className="cp">{r.counterparty_name}</td>
                      <td>{r.nda_type === "MUTUAL" ? "Mutual" : "One-way"}</td>
                      <td><LanePill lane={r.lane} /></td>
                      <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
