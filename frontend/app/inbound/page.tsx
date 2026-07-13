"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "../../lib/api";

const SAMPLE = `1. Confidential Information
"Confidential Information" means any information disclosed by Globex LLC to the Receiving Party in connection with the proposed engagement.

2. Purpose
The Receiving Party may use the Confidential Information to evaluate a potential business relationship between the parties.

3. Term
This Agreement shall remain in effect for sixty (60) months from the Effective Date.

4. Limitation of Liability
In no event shall either party's total aggregate liability arising out of this Agreement exceed the fees paid in the six (6) months preceding the claim.

5. Governing Law
This Agreement shall be governed by and construed in accordance with the laws of England and Wales.`;

export default function InboundReview() {
  const router = useRouter();
  const [counterparty, setCounterparty] = useState("Globex LLC");
  const [body, setBody] = useState(SAMPLE);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api.createInbound({
        counterparty_name: counterparty,
        nda_type: "ONE_WAY",
        purpose: "vendor_evaluation",
        body_text: body,
      });
      router.push(`/review/${r.id}`);
    } catch (e2) {
      setErr(String(e2));
      setBusy(false);
    }
  }

  return (
    <div className="container narrow">
      <p className="kicker">Inbound · third-party paper</p>
      <h1 className="h-serif" style={{ fontSize: 28, margin: "8px 0 6px" }}>Review a counterparty&rsquo;s NDA</h1>
      <p className="muted" style={{ marginBottom: 22 }}>
        Paste the NDA they sent. The engine parses it clause-by-clause, checks it against your
        playbook (numbers &amp; dates deterministically, positions semantically), and proposes
        redlines you approve or reject.
      </p>

      <form onSubmit={submit} className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Counterparty</label>
          <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} required />
        </div>
        <div className="field">
          <label>Their NDA text</label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={16}
            style={{
              fontFamily: "var(--mono)", fontSize: 12.5, lineHeight: 1.6, padding: "12px 14px",
              borderRadius: 9, border: "1px solid var(--hairline)", background: "var(--surface)",
              color: "var(--ink)", resize: "vertical",
            }}
          />
        </div>
        {err && <div className="notice warn" style={{ marginBottom: 14 }}>{err}</div>}
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
          Prefilled with a deliberately aggressive sample (6-month liability cap, no confidentiality
          carve-out, 60-month term, English law, several missing clauses) so you can see the engine work.
        </p>
        <button className="btn primary" disabled={busy} type="submit">
          {busy ? "Analyzing…" : "Run redline review"}
        </button>
      </form>
    </div>
  );
}
