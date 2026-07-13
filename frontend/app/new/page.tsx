"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, PURPOSES, type PlaybookSummary } from "../../lib/api";

export default function NewRequest() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [playbookId, setPlaybookId] = useState("");   // "" = org default
  const [form, setForm] = useState({
    requester_name: "Sam Carter",
    requester_email: "sam.carter@northwind.example",
    counterparty_name: "",
    nda_type: "MUTUAL",
    purpose: "sales_evaluation",
    jurisdiction: "US",
    term_months: 24,
  });

  // offer a playbook picker only to users who can see the library (legal staff);
  // requesters get the org default transparently
  useEffect(() => { api.listPlaybooks().then(setBooks).catch(() => setBooks([])); }, []);

  const set = (k: string, v: string | number) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await api.createRequest({
        ...form, term_months: Number(form.term_months),
        ...(playbookId ? { playbook_id: playbookId } : {}),
      });
      router.push(`/r/${r.id}`);
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="container narrow">
      <p className="kicker">New request</p>
      <h1 className="h-serif" style={{ fontSize: 28, margin: "8px 0 6px" }}>Request an NDA</h1>
      <p className="muted" style={{ marginBottom: 26 }}>
        Tell us who it&rsquo;s with and what it&rsquo;s for. We&rsquo;ll draft it and take it from there.
      </p>

      <form onSubmit={submit} className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Counterparty (the other company)</label>
          <input
            required
            placeholder="e.g. Acme Corporation"
            value={form.counterparty_name}
            onChange={(e) => set("counterparty_name", e.target.value)}
          />
        </div>

        <div className="row2">
          <div className="field">
            <label>NDA type</label>
            <select value={form.nda_type} onChange={(e) => set("nda_type", e.target.value)}>
              <option value="MUTUAL">Mutual (both sides share)</option>
              <option value="ONE_WAY">One-way (only we disclose)</option>
            </select>
          </div>
          <div className="field">
            <label>Purpose</label>
            <select value={form.purpose} onChange={(e) => set("purpose", e.target.value)}>
              {PURPOSES.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="row2">
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
          <div className="field">
            <label>Confidentiality term (months)</label>
            <input
              type="number"
              min={1}
              max={120}
              value={form.term_months}
              onChange={(e) => set("term_months", e.target.value)}
            />
          </div>
        </div>

        {books.length > 1 && (
          <div className="field">
            <label>Playbook</label>
            <select value={playbookId} onChange={(e) => setPlaybookId(e.target.value)}>
              <option value="">Org default{books.find((b) => b.active) ? ` (${books.find((b) => b.active)!.name})` : ""}</option>
              {books.map((b) => (
                <option key={b.id} value={b.id}>{b.name} · v{b.version}{b.active ? " · default" : ""}</option>
              ))}
            </select>
            <span className="hint">Which set of company positions to draft from. Leave as default unless this deal needs a specific standard.</span>
          </div>
        )}

        {error && <div className="notice warn" style={{ marginBottom: 14 }}>{error}</div>}

        <p className="muted" style={{ fontSize: 12.5, marginTop: 4, marginBottom: 16 }}>
          Standard, low-risk requests are drafted and sent automatically. Anything outside policy
          (long terms, foreign law, sensitive purposes) is routed to a lawyer first — you&rsquo;ll see
          which on the next screen.
        </p>

        <button className="btn primary" disabled={submitting} type="submit">
          {submitting ? "Submitting…" : "Submit request"}
        </button>
      </form>
    </div>
  );
}
