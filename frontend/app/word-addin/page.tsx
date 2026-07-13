"use client";
import Script from "next/script";
import { useEffect, useState } from "react";
import { api, getToken, setToken, type ProposedChange, type Review } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window { Office?: any; Word?: any; }
}

export default function WordAddin() {
  const [ready, setReady] = useState(false);
  const [inWord, setInWord] = useState(false);
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [counterparty, setCounterparty] = useState("Counterparty");
  const [pasteText, setPasteText] = useState("");

  // login form
  const [email, setEmail] = useState("marcus.reid@northwind.example");
  const [password, setPassword] = useState("demo1234");

  useEffect(() => {
    if (!ready) return;
    const O = window.Office;
    if (O?.onReady) O.onReady().then(() => setInWord(!!window.Word));
  }, [ready]);

  async function doLogin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setStatus(null);
    try { const { token } = await api.login(email, password); setToken(token); setAuthed(true); }
    catch { setStatus("Sign-in failed."); }
    finally { setBusy(false); }
  }

  async function getDocText(): Promise<string> {
    if (inWord) {
      const W = window.Word;
      return await W.run(async (ctx: any) => {
        const body = ctx.document.body; body.load("text"); await ctx.sync(); return body.text as string;
      });
    }
    return pasteText;
  }

  async function review_() {
    setBusy(true); setStatus("Reading document…"); setReview(null);
    try {
      const text = (await getDocText()).trim();
      if (!text) { setStatus("No text found. Open a document (or paste some) first."); return; }
      setStatus("Running redline engine…");
      const r = await api.createInbound({ counterparty_name: counterparty, nda_type: "MUTUAL", purpose: "vendor_evaluation", body_text: text });
      setReview(r.review);
      setStatus(null);
    } catch (e) { setStatus(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  async function apply(c: ProposedChange) {
    if (!inWord) { setStatus("Open this in Word to apply tracked changes."); return; }
    setBusy(true);
    try {
      const W = window.Word;
      await W.run(async (ctx: any) => {
        ctx.document.changeTrackingMode = W.ChangeTrackingMode.trackAll;  // edits become tracked changes
        if (c.before_text) {
          const needle = c.before_text.slice(0, 200);
          const results = ctx.document.body.search(needle, { matchCase: false, ignoreSpace: true });
          results.load("items"); await ctx.sync();
          if (results.items.length > 0) results.items[0].insertText(c.after_text, "Replace");
          else ctx.document.body.insertParagraph(`${c.heading}: ${c.after_text}`, "End");
        } else {
          ctx.document.body.insertParagraph(`${c.heading}\n${c.after_text}`, "End");
        }
        await ctx.sync();
      });
      setStatus(`Applied “${c.heading}” as a tracked change.`);
    } catch (e) { setStatus("Couldn't apply: " + String(e)); }
    finally { setBusy(false); }
  }

  const deviations = review?.changes.filter((c) => c.finding === "DEVIATION") ?? [];
  const missing = review?.changes.filter((c) => c.finding === "MISSING") ?? [];

  return (
    <div style={{ padding: 14, maxWidth: 380, margin: "0 auto", fontFamily: "var(--sans)" }}>
      <Script src="https://appsforoffice.microsoft.com/lib/1/hosted/office.js" strategy="afterInteractive" onLoad={() => setReady(true)} />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span className="mk" style={{ width: 22, height: 22, borderRadius: 6, background: "var(--accent)", color: "#fff", display: "grid", placeItems: "center", fontFamily: "var(--serif)", fontWeight: 700 }}>F</span>
        <b>Frontdoor Redline</b>
        <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--muted)" }}>{inWord ? "Word" : "browser"}</span>
      </div>

      {!authed ? (
        <form onSubmit={doLogin} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>Sign in to review against your playbook.</p>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" style={inp} />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" style={inp} />
          <button className="btn primary" disabled={busy} type="submit">Sign in</button>
          {status && <div className="notice warn" style={{ fontSize: 12 }}>{status}</div>}
        </form>
      ) : (
        <>
          <div className="field" style={{ marginBottom: 8 }}>
            <label style={{ fontSize: 12 }}>Counterparty</label>
            <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} style={inp} />
          </div>
          {!inWord && (
            <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} rows={5} placeholder="(browser preview) paste NDA text…"
              style={{ ...inp, fontFamily: "var(--mono)", fontSize: 11.5, marginBottom: 8 }} />
          )}
          <button className="btn primary" style={{ width: "100%" }} disabled={busy} onClick={review_}>
            {busy ? "Working…" : inWord ? "Review this document" : "Review pasted text"}
          </button>
          {status && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{status}</div>}

          {review && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 10, fontSize: 11.5 }}>
                <span className="schip dev"><b>{deviations.length}</b> deviations</span>
                <span className="schip miss"><b>{missing.length}</b> missing</span>
              </div>
              {[...deviations, ...missing].map((c) => (
                <div key={c.id} className="change-card" style={{ padding: 10, marginBottom: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <span className={`find-badge ${c.finding}`}>{c.finding}</span>
                    <span style={{ fontSize: 12.5, fontWeight: 650 }}>{c.heading}</span>
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginBottom: 6 }}>{c.rationale}</div>
                  {c.rule_key && <div className="mono muted" style={{ fontSize: 10.5, marginBottom: 6 }}>playbook · {c.rule_key}</div>}
                  <button className="btn" style={{ width: "100%", fontSize: 12, padding: "6px" }} disabled={busy || !inWord}
                    title={inWord ? "" : "Open in Word to apply"} onClick={() => apply(c)}>
                    Insert as tracked change
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const inp: React.CSSProperties = {
  fontFamily: "inherit", fontSize: 13, padding: "8px 10px", borderRadius: 8,
  border: "1px solid var(--hairline)", background: "var(--surface)", color: "var(--ink)", width: "100%",
};
