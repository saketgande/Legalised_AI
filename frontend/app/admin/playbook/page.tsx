"use client";
import { useEffect, useState } from "react";
import { api, type PlaybookRule } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";

const RUNGS = ["none", "requesting_manager", "vp_legal", "gc"];
const EMPTY: PlaybookRule = {
  id: "", rule_key: "", clause_type: "", heading: "", ordinal: 0,
  preferred_position: "", preferred_body: "", rationale: "", mandatory: true,
  deviation_rung: "none", nda_type: null,
};

const ta: React.CSSProperties = {
  fontFamily: "inherit", fontSize: 13, padding: "8px 10px", borderRadius: 8, width: "100%",
  border: "1px solid var(--hairline)", background: "var(--surface)", color: "var(--ink)", resize: "vertical",
};

export default function PlaybookAdmin() {
  const { has } = useAuth();
  const [meta, setMeta] = useState<{ name: string; version: number } | null>(null);
  const [rules, setRules] = useState<PlaybookRule[]>([]);
  const [draft, setDraft] = useState<PlaybookRule | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => api.getPlaybook().then((d) => { setMeta(d.playbook); setRules(d.rules); }).catch((e) => setErr(String(e)));
  useEffect(() => { if (has("playbook:manage")) load(); /* eslint-disable-next-line */ }, []);

  const set = (k: keyof PlaybookRule, v: unknown) => setDraft((d) => (d ? { ...d, [k]: v } as PlaybookRule : d));

  async function save() {
    if (!draft) return;
    setBusy(true); setErr(null); setMsg(null);
    const body = {
      rule_key: draft.rule_key, clause_type: draft.clause_type, heading: draft.heading,
      ordinal: Number(draft.ordinal), preferred_position: draft.preferred_position,
      preferred_body: draft.preferred_body, rationale: draft.rationale, mandatory: draft.mandatory,
      deviation_rung: draft.deviation_rung, nda_type: draft.nda_type,
    };
    try {
      if (draft.id) await api.updateRule(draft.id, body);
      else await api.createRule(body);
      setDraft(null); setMsg("Saved — playbook version bumped."); await load();
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  async function del(r: PlaybookRule) {
    if (!window.confirm(`Delete rule ${r.rule_key} (${r.heading})?`)) return;
    setBusy(true); setErr(null);
    try { await api.deleteRule(r.id); setMsg(`Deleted ${r.rule_key}.`); await load(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  if (!has("playbook:manage")) return <div className="container muted">You don&rsquo;t have access to manage the playbook.</div>;

  return (
    <div className="container">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <p className="kicker">Admin · playbook</p>
        {meta && <span className="muted" style={{ fontSize: 13 }}>{meta.name} · v{meta.version} · {rules.length} rules</span>}
      </div>
      <h1 className="h-serif" style={{ fontSize: 26, margin: "4px 0 8px" }}>Playbook rules</h1>
      <p className="muted" style={{ fontSize: 13.5, marginBottom: 14, maxWidth: "72ch" }}>
        These are the positions the engine reasons against — the preferred clause language, which
        deviations need which sign-off, and which clauses are mandatory. Every change bumps the
        playbook version and is chain-sealed in the audit log.
      </p>

      {err && <div className="notice warn" style={{ marginBottom: 12 }}>{err}</div>}
      {msg && <div className="notice info" style={{ marginBottom: 12, background: "var(--good-soft)", color: "var(--good)" }}>{msg}</div>}

      {!draft && (
        <button className="btn primary" style={{ marginBottom: 16 }} onClick={() => setDraft({ ...EMPTY })}>+ New rule</button>
      )}

      {draft && (
        <div className="card" style={{ padding: 18, marginBottom: 18 }}>
          <div className="kicker" style={{ marginBottom: 12 }}>{draft.id ? `Edit ${draft.rule_key}` : "New rule"}</div>
          <div className="row2">
            <div className="field"><label>Rule key</label><input value={draft.rule_key} onChange={(e) => set("rule_key", e.target.value)} placeholder="e.g. LoL-02" style={ta} /></div>
            <div className="field"><label>Clause type</label><input value={draft.clause_type} onChange={(e) => set("clause_type", e.target.value)} placeholder="limitation_of_liability" style={ta} /></div>
          </div>
          <div className="field"><label>Heading</label><input value={draft.heading} onChange={(e) => set("heading", e.target.value)} style={ta} /></div>
          <div className="row2">
            <div className="field"><label>Deviation sign-off (rung)</label>
              <select value={draft.deviation_rung} onChange={(e) => set("deviation_rung", e.target.value)} style={ta}>
                {RUNGS.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
              </select>
            </div>
            <div className="field"><label>Applies to</label>
              <select value={draft.nda_type ?? ""} onChange={(e) => set("nda_type", e.target.value || null)} style={ta}>
                <option value="">Any NDA</option><option value="MUTUAL">Mutual only</option><option value="ONE_WAY">One-way only</option>
              </select>
            </div>
          </div>
          <div className="row2">
            <div className="field"><label>Order</label><input type="number" value={draft.ordinal} onChange={(e) => set("ordinal", e.target.value)} style={ta} /></div>
            <div className="field"><label>Mandatory?</label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, paddingTop: 8 }}>
                <input type="checkbox" checked={draft.mandatory} onChange={(e) => set("mandatory", e.target.checked)} />
                Flag as MISSING if absent from counterparty paper
              </label>
            </div>
          </div>
          <div className="field"><label>Preferred position (short)</label><input value={draft.preferred_position} onChange={(e) => set("preferred_position", e.target.value)} style={ta} /></div>
          <div className="field"><label>Preferred clause language</label><textarea rows={4} value={draft.preferred_body} onChange={(e) => set("preferred_body", e.target.value)} style={ta} /></div>
          <div className="field"><label>Rationale (shown to approvers)</label><textarea rows={2} value={draft.rationale} onChange={(e) => set("rationale", e.target.value)} style={ta} /></div>
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <button className="btn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save rule"}</button>
            <button className="btn ghost" disabled={busy} onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rules.map((r) => (
          <div key={r.id} className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 12 }}>
            <span className="mono" style={{ fontSize: 12, color: "var(--accent)", width: 64 }}>{r.rule_key}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>{r.heading}
                {r.mandatory && <span className="pill state" style={{ marginLeft: 8, fontSize: 10 }}>mandatory</span>}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                {r.clause_type}{r.deviation_rung !== "none" ? ` · deviation → ${r.deviation_rung.replace(/_/g, " ")}` : ""}{r.nda_type ? ` · ${r.nda_type}` : ""}
              </div>
            </div>
            <button className="btn ghost" style={{ padding: "5px 11px", fontSize: 12.5 }} onClick={() => { setDraft(r); setMsg(null); }}>Edit</button>
            <button className="btn ghost" style={{ padding: "5px 11px", fontSize: 12.5, color: "var(--crit)" }} onClick={() => del(r)}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}
