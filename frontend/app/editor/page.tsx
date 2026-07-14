"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { api, type EditorGrounding, type TabularDoc } from "../../lib/api";

const STARTER = `MUTUAL NON-DISCLOSURE AGREEMENT

1. Confidential Information
[Draft or paste clause text here, select any passage, and tell the AI how to revise it — grounded in your playbook.]

2. Term
`;

const PRESETS = [
  "Draft a limitation of liability clause capped at 12 months' fees",
  "Add a mutual confidentiality clause",
  "Tighten this to match our playbook",
  "Make this clause mutual",
];

type Sel = { start: number; end: number; text: string };

export default function Editor() {
  const [doc, setDoc] = useState(STARTER);
  const [instruction, setInstruction] = useState("");
  const [sel, setSel] = useState<Sel>({ start: 0, end: 0, text: "" });
  // a live suggestion: frozen target range + streaming replacement
  const [sug, setSug] = useState<{ range: Sel; after: string; grounding: EditorGrounding[]; streaming: boolean } | null>(null);
  const [picking, setPicking] = useState(false);
  const [docs, setDocs] = useState<TabularDoc[]>([]);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);

  function captureSel() {
    const el = taRef.current;
    if (!el) return;
    const start = el.selectionStart, end = el.selectionEnd;
    setSel({ start, end, text: doc.slice(start, end) });
  }

  async function generate(inst?: string) {
    const instr = (inst ?? instruction).trim();
    if (!instr || sug?.streaming) return;
    const range: Sel = { ...sel };  // freeze the target at run time
    setSug({ range, after: "", grounding: [], streaming: true });
    setInstruction("");
    try {
      await api.editorDraft(instr, range.text, {
        onGrounding: (g) => setSug((s) => s ? { ...s, grounding: g } : s),
        onDelta: (t) => setSug((s) => s ? { ...s, after: s.after + t } : s),
        onDone: () => setSug((s) => s ? { ...s, streaming: false } : s),
      });
    } catch (e) {
      setSug((s) => s ? { ...s, after: s.after || `⚠ ${String(e)}`, streaming: false } : s);
    } finally {
      setSug((s) => s ? { ...s, streaming: false } : s);
    }
  }

  function accept() {
    if (!sug) return;
    const { start, end } = sug.range;
    const next = doc.slice(0, start) + sug.after + doc.slice(end);
    setDoc(next);
    setSug(null);
    // restore focus + place cursor after the inserted text
    requestAnimationFrame(() => {
      const el = taRef.current;
      if (el) { const pos = start + sug.after.length; el.focus(); el.setSelectionRange(pos, pos); }
    });
  }

  async function openPicker() {
    setPicking(true);
    if (docs.length === 0) api.tabularDocuments().then(setDocs).catch(() => {});
  }
  async function loadDoc(d: TabularDoc) {
    setLoadingDoc(true);
    try {
      const full = await api.getRequest(d.request_id);
      if (full.document?.body_markdown) { setDoc(full.document.body_markdown); setSug(null); }
    } catch {} finally { setLoadingDoc(false); setPicking(false); }
  }

  const words = doc.trim() ? doc.trim().split(/\s+/).length : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 92px)" }}>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div className="page-head-row">
          <div>
            <p className="kicker">AI · drafting editor</p>
            <h1>Editor</h1>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="mono" style={{ fontSize: 10.5, color: "var(--faint)" }}>{words} words</span>
            <button className="btn sm" onClick={() => { setDoc(STARTER); setSug(null); }}>New</button>
            <button className="btn sm" onClick={openPicker}>Load document</button>
          </div>
        </div>
      </div>

      {/* document canvas */}
      <div style={{ flex: 1, overflowY: "auto", display: "flex", justifyContent: "center", padding: "0 2px" }}>
        <div className="editor-page">
          <textarea
            ref={taRef}
            value={doc}
            onChange={(e) => setDoc(e.target.value)}
            onSelect={captureSel}
            onKeyUp={captureSel}
            onMouseUp={captureSel}
            spellCheck={false}
          />
        </div>
      </div>

      {/* suggestion card */}
      {sug && (
        <div style={{ maxWidth: 820, margin: "10px auto 0", width: "100%" }}>
          <div className="card card-pad" style={{ borderLeft: "3px solid var(--teal)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
              <span className="kicker" style={{ color: "var(--teal)" }}>
                {sug.range.text ? "◆ Suggested revision" : "◆ Suggested insertion"}{sug.streaming && " · drafting…"}
              </span>
              {sug.grounding.length > 0 && (
                <span style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                  <span className="mono" style={{ fontSize: 9, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.08em" }}>grounded in</span>
                  {sug.grounding.map((g) => (
                    <Link key={g.rule_key} href={g.url} className="ground-chip" title={g.heading}>{g.rule_key}</Link>
                  ))}
                </span>
              )}
            </div>
            {sug.range.text && (
              <div className="diff-before">{sug.range.text}</div>
            )}
            <div className="diff-after">
              {sug.after}{sug.streaming && <span className="type-caret" />}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button className="btn primary sm" disabled={sug.streaming || !sug.after.trim()} onClick={accept}>
                ✓ Accept {sug.range.text ? "replacement" : "insertion"}
              </button>
              <button className="btn sm ghost" onClick={() => setSug(null)}>Reject</button>
            </div>
          </div>
        </div>
      )}

      {/* instruction composer */}
      <div style={{ maxWidth: 820, margin: "10px auto 0", width: "100%" }}>
        {sel.text && !sug && (
          <div className="mono" style={{ fontSize: 10.5, color: "var(--teal)", marginBottom: 5 }}>
            ✎ editing selection ({sel.text.length} chars) — the AI will revise it in place
          </div>
        )}
        <div className="composer">
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); generate(); } }}
            placeholder={sel.text ? "How should the AI revise the selected text?" : "Tell the AI what to draft (or select text first to revise it)…"}
            rows={1}
            disabled={!!sug?.streaming}
          />
          <button className="btn primary" disabled={!!sug?.streaming || !instruction.trim()} onClick={() => generate()}>
            {sug?.streaming ? "…" : sel.text ? "Revise" : "Draft"}
          </button>
        </div>
        {!sel.text && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 7 }}>
            {PRESETS.map((p) => <button key={p} className="preset-chip" onClick={() => generate(p)}>{p}</button>)}
          </div>
        )}
        <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textAlign: "center", marginTop: 6 }}>
          Advisory · drafts grounded in your playbook · nothing applied until you accept · every generation sealed on the audit chain
        </div>
      </div>

      {/* load-document picker */}
      {picking && (
        <div className="modal-scrim" onClick={() => setPicking(false)}>
          <div className="card card-pad" style={{ width: "min(540px, 94vw)", maxHeight: "80vh", display: "flex", flexDirection: "column" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <span className="kicker">Load a document{loadingDoc && " · loading…"}</span>
              <button className="btn sm ghost" onClick={() => setPicking(false)}>Close</button>
            </div>
            <div style={{ overflowY: "auto", flex: 1 }}>
              {docs.map((d) => (
                <button key={d.request_id} className="pick-row" style={{ width: "100%", textAlign: "left", background: "none", border: "none", borderBottom: "1px solid var(--line)" }} onClick={() => loadDoc(d)}>
                  <span className="mono" style={{ fontSize: 11, color: "var(--accent-ink)", width: 110 }}>{d.ref}</span>
                  <span style={{ fontSize: 12.5, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.counterparty}</span>
                  <span className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textTransform: "uppercase" }}>{d.type}</span>
                </button>
              ))}
              {docs.length === 0 && <div className="muted" style={{ fontSize: 12.5, padding: 12 }}>No documents available.</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
