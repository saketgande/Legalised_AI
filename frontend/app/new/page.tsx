"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, PURPOSES, type PlaybookSummary } from "../../lib/api";

// mirrors the backend auto-send policy so the requester sees the likely outcome as they fill it in
const AUTO_PURPOSES = new Set(["sales_evaluation", "vendor_evaluation", "hiring", "partnership_exploration"]);
const AUTO_JX = new Set(["US", "US-CA", "US-NY", "US-DE"]);

export default function NewRequest() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [playbookId, setPlaybookId] = useState("");
  const [form, setForm] = useState({
    requester_name: "Sam Carter",
    requester_email: "sam.carter@northwind.example",
    counterparty_name: "",
    nda_type: "MUTUAL",
    purpose: "sales_evaluation",
    jurisdiction: "US",
    term_months: 24,
  });

  useEffect(() => { api.listPlaybooks().then(setBooks).catch(() => setBooks([])); }, []);
  const set = (k: string, v: string | number) => setForm((f) => ({ ...f, [k]: v }));

  const auto = useMemo(() =>
    Number(form.term_months) <= 24 && AUTO_PURPOSES.has(form.purpose) && AUTO_JX.has(form.jurisdiction),
    [form.term_months, form.purpose, form.jurisdiction]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setError(null);
    try {
      const r = await api.createRequest({
        ...form, term_months: Number(form.term_months),
        ...(playbookId ? { playbook_id: playbookId } : {}),
      });
      router.push(`/r/${r.id}`);
    } catch (err) { setError(String(err)); setSubmitting(false); }
  }

  return (
    <div style={{ maxWidth: 620, margin: "0 auto" }}>
      <div className="page-head">
        <p className="kicker">New request</p>
        <h1>Request an NDA</h1>
        <p className="sub">Tell us who it&rsquo;s with and what it&rsquo;s for — we&rsquo;ll draft it and take it from there.</p>
      </div>

      <form onSubmit={submit} className="card card-pad">
        <div className="field">
          <label>Counterparty (the other company)</label>
          <input required placeholder="e.g. Umbrella Corp" value={form.counterparty_name}
            onChange={(e) => set("counterparty_name", e.target.value)} />
        </div>

        <div className="field">
          <label>NDA type</label>
          <div className="seg" style={{ width: "100%" }}>
            <button type="button" className={form.nda_type === "MUTUAL" ? "on" : ""} style={{ flex: 1 }}
              onClick={() => set("nda_type", "MUTUAL")}>Mutual <span className="faint" style={{ fontWeight: 400 }}>· both sides share</span></button>
            <button type="button" className={form.nda_type === "ONE_WAY" ? "on" : ""} style={{ flex: 1 }}
              onClick={() => set("nda_type", "ONE_WAY")}>One-way <span className="faint" style={{ fontWeight: 400 }}>· only we disclose</span></button>
          </div>
        </div>

        <div className="row2">
          <div className="field">
            <label>Purpose</label>
            <select value={form.purpose} onChange={(e) => set("purpose", e.target.value)}>
              {PURPOSES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Governing jurisdiction</label>
            <select value={form.jurisdiction} onChange={(e) => set("jurisdiction", e.target.value)}>
              <option value="US">United States</option>
              <option value="US-CA">California</option>
              <option value="US-NY">New York</option>
              <option value="US-DE">Delaware</option>
              <option value="EU-DE">Germany (EU)</option>
              <option value="UK">United Kingdom</option>
            </select>
          </div>
        </div>

        <div className="field">
          <label>Confidentiality term (months)</label>
          <input type="number" min={1} max={120} value={form.term_months}
            onChange={(e) => set("term_months", e.target.value)} style={{ maxWidth: 160 }} />
          <span className="hint">How long the confidentiality lasts.</span>
        </div>

        {books.length > 1 && (
          <div className="field">
            <label>Playbook</label>
            <select value={playbookId} onChange={(e) => setPlaybookId(e.target.value)}>
              <option value="">Org default{books.find((b) => b.active) ? ` (${books.find((b) => b.active)!.name})` : ""}</option>
              {books.map((b) => <option key={b.id} value={b.id}>{b.name} · v{b.version}{b.active ? " · default" : ""}</option>)}
            </select>
          </div>
        )}

        <div className="notice info" style={{ display: "block", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 650, fontSize: 12.5 }}>What happens next</span>
            {auto
              ? <span className="pill good"><span className="dot" />Looks standard — likely auto-approved</span>
              : <span className="pill warn"><span className="dot" />Will be routed to a lawyer first</span>}
          </div>
          <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.55, color: "var(--ink-2)" }}>
            Standard, low-risk requests are drafted from your approved playbook and sent automatically.
            Anything outside policy — long terms, foreign law, sensitive purposes — is reviewed by a lawyer
            first. You&rsquo;ll get a tracking page to follow it either way.
          </p>
        </div>

        {error && <div className="notice warn" style={{ marginBottom: 14 }}>{error}</div>}

        <button className="btn primary" disabled={submitting} type="submit">
          {submitting ? "Submitting…" : "Submit request"}
        </button>
        <p className="faint" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>You&rsquo;ll get a tracking page you can check any time.</p>
      </form>
    </div>
  );
}
