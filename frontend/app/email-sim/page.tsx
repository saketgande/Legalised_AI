"use client";
import Link from "next/link";
import { useState } from "react";
import { api, type RequestSummary } from "../../lib/api";

const SAMPLES = {
  outbound: {
    from_email: "jordan@bigco.example", from_name: "Jordan Lee", subject: "Need an NDA",
    body: "Hi legal — can you set up a mutual NDA with Umbrella Corp for a sales evaluation? 12-month term is fine. Thanks!",
  },
  inbound: {
    from_email: "legal@globex.example", from_name: "Globex Legal", subject: "Our NDA for your signature",
    body: "1. Term\nThis Agreement remains in effect for sixty (60) months.\n2. Governing Law\nGoverned by the laws of England and Wales.\n3. Limitation of Liability\nLiability shall not exceed the fees paid in the three (3) months preceding the claim.",
  },
};

export default function EmailSim() {
  const [form, setForm] = useState(SAMPLES.outbound);
  const [result, setResult] = useState<{ created: boolean; classified: string; request?: RequestSummary; reply?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null); setResult(null);
    try { setResult(await api.emailWebhook(form)); }
    catch (e2) { setErr(String(e2).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  return (
    <div className="container narrow">
      <p className="kicker">Intake · email channel</p>
      <h1 className="h-serif" style={{ fontSize: 26, margin: "6px 0 4px" }}>Simulate an inbound email</h1>
      <p className="muted" style={{ marginBottom: 16, fontSize: 14 }}>
        This posts to <span className="mono">POST /api/intake/email-webhook</span> — the same endpoint a real
        mail integration would call. The assistant classifies it (a request for an NDA vs. a counterparty's
        paper to review) and files it through the shared pipeline.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <button className="btn ghost" onClick={() => setForm(SAMPLES.outbound)}>Load: request email</button>
        <button className="btn ghost" onClick={() => setForm(SAMPLES.inbound)}>Load: their NDA email</button>
      </div>

      <form onSubmit={submit} className="card" style={{ padding: 22 }}>
        <div className="row2">
          <div className="field"><label>From (email)</label><input value={form.from_email} onChange={(e) => set("from_email", e.target.value)} /></div>
          <div className="field"><label>From (name)</label><input value={form.from_name} onChange={(e) => set("from_name", e.target.value)} /></div>
        </div>
        <div className="field"><label>Subject</label><input value={form.subject} onChange={(e) => set("subject", e.target.value)} /></div>
        <div className="field">
          <label>Body</label>
          <textarea value={form.body} onChange={(e) => set("body", e.target.value)} rows={9}
            style={{ fontFamily: "var(--mono)", fontSize: 12.5, lineHeight: 1.55, padding: "10px 12px", borderRadius: 9, border: "1px solid var(--hairline)", background: "var(--surface)", color: "var(--ink)", resize: "vertical" }} />
        </div>
        {err && <div className="notice warn" style={{ marginBottom: 12 }}>{err}</div>}
        <button className="btn primary" disabled={busy} type="submit">{busy ? "Processing…" : "Deliver email"}</button>
      </form>

      {result && (
        <div className="card" style={{ padding: 18, marginTop: 16 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Result · classified {result.classified}</div>
          {result.created && result.request ? (
            <div>
              <p style={{ margin: "0 0 8px", fontSize: 14 }}>
                Created <b>{result.request.ref}</b> — {result.request.direction === "INBOUND" ? "counterparty paper queued for redline review" : `${result.request.lane} lane`} · {result.request.counterparty_name}
              </p>
              <Link className="ticket-chip" href={result.request.direction === "INBOUND" ? `/review/${result.request.id}` : `/r/${result.request.id}`}>
                Open {result.request.ref} →
              </Link>
            </div>
          ) : (
            <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>{result.reply}</p>
          )}
        </div>
      )}
    </div>
  );
}
