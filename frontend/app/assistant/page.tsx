"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type AssistantSource, type RequestSummary } from "../../lib/api";

type Msg = { role: "user" | "assistant"; text: string; sources?: AssistantSource[]; streaming?: boolean };

const SUGGESTIONS = [
  "What's our position on limitation of liability?",
  "Which contracts expire in the next 90 days?",
  "Summarize the open redlines on our inbound NDAs",
  "What does our playbook say about governing law?",
];

const KIND_ICON: Record<string, string> = { clause: "§", playbook: "▦", request: "◆" };
const KIND_COLOR: Record<string, string> = { clause: "var(--teal)", playbook: "var(--amber)", request: "var(--accent)" };

/* render an assistant answer: **bold**, [n] → citation chip, newlines preserved */
function Answer({ text, sources }: { text: string; sources?: AssistantSource[] }) {
  const byN = new Map((sources || []).map((s) => [s.n, s]));
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, li) => {
        const parts: React.ReactNode[] = [];
        const re = /\*\*(.+?)\*\*|\[(\d+)\]|`([^`]+)`/g;
        let last = 0, m: RegExpExecArray | null, k = 0;
        while ((m = re.exec(line)) !== null) {
          if (m.index > last) parts.push(line.slice(last, m.index));
          if (m[1] !== undefined) parts.push(<strong key={k++}>{m[1]}</strong>);
          else if (m[2] !== undefined) {
            const src = byN.get(Number(m[2]));
            parts.push(
              src?.url
                ? <Link key={k++} href={src.url} title={src.title} className="cite-chip">{m[2]}</Link>
                : <span key={k++} className="cite-chip" title={src?.title}>{m[2]}</span>,
            );
          } else if (m[3] !== undefined) parts.push(<code key={k++} className="mono cite-code">{m[3]}</code>);
          last = re.lastIndex;
        }
        if (last < line.length) parts.push(line.slice(last));
        return <div key={li} style={{ minHeight: line ? undefined : 8 }}>{parts}</div>;
      })}
    </>
  );
}

export default function Assistant() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [scopeId, setScopeId] = useState<string>("");
  const [reqs, setReqs] = useState<RequestSummary[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { api.listRequests().then(setReqs).catch(() => {}); }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  async function ask(q: string) {
    const query = q.trim();
    if (!query || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: query }, { role: "assistant", text: "", streaming: true }]);
    setStreaming(true);
    const patchLast = (fn: (m: Msg) => Msg) =>
      setMessages((prev) => { const c = [...prev]; c[c.length - 1] = fn(c[c.length - 1]); return c; });
    try {
      await api.assistantAsk(query, scopeId || null, {
        onSources: (s) => patchLast((m) => ({ ...m, sources: s })),
        onDelta: (t) => patchLast((m) => ({ ...m, text: m.text + t })),
        onDone: () => patchLast((m) => ({ ...m, streaming: false })),
      });
    } catch (e) {
      patchLast((m) => ({ ...m, text: m.text || `⚠ ${String(e)}`, streaming: false }));
    } finally {
      setStreaming(false);
      patchLast((m) => ({ ...m, streaming: false }));
    }
  }

  const scopeReq = reqs.find((r) => r.id === scopeId);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 92px)" }}>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div className="page-head-row">
          <div>
            <p className="kicker">AI · grounded in your workspace</p>
            <h1>Assistant</h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.1em" }}>Scope</span>
            <select value={scopeId} onChange={(e) => setScopeId(e.target.value)} style={{ width: 240, fontSize: 12.5 }}>
              <option value="">All matters</option>
              {reqs.slice(0, 100).map((r) => (
                <option key={r.id} value={r.id}>{r.ref} · {r.category === "ADVICE" ? (r.purpose || r.type_label || "advice") : r.counterparty_name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* conversation */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "4px 2px" }}>
        {messages.length === 0 ? (
          <div style={{ maxWidth: 620, margin: "6vh auto 0", textAlign: "center" }}>
            <div style={{ fontSize: 34, marginBottom: 10 }}>◆</div>
            <h2 className="h-serif" style={{ fontSize: 26, marginBottom: 8 }}>Ask anything about your legal workspace</h2>
            <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.55, marginBottom: 22 }}>
              Every answer is grounded in your own contracts, clauses, and playbook — with a source you can click on each claim.
              {scopeReq && <> Scoped to <span className="mono" style={{ color: "var(--teal)" }}>{scopeReq.ref}</span>.</>}
            </p>
            <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggest-card" onClick={() => ask(s)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ maxWidth: 780, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16, paddingBottom: 8 }}>
            {messages.map((m, i) => (
              <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                {m.role === "user" ? (
                  <div className="msg-user">{m.text}</div>
                ) : (
                  <div style={{ maxWidth: "100%", width: "100%" }}>
                    <div className="msg-assistant">
                      <div style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink)" }}>
                        <Answer text={m.text} sources={m.sources} />
                        {m.streaming && <span className="type-caret" />}
                      </div>
                    </div>
                    {m.sources && m.sources.length > 0 && (
                      <div className="src-panel">
                        <div className="kicker" style={{ marginBottom: 6 }}>Sources · {m.sources.length}</div>
                        {m.sources.map((s) => (
                          s.url ? (
                            <Link key={s.n} href={s.url} className="src-row">
                              <span className="src-n">{s.n}</span>
                              <span className="src-ic" style={{ color: KIND_COLOR[s.kind] || "var(--faint)" }}>{KIND_ICON[s.kind] || "•"}</span>
                              <span className="src-title">{s.title}</span>
                              <span className="src-kind">{s.kind}</span>
                            </Link>
                          ) : (
                            <div key={s.n} className="src-row">
                              <span className="src-n">{s.n}</span>
                              <span className="src-ic">{KIND_ICON[s.kind] || "•"}</span>
                              <span className="src-title">{s.title}</span>
                              <span className="src-kind">{s.kind}</span>
                            </div>
                          )
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* composer */}
      <div style={{ maxWidth: 780, margin: "0 auto", width: "100%", paddingTop: 10 }}>
        <div className="composer">
          <textarea
            ref={taRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }}
            placeholder={scopeReq ? `Ask about ${scopeReq.ref}…` : "Ask about a contract, clause, counterparty, or your playbook…"}
            rows={1}
            disabled={streaming}
          />
          <button className="btn primary" disabled={streaming || !input.trim()} onClick={() => ask(input)}>
            {streaming ? "…" : "Ask"}
          </button>
        </div>
        <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textAlign: "center", marginTop: 6 }}>
          Advisory only · grounded in your workspace · every query is sealed on the audit chain · <kbd>↵</kbd> send · <kbd>⇧↵</kbd> newline
        </div>
      </div>
    </div>
  );
}
