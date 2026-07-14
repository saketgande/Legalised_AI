"use client";
import { useEffect, useMemo, useState } from "react";
import { api, type ContractRegistry, type ContractRow } from "../../lib/api";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/* Human "time left" from a signed day-count. Negative = lapsed. */
function fmtLeft(days: number | null): string {
  if (days === null) return "no term";
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "expires today";
  if (days < 60) return `${days}d left`;
  const mo = Math.round(days / 30.44);
  if (mo < 24) return `${mo} mo left`;
  return `${(days / 365).toFixed(1)} yr left`;
}

const STATUS_LABEL: Record<string, string> = {
  active: "Active", expiring: "Expiring", expired: "Expired", renewed: "Renewed",
};
const STATUS_PILL: Record<string, string> = {
  active: "good", expiring: "warn", expired: "crit", renewed: "accent",
};

/* Life bar: fraction of the contract's term elapsed, coloured by posture. */
function LifeBar({ row }: { row: ContractRow }) {
  if (!row.executed_at || !row.expires_at) return <span className="faint">—</span>;
  const start = new Date(row.executed_at).getTime();
  const end = new Date(row.expires_at).getTime();
  const pct = end > start ? Math.max(0.02, Math.min(1, (Date.now() - start) / (end - start))) : 1;
  const fill = row.status === "expired" ? "crit" : row.status === "expiring" ? "warn"
    : row.status === "renewed" ? "accent" : "good";
  return (
    <div className="sla-clock">
      <div className="sla-bar"><span className={`fill ${fill}`} style={{ width: `${pct * 100}%` }} /></div>
      <div className="sla-num tnum"><b>{fmtLeft(row.days_left)}</b> <span className="faint">· {fmtDate(row.expires_at)}</span></div>
    </div>
  );
}

type Filter = "all" | "expiring" | "expired" | "active" | "renewed";

export default function ContractRegistryPage() {
  const [d, setD] = useState<ContractRegistry | null>(null);
  const [err, setErr] = useState<string | null>(null);        // fatal load error
  const [renewErr, setRenewErr] = useState<string | null>(null); // non-fatal renew error
  const [filter, setFilter] = useState<Filter>("all");
  const [renewing, setRenewing] = useState<string | null>(null);

  const load = () => api.contracts().then(setD).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  const shown = useMemo(() => {
    const rows = d?.rows ?? [];
    return filter === "all" ? rows : rows.filter((r) => r.status === filter);
  }, [d, filter]);

  async function renew(row: ContractRow) {
    setRenewing(row.id);
    setRenewErr(null);
    try {
      const res = await api.renewContract(row.id);
      window.location.href = `/review/${res.id}`;
    } catch (e) {
      // non-fatal: keep the registry rendered, surface an inline dismissible banner
      setRenewErr(`Couldn't renew ${row.ref}: ${String(e).replace(/^Error:\s*/, "")}`);
      setRenewing(null);
      load();  // refresh in case the row changed under us (e.g. already renewed)
    }
  }

  if (err) return <div style={{ maxWidth: 720 }}><div className="notice warn">{err}</div></div>;
  if (!d) return <div className="muted">Loading…</div>;

  const counts = {
    all: d.totals.total, expiring: d.totals.expiring, expired: d.totals.expired,
    active: d.totals.active, renewed: d.totals.renewed,
  };
  const seg = (key: Filter, label: string) => (
    <button className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
      {label} <span className="tnum" style={{ opacity: 0.6 }}>{counts[key]}</span>
    </button>
  );
  const attention = d.totals.expiring + d.totals.expired;

  return (
    <div>
      <div className="page-head">
        <div className="page-head-row">
          <div>
            <p className="kicker">Operations · Contract registry</p>
            <h1>Executed NDAs on file</h1>
          </div>
          <span className="muted tnum" style={{ fontSize: 13 }}>{d.totals.total} contracts</span>
        </div>
        <p className="sub">
          Every signed NDA, its renewal clock running. {attention > 0
            ? <><b>{attention}</b> need attention — {d.totals.expired > 0 && <span className="crit-txt">{d.totals.expired} expired</span>}
                {d.totals.expired > 0 && d.totals.expiring > 0 && ", "}
                {d.totals.expiring > 0 && <>{d.totals.expiring} expiring within {d.expiring_soon_days} days</>}.</>
            : "nothing expiring soon."}
        </p>
      </div>

      {/* headline tiles */}
      <div className="stat-grid" style={{ marginBottom: 20 }}>
        <div className="stat">
          <div className="lbl">On file</div>
          <div className="val">{d.totals.total}</div>
          <div className="stat-sub">executed &amp; tracked</div>
        </div>
        <div className="stat">
          <div className="lbl">Active</div>
          <div className="val good">{d.totals.active}</div>
          <div className="stat-sub">in force, &gt;{d.expiring_soon_days}d out</div>
        </div>
        <div className={`stat ${d.totals.expiring > 0 ? "stat-warn" : ""}`}>
          <div className="lbl">Expiring soon</div>
          <div className={`val ${d.totals.expiring > 0 ? "warn" : ""}`}>{d.totals.expiring}</div>
          <div className="stat-sub">within {d.expiring_soon_days} days</div>
        </div>
        <div className={`stat ${d.totals.expired > 0 ? "stat-crit" : ""}`}>
          <div className="lbl">Expired</div>
          <div className={`val ${d.totals.expired > 0 ? "crit" : ""}`}>{d.totals.expired}</div>
          <div className="stat-sub">{d.totals.expired > 0 ? "lapsed — renew now" : "none lapsed"}</div>
        </div>
        <div className="stat">
          <div className="lbl">Renewed</div>
          <div className="val">{d.totals.renewed}</div>
          <div className="stat-sub">continued forward</div>
        </div>
      </div>

      {renewErr && (
        <div className="notice warn" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span style={{ flex: 1 }}>{renewErr}</span>
          <button className="btn sm ghost" onClick={() => setRenewErr(null)}>Dismiss</button>
        </div>
      )}

      <div style={{ display: "flex", gap: 12, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        <div className="seg">
          {seg("all", "All")}
          {seg("expiring", "Expiring")}
          {seg("expired", "Expired")}
          {seg("active", "Active")}
          {seg("renewed", "Renewed")}
        </div>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Counterparty</th>
                <th>Type</th>
                <th>Executed</th>
                <th style={{ width: 210 }}>Renewal clock</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const act = r.status === "expired" || r.status === "expiring";
                return (
                  <tr key={r.id} className={r.status === "expired" ? "sev" : ""}>
                    <td className="ref">{r.ref}</td>
                    <td className="cp">{r.counterparty}</td>
                    <td className="muted">{r.nda_type === "MUTUAL" ? "Mutual" : "One-way"}</td>
                    <td className="muted tnum">{fmtDate(r.executed_at)}</td>
                    <td><LifeBar row={r} /></td>
                    <td><span className={`pill ${STATUS_PILL[r.status]}`}>{STATUS_LABEL[r.status]}</span></td>
                    <td style={{ textAlign: "right" }}>
                      {r.status === "renewed" ? (
                        <span className="faint" style={{ fontSize: 12 }}>renewed ✓</span>
                      ) : (
                        <button className={`btn sm ${act ? "primary" : "ghost"}`} disabled={renewing === r.id}
                          onClick={() => renew(r)}>
                          {renewing === r.id ? "Renewing…" : "Renew →"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {shown.length === 0 && (
                <tr><td colSpan={7} className="muted" style={{ padding: 30, textAlign: "center" }}>
                  {d.totals.total === 0 ? "No executed contracts yet. Sign one and it lands here." : "Nothing matches this filter."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
