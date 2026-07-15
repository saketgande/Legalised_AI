"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AgentStep, type AssistantSource, type EditorGrounding, type RequestSummary, type TabularDoc } from "../../lib/api";

/* ─────────────────────────── types ─────────────────────────── */
type Rich =
  | { kind: "table"; rows: TabularDoc[]; cols: string[]; cells: Record<string, { value: string; section: string; url: string | null }> }
  | { kind: "agent"; steps: AgentStep[]; results: Record<string, { status: string; result: string; sources?: { title: string; url: string | null }[] }> }
  | { kind: "draft"; text: string; grounding: EditorGrounding[] };
type Msg = { role: "user" | "assistant"; text: string; sources?: AssistantSource[]; streaming?: boolean; rich?: Rich };
type Thread = { id: string; title: string; messages: Msg[]; at: number };

const THREADS_KEY = "fd_assistant_threads_v1";
const KIND_ICON: Record<string, string> = { clause: "§", playbook: "▦", request: "◆" };
const KIND_COLOR: Record<string, string> = { clause: "var(--teal)", playbook: "var(--amber)", request: "var(--accent)" };
const DEFAULT_COLS = ["Limitation of liability cap", "Governing law", "Term length"];

const QUICK = [
  { k: "Ask", q: "What's our position on limitation of liability?", c: "var(--teal)" },
  { k: "Compare", q: "Compare liability and governing law across our open NDAs", c: "var(--accent)" },
  { k: "Draft", q: "Draft a limitation of liability clause capped at 12 months' fees", c: "var(--amber)" },
  { k: "Run", q: "Review our highest-risk matter against the playbook and recommend next steps", c: "var(--purple)" },
];

/* which capability a question implies — the assistant spawns the right tool inline */
function route(q: string): "table" | "draft" | "agent" | "ask" {
  const s = q.toLowerCase();
  if (/\b(compare|across|vs\.?|side by side|table|grid|which of)\b/.test(s) && /(nda|ndas|contract|contracts|matters|paper|them)/.test(s)) return "table";
  if (/\b(draft|re-?write|redraft|write (a|the)|counter(-| )?(proposal|clause)?|revise|clause for)\b/.test(s)) return "draft";
  if (/\b(review|assess|recommend|next steps|what should we|run the agent|plan|blocking|walk me through)\b/.test(s)) return "agent";
  return "ask";
}

