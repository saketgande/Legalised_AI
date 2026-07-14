"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Decision, type DecisionFeed } from "../lib/api";
import { useAuth } from "../lib/auth";

const KIND: Record<string, { icon: string; color: string; label: string }> = {
  advice_answer: { icon: "◈", color: "var(--teal)", label: "Advice answer" },
  redlines: { icon: "▤", color: "var(--accent)", label: "Redlines" },
  ready_to_send: { icon: "➤", color: "var(--good)", label: "Ready to send" },
  renewal: { icon: "↻", color: "var(--amber)", label: "Renewal" },
};
const sevColor = (s: string) => s === "critical" ? "var(--crit)" : s === "warn" ? "var(--warn)" : "var(--teal)";
function greeting() { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; }
function firstName(n: string) { return (n || "").trim().split(/\s+/)[0] || "there"; }

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

export default function Home() {
  const { user } = useAuth();
  const [feed, setFeed] = useState<DecisionFeed | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(() => api.decisions().then(setFeed).catch(() => setFeed({ decisions: [], summary: { total: 0, critical: 0, by_kind: {} } })), []);
  useEffect(() => { load(); const t = setInterval(load, 12000); return () => clearInterval(t); }, [load]);

  async function act(d: Decision, key: string) {
    if (key === "open") { window.location.href = `/t/${d.request_id}`; return; }
    if (key === "review") { window.location.href = `/review/${d.request_id}`; return; }
    if (key === "edit") { setEditing(d.id); setDraft(String(d.meta.draft || "")); return; }
    setBusy(d.id);
    try {
      if (key === "approve") await api.resolveAdvice(d.request_id, String(d.meta.draft || ""));
      else if (key === "send") await api.send(d.request_id);
      else if (key === "renew") await api.renewContract(d.request_id);
      await load();
    } catch { /* stays in the feed; the reload reflects the truth */ } finally { setBusy(null); }
  }
  async function saveEdit(d: Decision) {
    if (!draft.trim()) return;
    setBusy(d.id);
    try { await api.resolveAdvice(d.request_id, draft); setEditing(null); await load(); }
    catch {} finally { setBusy(null); }
  }

  return (
    <div>
      {/* Daily brief */}
      <div className="page-head" style={{ marginBottom: 6 }}>
        <p className="kicker">Supervisor feed · your legal day</p>
        <h1 className="h-serif" style={{ fontSize: 30 }}>{greeting()}, {firstName(user?.name || "")}</h1>
      </div>
      {feed && (
        <div className="brief-strip">
          <span style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.5 }}>{brief(feed)}</span>
          {feed.summary.total > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginLeft: "auto" }}>
              {feed.summary.critical > 0 && <span className="pill crit">{feed.summary.critical} critical</span>}
              {Object.entries(feed.summary.by_kind).map(([k, n]) => (
                <span key={k} className="pill" style={{ background: "var(--surface-2)", color: KIND[k]?.color || "var(--muted)" }}>
                  {KIND[k]?.icon} {n} {KIND[k]?.label.toLowerCase() ?? k}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Decisions feed */}
      <div className="kicker" style={{ margin: "18px 0 10px" }}>Decisions awaiting you {feed && <span className="faint">· {feed.summary.total}</span>}</div>

      {!feed ? (
        <div className="muted" style={{ padding: 20 }}>Loading…</div>
      ) : feed.decisions.length === 0 ? (
        <div className="card card-pad" style={{ textAlign: "center", padding: 48, borderLeft: "3px solid var(--good)" }}>
          <div style={{ fontSize: 30, marginBottom: 8 }}>✓</div>
          <div className="h-serif" style={{ fontSize: 22, marginBottom: 6 }}>Inbox zero</div>
          <p className="muted" style={{ fontSize: 13 }}>The AI is caught up — nothing needs your decision right now.</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 14 }}>
            <Link href="/assistant" className="btn sm primary">Ask the assistant</Link>
            <Link href="/inbox" className="btn sm">Open the queue</Link>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {feed.decisions.map((d) => {
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
                    <div style={{ fontSize: 13.5, color: "var(--ink)", marginBottom: 3 }}>{d.headline}</div>
                    <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{d.detail}</div>

                    {isEditing ? (
                      <div style={{ marginTop: 10 }}>
                        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={6} style={{ width: "100%", fontSize: 13, lineHeight: 1.5 }} />
                        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                          <button className="btn primary sm" disabled={busy === d.id || !draft.trim()} onClick={() => saveEdit(d)}>Save &amp; approve</button>
                          <button className="btn ghost sm" onClick={() => setEditing(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: 7, marginTop: 10, flexWrap: "wrap" }}>
                        {d.actions.map((a) => (
                          <button key={a.key} disabled={busy === d.id}
                            className={`btn sm ${a.primary ? "primary" : a.key === "reject" ? "ghost" : ""}`}
                            onClick={() => act(d, a.key)}>
                            {a.label}
                          </button>
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
    </div>
  );
}
