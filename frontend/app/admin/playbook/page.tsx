"use client";
import { useEffect, useState } from "react";
import { api, type PlaybookRule, type PlaybookSummary } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";

const RUNGS = ["none", "requesting_manager", "vp_legal", "gc"];
const EMPTY: PlaybookRule = {
  id: "", rule_key: "", clause_type: "", heading: "", ordinal: 0,
  preferred_position: "", preferred_body: "", rationale: "", mandatory: true,
  deviation_rung: "none", nda_type: null, fallbacks: [], walk_away_text: "",
};

const ta: React.CSSProperties = {
  fontSize: 13, padding: "8px 10px", borderRadius: 8, width: "100%", resize: "vertical",
};

export default function PlaybookAdmin() {
  const { has } = useAuth();
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [selId, setSelId] = useState<string>("");
  const [meta, setMeta] = useState<{ name: string; version: number; active: boolean } | null>(null);
  const [rules, setRules] = useState<PlaybookRule[]>([]);
  const [draft, setDraft] = useState<PlaybookRule | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const selected = books.find((b) => b.id === selId) || null;

  async function loadBooks(preferId?: string) {
    const list = await api.listPlaybooksAdmin();
    setBooks(list);
    const pick = preferId || selId || list.find((b) => b.active)?.id || list[0]?.id || "";
    setSelId(pick);
    return pick;
  }

  async function loadRules(id: string) {
    if (!id) return;
    const d = await api.getPlaybook(id);
    setMeta(d.playbook);
    setRules(d.rules);
  }

  useEffect(() => {
    if (!has("playbook:manage")) return;
    loadBooks().then((id) => loadRules(id)).catch((e) => setErr(String(e)));
    /* eslint-disable-next-line */
  }, []);

  // reload rules whenever the selected playbook changes
  useEffect(() => {
    if (selId) { setDraft(null); loadRules(selId).catch((e) => setErr(String(e))); }
    /* eslint-disable-next-line */
  }, [selId]);

  const set = (k: keyof PlaybookRule, v: unknown) => setDraft((d) => (d ? { ...d, [k]: v } as PlaybookRule : d));

  async function refresh() { await loadBooks(selId); await loadRules(selId); }

  async function save() {
    if (!draft) return;
    setBusy(true); setErr(null); setMsg(null);
    const body = {
      rule_key: draft.rule_key, clause_type: draft.clause_type, heading: draft.heading,
      ordinal: Number(draft.ordinal), preferred_position: draft.preferred_position,
      preferred_body: draft.preferred_body, rationale: draft.rationale, mandatory: draft.mandatory,
      deviation_rung: draft.deviation_rung, nda_type: draft.nda_type,
      fallbacks: (draft.fallbacks || []).filter((f) => f.body.trim()),
      walk_away_text: draft.walk_away_text || "",
    };
    try {
      if (draft.id) await api.updateRule(draft.id, body, selId);
      else await api.createRule(body, selId);
      setDraft(null); setMsg("Saved — playbook version bumped."); await refresh();
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  async function del(r: PlaybookRule) {
    if (!window.confirm(`Delete rule ${r.rule_key} (${r.heading})?`)) return;
    setBusy(true); setErr(null);
    try { await api.deleteRule(r.id, selId); setMsg(`Deleted ${r.rule_key}.`); await refresh(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  async function newPlaybook() {
    const name = window.prompt("Name the new playbook (e.g. “M&A NDA”, “EU/GDPR NDA”):")?.trim();
    if (!name) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const pb = await api.createPlaybook(name);
      await loadBooks(pb.id);
      setMsg(`Created “${pb.name}”. It’s inactive — add rules, then “Set as default” to make the engine use it.`);
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  async function activate() {
    if (!selected || selected.active) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      await api.activatePlaybook(selId);
      await refresh();
      setMsg(`“${selected.name}” is now the default — new requests use it unless another is chosen.`);
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  if (!has("playbook:manage")) return <div className="muted">You don&rsquo;t have access to manage the playbook.</div>;

  return (
    <div>
      <div className="page-head">
        <p className="kicker">Administration · playbook library</p>
        <h1>Playbook rules</h1>
        <p className="sub">
          These are the positions the engine reasons against — preferred clause language, which
          deviations need which sign-off, and which clauses are mandatory. Your org can keep several
          playbooks; one is the <b>default</b>, and any request can be reviewed against a specific one.
          Every change bumps the playbook version and is chain-sealed in the audit log.
        </p>
      </div>

      {/* playbook switcher */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "flex-end", gap: 14, marginBottom: 18, flexWrap: "wrap" }}>
        <div className="field" style={{ margin: 0, minWidth: 300, flex: 1 }}>
          <label>Playbook</label>
          <select value={selId} onChange={(e) => setSelId(e.target.value)}>
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} · v{b.version} · {b.rule_count} rules{b.active ? " · default" : ""}
              </option>
            ))}
          </select>
        </div>
        {selected?.active
          ? <span className="pill good" style={{ marginBottom: 9 }}><span className="dot" />Default</span>
          : <button className="btn" style={{ marginBottom: 1 }} disabled={busy || !selected} onClick={activate}>Set as default</button>}
        <button className="btn primary" style={{ marginBottom: 1 }} disabled={busy} onClick={newPlaybook}>+ New playbook</button>
      </div>

      {err && <div className="notice warn" style={{ marginBottom: 12 }}>{err}</div>}
      {msg && <div className="notice good" style={{ marginBottom: 12 }}>{msg}</div>}

      {!draft && (
        <button className="btn primary" style={{ marginBottom: 16 }} onClick={() => setDraft({ ...EMPTY })}>+ New rule</button>
      )}

      {draft && (
        <div className="card card-pad" style={{ marginBottom: 18 }}>
          <div className="kicker" style={{ marginBottom: 12 }}>
            {draft.id ? `Edit ${draft.rule_key}` : "New rule"}{meta ? ` · ${meta.name}` : ""}
          </div>
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
                <input type="checkbox" checked={draft.mandatory} onChange={(e) => set("mandatory", e.target.checked)} style={{ width: "auto" }} />
                Flag as MISSING if absent from counterparty paper
              </label>
            </div>
          </div>
          <div className="field"><label>Preferred position (short)</label><input value={draft.preferred_position} onChange={(e) => set("preferred_position", e.target.value)} style={ta} /></div>
          <div className="field"><label>Preferred clause language</label><textarea rows={4} value={draft.preferred_body} onChange={(e) => set("preferred_body", e.target.value)} style={ta} /></div>
          <div className="field"><label>Rationale (shown to approvers)</label><textarea rows={2} value={draft.rationale} onChange={(e) => set("rationale", e.target.value)} style={ta} /></div>

          {/* the position ladder: preferred (above) → fallbacks (here) → walk-away */}
          <div className="kicker" style={{ margin: "10px 0 6px" }}>Fallback positions (in order of preference)</div>
          {(draft.fallbacks || []).map((fb, i) => (
            <div key={i} className="card" style={{ padding: "10px 12px", marginBottom: 8, background: "var(--surface-2)" }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
                <input placeholder={`Fallback ${i + 1} label (e.g. "24-month cap")`} value={fb.label}
                  onChange={(e) => set("fallbacks", draft.fallbacks.map((f, j) => j === i ? { ...f, label: e.target.value } : f))}
                  style={{ flex: 1 }} />
                <select value={fb.rung}
                  onChange={(e) => set("fallbacks", draft.fallbacks.map((f, j) => j === i ? { ...f, rung: e.target.value } : f))}
                  style={{ width: 190 }}>
                  {RUNGS.map((g) => <option key={g} value={g}>approval: {g.replace(/_/g, " ")}</option>)}
                </select>
                <button className="icon-x" title="Remove fallback"
                  onClick={() => set("fallbacks", draft.fallbacks.filter((_, j) => j !== i))}>✕</button>
              </div>
              <textarea rows={2} placeholder="Acceptable clause language at this fallback…" value={fb.body}
                onChange={(e) => set("fallbacks", draft.fallbacks.map((f, j) => j === i ? { ...f, body: e.target.value } : f))}
                style={ta} />
            </div>
          ))}
          {(draft.fallbacks || []).length < 5 && (
            <button className="btn sm ghost" style={{ marginBottom: 10 }}
              onClick={() => set("fallbacks", [...(draft.fallbacks || []), { label: "", body: "", rung: "vp_legal" }])}>
              + Add fallback position
            </button>
          )}
          <div className="field">
            <label>Walk-away line <span className="faint" style={{ fontWeight: 400 }}>— the position we never accept; crossing it always escalates to GC</span></label>
            <textarea rows={2} value={draft.walk_away_text} onChange={(e) => set("walk_away_text", e.target.value)}
              placeholder='e.g. "Any cap that applies to breaches of confidentiality."' style={ta} />
          </div>

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
                {(r.fallbacks?.length ?? 0) > 0 && ` · ${r.fallbacks.length} fallback${r.fallbacks.length > 1 ? "s" : ""}`}
                {r.walk_away_text && " · walk-away set"}
              </div>
            </div>
            <button className="btn ghost sm" onClick={() => { setDraft(r); setMsg(null); }}>Edit</button>
            <button className="btn ghost sm" style={{ color: "var(--crit)" }} onClick={() => del(r)}>Delete</button>
          </div>
        ))}
        {rules.length === 0 && (
          <div className="card card-pad muted" style={{ textAlign: "center" }}>
            No rules in this playbook yet. Click <b>+ New rule</b> to add one.
          </div>
        )}
      </div>
    </div>
  );
}
