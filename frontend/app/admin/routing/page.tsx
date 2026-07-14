"use client";
import { useEffect, useMemo, useState } from "react";
import {
  api, type AssignableUser, type RequestTypeInfo, type RoutingRuleOut, type RulePreview,
} from "../../../lib/api";
import { ConfirmDialog } from "../../components/ConfirmDialog";

const EMPTY = {
  name: "", ordinal: 0, active: true, stop_on_match: false,
  match_type_key: "", match_direction: "", match_keyword: "", match_jurisdiction: "",
  set_assignee_user_id: "", set_priority: "", set_sla_hours: "" as string | number, escalate: false,
};
type Draft = typeof EMPTY;

function draftToBody(d: Draft) {
  return {
    name: d.name, ordinal: Number(d.ordinal) || 0, active: d.active, stop_on_match: d.stop_on_match,
    match_type_key: d.match_type_key || null,
    match_direction: d.match_direction || null,
    match_keyword: d.match_keyword || null,
    match_jurisdiction: d.match_jurisdiction || null,
    set_assignee_user_id: d.set_assignee_user_id || null,
    set_priority: d.set_priority || null,
    set_sla_hours: d.set_sla_hours ? Number(d.set_sla_hours) : null,
    escalate: d.escalate,
  };
}

function ruleToDraft(r: RoutingRuleOut): Draft {
  return {
    name: r.name, ordinal: r.ordinal, active: r.active, stop_on_match: r.stop_on_match,
    match_type_key: r.match_type_key || "", match_direction: r.match_direction || "",
    match_keyword: r.match_keyword || "", match_jurisdiction: r.match_jurisdiction || "",
    set_assignee_user_id: r.set_assignee_user_id || "", set_priority: r.set_priority || "",
    set_sla_hours: r.set_sla_hours ?? "", escalate: r.escalate,
  };
}

function conditionsOf(r: RoutingRuleOut): string {
  const parts: string[] = [];
  if (r.match_type_key) parts.push(`type = ${r.match_type_key}`);
  if (r.match_direction) parts.push(`direction = ${r.match_direction.toLowerCase()}`);
  if (r.match_keyword) parts.push(`keyword “${r.match_keyword}”`);
  if (r.match_jurisdiction) parts.push(`jurisdiction = ${r.match_jurisdiction}`);
  return parts.join("  AND  ") || "—";
}
function actionsOf(r: RoutingRuleOut): string {
  const parts: string[] = [];
  if (r.set_assignee_name) parts.push(`assign → ${r.set_assignee_name}`);
  if (r.set_priority) parts.push(`priority ${r.set_priority.toLowerCase()}`);
  if (r.set_sla_hours) parts.push(`SLA ${r.set_sla_hours}h`);
  if (r.escalate) parts.push("escalate");
  return parts.join(" · ") || "—";
}

