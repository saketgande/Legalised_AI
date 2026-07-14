"use client";
import Link from "next/link";
import { useState } from "react";
import { api, type AgentStep, type AssistantSource } from "../../lib/api";

/* ───────── the AI copilot docked on a matter — Ask / Run, scoped in-context ───────── */

type AskMsg = { role: "user" | "assistant"; text: string; sources?: AssistantSource[]; streaming?: boolean };

function AskAnswer({ text, sources }: { text: string; sources?: AssistantSource[] }) {
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
          else if (m[2] !== undefined) {
            const s = byN.get(Number(m[2]));
            parts.push(s?.url ? <Link key={k++} href={s.url} className="cite-chip" title={s.title}>{m[2]}</Link> : <span key={k++} className="cite-chip">{m[2]}</span>);
          } else if (m[3] !== undefined) parts.push(<code key={k++} className="mono cite-code">{m[3]}</code>);
          last = re.lastIndex;
        }
        if (last < line.length) parts.push(line.slice(last));
        return <div key={li} style={{ minHeight: line ? undefined : 7 }}>{parts}</div>;
      })}
    </>
  );
}

function AskMode({ requestId, matterRef }: { requestId: string; matterRef: string }) {
  const [messages, setMessages] = useState<AskMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const suggestions = ["Summarize this matter", "What's blocking this?", "Is the liability clause on-playbook?"];

  async function ask(q: string) {
    const query = q.trim();
    if (!query || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: query }, { role: "assistant", text: "", streaming: true }]);
    setStreaming(true);
    const patch = (fn: (m: AskMsg) => AskMsg) => setMessages((p) => { const c = [...p]; c[c.length - 1] = fn(c[c.length - 1]); return c; });
    try {
      await api.assistantAsk(query, requestId, {
        onSources: (s) => patch((m) => ({ ...m, sources: s })),
        onDelta: (t) => patch((m) => ({ ...m, text: m.text + t })),
        onDone: () => patch((m) => ({ ...m, streaming: false })),
      });
    } catch (e) { patch((m) => ({ ...m, text: m.text || `⚠ ${String(e)}`, streaming: false })); }
    finally { setStreaming(false); patch((m) => ({ ...m, streaming: false })); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {messages.length === 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <p className="muted" style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 2 }}>Ask anything about <span className="mono" style={{ color: "var(--teal)" }}>{matterRef}</span> — grounded in its clauses, playbook, and history.</p>
          {suggestions.map((s) => <button key={s} className="suggest-card" style={{ padding: "8px 11px", fontSize: 12 }} onClick={() => ask(s)}>{s}</button>)}
        </div>
      )}
      {messages.map((m, i) => m.role === "user" ? (
        <div key={i} style={{ alignSelf: "flex-end", maxWidth: "90%" }} className="msg-user">{m.text}</div>
      ) : (
        <div key={i}>
          <div className="msg-assistant"><div style={{ fontSize: 13, lineHeight: 1.55 }}><AskAnswer text={m.text} sources={m.sources} />{m.streaming && <span className="type-caret" />}</div></div>
          {m.sources && m.sources.length > 0 && (
            <div className="src-panel" style={{ marginTop: 6 }}>
              {m.sources.slice(0, 5).map((s) => s.url
                ? <Link key={s.n} href={s.url} className="src-row"><span className="src-n">{s.n}</span><span className="src-title">{s.title}</span></Link>
                : <div key={s.n} className="src-row"><span className="src-n">{s.n}</span><span className="src-title">{s.title}</span></div>)}
            </div>
          )}
        </div>
      ))}
      <div className="composer" style={{ borderRadius: 10 }}>
        <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} disabled={streaming}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); } }}
          placeholder="Ask about this matter…" />
        <button className="btn primary sm" disabled={streaming || !input.trim()} onClick={() => ask(input)}>{streaming ? "…" : "Ask"}</button>
      </div>
    </div>
  );
}

type Res = { status: "pending" | "running" | "done"; result: string; sources: { title: string; url: string | null }[] };

