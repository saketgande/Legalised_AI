"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, RUNG_RANK, type ProposedChange, type RequestDetail } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { Timeline } from "../../components/Timeline";

/* ---------- markdown renderers ---------- */
function inline(text: string, key: number) {
  // handles **bold** and ~~strike~~ inline
  const parts = text.split(/(\*\*[^*]+\*\*|~~[^~]+~~)/g);
  return (
    <span key={key}>
      {parts.map((p, j) => {
        if (p.startsWith("**") && p.endsWith("**")) return <ins key={j}>{p.slice(2, -2)}</ins>;
        if (p.startsWith("~~") && p.endsWith("~~")) return <del key={j}>{p.slice(2, -2)}</del>;
        return p;
      })}
    </span>
  );
}
function Md({ md, redline = false }: { md: string; redline?: boolean }) {
  return (
    <div className={redline ? "cc-redline" : "doc-body"}>
      {md.split("\n").map((line, i) => {
        if (line.startsWith("## ")) return <h2 key={i} className="h-serif">{line.slice(3)}</h2>;
        if (line.startsWith("# ")) return <h1 key={i} className="h-serif">{line.slice(2)}</h1>;
        if (line.trim() === "---") return <hr key={i} />;
        if (line.trim() === "") return null;
        if (line.startsWith("_") && line.endsWith("_")) return <p key={i}><em>{line.slice(1, -1)}</em></p>;
        return <p key={i}>{inline(line, i)}</p>;
      })}
    </div>
  );
}

