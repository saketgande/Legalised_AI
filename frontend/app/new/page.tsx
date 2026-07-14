"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, PURPOSES, type PlaybookSummary, type RequestTypeInfo } from "../../lib/api";

// mirrors the backend auto-send policy so the requester sees the likely outcome as they fill it in
const AUTO_PURPOSES = new Set(["sales_evaluation", "vendor_evaluation", "hiring", "partnership_exploration"]);
const AUTO_JX = new Set(["US", "US-CA", "US-NY", "US-DE"]);

/* ————— step 1: what do you need? ————— */
function TypePicker({ types, onPick }: { types: RequestTypeInfo[]; onPick: (t: RequestTypeInfo) => void }) {
  return (
    <div>
      <div className="page-head">
        <p className="kicker">New request</p>
        <h1>What do you need from legal?</h1>
        <p className="sub">Pick the closest match — we&rsquo;ll route it to the right process. You never need to know what happens behind the door.</p>
      </div>
      <div className="type-grid">
        {types.map((t) => (
          <button key={t.key} className="card card-pad card-hover type-card" onClick={() => onPick(t)}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span style={{ fontWeight: 640, fontSize: 15 }}>{t.label}</span>
              <span className="pill state" style={{ flexShrink: 0 }}>{t.default_sla_hours}h SLA</span>
            </div>
            <p className="muted" style={{ fontSize: 13, margin: "8px 0 0", lineHeight: 1.5 }}>{t.description}</p>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ————— the NDA form (the CONTRACT engine's front door) ————— */
function NdaForm({ onBack }: { onBack: () => void }) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [playbookId, setPlaybookId] = useState("");
  const [form, setForm] = useState({
    counterparty_name: "", nda_type: "MUTUAL", purpose: "sales_evaluation",
    jurisdiction: "US", term_months: 24,
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
    <div>
      <div className="page-head">
        <p className="kicker"><button className="linkish" onClick={onBack}>← New request</button> · NDA</p>
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
          <input type="number" required min={1} max={120} value={form.term_months}
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

/* ————— the advice form (every ADVICE-category type) ————— */
function AdviceForm({ type, onBack }: { type: RequestTypeInfo; onBack: () => void }) {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [urgency, setUrgency] = useState("NORMAL");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setError(null);
    try {
      const r = await api.createAdvice({ type_key: type.key, question, urgency });
      router.push(`/r/${r.id}`);
    } catch (err) { setError(String(err)); setSubmitting(false); }
  }

  return (
    <div>
      <div className="page-head">
        <p className="kicker"><button className="linkish" onClick={onBack}>← New request</button> · {type.label}</p>
        <h1>{type.label}</h1>
        <p className="sub">{type.description} Typical turnaround: {type.default_sla_hours} hours.</p>
      </div>

      <form onSubmit={submit} className="card card-pad">
        <div className="field">
          <label>What do you need? Be as specific as you can.</label>
          <textarea required rows={7} value={question} onChange={(e) => setQuestion(e.target.value)}
            placeholder={type.key === "marketing_review"
              ? "Paste the claim / copy you want reviewed, and where it will run…"
              : "Describe the situation, what you want to do, and any deadline…"} />
        </div>

        <div className="field">
          <label>How urgent is this?</label>
          <div className="seg" style={{ width: "100%" }}>
            {[["NORMAL", "Normal"], ["HIGH", "This week"], ["URGENT", "Blocking me now"]].map(([v, l]) => (
              <button key={v} type="button" className={urgency === v ? "on" : ""} style={{ flex: 1 }}
                onClick={() => setUrgency(v)}>{l}</button>
            ))}
          </div>
        </div>

        {error && <div className="notice warn" style={{ marginBottom: 14 }}>{error}</div>}

        <button className="btn primary" disabled={submitting} type="submit">
          {submitting ? "Filing…" : "Send to legal"}
        </button>
        <p className="faint" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
          You&rsquo;ll get a tracking page; the answer lands there — no need to chase anyone.
        </p>
      </form>
    </div>
  );
}

export default function NewRequest() {
  const [types, setTypes] = useState<RequestTypeInfo[] | null>(null);
  const [picked, setPicked] = useState<RequestTypeInfo | null>(null);

  useEffect(() => { api.requestTypes().then(setTypes).catch(() => setTypes([])); }, []);

  if (types === null) return <div className="muted">Loading…</div>;
  const container = { maxWidth: 640, margin: "0 auto" } as const;

  if (!picked) {
    // no catalog (backend older than this build) -> fall straight into the NDA form
    if (types.length === 0) return <div style={container}><NdaForm onBack={() => {}} /></div>;
    return <div style={{ maxWidth: 720, margin: "0 auto" }}><TypePicker types={types} onPick={setPicked} /></div>;
  }
  return (
    <div style={container}>
      {picked.category === "CONTRACT"
        ? <NdaForm onBack={() => setPicked(null)} />
        : <AdviceForm type={picked} onBack={() => setPicked(null)} />}
    </div>
  );
}