/* render answer text: **bold**, [n]→citation, `code` */
function Answer({ text, sources }: { text: string; sources?: AssistantSource[] }) {
  const byN = new Map((sources || []).map((s) => [s.n, s]));
  return (
    <>
      {text.split("\n").map((line, li) => {
        const parts: React.ReactNode[] = [];
        const re = /\*\*(.+?)\*\*|\[(\d+)\]|`([^`]+)`/g;
        let last = 0, m: RegExpExecArray | null, k = 0;
        while ((m = re.exec(line)) !== null) {
          if (m.index > last) parts.push(line.slice(last, m.index));
          if (m[1] !== undefined) parts.push(<strong key={k++}>{m[1]}</strong>);
          else if (m[2] !== undefined) { const src = byN.get(Number(m[2])); parts.push(src?.url ? <Link key={k++} href={src.url} title={src.title} className="cite-chip">{m[2]}</Link> : <span key={k++} className="cite-chip" title={src?.title}>{m[2]}</span>); }
          else if (m[3] !== undefined) parts.push(<code key={k++} className="mono cite-code">{m[3]}</code>);
          last = re.lastIndex;
        }
        if (last < line.length) parts.push(line.slice(last));
        return <div key={li} style={{ minHeight: line ? undefined : 8 }}>{parts}</div>;
      })}
    </>
  );
}

/* inline rich result cards — the four tools, spawned in the thread */
function RichCard({ r }: { r: Rich }) {
  if (r.kind === "table") {
    return (
      <div className="rich-card">
        <div className="rich-head"><span>▦ Tabular review · {r.rows.length} docs × {r.cols.length} questions</span><Link href="/tabular" className="rich-open">Open full →</Link></div>
        <div style={{ overflowX: "auto" }}>
          <table className="tab-grid">
            <thead><tr><th className="doc-col">Document</th>{r.cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {r.rows.map((d) => (
                <tr key={d.request_id}>
                  <td className="doc-col"><Link href={d.url} className="mono" style={{ color: "var(--accent-ink)", fontSize: 11, fontWeight: 600, textDecoration: "none" }}>{d.ref}</Link><div style={{ fontSize: 11.5 }}>{d.counterparty}</div></td>
                  {r.cols.map((c, ci) => {
                    const cell = r.cells[`${d.request_id}::${ci}`];
                    return <td key={c}>{cell ? <><div style={{ fontSize: 12, color: cell.value === "Not addressed" ? "var(--faint)" : "var(--ink)" }}>{cell.value}</div>{cell.section && cell.url && <Link href={cell.url} className="cell-src">§{cell.section} →</Link>}</> : <span className="cell-spin" />}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  if (r.kind === "agent") {
    const dot = (s: string) => s === "done" ? "✓" : s === "running" ? "⟳" : "○";
    const dc = (s: string) => s === "done" ? "var(--good)" : s === "running" ? "var(--warn)" : "var(--faint)";
    return (
      <div className="rich-card" style={{ padding: "14px 16px" }}>
        <div className="rich-head" style={{ border: 0, padding: 0, marginBottom: 10 }}><span>▷ Agent run · {r.steps.length} steps</span></div>
        <div className="agent-steps">
          {r.steps.map((st, i) => {
            const res = r.results[st.key] || { status: "pending", result: "" };
            const isRec = st.key === "recommend";
            return (
              <div key={st.key} className="agent-step">
                <div className="agent-rail"><span className="agent-dot" style={{ color: dc(res.status), borderColor: dc(res.status), width: 22, height: 22, fontSize: 11 }}>{dot(res.status)}</span>{i < r.steps.length - 1 && <span className="agent-line" />}</div>
                <div className="agent-body" style={{ paddingBottom: 12 }}>
                  <div className="agent-title" style={{ fontSize: 13, color: res.status === "pending" ? "var(--faint)" : "var(--ink)" }}>{st.title}</div>
                  {res.result && (isRec
                    ? <div className="agent-rec" style={{ fontSize: 12.5 }}>{res.result.split("\n").map((l, k) => <div key={k} style={{ minHeight: l ? undefined : 6 }}>{l}</div>)}</div>
                    : <div className="agent-result" style={{ fontSize: 12 }}>{res.result}{res.sources?.[0]?.url && <Link href={res.sources[0].url!} className="cell-src" style={{ marginLeft: 6 }}>open →</Link>}</div>)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  // draft
  return (
    <div className="rich-card">
      <div className="rich-head"><span>✎ Draft{r.grounding.length > 0 && <> · grounded in {r.grounding.map((g) => g.rule_key).join(", ")}</>}</span><Link href="/editor" className="rich-open">Open in editor →</Link></div>
      <div className="diff-after" style={{ margin: 14, borderRadius: 8 }}>{r.text || <span className="faint">drafting…</span>}</div>
    </div>
  );
}

export default function Assistant() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadId, setThreadId] = useState<string>("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [scopeId, setScopeId] = useState<string>("");
  const [reqs, setReqs] = useState<RequestSummary[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listRequests().then(setReqs).catch(() => {});
    try { const t = JSON.parse(localStorage.getItem(THREADS_KEY) || "[]"); if (Array.isArray(t)) setThreads(t); } catch {}
  }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  const persist = useCallback((msgs: Msg[]) => {
    if (msgs.length === 0) return;
    const id = threadId || `t${Date.now()}`;
    const title = msgs.find((m) => m.role === "user")?.text.slice(0, 48) || "New conversation";
    setThreadId(id);
    setThreads((prev) => {
      const next = [{ id, title, messages: msgs, at: Date.now() }, ...prev.filter((t) => t.id !== id)].slice(0, 25);
      localStorage.setItem(THREADS_KEY, JSON.stringify(next));
      return next;
    });
  }, [threadId]);

  const patchLast = (fn: (m: Msg) => Msg) => setMessages((prev) => { const c = [...prev]; c[c.length - 1] = fn(c[c.length - 1]); return c; });

  async function send(q: string) {
    const query = q.trim();
    if (!query || busy) return;
    setInput(""); setBusy(true);
    const kind = route(query);
    setMessages((m) => [...m, { role: "user", text: query }, { role: "assistant", text: "", streaming: true }]);
    try {
      if (kind === "table") await runTable(query);
      else if (kind === "draft") await runDraft(query);
      else if (kind === "agent") await runAgent(query);
      else await runAsk(query);
    } catch (e) {
      patchLast((m) => ({ ...m, text: m.text || `⚠ ${String(e)}`, streaming: false }));
    } finally {
      setBusy(false);
      patchLast((m) => ({ ...m, streaming: false }));
      setMessages((cur) => { persist(cur); return cur; });
    }
  }

  async function runAsk(query: string) {
    await api.assistantAsk(query, scopeId || null, {
      onSources: (s) => patchLast((m) => ({ ...m, sources: s })),
      onDelta: (t) => patchLast((m) => ({ ...m, text: m.text + t })),
      onDone: () => patchLast((m) => ({ ...m, streaming: false })),
    });
  }
  async function runTable(query: string) {
    patchLast((m) => ({ ...m, text: "Comparing across your documents — spinning up a tabular review:", streaming: false }));
    const docs = (await api.tabularDocuments()).slice(0, 6);
    if (!docs.length) { patchLast((m) => ({ ...m, text: "No documents to compare yet." })); return; }
    const cols = DEFAULT_COLS;
    patchLast((m) => ({ ...m, rich: { kind: "table", rows: docs, cols, cells: {} } }));
    await api.tabularRun(docs.map((d) => d.request_id), cols, {
      onMeta: () => {},
      onCell: (c) => patchLast((m) => m.rich?.kind === "table" ? { ...m, rich: { ...m.rich, cells: { ...m.rich.cells, [`${c.request_id}::${c.col}`]: { value: c.value, section: c.section, url: c.url } } } } : m),
      onDone: () => {},
    });
  }
  async function runDraft(query: string) {
    patchLast((m) => ({ ...m, text: "Drafting from your playbook:", streaming: false, rich: { kind: "draft", text: "", grounding: [] } }));
    await api.editorDraft(query, "", {
      onGrounding: (g) => patchLast((m) => m.rich?.kind === "draft" ? { ...m, rich: { ...m.rich, grounding: g } } : m),
      onDelta: (t) => patchLast((m) => m.rich?.kind === "draft" ? { ...m, rich: { ...m.rich, text: m.rich.text + t } } : m),
      onDone: () => {},
    });
  }
  async function runAgent(query: string) {
    patchLast((m) => ({ ...m, text: "Running the agent over your workspace:", streaming: false, rich: { kind: "agent", steps: [], results: {} } }));
    await api.agentRun(query, scopeId || null, {
      onPlan: (pl) => patchLast((m) => m.rich?.kind === "agent" ? { ...m, rich: { ...m.rich, steps: pl, results: Object.fromEntries(pl.map((s) => [s.key, { status: "pending", result: "" }])) } } : m),
      onStep: (s) => patchLast((m) => m.rich?.kind === "agent" ? { ...m, rich: { ...m.rich, results: { ...m.rich.results, [s.key]: { status: s.status, result: s.result ?? m.rich.results[s.key]?.result ?? "", sources: s.sources } } } } : m),
      onDelta: (key, text) => patchLast((m) => m.rich?.kind === "agent" ? { ...m, rich: { ...m.rich, results: { ...m.rich.results, [key]: { ...(m.rich.results[key] || { status: "running", result: "" }), status: "running", result: (m.rich.results[key]?.result || "") + text } } } } : m),
      onDone: () => {},
    });
  }

  function newChat() { setMessages([]); setThreadId(""); }
  function openThread(t: Thread) { setMessages(t.messages); setThreadId(t.id); }

  const scopeReq = reqs.find((r) => r.id === scopeId);
  const recentMatters = reqs.filter((r) => r.category === "CONTRACT" || r.category === "ADVICE").slice(0, 5);

  return (
    <div className="asst-grid">
      {/* thread rail */}
      <aside className="thread-rail">
        <button className="thr-new" onClick={newChat}>✦ New conversation</button>
        <div className="thr-lab">History</div>
        <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 2 }}>
          {threads.length === 0 && <div className="faint" style={{ fontSize: 11.5, padding: "6px 8px" }}>Your conversations will appear here.</div>}
          {threads.map((t) => (
            <button key={t.id} className={`thr-item ${t.id === threadId ? "on" : ""}`} onClick={() => openThread(t)} title={t.title}>{t.title}</button>
          ))}
        </div>
        <div className="thr-lab">Jump into a matter</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {recentMatters.map((r) => (
            <button key={r.id} className="thr-item" onClick={() => setScopeId(r.id)} style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>
              <span style={{ color: "var(--accent-ink)" }}>{r.ref}</span> · {r.category === "ADVICE" ? "advice" : r.counterparty_name}
            </button>
          ))}
        </div>
      </aside>

      {/* conversation column */}
      <div className="chat-col">
        <div className="chat-head">
          <div><p className="kicker" style={{ margin: 0 }}>AI · grounded in your workspace</p><h1 style={{ fontSize: 22, margin: "2px 0 0" }}>Assistant</h1></div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.1em" }}>Scope</span>
            <select value={scopeId} onChange={(e) => setScopeId(e.target.value)} style={{ width: 230, fontSize: 12.5 }}>
              <option value="">All matters</option>
              {reqs.slice(0, 100).map((r) => <option key={r.id} value={r.id}>{r.ref} · {r.category === "ADVICE" ? (r.purpose || "advice") : r.counterparty_name}</option>)}
            </select>
          </div>
        </div>

        <div ref={scrollRef} className="chat-scroll">
          {messages.length === 0 ? (
            <div style={{ maxWidth: 680, margin: "5vh auto 0" }}>
              <div style={{ textAlign: "center", marginBottom: 24 }}>
                <div style={{ fontSize: 30, marginBottom: 8 }}>◆</div>
                <h2 className="h-serif" style={{ fontSize: 25, marginBottom: 8 }}>What can I help you with?</h2>
                <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.55 }}>Ask, compare, draft, or run an agent — grounded in your contracts, clauses, and playbook. I'll open a table, a draft, or an agent run right here in the thread.{scopeReq && <> Scoped to <span className="mono" style={{ color: "var(--teal)" }}>{scopeReq.ref}</span>.</>}</p>
              </div>
              <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
                {QUICK.map((s) => (
                  <button key={s.q} className="suggest-card" onClick={() => send(s.q)}>
                    <span className="mono" style={{ fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: s.c, display: "block", marginBottom: 5 }}>{s.k}</span>{s.q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ maxWidth: 820, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16, paddingBottom: 8 }}>
              {messages.map((m, i) => (
                <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                  {m.role === "user" ? <div className="msg-user">{m.text}</div> : (
                    <div style={{ width: "100%" }}>
                      {m.text && <div className="msg-assistant"><div style={{ fontSize: 14, lineHeight: 1.6, color: "var(--ink)" }}><Answer text={m.text} sources={m.sources} />{m.streaming && !m.rich && <span className="type-caret" />}</div></div>}
                      {m.rich && <RichCard r={m.rich} />}
                      {m.sources && m.sources.length > 0 && (
                        <div className="src-panel">
                          <div className="kicker" style={{ marginBottom: 6 }}>Sources · {m.sources.length}</div>
                          {m.sources.map((s) => s.url
                            ? <Link key={s.n} href={s.url} className="src-row"><span className="src-n">{s.n}</span><span className="src-ic" style={{ color: KIND_COLOR[s.kind] || "var(--faint)" }}>{KIND_ICON[s.kind] || "•"}</span><span className="src-title">{s.title}</span><span className="src-kind">{s.kind}</span></Link>
                            : <div key={s.n} className="src-row"><span className="src-n">{s.n}</span><span className="src-ic">{KIND_ICON[s.kind] || "•"}</span><span className="src-title">{s.title}</span><span className="src-kind">{s.kind}</span></div>)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="chat-composer">
          <div className="composer">
            <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
              placeholder={scopeReq ? `Ask, compare, draft, or run — about ${scopeReq.ref}…` : "Ask, compare across NDAs, draft a clause, or run an agent…"} rows={1} disabled={busy} />
            <button className="btn primary" disabled={busy || !input.trim()} onClick={() => send(input)}>{busy ? "…" : "Ask"}</button>
          </div>
          <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textAlign: "center", marginTop: 6 }}>Advisory · grounded in your workspace · every query sealed on the audit chain · <kbd>↵</kbd> send</div>
        </div>
      </div>
    </div>
  );
}