/* ---------- inbound: a single proposed-change card ---------- */
function ChangeCard({ c, onDecide, busy, canApprove, canLearn, onLearn }: { c: ProposedChange; onDecide: (a: "approve" | "reject" | "edit", t?: string) => void; busy: boolean; canApprove: boolean; canLearn: boolean; onLearn: () => void }) {
  const decided = c.decision !== "PENDING";
  return (
    <div className={`change-card ${decided ? "decided" : ""}`}>
      <div className="cc-top">
        <span className={`find-badge ${c.finding}`}>{c.finding}</span>
        {c.section_no && <span className="cc-sec">§{c.section_no}</span>}
        <span className="cc-head">{c.heading}</span>
      </div>
      <p className="cc-rationale">{c.rationale}</p>

      <div className="checks2">
        {c.checks.map((ch, i) => (
          <div key={i} className={`chk2 ${ch.passed ? "pass" : "fail"}`}>
            <span className="ci2">{ch.passed ? "✓" : "✕"}</span>
            <span className="cx2">
              <span className={`kind ${ch.kind}`}>{ch.kind === "DETERMINISTIC" ? "DET" : "SEM"}</span>
              {ch.detail}
              {ch.model && ch.model !== "heuristic" && <span className="model-tag">🤖 {ch.model}</span>}
            </span>
          </div>
        ))}
      </div>

      {c.rule_key && (
        <div className="cc-cite">📖<div>Grounded in <b>Playbook · {c.rule_key}</b></div></div>
      )}

      {(c.before_text || c.after_text) && (
        <div className="cc-redline">
          {c.before_text && <p><del>{c.before_text}</del></p>}
          {c.after_text && <p><ins>{c.after_text}</ins></p>}
        </div>
      )}

      <div className="cc-meta">
        {c.confidence != null && (
          <span className="cc-conf">conf <span className="bar2"><i style={{ width: `${Math.round(c.confidence * 100)}%` }} /></span>
            <b style={{ fontFamily: "var(--mono)" }}>{c.confidence.toFixed(2)}</b></span>
        )}
        {c.triggered_rung !== "none" && <span className="cc-rung">needs {c.triggered_rung.replace(/_/g, " ")}</span>}
      </div>

      {decided ? (
        <>
          <div className={`cc-decided ${c.decision}`}>
            {c.decision === "REJECTED" ? "✕ Rejected — their language kept" : "✓ Accepted into counter-proposal"}
          </div>
          {c.decision === "APPROVED_WITH_EDIT" && c.rule_key && canLearn && (
            <button className="btn ghost" style={{ marginTop: 8, fontSize: 12, padding: "5px 10px" }} disabled={busy} onClick={onLearn}>
              📖 Teach the playbook · adopt this as {c.rule_key}&rsquo;s language →
            </button>
          )}
        </>
      ) : (
        <>
          <div className="cc-actions">
            <button className="btn primary" disabled={busy || !canApprove}
              title={canApprove ? "" : `Needs ${c.triggered_rung.replace(/_/g, " ")} sign-off`}
              onClick={() => onDecide("approve")}>Approve</button>
            <button className="btn" disabled={busy || !canApprove}
              title={canApprove ? "" : `Needs ${c.triggered_rung.replace(/_/g, " ")} sign-off`}
              onClick={() => {
                const t = window.prompt("Edit the proposed language:", c.after_text);
                if (t) onDecide("edit", t);
              }}>Edit</button>
            <button className="btn reject" disabled={busy} onClick={() => onDecide("reject")}>Reject</button>
          </div>
          {!canApprove && (
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              You can reject, but approving this needs {c.triggered_rung.replace(/_/g, " ")} sign-off.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return null;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane}</span>;
}

export default function ReviewPage({ params }: { params: { id: string } }) {
  const { user } = useAuth();
  const [r, setR] = useState<RequestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showCounter, setShowCounter] = useState(false);
  const rank = user?.rank ?? 0;
  const canClear = (rung: string) => (user?.permissions.includes("review:decide") ?? false) && rank >= (RUNG_RANK[rung] ?? 0);

  const load = useCallback(() => api.getRequest(params.id).then(setR).catch((e) => setErr(String(e))), [params.id]);
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<RequestDetail>) {
    setBusy(true); setErr(null);
    try { setR(await fn()); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  async function learn(changeId: string, ruleKey: string | null) {
    setBusy(true); setErr(null);
    try { await api.learnFromChange(changeId); setErr(null); alert(`Playbook updated — ${ruleKey} now uses your edited language.`); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  if (err && !r) return <div className="container"><div className="notice warn">{err}</div></div>;
  if (!r) return <div className="container muted">Loading…</div>;

  const canSend = r.state === "APPROVED";
  const outForSig = r.state === "OUT_FOR_SIGNATURE";
  const filed = r.state === "EXECUTED" || r.state === "FILED";
  const inbound = !!r.review;

  return (
    <div className="container">
      <Link href="/inbox" className="muted" style={{ fontSize: 13 }}>← Inbox</Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", margin: "10px 0 4px" }}>
        <span className="mono muted" style={{ fontSize: 12.5 }}>{r.ref}</span>
        <h1 className="h-serif" style={{ fontSize: 22, margin: 0 }}>{r.counterparty_name}</h1>
        <span className="muted" style={{ fontSize: 12 }}>
          {r.nda_type === "MUTUAL" ? "Mutual NDA" : "One-way NDA"} · {r.direction === "INBOUND" ? "their paper — we review" : "our paper — we send"}
        </span>
        {inbound ? <span className="pill escalated">INBOUND</span> : <LanePill lane={r.lane} />}
        <span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span>
        {r.playbook_name && (
          <span className="pill accent" title="The playbook this request was reviewed against">
            📕 {r.playbook_name} v{r.playbook_version}
          </span>
        )}
      </div>

      {inbound ? (
        /* ===================== DOCUMENT DESK (inbound review) ===================== */
        (() => {
          const clauses = r.document?.clauses ?? [];
          const changes = r.review!.changes;
          const devBySec: Record<string, ProposedChange> = {};
          changes.forEach((c) => { if (c.section_no && c.finding !== "MISSING") devBySec[c.section_no] = c; });
          const missing = changes.filter((c) => c.finding === "MISSING");
          const canLearn = user?.permissions.includes("playbook:manage") ?? false;
          return (
            <>
              <div className="summary-chips" style={{ marginTop: 14 }}>
                <span className="schip dev"><b>{r.review!.summary.deviation ?? 0}</b> deviations</span>
                <span className="schip miss"><b>{r.review!.summary.missing ?? 0}</b> missing clauses</span>
                <span className="schip ok"><b>{r.review!.summary.compliant ?? 0}</b> on-playbook</span>
                {r.review!.required_rungs.length > 0 && (
                  <span className="schip" style={{ marginLeft: "auto" }}>
                    needs sign-off: {r.review!.required_rungs.map((x) => x.replace(/_/g, " ")).join(" · ")}
                  </span>
                )}
              </div>

              {/* action strip */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
                {canSend && (
                  <button className="btn primary" disabled={busy} onClick={() => act(() => api.send(params.id))}>
                    Send counter-proposal →
                  </button>
                )}
                {!canSend && !outForSig && !filed && (
                  <span className="muted" style={{ fontSize: 12.5 }}>Decide every proposed change to unlock the counter-proposal.</span>
                )}
                <button className="btn ghost sm" onClick={() => setShowCounter((s) => !s)}>
                  {showCounter ? "Hide" : "Preview"} counter-proposal
                </button>
                {err && <span className="notice warn" style={{ padding: "6px 10px" }}>{err}</span>}
              </div>

              {outForSig && (
                <div className="notice info" style={{ marginTop: 12 }}>
                  Counter-proposal sent for signature{r.esign_provider ? ` via ${r.esign_provider}` : ""}. Awaiting the counterparty.
                  {r.esign_provider !== "docusign" && (
                    <button className="btn sm" style={{ marginLeft: 12 }} disabled={busy}
                      onClick={() => act(() => api.simulateSignature(params.id))}>Simulate signature (dev)</button>
                  )}
                </div>
              )}
              {filed && <div className="notice good" style={{ marginTop: 12 }}>✓ Executed and filed{r.esign_provider ? ` (${r.esign_provider})` : ""}.</div>}

              <div className="desk">
                {/* clause outline */}
                <aside className="desk-outline">
                  <div className="desk-ol-label">Clauses</div>
                  {clauses.map((c) => (
                    <a key={c.id} href={`#cl-${c.section_no}`} className={`desk-ol-link ${devBySec[c.section_no] ? "dev" : ""}`}>
                      <span className="desk-ol-dot" /><span className="num">{c.section_no}</span>
                      <span className="nm">{c.heading}</span>
                    </a>
                  ))}
                  {missing.length > 0 && (
                    <a href="#missing" className="desk-ol-missing"><b>{missing.length}</b> missing clauses</a>
                  )}
                </aside>

                {/* the document */}
                <div className="desk-paper">
                  <div className="desk-paper-head">
                    <h1>{r.nda_type === "MUTUAL" ? "Mutual" : "One-Way"} Non-Disclosure Agreement</h1>
                    <div className="parties">their paper — {r.counterparty_name}</div>
                  </div>
                  {clauses.map((c) => {
                    const dev = devBySec[c.section_no];
                    return (
                      <section key={c.id} id={`cl-${c.section_no}`} className={`desk-clause ${dev ? "flagged" : ""}`}>
                        <h2><span className="cn">{c.section_no}.</span> {c.heading}{dev && <span className="desk-anchor">REDLINE</span>}</h2>
                        <p>{c.body_text}</p>
                        {dev && (dev.before_text || dev.after_text) && (
                          <div className="desk-inline-redline">
                            {dev.before_text && <del>{dev.before_text}</del>}{dev.before_text && dev.after_text ? " " : ""}{dev.after_text && <ins>{dev.after_text}</ins>}
                          </div>
                        )}
                      </section>
                    );
                  })}
                  {missing.length > 0 && (
                    <div id="missing" className="desk-missing">
                      <div className="desk-missing-h">{missing.length} standard clauses are absent from their paper</div>
                      <div className="desk-missing-list">
                        {missing.map((m) => <span key={m.id} className="desk-missing-chip">{m.heading}</span>)}
                      </div>
                    </div>
                  )}
                </div>

                {/* margin comments = the proposed redlines */}
                <div className="desk-margin">
                  <div className="desk-margin-label">Open redlines · {changes.length}</div>
                  {changes.map((c) => (
                    <ChangeCard key={c.id} c={c} busy={busy} canApprove={canClear(c.triggered_rung)}
                      canLearn={canLearn} onLearn={() => learn(c.id, c.rule_key)}
                      onDecide={(a, t) => act(() => api.decideChange(c.id, a, t))} />
                  ))}
                  <div className="card card-pad" style={{ marginTop: 4 }}>
                    <div className="kicker" style={{ marginBottom: 10 }}>Audit timeline</div>
                    <Timeline events={r.timeline} />
                  </div>
                </div>
              </div>

              {showCounter && (
                <div className="card" style={{ padding: "22px 26px", marginTop: 16 }}>
                  <div className="kicker" style={{ marginBottom: 8 }}>Counter-proposal preview (approved edits applied)</div>
                  <hr className="hr" />
                  <Md md={r.review!.counter_markdown} redline />
                </div>
              )}
            </>
          );
        })()
      ) : (
        /* ===================== OUTBOUND (document + ladder) ===================== */
        <div className="cockpit-grid" style={{ marginTop: 20 }}>
          <div className="card" style={{ padding: "22px 26px" }}>
            {r.document ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span className="kicker">Draft · v{r.document.version_no} · {r.document.clauses.length} clauses</span>
                  <span className="mono muted" style={{ fontSize: 11 }} title="content hash">#{r.document.content_hash.slice(0, 12)}</span>
                </div>
                <hr className="hr" />
                <Md md={r.document.body_markdown} />
              </>
            ) : <div className="muted">No document generated.</div>}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="card" style={{ padding: 16 }}>
              <div className="kicker" style={{ marginBottom: 10 }}>Why this lane</div>
              <ul className="reasons">{r.triage_reasons.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </div>
            {r.ladder && (
              <div className="card" style={{ padding: 16 }}>
                <div className="kicker" style={{ marginBottom: 10 }}>Approval ladder</div>
                <div className="ladder-rows">
                  {r.ladder.steps.map((s) => {
                    const done = s.status === "APPROVED";
                    return (
                      <div key={s.id} className={`lr ${done ? "done" : "here"}`}>
                        <span className="lnode" />
                        <div style={{ flex: 1 }}>
                          <div className="who2">{s.assignee_name ?? s.rung} · {s.rung.replace(/_/g, " ")}{done && " ✓"}</div>
                          <div className="why">{s.reason}</div>
                          {!done && (
                            <button className="btn primary" style={{ marginTop: 8, padding: "6px 12px", fontSize: 12.5 }}
                              disabled={busy || !canClear(s.rung)}
                              title={canClear(s.rung) ? "" : `Needs ${s.rung.replace(/_/g, " ")} sign-off`}
                              onClick={() => act(() => api.approveStep(s.id))}>
                              Approve as {s.rung.replace(/_/g, " ")}
                            </button>
                          )}
                          {!done && !canClear(s.rung) && (
                            <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>Needs {s.rung.replace(/_/g, " ")} sign-off.</div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="card" style={{ padding: 16 }}>
              <div className="kicker" style={{ marginBottom: 10 }}>Actions</div>
              {canSend && <button className="btn primary" style={{ width: "100%" }} disabled={busy} onClick={() => act(() => api.send(params.id))}>Approve &amp; send for signature</button>}
              {outForSig && (<>
                <div className="notice info" style={{ marginBottom: 10 }}>
                  Sent for signature{r.esign_provider ? ` via ${r.esign_provider}` : ""}. Awaiting the counterparty.
                </div>
                {r.esign_envelope_id && <div className="mono muted" style={{ fontSize: 11, marginBottom: 10 }}>envelope {r.esign_envelope_id}</div>}
                {r.esign_provider !== "docusign" && (
                  <button className="btn" style={{ width: "100%" }} disabled={busy} onClick={() => act(() => api.simulateSignature(params.id))}>Simulate counterparty signature (dev)</button>
                )}
              </>)}
              {filed && <div className="notice info" style={{ background: "var(--good-soft)", color: "var(--good)" }}>✓ Executed and filed{r.esign_provider ? ` (${r.esign_provider})` : ""}. Renewal in {r.term_months} months tracked.</div>}
              {!canSend && !outForSig && !filed && <div className="muted" style={{ fontSize: 12.5 }}>Clear the approval ladder to unlock sending.</div>}
              {err && <div className="notice warn" style={{ marginTop: 10 }}>{err}</div>}
            </div>
            <div className="card" style={{ padding: 16 }}>
              <div className="kicker" style={{ marginBottom: 10 }}>Audit timeline</div>
              <Timeline events={r.timeline} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