function RunMode({ requestId, matterRef }: { requestId: string; matterRef: string }) {
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [results, setResults] = useState<Record<string, Res>>({});
  const [ran, setRan] = useState(false);
  const runQs = ["Review this against our playbook and recommend next steps", "What's blocking this from being sent?"];

  async function run(g?: string) {
    const goalText = (g ?? goal).trim();
    if (!goalText || running) return;
    setRunning(true); setRan(true); setSteps([]); setResults({}); setGoal("");
    try {
      await api.agentRun(goalText, requestId, {
        onPlan: (pl) => { setSteps(pl); setResults(Object.fromEntries(pl.map((s) => [s.key, { status: "pending", result: "", sources: [] }])) as Record<string, Res>); },
        onStep: (s) => setResults((r) => ({ ...r, [s.key]: { status: s.status, result: s.result ?? r[s.key]?.result ?? "", sources: s.sources ?? r[s.key]?.sources ?? [] } })),
        onDelta: (key, text) => setResults((r) => ({ ...r, [key]: { ...(r[key] || { status: "running", result: "", sources: [] }), status: "running", result: (r[key]?.result || "") + text } })),
        onDone: () => setRunning(false),
      });
    } catch { /* leave partial */ } finally { setRunning(false); }
  }
  const dot = (s: Res["status"]) => s === "done" ? "✓" : s === "running" ? "⟳" : "○";
  const dotColor = (s: Res["status"]) => s === "done" ? "var(--good)" : s === "running" ? "var(--warn)" : "var(--faint)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {!ran && (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <p className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>Give the agent a goal for <span className="mono" style={{ color: "var(--teal)" }}>{matterRef}</span> — it plans, runs the engines, and recommends.</p>
          {runQs.map((s) => <button key={s} className="suggest-card" style={{ padding: "8px 11px", fontSize: 12 }} onClick={() => run(s)}>{s}</button>)}
        </div>
      )}
      {ran && (
        <div className="agent-steps">
          {steps.map((st, i) => {
            const r = results[st.key] || { status: "pending", result: "", sources: [] };
            const isRec = st.key === "recommend";
            return (
              <div key={st.key} className="agent-step">
                <div className="agent-rail"><span className="agent-dot" style={{ color: dotColor(r.status), borderColor: dotColor(r.status), width: 20, height: 20, fontSize: 11 }}>{dot(r.status)}</span>{i < steps.length - 1 && <span className="agent-line" />}</div>
                <div className="agent-body" style={{ paddingBottom: 12 }}>
                  <div className="agent-title" style={{ fontSize: 12.5, color: r.status === "pending" ? "var(--faint)" : "var(--ink)" }}>{st.title}</div>
                  {r.result && (isRec
                    ? <div className="agent-rec" style={{ fontSize: 12.5, padding: "10px 12px" }}>{r.result.split("\n").map((ln, k) => <div key={k} style={{ minHeight: ln ? undefined : 6 }}>{ln}</div>)}{r.status === "running" && <span className="type-caret" />}</div>
                    : <div className="agent-result" style={{ fontSize: 12 }}>{r.result}{r.sources?.[0]?.url && <Link href={r.sources[0].url!} className="cell-src" style={{ marginLeft: 6 }}>open →</Link>}</div>)}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="composer" style={{ borderRadius: 10 }}>
        <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={1} disabled={running}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } }}
          placeholder="State a goal for this matter…" />
        <button className="btn primary sm" disabled={running || !goal.trim()} onClick={() => run()}>{running ? "…" : "Run"}</button>
      </div>
    </div>
  );
}

export function MatterCopilot({ requestId, matterRef }: { requestId: string; matterRef: string }) {
  const [mode, setMode] = useState<"ask" | "run">("ask");
  return (
    <div className="card card-pad" style={{ position: "sticky", top: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span className="kicker" style={{ color: "var(--em, var(--accent))" }}>◆ Copilot · on this matter</span>
        <div className="seg" style={{ transform: "scale(0.92)", transformOrigin: "right" }}>
          <button className={mode === "ask" ? "on" : ""} onClick={() => setMode("ask")}>Ask</button>
          <button className={mode === "run" ? "on" : ""} onClick={() => setMode("run")}>Run</button>
        </div>
      </div>
      {mode === "ask" ? <AskMode requestId={requestId} matterRef={matterRef} /> : <RunMode requestId={requestId} matterRef={matterRef} />}
      <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap", borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        <Link href={`/editor`} className="btn sm ghost" style={{ fontSize: 11 }}>✎ Draft in Editor</Link>
        <Link href={`/review/${requestId}`} className="btn sm ghost" style={{ fontSize: 11 }}>▤ Redline cockpit</Link>
      </div>
    </div>
  );
}