export default function RoutingAdmin() {
  const [rules, setRules] = useState<RoutingRuleOut[]>([]);
  const [types, setTypes] = useState<RequestTypeInfo[]>([]);
  const [staff, setStaff] = useState<AssignableUser[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);  // rule id or "new"
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [preview, setPreview] = useState<RulePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [killRule, setKillRule] = useState<RoutingRuleOut | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.listRoutingRules().then(setRules).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
    api.requestTypes().then(setTypes).catch(() => {});
    api.assignableUsers().then(setStaff).catch(() => {});
  }, []);

  const set = (k: keyof Draft, v: unknown) => setDraft((d) => ({ ...d, [k]: v }));
  const hasCondition = useMemo(
    () => !!(draft.match_type_key || draft.match_direction || draft.match_keyword || draft.match_jurisdiction),
    [draft]);
  const hasAction = useMemo(
    () => !!(draft.set_assignee_user_id || draft.set_priority || draft.set_sla_hours || draft.escalate),
    [draft]);

  async function runPreview() {
    setPreviewing(true); setPreview(null);
    try {
      setPreview(await api.previewRoutingRule({
        match_type_key: draft.match_type_key || null,
        match_direction: draft.match_direction || null,
        match_keyword: draft.match_keyword || null,
        match_jurisdiction: draft.match_jurisdiction || null,
      }));
    } catch (e) { setError(String(e)); } finally { setPreviewing(false); }
  }

  async function save() {
    setBusy(true); setError(null);
    try {
      if (editing === "new") await api.createRoutingRule(draftToBody(draft));
      else if (editing) await api.updateRoutingRule(editing, draftToBody(draft));
      setEditing(null); setPreview(null);
      await load();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  async function doDelete() {
    if (!killRule) return;
    setBusy(true);
    try {
      await api.deleteRoutingRule(killRule.id);
      setKillRule(null);
      await load();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div className="page-head-row">
          <div>
            <p className="kicker">Administration · Routing</p>
            <h1>Routing rules</h1>
          </div>
          <button className="btn primary" onClick={() => { setEditing("new"); setDraft(EMPTY); setPreview(null); }}>
            + New rule
          </button>
        </div>
        <p className="sub">
          WHEN conditions → THEN actions, evaluated in order after every request is classified —
          whatever the channel. Each fired rule is stamped on the request and chain-audited, so
          you can always answer “why is this here?”.
        </p>
      </div>

      {error && <div className="notice warn" style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14 }}>
        <span style={{ flex: 1 }}>{error}</span>
        <button className="btn sm ghost" onClick={() => setError(null)}>Dismiss</button>
      </div>}

      {editing && (
        <div className="card card-pad" style={{ marginBottom: 18 }}>
          <div style={{ fontWeight: 650, marginBottom: 12 }}>{editing === "new" ? "New rule" : "Edit rule"}</div>
          <div className="row2">
            <div className="field"><label>Name</label>
              <input value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Questions go to Marcus" /></div>
            <div className="field"><label>Order (lower runs first)</label>
              <input type="number" value={draft.ordinal} onChange={(e) => set("ordinal", e.target.value)} style={{ maxWidth: 120 }} /></div>
          </div>

          <div className="kicker" style={{ margin: "8px 0" }}>WHEN (all must match)</div>
          <div className="row2">
            <div className="field"><label>Request type</label>
              <select value={draft.match_type_key} onChange={(e) => set("match_type_key", e.target.value)}>
                <option value="">any</option>
                {types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select></div>
            <div className="field"><label>Direction</label>
              <select value={draft.match_direction} onChange={(e) => set("match_direction", e.target.value)}>
                <option value="">any</option>
                <option value="OUTBOUND">Outbound (our paper)</option>
                <option value="INBOUND">Inbound (their paper)</option>
              </select></div>
          </div>
          <div className="row2">
            <div className="field"><label>Keyword (counterparty / purpose / details)</label>
              <input value={draft.match_keyword} onChange={(e) => set("match_keyword", e.target.value)} placeholder="e.g. acme" /></div>
            <div className="field"><label>Jurisdiction</label>
              <input value={draft.match_jurisdiction} onChange={(e) => set("match_jurisdiction", e.target.value)} placeholder="e.g. EU-DE" /></div>
          </div>

          <div className="kicker" style={{ margin: "8px 0" }}>THEN</div>
          <div className="row2">
            <div className="field"><label>Assign to</label>
              <select value={draft.set_assignee_user_id} onChange={(e) => set("set_assignee_user_id", e.target.value)}>
                <option value="">— no change —</option>
                {staff.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.role.replace(/_/g, " ")})</option>)}
              </select></div>
            <div className="field"><label>Set priority</label>
              <select value={draft.set_priority} onChange={(e) => set("set_priority", e.target.value)}>
                <option value="">— no change —</option>
                <option value="LOW">Low</option><option value="NORMAL">Normal</option>
                <option value="HIGH">High</option><option value="URGENT">Urgent</option>
              </select></div>
          </div>
          <div className="row2">
            <div className="field"><label>Set SLA (hours)</label>
              <input type="number" min={1} value={draft.set_sla_hours} onChange={(e) => set("set_sla_hours", e.target.value)} style={{ maxWidth: 140 }} /></div>
            <div className="field"><label>Flags</label>
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center", paddingTop: 6 }}>
                <label style={{ fontWeight: 400, display: "inline-flex", gap: 6, alignItems: "center", whiteSpace: "nowrap", margin: 0 }}>
                  <input type="checkbox" checked={draft.escalate} onChange={(e) => set("escalate", e.target.checked)} /> escalate lane
                </label>
                <label style={{ fontWeight: 400, display: "inline-flex", gap: 6, alignItems: "center", whiteSpace: "nowrap", margin: 0 }}>
                  <input type="checkbox" checked={draft.stop_on_match} onChange={(e) => set("stop_on_match", e.target.checked)} /> stop after this rule
                </label>
                <label style={{ fontWeight: 400, display: "inline-flex", gap: 6, alignItems: "center", whiteSpace: "nowrap", margin: 0 }}>
                  <input type="checkbox" checked={draft.active} onChange={(e) => set("active", e.target.checked)} /> active
                </label>
              </div>
            </div>
          </div>

          {/* the dry-run: watch it match before you trust it */}
          <div className="notice info" style={{ display: "block", marginTop: 4, marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontWeight: 650, fontSize: 12.5 }}>Dry run</span>
              <button type="button" className="btn sm" disabled={!hasCondition || previewing} onClick={runPreview}>
                {previewing ? "Testing…" : "Test against recent requests"}
              </button>
              {preview && (
                <span style={{ fontSize: 12.5 }}>
                  would have matched <b>{preview.matched}</b> of the last <b>{preview.evaluated}</b>
                </span>
              )}
            </div>
            {preview && preview.matches.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.7 }}>
                {preview.matches.slice(0, 8).map((m) => (
                  <span key={m.ref} className="pill state" style={{ marginRight: 6 }}>{m.ref} · {m.counterparty}</span>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn primary" disabled={busy || !draft.name.trim() || !hasCondition || !hasAction} onClick={save}>
              {busy ? "Saving…" : editing === "new" ? "Create rule" : "Save changes"}
            </button>
            <button className="btn" onClick={() => { setEditing(null); setPreview(null); }}>Cancel</button>
            {(!hasCondition || !hasAction) && (
              <span className="faint" style={{ fontSize: 12, alignSelf: "center" }}>
                a rule needs at least one condition and one action
              </span>
            )}
          </div>
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <table className="tbl">
          <thead><tr><th style={{ width: 40 }}>#</th><th>Rule</th><th>WHEN</th><th>THEN</th><th style={{ width: 130 }}></th></tr></thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} style={{ opacity: r.active ? 1 : 0.45 }}>
                <td className="tnum muted">{r.ordinal}</td>
                <td style={{ fontWeight: 600 }}>{r.name}{!r.active && <span className="sub">inactive</span>}{r.stop_on_match && <span className="sub">stops chain</span>}</td>
                <td className="muted" style={{ fontSize: 12.5 }}>{conditionsOf(r)}</td>
                <td style={{ fontSize: 12.5 }}>{actionsOf(r)}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn sm ghost" onClick={() => { setEditing(r.id); setDraft(ruleToDraft(r)); setPreview(null); }}>Edit</button>
                  <button className="btn sm ghost" onClick={() => setKillRule(r)}>Delete</button>
                </td>
              </tr>
            ))}
            {rules.length === 0 && (
              <tr><td colSpan={5} className="muted" style={{ padding: 30, textAlign: "center" }}>
                No routing rules yet. Requests follow the built-in triage until you add one.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <ConfirmDialog
        open={killRule !== null}
        title="Delete this routing rule?"
        body={<>Requests will stop being routed by <b>{killRule?.name}</b> immediately. The rule&rsquo;s
          past routing decisions stay on the audit chain; deleting it is itself audited.</>}
        phrase={killRule?.name || ""}
        actionLabel="Delete rule"
        busy={busy}
        onConfirm={doDelete}
        onClose={() => setKillRule(null)}
      />
    </div>
  );
}
