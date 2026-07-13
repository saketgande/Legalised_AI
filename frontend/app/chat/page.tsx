"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { api } from "../../lib/api";

type Msg = {
  who: "you" | "bot";
  text: string;
  created?: { id: string; ref: string; lane: string | null; counterparty: string } | null;
};

const STARTERS = [
  "I need a mutual NDA with Acme Corporation for a sales evaluation, 2 year term",
  "One-way NDA with a vendor, Globex LLC",
  "NDA with Wayne Enterprises for hiring",
];

export default function ChatIntake() {
  const [msgs, setMsgs] = useState<Msg[]>([
    { who: "bot", text: "Hi — tell me what NDA you need and I'll file it. e.g. “a mutual NDA with Acme for a sales eval, 2-year term.”" },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    setMsgs((m) => [...m, { who: "you", text }]);
    setBusy(true);
    try {
      const r = await api.chatIntake(text);
      setMsgs((m) => [...m, { who: "bot", text: r.reply, created: r.created }]);
    } catch (e) {
      setMsgs((m) => [...m, { who: "bot", text: "Something went wrong: " + String(e).replace(/^Error:\s*/, "") }]);
    } finally {
      setBusy(false);
      setTimeout(() => scroller.current?.scrollTo(0, scroller.current.scrollHeight), 50);
    }
  }

  return (
    <div className="container narrow" style={{ maxWidth: 640 }}>
      <p className="kicker">Intake · chat</p>
      <h1 className="h-serif" style={{ fontSize: 26, margin: "6px 0 4px" }}>Ask for an NDA</h1>
      <p className="muted" style={{ marginBottom: 18, fontSize: 14 }}>
        Describe it in plain language. The assistant extracts the details and files it through the same
        pipeline as the form — with the same triage, drafting, and audit trail.
      </p>

      <div ref={scroller} className="card" style={{ padding: 16, height: 420, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
        {msgs.map((m, i) => (
          <div key={i} style={{ alignSelf: m.who === "you" ? "flex-end" : "flex-start", maxWidth: "82%" }}>
            <div className={`bubble ${m.who}`}>{m.text}</div>
            {m.created && (
              <Link href={`/r/${m.created.id}`} className="ticket-chip">
                ✓ {m.created.ref} created{m.created.lane ? ` · ${m.created.lane}` : ""} — track it →
              </Link>
            )}
          </div>
        ))}
        {busy && <div className="bubble bot" style={{ alignSelf: "flex-start", opacity: 0.6 }}>…</div>}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }} style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your request…"
          style={{ flex: 1, fontFamily: "inherit", fontSize: 14, padding: "10px 12px", borderRadius: 9, border: "1px solid var(--hairline)", background: "var(--surface)", color: "var(--ink)" }} />
        <button className="btn primary" disabled={busy || !input.trim()} type="submit">Send</button>
      </form>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {STARTERS.map((s) => (
          <button key={s} className="btn ghost" style={{ fontSize: 12, padding: "5px 10px" }} onClick={() => send(s)}>{s}</button>
        ))}
      </div>
    </div>
  );
}
