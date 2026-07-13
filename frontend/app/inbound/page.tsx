"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type PlaybookSummary } from "../../lib/api";

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
  const [mode, setMode] = useState<"paste" | "file">("paste");
  const [counterparty, setCounterparty] = useState("Globex LLC");
  const [body, setBody] = useState(SAMPLE);
  const [file, setFile] = useState<File | null>(null);
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [playbookId, setPlaybookId] = useState("");   // "" = org default
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.listPlaybooks().then(setBooks).catch(() => setBooks([])); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const fields = {
        counterparty_name: counterparty, nda_type: "ONE_WAY", purpose: "vendor_evaluation",
        ...(playbookId ? { playbook_id: playbookId } : {}),
      };
      const r = mode === "file" && file
        ? await api.createInboundUpload(fields, file)
        : await api.createInbound({ ...fields, body_text: body });
      router.push(`/review/${r.id}`);
    } catch (e2) {
      setErr(String(e2).replace(/^Error:\s*/, ""));
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

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <button type="button" className={`btn ${mode === "paste" ? "primary" : "ghost"}`} onClick={() => setMode("paste")}>Paste text</button>
        <button type="button" className={`btn ${mode === "file" ? "primary" : "ghost"}`} onClick={() => setMode("file")}>Upload file</button>
      </div>

      <form onSubmit={submit} className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Counterparty</label>
          <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} required />
        </div>

        {books.length > 1 && (
          <div className="field">
            <label>Review against playbook</label>
            <select value={playbookId} onChange={(e) => setPlaybookId(e.target.value)}>
              <option value="">Org default{books.find((b) => b.active) ? ` (${books.find((b) => b.active)!.name})` : ""}</option>
              {books.map((b) => (
                <option key={b.id} value={b.id}>{b.name} · v{b.version}{b.active ? " · default" : ""}</option>
              ))}
            </select>
            <span className="hint">The counterparty&rsquo;s paper is redlined against these positions.</span>
          </div>
        )}

        {mode === "paste" ? (
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
        ) : (
          <div className="field">
            <label>Their NDA file (.docx, .pdf, .txt)</label>
            <label className="dropzone">
              <input type="file" accept=".docx,.pdf,.txt,.md" style={{ display: "none" }}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              {file ? (
                <span><b>{file.name}</b> · {(file.size / 1024).toFixed(0)} KB — click to change</span>
              ) : (
                <span className="muted">📄 Click to choose a .docx or .pdf file</span>
              )}
            </label>
          </div>
        )}

        {err && <div className="notice warn" style={{ marginBottom: 14 }}>{err}</div>}
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 16 }}>
          {mode === "paste"
            ? "Prefilled with a deliberately aggressive sample (6-month liability cap, no carve-out, 60-month term, English law, missing clauses) so you can see the engine work."
            : "The file's text is extracted and run through the same engine. Scanned PDFs (image-only) need OCR and aren't supported yet."}
        </p>
        <button className="btn primary" disabled={busy || (mode === "file" && !file)} type="submit">
          {busy ? "Analyzing…" : "Run redline review"}
        </button>
      </form>
    </div>
  );
}
