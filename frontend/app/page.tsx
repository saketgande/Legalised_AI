"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type RequestSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { IconChat, IconInbox, IconMail, IconPlus, IconReview } from "./components/Icons";

type Action = { href: string; label: string; desc: string; perm: string | null; Icon: (p: any) => JSX.Element };
const ACTIONS: Action[] = [
  { href: "/new", label: "New request", desc: "NDA, DPA, or a legal question — pick and track it like a package.", perm: "request:create", Icon: IconPlus },
  { href: "/inbound", label: "Review their paper", desc: "Paste a counterparty contract — the engine redlines it against your playbook.", perm: "request:read_all", Icon: IconReview },
  { href: "/inbox", label: "Legal inbox", desc: "Triage the queue, approve deviations, send.", perm: "request:read_all", Icon: IconInbox },
  { href: "/chat", label: "Ask legal", desc: "Describe what you need in plain language.", perm: "request:create", Icon: IconChat },
  { href: "/email-sim", label: "Email intake", desc: "See how an inbound email becomes a triaged ticket.", perm: "request:read_all", Icon: IconMail },
];

const CLOSED = new Set(["SIGNED", "FILED", "EXECUTED", "REJECTED", "CANCELLED"]);
function firstName(name: string) { return name.trim().split(/\s+/)[0] || name; }

function Sparkline({ data }: { data: number[] }) {
  const W = 180, H = 46, n = Math.max(2, data.length);
  const max = Math.max(1, ...data);
  const pts = data.map((v, i) => [(i / (n - 1)) * W, H - 4 - (v / max) * (H - 10)] as const);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const [ex, ey] = pts[pts.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: "var(--good)", stopOpacity: 0.18 }} />
          <stop offset="1" style={{ stopColor: "var(--good)", stopOpacity: 0 }} />
        </linearGradient>
      </defs>
      <path d={`${line} L${W},${H} L0,${H} Z`} fill="url(#sg)" />
      <path d={line} fill="none" style={{ stroke: "var(--good)" }} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={ex} cy={ey} r={3.5} fill="var(--surface)" style={{ stroke: "var(--good)" }} strokeWidth={2} />
    </svg>
  );
}

