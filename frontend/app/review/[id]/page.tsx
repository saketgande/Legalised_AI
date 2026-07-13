"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type RequestDetail } from "../../../lib/api";
import { Timeline } from "../../components/Timeline";

/** Minimal markdown render — headings, rules, emphasis, paragraphs. */
function Doc({ md }: { md: string }) {
  const blocks = md.split("\n");
  return (
    <div className="doc-body">
      {blocks.map((line, i) => {
        if (line.startsWith("## ")) return <h2 key={i} className="h-serif">{line.slice(3)}</h2>;
        if (line.startsWith("# ")) return <h1 key={i} className="h-serif">{line.slice(2)}</h1>;
        if (line.trim() === "---") return <hr key={i} />;
        if (line.trim() === "") return null;
        if (line.startsWith("_") && line.endsWith("_")) return <p key={i}><em>{line.slice(1, -1)}</em></p>;
        // bold spans **x**
        const parts = line.split(/(\*\*[^*]+\*\*)/g);
        return (
          <p key={i}>
            {parts.map((p, j) =>
              p.startsWith("**") && p.endsWith("**") ? <strong key={j}>{p.slice(2, -2)}</strong> : p,
            )}
          </p>
        );
      })}
    </div>
  );
}

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return null;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane}</span>;
}

export default function ReviewPage({ params }: { params: { id: string } }) {
  const [r, setR] = useState<RequestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(
    () => api.getRequest(params.id).then(setR).catch((e) => setErr(String(e))),
    [params.id],
  );
  useEffect(() => { load(); }, [load]);

  async function act(fn: () => Promise<RequestDetail>) {
    setBusy(true);
    setErr(null);
    try { setR(await fn()); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  if (err && !r) return <div className="container"><div className="notice warn">{err}</div></div>;
  if (!r) return <div className="container muted">Loading…</div>;

  const canSend = r.state === "APPROVED";
  const outForSig = r.state === "OUT_FOR_SIGNATURE";
  const filed = r.state === "EXECUTED" || r.state === "FILED";

  return (
    <div className="container">
      <Link href="/inbox" className="muted" style={{ fontSize: 13 }}>← Inbox</Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", margin: "10px 0 4px" }}>
        <span className="mono muted" style={{ fontSize: 12.5 }}>{r.ref}</span>
        <h1 className="h-serif" style={{ fontSize: 22, margin: 0 }}>{r.counterparty_name}</h1>
        <span className="muted" style={{ fontSize: 12 }}>
          {r.nda_type === "MUTUAL" ? "Mutual NDA" : "One-way NDA"} · we are {r.direction === "OUTBOUND" ? "disclosing" : "receiving"}
        </span>
        <LanePill lane={r.lane} />
        <span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span>
      </div>

      <div className="cockpit-grid" style={{ marginTop: 20 }}>
        {/* main: the document */}
        <div className="card" style={{ padding: "22px 26px" }}>
          {r.document ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span className="kicker">Draft · v{r.document.version_no} · {r.document.clauses.length} clauses</span>
                <span className="mono muted" style={{ fontSize: 11 }} title="content hash (provenance)">
                  #{r.document.content_hash.slice(0, 12)}
                </span>
              </div>
              <hr className="hr" />
              <Doc md={r.document.body_markdown} />
            </>
          ) : (
            <div className="muted">No document generated.</div>
          )}
        </div>

        {/* rail */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* triage */}
          <div className="card" style={{ padding: 16 }}>
            <div className="kicker" style={{ marginBottom: 10 }}>Why this lane</div>
            <ul className="reasons">
              {r.triage_reasons.map((t, i) => <li key={i}>{t}</li>)}
            </ul>
          </div>

          {/* approval ladder */}
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
                        <div className="who2">
                          {s.assignee_name ?? s.rung} · {s.rung.replace(/_/g, " ")}
                          {done && " ✓"}
                        </div>
                        <div className="why">{s.reason}</div>
                        {!done && (
                          <button
                            className="btn primary"
                            style={{ marginTop: 8, padding: "6px 12px", fontSize: 12.5 }}
                            disabled={busy}
                            onClick={() => act(() => api.approveStep(s.id))}
                          >
                            Approve as {s.assignee_name ?? s.rung}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* actions */}
          <div className="card" style={{ padding: 16 }}>
            <div className="kicker" style={{ marginBottom: 10 }}>Actions</div>
            {canSend && (
              <button className="btn primary" style={{ width: "100%" }} disabled={busy}
                onClick={() => act(() => api.send(params.id))}>
                Approve &amp; send for signature
              </button>
            )}
            {outForSig && (
              <>
                <div className="notice info" style={{ marginBottom: 10 }}>
                  Sent for signature. Awaiting the counterparty.
                </div>
                <button className="btn" style={{ width: "100%" }} disabled={busy}
                  onClick={() => act(() => api.simulateSignature(params.id))}>
                  Simulate counterparty signature (dev)
                </button>
              </>
            )}
            {filed && (
              <div className="notice info" style={{ background: "var(--good-soft)", color: "var(--good)" }}>
                ✓ Executed and filed. Renewal in {r.term_months} months is being tracked.
              </div>
            )}
            {!canSend && !outForSig && !filed && (
              <div className="muted" style={{ fontSize: 12.5 }}>
                Clear the approval ladder to unlock sending.
              </div>
            )}
            {err && <div className="notice warn" style={{ marginTop: 10 }}>{err}</div>}
          </div>

          {/* timeline */}
          <div className="card" style={{ padding: 16 }}>
            <div className="kicker" style={{ marginBottom: 10 }}>Audit timeline</div>
            <Timeline events={r.timeline} />
          </div>
        </div>
      </div>
    </div>
  );
}
