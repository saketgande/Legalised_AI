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
function ChangeCard({ c, onDecide, busy, canApprove }: { c: ProposedChange; onDecide: (a: "approve" | "reject" | "edit", t?: string) => void; busy: boolean; canApprove: boolean }) {
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
            <span className="cx2"><span className={`kind ${ch.kind}`}>{ch.kind === "DETERMINISTIC" ? "DET" : "SEM"}</span>{ch.detail}</span>
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
        <div className={`cc-decided ${c.decision}`}>
          {c.decision === "REJECTED" ? "✕ Rejected — their language kept" : "✓ Accepted into counter-proposal"}
        </div>
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
      </div>

      {inbound ? (
        /* ===================== INBOUND REDLINE COCKPIT ===================== */
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

          <div className="cockpit-grid" style={{ marginTop: 16 }}>
            <div>
              {r.review!.changes.map((c) => (
                <ChangeCard key={c.id} c={c} busy={busy} canApprove={canClear(c.triggered_rung)}
                  onDecide={(a, t) => act(() => api.decideChange(c.id, a, t))} />
              ))}
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div className="card" style={{ padding: 16 }}>
                <div className="kicker" style={{ marginBottom: 10 }}>Actions</div>
                {canSend && (
                  <button className="btn primary" style={{ width: "100%" }} disabled={busy}
                    onClick={() => act(() => api.send(params.id))}>Send counter-proposal</button>
                )}
                {outForSig && (
                  <>
                    <div className="notice info" style={{ marginBottom: 10 }}>Counter-proposal sent. Awaiting the counterparty.</div>
                    <button className="btn" style={{ width: "100%" }} disabled={busy}
                      onClick={() => act(() => api.simulateSignature(params.id))}>Simulate counterparty signature (dev)</button>
                  </>
                )}
                {filed && <div className="notice info" style={{ background: "var(--good-soft)", color: "var(--good)" }}>✓ Executed and filed.</div>}
                {!canSend && !outForSig && !filed && (
                  <div className="muted" style={{ fontSize: 12.5 }}>Decide every proposed change to unlock the counter-proposal.</div>
                )}
                <button className="btn ghost" style={{ width: "100%", marginTop: 10 }}
                  onClick={() => setShowCounter((s) => !s)}>
                  {showCounter ? "Hide" : "Preview"} counter-proposal
                </button>
                {err && <div className="notice warn" style={{ marginTop: 10 }}>{err}</div>}
              </div>

              <div className="card" style={{ padding: 16 }}>
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
                <div className="notice info" style={{ marginBottom: 10 }}>Sent for signature. Awaiting the counterparty.</div>
                <button className="btn" style={{ width: "100%" }} disabled={busy} onClick={() => act(() => api.simulateSignature(params.id))}>Simulate counterparty signature (dev)</button>
              </>)}
              {filed && <div className="notice info" style={{ background: "var(--good-soft)", color: "var(--good)" }}>✓ Executed and filed. Renewal in {r.term_months} months tracked.</div>}
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