function MorningBrief({ rows, name }: { rows: RequestSummary[]; name: string }) {
  const decisions = useMemo(() => rows.filter((r) => r.open_steps > 0 || r.state === "APPROVED").slice(0, 5), [rows]);
  const health = useMemo(() => ({
    inReview: rows.filter((r) => r.state === "IN_REVIEW").length,
    awaiting: rows.filter((r) => r.open_steps > 0).length,
    ready: rows.filter((r) => r.state === "APPROVED").length,
    signed: rows.filter((r) => ["SIGNED", "FILED", "EXECUTED"].includes(r.state)).length,
  }), [rows]);
  const spark = useMemo(() => {
    const buckets = Array(7).fill(0);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    rows.forEach((r) => {
      const d = new Date(r.created_at); d.setHours(0, 0, 0, 0);
      const idx = 6 - Math.round((today.getTime() - d.getTime()) / 86_400_000);
      if (idx >= 0 && idx < 7) buckets[idx] += 1;
    });
    return buckets;
  }, [rows]);
  const active = rows.filter((r) => !CLOSED.has(r.state)).length;
  const critical = decisions[0]?.counterparty_name;

  return (
    <div>
      <div className="page-head">
        <p className="kicker">Operations · Legal Front Door + CLM</p>
        <h1>Mission control for every legal request — <em style={{ fontStyle: "italic", color: "var(--teal)" }}>triaged, drafted, resolved</em>.</h1>
        <p className="sub">
          <span className="pill accent" style={{ marginRight: 8, verticalAlign: "middle" }}>✦ AI summary</span>
          Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}, {name} · <b>{active} active requests</b> · <b>{decisions.length} need you</b>
          {critical ? <> · {critical} is your critical path.</> : " · you’re all clear."}
        </p>
      </div>

      <div className="page-head-row" style={{ marginBottom: 10 }}>
        <div className="kicker">Needs your decision</div>
        <span className="faint" style={{ fontSize: 12 }}>{decisions.length} items</span>
      </div>
      <div className="card" style={{ overflow: "hidden", marginBottom: 26 }}>
        <div className="brief-rows" style={{ padding: "2px 18px" }}>
          {decisions.map((r, i) => {
            const ready = r.state === "APPROVED";
            const inbound = r.direction === "INBOUND";
            return (
              <div className="brow" key={r.id} style={i === 0 && !ready ? { background: "linear-gradient(90deg,var(--crit-bg),transparent 60%)", borderRadius: 10 } : undefined}>
                <span className="bdot" style={{ background: ready ? "var(--good)" : inbound ? "var(--crit)" : "var(--warn)", boxShadow: `0 0 0 4px ${ready ? "var(--good-bg)" : inbound ? "var(--crit-bg)" : "var(--warn-bg)"}` }} />
                <div style={{ minWidth: 0 }}>
                  <div><span className="bref">{r.ref}</span><span className="bhead">{r.counterparty_name}</span></div>
                  <div className="bsub">
                    {ready ? "Cleared review — ready to send to the counterparty."
                      : inbound ? `Their paper — ${r.open_steps} redline${r.open_steps > 1 ? "s" : ""} awaiting your decision.`
                      : `${r.open_steps} approval${r.open_steps > 1 ? "s" : ""} pending on the ladder.`}
                  </div>
                </div>
                <Link href={`/review/${r.id}`} className={`btn sm ${i === 0 && !ready ? "primary" : ""}`}>
                  {ready ? "Review & send →" : "Review →"}
                </Link>
              </div>
            );
          })}
          {decisions.length === 0 && (
            <div className="brow"><span className="bdot" style={{ background: "var(--good)" }} />
              <div className="bsub" style={{ gridColumn: "2 / span 2" }}>Nothing needs a decision right now. 🎉</div></div>
          )}
        </div>
      </div>

      <div className="page-head-row" style={{ marginBottom: 10 }}>
        <div className="kicker">Queue health</div>
      </div>
      <div className="card card-pad" style={{ marginBottom: 26 }}>
        <div className="qhealth">
          <div className="qstats">
            <div className="qstat"><div className="n tnum">{health.inReview}</div><div className="l">In review</div></div>
            <div className="qstat"><div className="n tnum">{health.awaiting}</div><div className="l">Awaiting decisions</div></div>
            <div className="qstat"><div className="n tnum">{health.ready}</div><div className="l">Ready to send</div></div>
            <div className="qstat"><div className="n tnum good">{health.signed}</div><div className="l">Signed</div></div>
          </div>
          <div className="spark-wrap">
            <div className="spark-cap">Requests filed · last 7 days</div>
            <Sparkline data={spark} />
          </div>
        </div>
      </div>

      <div className="page-head-row" style={{ marginBottom: 10 }}>
        <div className="kicker">Recent requests</div>
        <Link href="/inbox" className="btn sm ghost">Open inbox →</Link>
      </div>
      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead><tr><th>Ref</th><th>Counterparty</th><th>Dir</th><th>State</th></tr></thead>
            <tbody>
              {rows.slice(0, 6).map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => (window.location.href = `/review/${r.id}`)}>
                  <td className="ref">{r.ref}</td>
                  <td className="cp">{r.counterparty_name}</td>
                  <td><span className={`dir-b ${r.direction === "INBOUND" ? "in" : ""}`}>{r.direction === "INBOUND" ? "↓ in" : "↑ out"}</span></td>
                  <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function RequesterHome({ rows, name, has }: { rows: RequestSummary[]; name: string; has: (p: string) => boolean }) {
  const actions = ACTIONS.filter((a) => a.perm === null || has(a.perm));
  return (
    <div>
      <div className="page-head">
        <p className="kicker">Legal front door + CLM</p>
        <h1>Welcome back, {name}.</h1>
        <p className="sub">Ask legal for anything — an NDA, a DPA, a question — then track it like a package. We draft it, route only the risky parts to a lawyer, and file the signed copy.</p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14, marginBottom: 30 }}>
        {actions.map((a) => (
          <Link key={a.href} href={a.href} className="card card-pad card-hover" style={{ display: "block" }}>
            <span className="qa-ico"><a.Icon /></span>
            <div style={{ fontWeight: 620, fontSize: 15, margin: "12px 0 4px" }}>{a.label}</div>
            <p className="muted" style={{ fontSize: 13, margin: 0, lineHeight: 1.5 }}>{a.desc}</p>
          </Link>
        ))}
      </div>
      {rows.length > 0 && (
        <>
          <div className="kicker" style={{ marginBottom: 10 }}>Your requests</div>
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="tbl">
              <thead><tr><th>Ref</th><th>Counterparty</th><th>State</th><th></th></tr></thead>
              <tbody>
                {rows.slice(0, 8).map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => (window.location.href = `/r/${r.id}`)}>
                    <td className="ref">{r.ref}</td>
                    <td className="cp">{r.counterparty_name}</td>
                    <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                    <td><span className="btn sm ghost">Track →</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default function Home() {
  const { user, has } = useAuth();
  const canReadAll = has("request:read_all");
  const [rows, setRows] = useState<RequestSummary[] | null>(null);

  useEffect(() => { api.listRequests().then(setRows).catch(() => setRows([])); }, []);

  const name = user ? firstName(user.name) : "there";
  if (rows === null) return <div className="muted">Loading…</div>;
  return canReadAll
    ? <MorningBrief rows={rows} name={name} />
    : <RequesterHome rows={rows} name={name} has={has} />;
}
