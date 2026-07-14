"use client";
import { useEffect, useState } from "react";
import { api, STAGES, type RequesterStatus } from "../../../lib/api";
import { Timeline } from "../../components/Timeline";

const ETA: Record<number, string> = {
  1: "Usually drafted in seconds.",
  2: "Usually cleared within a day.",
  3: "Usually signed within 2 business days.",
};

export default function RequesterStatusPage({ params }: { params: { id: string } }) {
  const [s, setS] = useState<RequesterStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.requesterStatus(params.id).then(setS).catch((e) => setErr(String(e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (err) return <div style={{ maxWidth: 720, margin: "0 auto" }}><div className="notice warn">{err}</div></div>;
  if (!s) return <div className="muted">Loading…</div>;
  const stages = s.stages ?? STAGES;           // ADVICE requests carry their own tracker
  const advice = s.stages !== null && s.stages !== undefined;
  const done = s.stage_index >= stages.length - 1;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <div className="page-head" style={{ marginBottom: 16 }}>
        <p className="kicker">Your request · <span className="mono">{s.ref}</span></p>
        <h1>{advice ? s.counterparty_name : `Your NDA with ${s.counterparty_name}`}</h1>
        {advice && <p className="sub" style={{ marginTop: 4 }}>{s.purpose}</p>}
      </div>

      {/* status headline */}
      <div className={`banner ${done ? "done" : ""}`} style={{ marginBottom: 8 }}>
        <span className="pulse" />
        <div>
          <div style={{ fontWeight: 650, fontSize: 15 }}>{s.headline}</div>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 2 }}>{s.detail}</div>
          {ETA[s.stage_index] && !done && (
            <span className="pill accent" style={{ marginTop: 10 }}>◷ {ETA[s.stage_index]}</span>
          )}
        </div>
      </div>

      {/* answer card — the ADVICE engine's payoff */}
      {advice && s.answer && (
        <div className="card card-pad" style={{ marginTop: 18, borderColor: "var(--good-line)" }}>
          <div className="kicker" style={{ marginBottom: 8 }}>Legal&rsquo;s answer</div>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.65, whiteSpace: "pre-wrap" }}>{s.answer}</p>
        </div>
      )}

      {/* package tracker */}
      <div className="kicker" style={{ margin: "26px 4px 0" }}>Progress</div>
      <div className="card card-pad">
        <div className="pkg">
          {stages.map((label, i) => {
            const cls = i < s.stage_index ? "done" : i === s.stage_index ? "here" : "todo";
            return (
              <div key={label} className={`pkg-step ${cls}`}>
                <span className="rail" />
                <span className="pnode">{i < s.stage_index ? "✓" : i === s.stage_index ? "●" : ""}</span>
                <div className="plabel">{label}</div>
                {i === s.stage_index && !done && <div className="ptime">In progress</div>}
              </div>
            );
          })}
        </div>
      </div>

      {/* history */}
      <div className="kicker" style={{ margin: "26px 4px 0" }}>What&rsquo;s happened so far</div>
      <div className="card card-pad">
        <Timeline events={s.timeline} />
      </div>

      {/* document */}
      {s.document_ready && (
        <div className="notice good" style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 18 }}>
          <span style={{ fontSize: 16 }}>✓</span>
          <div>
            <div style={{ fontWeight: 620 }}>Your executed NDA is on file.</div>
            <div style={{ fontSize: 12.5, opacity: 0.9 }}>
              The {s.nda_type === "MUTUAL" ? "mutual" : "one-way"} NDA with {s.counterparty_name} is signed
              {s.expires_at
                ? <> — renewal tracked, expires <b>{new Date(s.expires_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</b>.</>
                : <> and its renewal is tracked.</>}
            </div>
          </div>
        </div>
      )}

      <p className="faint" style={{ fontSize: 12.5, marginTop: 18, textAlign: "center" }}>
        This page updates itself — no need to refresh. We&rsquo;ll drop the signed copy here.
      </p>
    </div>
  );
}
