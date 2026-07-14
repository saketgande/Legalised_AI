"use client";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  type RiskMatrixRow,
  type WorkflowLibrary,
  type WorkflowTemplateOut,
} from "../../../lib/api";

type Rung = {
  key: string; kind: string; name: string; desc?: string;
  mode: string; rung?: string | null; sla_hours?: number | null;
  cond?: { field: string; value?: number; label?: string };
};

const KIND_LABEL: Record<string, string> = {
  D: "DETERMINISTIC", A: "AI", H: "HUMAN", T: "THIRD PARTY",
};
const BAND_DESC: Record<string, string> = {
  LOW: "on-playbook / trivial deltas",
  MEDIUM: "bounded deviations",
  HIGH: "serious deviations / off-policy facts",
  CRITICAL: "walk-away breaches, sanctions posture",
};

function KindBadge({ k }: { k: string }) {
  return <span className={`tbadge ${k}`}>{k} · {KIND_LABEL[k]}</span>;
}

/* ————— the risk-ladder matrix editor (band -> rung chips) ————— */
function MatrixEditor({ row, onSaved }: { row: RiskMatrixRow; onSaved: () => void }) {
  const [m, setM] = useState<Record<string, string[]>>(row.risk_ladders);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // re-sync after save/reset reloads the row — stale local state here would
  // render a matrix that no longer matches what the engine reads
  useEffect(() => { setM(row.risk_ladders); }, [row.risk_ladders]);
  const dirty = JSON.stringify(m) !== JSON.stringify(row.risk_ladders);

  const toggle = (band: string, rung: string) => {
    setM((prev) => {
      const cur = prev[band] ?? [];
      const next = cur.includes(rung) ? cur.filter((x) => x !== rung)
        : [...cur.filter((x) => x !== rung), rung].sort((a, b) => (a === "vp_legal" ? -1 : 1) - (b === "vp_legal" ? -1 : 1));
      return { ...prev, [band]: next };
    });
  };

  async function save() {
    setBusy(true); setErr(null);
    try { await api.saveRiskMatrix(row.type_key, m); onSaved(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }
  async function reset() {
    setBusy(true); setErr(null);
    try { await api.resetRiskMatrix(row.type_key); onSaved(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 650 }}>{row.label}</span>
        <span className="mono faint" style={{ fontSize: 11 }}>{row.type_key}</span>
        {row.is_default && <span className="pill state">category default</span>}
        <span style={{ flex: 1 }} />
        {dirty && <button className="btn primary sm" disabled={busy} onClick={save}>Save matrix</button>}
        {!row.is_default && <button className="btn ghost sm" disabled={busy} onClick={reset}>Reset to default</button>}
      </div>
      <table className="tbl" style={{ fontSize: 12.5 }}>
        <thead><tr><th style={{ width: 110 }}>Risk band</th><th>Approval ladder</th><th className="muted">meaning</th></tr></thead>
        <tbody>
          {row.bands.map((band) => (
            <tr key={band}>
              <td><span className={`pill ${band === "LOW" ? "good" : band === "MEDIUM" ? "warn" : "crit"}`}>{band}</span></td>
              <td>
                {["vp_legal", "gc"].map((rung) => {
                  const on = (m[band] ?? []).includes(rung);
                  return (
                    <button key={rung} type="button"
                      className={`pill ${on ? "accent" : "state"}`}
                      style={{ marginRight: 6, cursor: "pointer", opacity: on ? 1 : 0.5 }}
                      onClick={() => toggle(band, rung)}>
                      {on ? "✓ " : "+ "}{rung.replace(/_/g, " ")}
                    </button>
                  );
                })}
                {(m[band] ?? []).length === 0 && <span className="faint" style={{ fontSize: 11.5 }}>auto-approve (no human)</span>}
              </td>
              <td className="faint" style={{ fontSize: 11.5 }}>{BAND_DESC[band]}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {err && <div className="notice warn" style={{ marginTop: 8 }}>{err}</div>}
      <p className="faint" style={{ fontSize: 11.5, margin: "8px 0 0" }}>
        This matrix is not documentation — it is the exact table the engine reads when it builds
        a ladder from a round&rsquo;s risk score. Edits apply to the next scored round.
      </p>
    </div>
  );
}

/* ————— the template designer ————— */
function TemplateEditor({ tpl, lib, onChanged }: {
  tpl: WorkflowTemplateOut; lib: WorkflowLibrary; onChanged: () => void;
}) {
  const [rungs, setRungs] = useState<Rung[]>(tpl.rungs as unknown as Rung[]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [gateName, setGateName] = useState("");
  const [gateRung, setGateRung] = useState("vp_legal");
  const [gateCond, setGateCond] = useState("");
  const [gateTerm, setGateTerm] = useState(36);
  useEffect(() => { setRungs(tpl.rungs as unknown as Rung[]); setErr(null); setMsg(null); }, [tpl]);

  const dirty = JSON.stringify(rungs) !== JSON.stringify(tpl.rungs);

  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= rungs.length) return;
    const next = [...rungs];
    [next[i], next[j]] = [next[j], next[i]];
    setRungs(next);
  };
  const del = (i: number) => {
    if (rungs[i].mode === "pinned") return;
    setRungs(rungs.filter((_, x) => x !== i));
  };
  const addGate = () => {
    const name = gateName.trim();
    if (!name) return;
    const key = "gate_" + name.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 24);
    const rung: Rung = {
      key, kind: "H", name, mode: gateCond ? "cond" : "always", rung: gateRung,
      desc: "Adds a " + gateRung.replace(/_/g, " ") + " step to every round's approval ladder.",
    };
    if (gateCond) {
      rung.cond = { field: gateCond, label: lib.cond_fields[gateCond] ?? gateCond };
      if (gateCond === "term_over") rung.cond.value = gateTerm;
    }
    const idx = rungs.findIndex((r) => r.key === "approvals");
    const next = [...rungs];
    next.splice(idx < 0 ? rungs.length - 1 : idx, 0, rung);
    setRungs(next);
    setGateName("");
  };

  async function act(fn: () => Promise<unknown>, note: string) {
    setBusy(true); setErr(null); setMsg(null);
    try { await fn(); setMsg(note); onChanged(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 650, fontSize: 15 }}>{tpl.name}</span>
        <span className="pill state">v{tpl.version}</span>
        {tpl.active ? <span className="pill good">● default for {tpl.type_key}</span>
          : <button className="btn ghost sm" disabled={busy}
              onClick={() => act(() => api.activateWorkflow(tpl.id), "Now the default — new matters use this template.")}>
              Set as default
            </button>}
        <span style={{ flex: 1 }} />
        {dirty && (
          <button className="btn primary sm" disabled={busy}
            onClick={() => act(() => api.updateWorkflow(tpl.id, { rungs: rungs as unknown as Record<string, unknown>[] }), "Saved.")}>
            Save changes
          </button>
        )}
        <button className="btn sm" disabled={busy || dirty}
          title={dirty ? "Save first" : "Bump the version — applies to NEW matters only"}
          onClick={() => act(() => api.publishWorkflow(tpl.id), `Published v${tpl.version + 1} — in-flight matters keep their pinned version.`)}>
          Publish v{tpl.version + 1}
        </button>
      </div>

      {rungs.map((r, i) => (
        <div key={r.key} style={{
          display: "flex", gap: 10, alignItems: "center", padding: "8px 10px",
          border: "1px solid var(--hairline)", borderRadius: 9, marginBottom: 6,
          background: "var(--surface)", flexWrap: "wrap",
        }}>
          <span style={{ display: "inline-flex", gap: 3 }}>
            <button className="btn ghost sm" style={{ padding: "2px 8px" }} disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</button>
            <button className="btn ghost sm" style={{ padding: "2px 8px" }} disabled={i === rungs.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</button>
          </span>
          <KindBadge k={r.kind} />
          <span style={{ fontWeight: 620, fontSize: 13, minWidth: 160 }}>{r.name}</span>
          {r.mode === "pinned" && <span className="pill state" title="Can move, can never be removed">PINNED 🔒</span>}
          {r.mode === "cond" && (
            <span className="pill accent" title="Only instantiates when the condition fires">
              IF {r.cond?.label ?? r.cond?.field}{r.cond?.field === "term_over" ? ` ${r.cond?.value}mo` : ""}
            </span>
          )}
          {r.kind === "H" && r.rung && <span className="pill warn">→ +{r.rung.replace(/_/g, " ")} on the ladder</span>}
          <span style={{ flex: 1 }} />
          {r.mode !== "pinned" && (
            <button className="btn ghost sm" style={{ color: "var(--crit, #B04141)" }} onClick={() => del(i)}>✕ Remove</button>
          )}
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <span className="kicker" style={{ margin: 0 }}>Add approval gate</span>
        <input placeholder="e.g. Security review" value={gateName} onChange={(e) => setGateName(e.target.value)} style={{ width: 180 }} />
        <select value={gateRung} onChange={(e) => setGateRung(e.target.value)}>
          {lib.gate_rungs.map((g) => <option key={g} value={g}>{g.replace(/_/g, " ")}</option>)}
        </select>
        <select value={gateCond} onChange={(e) => setGateCond(e.target.value)}>
          <option value="">always in the ladder</option>
          {Object.entries(lib.cond_fields).map(([k, label]) => <option key={k} value={k}>only if: {label}</option>)}
        </select>
        {gateCond === "term_over" && (
          <input type="number" value={gateTerm} min={1} max={120} onChange={(e) => setGateTerm(Number(e.target.value))} style={{ width: 80 }} />
        )}
        <button className="btn ghost sm" onClick={addGate} disabled={!gateName.trim()}>⊕ Add rung</button>
      </div>

      {err && <div className="notice warn" style={{ marginTop: 10 }}>{err}</div>}
      {msg && <div className="notice good" style={{ marginTop: 10 }}>{msg}</div>}
      <p className="faint" style={{ fontSize: 11.5, margin: "10px 0 0" }}>
        🔒 pinned rungs (intake, seal) can move but never leave. Publishing bumps the version and
        applies to <b>new</b> matters only — in-flight matters keep the snapshot they started with.
        Every save, publish, and activation is chain-sealed.
      </p>
    </div>
  );
}

export default function WorkflowsAdmin() {
  const [templates, setTemplates] = useState<WorkflowTemplateOut[]>([]);
  const [lib, setLib] = useState<WorkflowLibrary | null>(null);
  const [matrices, setMatrices] = useState<RiskMatrixRow[]>([]);
  const [selId, setSelId] = useState<string>("");
  const [tab, setTab] = useState<"ladders" | "matrix">("ladders");
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("nda");
  const [err, setErr] = useState<string | null>(null);

  const load = () => Promise.all([api.listWorkflows(), api.riskMatrices()])
    .then(([w, m]) => {
      setTemplates(w.templates); setLib(w.library); setMatrices(m);
      setSelId((cur) => cur && w.templates.some((t) => t.id === cur) ? cur : (w.templates[0]?.id ?? ""));
    })
    .catch((e) => setErr(String(e).replace(/^Error:\s*/, "")));
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const sel = useMemo(() => templates.find((t) => t.id === selId) ?? null, [templates, selId]);
  const contractTypes = useMemo(
    () => Array.from(new Set([...matrices.map((m) => m.type_key), ...templates.map((t) => t.type_key)])),
    [matrices, templates]);

  async function createTpl() {
    const name = newName.trim();
    if (!name) return;
    try {
      const t = await api.createWorkflow(newType, name);
      setNewName("");
      await load();
      setSelId(t.id);
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
  }

  return (
    <div>
      <div className="page-head">
        <p className="kicker">Administration · Workflow designer</p>
        <h1>Workflows &amp; governance</h1>
        <p className="sub">
          The ladder as data. Each contract type walks a versioned template — deterministic,
          AI, human, and third-party rungs — and every round&rsquo;s approval ladder is picked by
          the risk score through the matrix below. Change either and the engine routes differently;
          governance and execution can&rsquo;t drift apart.
        </p>
      </div>

      <div className="seg" style={{ marginBottom: 18 }}>
        <button className={tab === "ladders" ? "on" : ""} onClick={() => setTab("ladders")}>Workflow templates</button>
        <button className={tab === "matrix" ? "on" : ""} onClick={() => setTab("matrix")}>Risk → approval matrix</button>
      </div>

      {err && <div className="notice warn" style={{ marginBottom: 14 }}>{err}</div>}

      {tab === "matrix" ? (
        <div style={{ maxWidth: 860 }}>
          {matrices.map((m) => <MatrixEditor key={m.type_key} row={m} onSaved={load} />)}
        </div>
      ) : (
        <div style={{ maxWidth: 980 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
            {templates.map((t) => (
              <button key={t.id} className={`btn sm ${t.id === selId ? "primary" : "ghost"}`} onClick={() => setSelId(t.id)}>
                [{t.type_key}] {t.name} · v{t.version}{t.active ? " ●" : ""}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <input placeholder="New template name…" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: 190 }} />
            <select value={newType} onChange={(e) => setNewType(e.target.value)}>
              {contractTypes.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button className="btn sm" onClick={createTpl} disabled={!newName.trim()}>＋ Create</button>
          </div>
          {sel && lib && <TemplateEditor tpl={sel} lib={lib} onChanged={load} />}
          {!sel && <div className="muted">No workflow templates yet — create one above.</div>}
        </div>
      )}
    </div>
  );
}
