"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type AgentStep, type AgentStepResult, type RequestSummary } from "../../lib/api";

const SUGGESTIONS = [
  "Review this NDA against our playbook and recommend next steps",
  "Assess the risk on this request and tell me what to do",
  "Summarize this contract's key terms and any red flags",
  "What's blocking this from being sent?",
];

type Res = { status: "pending" | "running" | "done"; result: string; sources: { title: string; url: string | null }[] };

export default function Agent() {
  const [goal, setGoal] = useState("");
  const [scopeId, setScopeId] = useState("");
  const [reqs, setReqs] = useState<RequestSummary[]>([]);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [results, setResults] = useState<Record<string, Res>>({});
  const [ran, setRan] = useState(false);

  useEffect(() => { api.listRequests().then(setReqs).catch(() => {}); }, []);

  async function run(g?: string) {
    const goalText = (g ?? goal).trim();
    if (!goalText || running) return;
    setRunning(true); setRan(true); setSteps([]); setResults({});
    try {
      await api.agentRun(goalText, scopeId || null, {
        onPlan: (pl) => {
          setSteps(pl);
          setResults(Object.fromEntries(pl.map((s) => [s.key, { status: "pending", result: "", sources: [] }])) as Record<string, Res>);
        },
        onStep: (s: AgentStepResult) => setResults((r) => ({
          ...r,
          [s.key]: {
            status: s.status,
            result: s.result ?? r[s.key]?.result ?? "",
            sources: s.sources ?? r[s.key]?.sources ?? [],
          },
        })),
        onDelta: (key, text) => setResults((r) => ({ ...r, [key]: { ...(r[key] || { status: "running", result: "", sources: [] }), status: "running", result: (r[key]?.result || "") + text } })),
        onDone: () => setRunning(false),
      });
    } catch (e) {
      setResults((r) => ({ ...r, _err: { status: "done", result: `⚠ ${String(e)}`, sources: [] } }));
    } finally { setRunning(false); }
  }

  const scopeReq = reqs.find((r) => r.id === scopeId);
  const dot = (s: Res["status"]) => s === "done" ? "✓" : s === "running" ? "⟳" : "○";
  const dotColor = (s: Res["status"]) => s === "done" ? "var(--good)" : s === "running" ? "var(--warn)" : "var(--faint)";

  return (
    <div>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div className="page-head-row">
          <div>
            <p className="kicker">AI · agentic workflow</p>
            <h1>Agent</h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.1em" }}>Scope</span>
            <select value={scopeId} onChange={(e) => setScopeId(e.target.value)} style={{ width: 250, fontSize: 12.5 }}>
              <option value="">Whole workspace</option>
              {reqs.slice(0, 100).map((r) => (
                <option key={r.id} value={r.id}>{r.ref} · {r.category === "ADVICE" ? (r.purpose || "advice") : r.counterparty_name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* goal composer */}
      <div className="composer" style={{ maxWidth: 900, margin: "0 auto" }}>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } }}
          placeholder={scopeReq ? `State a goal for ${scopeReq.ref}…` : "State a goal in plain language — the agent will plan and run it…"}
          rows={1}
          disabled={running}
        />
        <button className="btn primary" disabled={running || !goal.trim()} onClick={() => run()}>
          {running ? "Running…" : "Run agent"}
        </button>
      </div>

      {!ran ? (
        <div style={{ maxWidth: 620, margin: "6vh auto 0", textAlign: "center" }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>◆</div>
          <h2 className="h-serif" style={{ fontSize: 24, marginBottom: 8 }}>Give the agent a goal</h2>
          <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.55, marginBottom: 20 }}>
            It plans a multi-step run over your real engines — classification, contract summary, the risk engine, the redline engine, the playbook — executes each step, and synthesizes a recommendation. Advisory: it recommends; you approve.
          </p>
          <div style={{ display: "grid", gap: 8 }}>
            {SUGGESTIONS.map((s) => <button key={s} className="suggest-card" onClick={() => run(s)}>{s}</button>)}
          </div>
        </div>
      ) : (
        <div style={{ maxWidth: 900, margin: "16px auto 0" }}>
          <div className="kicker" style={{ marginBottom: 12 }}>Run plan{scopeReq && <> · scoped to <span className="mono" style={{ color: "var(--teal)" }}>{scopeReq.ref}</span></>}</div>
          <div className="agent-steps">
            {steps.map((st, i) => {
              const r = results[st.key] || { status: "pending", result: "", sources: [] };
              const isRec = st.key === "recommend";
              return (
                <div key={st.key} className="agent-step">
                  <div className="agent-rail">
                    <span className="agent-dot" style={{ color: dotColor(r.status), borderColor: dotColor(r.status) }}>{dot(r.status)}</span>
                    {i < steps.length - 1 && <span className="agent-line" />}
                  </div>
                  <div className="agent-body">
                    <div className="agent-title" style={{ color: r.status === "pending" ? "var(--faint)" : "var(--ink)" }}>{st.title}</div>
                    {r.result && (
                      <div className={isRec ? "agent-rec" : "agent-result"}>
                        {isRec ? r.result.split("\n").map((ln, k) => <div key={k} style={{ minHeight: ln ? undefined : 7 }}>{ln}</div>) : r.result}
                        {isRec && r.status === "running" && <span className="type-caret" />}
                      </div>
                    )}
                    {r.sources && r.sources.length > 0 && (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 5 }}>
                        {r.sources.map((s, k) => s.url
                          ? <Link key={k} href={s.url} className="ground-chip" style={{ color: "var(--teal)", background: "color-mix(in srgb, var(--teal) 14%, transparent)" }}>{s.title} →</Link>
                          : <span key={k} className="mono" style={{ fontSize: 9.5, color: "var(--faint)" }}>{s.title}</span>)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", marginTop: 10 }}>
            Advisory · the agent reads and recommends — it never mutates state · every run is sealed on the audit chain
          </div>
        </div>
      )}
    </div>
  );
}
