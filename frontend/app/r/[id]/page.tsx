"use client";
import { useEffect, useState } from "react";
import { api, STAGES, type RequesterStatus } from "../../../lib/api";
import { Timeline } from "../../components/Timeline";

export default function RequesterStatusPage({ params }: { params: { id: string } }) {
  const [s, setS] = useState<RequesterStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () =>
    api.requesterStatus(params.id).then(setS).catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
    const t = setInterval(load, 3000); // reflect legal's progress live
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (err) return <div className="container narrow"><div className="notice warn">{err}</div></div>;
  if (!s) return <div className="container narrow muted">Loading…</div>;

  const done = s.stage_index >= 4;

  return (
    <div className="container narrow">
      <p className="kicker">Your request · {s.ref}</p>
      <h1 className="h-serif" style={{ fontSize: 30, margin: "8px 0 4px" }}>
        Your NDA with <span style={{ color: "var(--accent)" }}>{s.counterparty_name}</span>
      </h1>
      <p className="muted" style={{ marginBottom: 26 }}>
        {s.nda_type === "MUTUAL" ? "Mutual NDA" : "One-way NDA"} · {s.purpose.replace(/_/g, " ")}
      </p>

      <div className="tracker">
        {STAGES.map((label, i) => {
          const cls = i < s.stage_index ? "done" : i === s.stage_index ? "here" : "todo";
          return (
            <div key={label} className={`tstep ${cls}`}>
              <span className="rail" />
              <span className="node" />
              <div className="lbl">{label}</div>
            </div>
          );
        })}
      </div>

      <div className={`banner ${done ? "done" : ""}`} style={{ marginBottom: 24 }}>
        <span className="pulse" />
        <div>
          <div style={{ fontWeight: 650, fontSize: 14.5 }}>{s.headline}</div>
          <div className="muted" style={{ fontSize: 13.5 }}>{s.detail}</div>
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <div className="kicker" style={{ marginBottom: 10 }}>Activity</div>
        <Timeline events={s.timeline} />
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 18 }}>
        This page updates itself — no need to refresh. You&rsquo;ll get the signed copy here.
      </p>
    </div>
  );
}
